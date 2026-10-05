#!/usr/bin/env python3
"""
flowcast_agent.py — one long-lived helper that holds the screen permissions.

Screen capture and synthetic clicks are granted to the APP that launches the
process, so anything an agent runs from its own sandbox is refused. The
workaround was to shell out through `osascript ... do script`, which opens a NEW
Terminal window every single time — screenshot, click, keystroke — and litters
the desktop.

Instead: start this ONCE in a terminal that has Screen Recording and
Accessibility. It then serves requests from a file queue, so an agent can look
at the screen and drive the UI without ever opening another window.

    # once, in a terminal that has the permissions
    uv run python tools/flowcast_agent.py

    # from anywhere afterwards
    python tools/flowcast_agent.py --do screenshot
    python tools/flowcast_agent.py --do "click 477 170"
    python tools/flowcast_agent.py --do "key escape"
    python tools/flowcast_agent.py --do "ask 'Stuck on Create' 'What should I click?'"

Commands:
    screenshot [path]        capture the screen (default: <run>/agent-NNN.png)
    click X Y                click at logical screen coordinates
    doubleclick X Y
    move X Y
    key <keys>               e.g. 'escape', 'cmd+s', 'ctrl+cmd+f'
    type <text>              type a literal string
    activate <app>           bring an app to the front
    fullscreen [app]         activate, then ctrl+cmd+F
    ask <title> <message>    native popup, returns what was typed
    state                    screen size, frontmost app, lock/awake status
    quit                     stop the agent

Coordinates are LOGICAL points (the screen is typically half the pixel size of
a Retina screenshot) — `state` reports both so callers can convert.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOX = ROOT / "output" / "supervisor" / "_agent"
REQ, RES, LOCK = BOX / "request.json", BOX / "response.json", BOX / "agent.alive"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── the operations, run inside the permitted process ─────────────────────────

def _screen_state() -> dict:
    import pyautogui
    w, h = pyautogui.size()
    locked = False
    try:
        out = subprocess.run(["ioreg", "-n", "Root", "-d1", "-w", "0"],
                             capture_output=True, text=True, timeout=10).stdout
        locked = '"CGSSessionScreenIsLocked"=Yes' in out
    except Exception:
        pass
    front = ""
    try:
        front = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to return name of '
             'first application process whose frontmost is true'],
            capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        pass
    return {"logical": [w, h], "frontmost": front, "screen_locked": locked}


def _capture(dest: Path) -> dict:
    """Capture, and REFUSE a black frame — a sleeping or locked display returns
    an all-black image that looks like a valid screenshot to everything
    downstream, which is how a run ends up clicking into nothing."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    r = subprocess.run(["screencapture", "-x", str(dest)], capture_output=True, text=True)
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        return {"ok": False, "error": f"screencapture failed: {r.stderr.strip()[:200]}"}
    try:
        from PIL import Image
        import numpy as np
        im = Image.open(dest).convert("RGB")
        mean = float(np.array(im).mean())
    except Exception:
        return {"ok": True, "path": str(dest), "note": "brightness not checked"}
    st = _screen_state()
    if mean < 3.0:
        return {"ok": False, "path": str(dest), "mean_brightness": mean,
                "screen_locked": st["screen_locked"],
                "error": "screen is black — display asleep or locked; "
                         "nothing can be recorded until it is woken/unlocked"}
    return {"ok": True, "path": str(dest), "size": list(im.size),
            "mean_brightness": round(mean, 1), "logical": st["logical"]}


def _ask(title: str, message: str, default: str = "") -> dict:
    """Native popup. This is the 'it asks instead of guessing' path."""
    script = (
        f'display dialog {json.dumps(message)} with title {json.dumps(title)} '
        f'default answer {json.dumps(default)} '
        f'buttons {{"Abort", "Skip", "Do it"}} default button "Do it" '
        f'with icon caution'
    )
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        return {"ok": False, "error": "dialog cancelled or failed",
                "detail": r.stderr.strip()[:200]}
    out = r.stdout.strip()
    button, text = "", ""
    for part in out.split(", "):
        if part.startswith("button returned:"):
            button = part.split(":", 1)[1]
        elif part.startswith("text returned:"):
            text = part.split(":", 1)[1]
    return {"ok": True, "button": button, "text": text}


def _run(cmd: str) -> dict:
    import pyautogui
    parts = cmd.strip().split()
    if not parts:
        return {"ok": False, "error": "empty command"}
    op, args = parts[0].lower(), parts[1:]

    if op == "state":
        return {"ok": True, **_screen_state()}
    if op == "screenshot":
        dest = Path(args[0]) if args else BOX / f"shot-{int(time.time())}.png"
        return _capture(dest)
    if op in ("click", "doubleclick", "move"):
        if len(args) < 2:
            return {"ok": False, "error": f"{op} needs X Y"}
        x, y = int(float(args[0])), int(float(args[1]))
        pyautogui.moveTo(x, y, duration=0.2)
        if op == "click":
            pyautogui.click()
        elif op == "doubleclick":
            pyautogui.doubleClick()
        return {"ok": True, "at": [x, y]}
    if op == "key":
        keys = " ".join(args).replace("+", " ").split()
        pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])
        return {"ok": True, "keys": keys}
    if op == "type":
        pyautogui.typewrite(" ".join(args), interval=0.02)
        return {"ok": True}
    if op == "activate":
        app = " ".join(args) or "WSO2 Integrator"
        subprocess.run(["osascript", "-e", f'tell application "{app}" to activate'],
                       capture_output=True)
        return {"ok": True, "app": app}
    if op == "fullscreen":
        app = " ".join(args) or "WSO2 Integrator"
        subprocess.run(["osascript", "-e", f'tell application "{app}" to activate'],
                       capture_output=True)
        time.sleep(1.0)
        pyautogui.hotkey("ctrl", "command", "f")
        time.sleep(2.0)
        return {"ok": True, "app": app}
    if op == "ask":
        rest = cmd.strip()[3:].strip()
        try:
            import shlex
            bits = shlex.split(rest)
        except ValueError:
            bits = [rest]
        title = bits[0] if bits else "FlowCast"
        message = bits[1] if len(bits) > 1 else "What should I do?"
        default = bits[2] if len(bits) > 2 else ""
        return _ask(title, message, default)
    return {"ok": False, "error": f"unknown command {op!r}"}


# ── server / client ───────────────────────────────────────────────────────────

def serve() -> None:
    BOX.mkdir(parents=True, exist_ok=True)
    for f in (REQ, RES):
        f.unlink(missing_ok=True)
    LOCK.write_text(_now())
    print(f"[agent] ready — serving {BOX}")
    print("[agent] this window holds the screen permissions; leave it open.")
    try:
        while True:
            if not REQ.exists():
                time.sleep(0.15)
                continue
            try:
                req = json.loads(REQ.read_text())
            except json.JSONDecodeError:
                REQ.unlink(missing_ok=True)
                continue
            REQ.unlink(missing_ok=True)
            cmd = str(req.get("cmd", ""))
            print(f"[agent] {cmd}")
            if cmd.strip().lower() == "quit":
                RES.write_text(json.dumps({"id": req.get("id"), "ok": True, "bye": True}))
                break
            try:
                out = _run(cmd)
            except Exception as e:
                out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            out["id"] = req.get("id")
            RES.write_text(json.dumps(out))
            print(f"[agent]   -> {json.dumps(out)[:200]}")
    finally:
        LOCK.unlink(missing_ok=True)
        print("[agent] stopped")


def call(cmd: str, timeout: float = 60.0) -> dict:
    if not LOCK.exists():
        return {"ok": False, "error": "agent not running — start it with: "
                                      "uv run python tools/flowcast_agent.py"}
    BOX.mkdir(parents=True, exist_ok=True)
    rid = f"{time.time():.6f}"
    RES.unlink(missing_ok=True)
    REQ.write_text(json.dumps({"id": rid, "cmd": cmd}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        if RES.exists():
            try:
                res = json.loads(RES.read_text())
            except json.JSONDecodeError:
                time.sleep(0.1)
                continue
            if res.get("id") == rid:
                RES.unlink(missing_ok=True)
                return res
        time.sleep(0.12)
    return {"ok": False, "error": f"agent did not answer within {timeout:.0f}s"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Persistent screen-permission helper.")
    ap.add_argument("--do", default=None, help="send one command to a running agent")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()
    if args.do is None:
        serve()
        return
    res = call(args.do, args.timeout)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
