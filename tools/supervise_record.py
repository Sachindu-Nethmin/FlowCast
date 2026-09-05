#!/usr/bin/env python3
"""
supervise_record.py — run a FlowCast recording under a pty so an agent can
answer the healer's prompts.

FlowCast's healer only asks for guidance when `sys.stdin.isatty()` is true
(see `src/interactive.py::available`). A command run from an agent has no
terminal, so the healer silently aborts the step instead of asking. This
supervisor puts the run inside a real pty, watches for prompts, and hands each
one to whoever is driving — capturing a screenshot at that moment so the
decision can be made from what is actually on screen.

Protocol — a run directory under `output/supervisor/<slug>/`:

    session.log     full transcript, ANSI stripped, appended live
    pending.json    written when the run is BLOCKED on a prompt; absent otherwise
    answer.json     write this to unblock it (or use --answer)
    screen-NNN.png  the screen at the moment of prompt NNN

Typical loop:

    # 1. start it (backgrounded — it blocks while waiting for answers)
    python tools/supervise_record.py --workflow workflows/<slug>.md

    # 2. whenever it blocks
    python tools/supervise_record.py --status        # shows prompt + screenshot path
    python tools/supervise_record.py --answer "skip for now"
    python tools/supervise_record.py --answer N

    # 3. if it needs to stop
    python tools/supervise_record.py --stop

`--auto-safe` answers only the one prompt that has a safe default: the
"Remember X -> click Y and fix the workflow file? [y/N]" confirmation, which
gets N. A wrong `y` there rewrites the workflow and poisons the knowledge base,
so it is never auto-answered `y`.

Screen capture needs macOS Screen Recording permission for the process that
launches this. Without it FlowCast cannot record at all, so the run fails early
with a clear message rather than part-way through.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "output" / "supervisor"

ANSI = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
QUIET = 1.2          # seconds of silence before a trailing line counts as a prompt
POLL = 0.2

PROMPTS = [
    re.compile(r"what next>\s*$"),
    re.compile(r"command>\s*$"),
    re.compile(r"\[y/N\]\s*$", re.I),
    re.compile(r"\[Y/n\]\s*$", re.I),
    re.compile(r"\(y/n\)\s*$", re.I),
    re.compile(r"choice>\s*$", re.I),
    re.compile(r"^\s*>\s*$"),
]

# Prompts with a defensible default. Conservative on purpose: `y` here would
# rewrite workflows/<slug>.md and teach the KB a wrong mapping.
AUTO_SAFE = [
    (re.compile(r"Remember .* and fix the workflow file\?\s*\[y/N\]\s*$", re.I), "N"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_dir(slug: str) -> Path:
    d = RUNS / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _latest_run() -> Path:
    if not RUNS.exists():
        sys.exit("no supervised run found (nothing under output/supervisor/)")
    dirs = [p for p in RUNS.iterdir() if p.is_dir()]
    if not dirs:
        sys.exit("no supervised run found (nothing under output/supervisor/)")
    return max(dirs, key=lambda p: (p / "session.log").stat().st_mtime
               if (p / "session.log").exists() else p.stat().st_mtime)


def _screenshot(dest: Path) -> str | None:
    """Grab the screen so the prompt can be judged from what is on it."""
    try:
        r = subprocess.run(["screencapture", "-x", str(dest)],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return str(dest)
        return None
    except Exception:
        return None


def _check_capture(d: Path) -> None:
    """Fail fast rather than half-way through a run the user has to redo.

    Probe into the real run directory: `screencapture` refuses some
    destinations (the per-user $TMPDIR among them) while having full
    permission, and it exits 0 even then — so the only reliable test is
    writing a real file where the run will actually put its screenshots.
    """
    probe = d / "capture-probe.png"
    probe.unlink(missing_ok=True)
    if _screenshot(probe) is None:
        sys.exit(
            f"Cannot capture the screen into {d}.\n"
            "Either Screen Recording permission is missing for this process, or "
            "that directory is not a destination `screencapture` will write to.\n"
            "Grant it in System Settings > Privacy & Security > Screen & System "
            "Audio Recording, then FULLY QUIT and reopen the app that launches "
            "this (the permission is only re-read at launch).")
    probe.unlink(missing_ok=True)


def _set_winsize(fd: int, rows: int = 48, cols: int = 120) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


def _tail_line(buf: str) -> str:
    return buf.rsplit("\n", 1)[-1] if buf else ""


def _is_prompt(line: str) -> bool:
    return any(p.search(line) for p in PROMPTS)


def _auto_answer(line: str) -> str | None:
    for pat, ans in AUTO_SAFE:
        if pat.search(line):
            return ans
    return None


def supervise(workflow: Path, extra: list[str], auto_safe: bool,
              wait_limit: float) -> int:
    slug = workflow.stem
    d = _run_dir(slug)
    log_path, pending_p, answer_p = d / "session.log", d / "pending.json", d / "answer.json"
    for p in (pending_p, answer_p):
        p.unlink(missing_ok=True)
    log = log_path.open("w", buffering=1)

    _check_capture(d)

    cmd = [sys.executable, str(ROOT / "main.py"), str(workflow), *extra]
    print(f"[supervisor] {' '.join(cmd)}")
    print(f"[supervisor] run dir: {d}")

    master, slave = pty.openpty()
    _set_winsize(slave)
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdin=slave, stdout=slave,
                            stderr=slave, close_fds=True, env={**os.environ,
                                                               "PYTHONUNBUFFERED": "1",
                                                               "TERM": "dumb"})
    os.close(slave)

    buf, seq = "", 0
    last_out = time.time()
    blocked_since: float | None = None

    try:
        while True:
            if proc.poll() is not None and not select.select([master], [], [], 0)[0]:
                break
            r, _, _ = select.select([master], [], [], POLL)
            if r:
                try:
                    chunk = os.read(master, 65536)
                except OSError as e:
                    if e.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                text = ANSI.sub("", chunk.decode("utf-8", "replace"))
                log.write(text)
                sys.stdout.write(text)
                sys.stdout.flush()
                buf = (buf + text)[-8000:]
                last_out = time.time()
                blocked_since = None
                continue

            # No output. If the tail looks like a prompt and it has been quiet,
            # the child is waiting on stdin.
            line = _tail_line(buf).rstrip("\r")
            if not (time.time() - last_out > QUIET and line.strip() and _is_prompt(line)):
                continue

            if not pending_p.exists():
                seq += 1
                auto = _auto_answer(line) if auto_safe else None
                if auto is not None:
                    msg = f"\n[supervisor] auto-safe answer to prompt #{seq}: {auto!r}\n"
                    log.write(msg)
                    sys.stdout.write(msg)
                    os.write(master, (auto + "\n").encode())
                    buf, last_out = "", time.time()
                    continue
                shot = _screenshot(d / f"screen-{seq:03d}.png")
                pending_p.write_text(json.dumps({
                    "seq": seq,
                    "prompt": line.strip(),
                    "context": "\n".join(buf.strip().splitlines()[-40:]),
                    "screen": shot,
                    "asked_at": _now(),
                }, indent=2))
                blocked_since = time.time()
                msg = (f"\n[supervisor] BLOCKED on prompt #{seq}: {line.strip()!r}\n"
                       f"[supervisor] screenshot: {shot or 'unavailable'}\n"
                       f"[supervisor] answer with: python tools/supervise_record.py "
                       f"--answer '<text>'\n")
                log.write(msg)
                sys.stdout.write(msg)
                sys.stdout.flush()

            # Wait for an answer for THIS prompt.
            if answer_p.exists():
                try:
                    ans = json.loads(answer_p.read_text())
                except json.JSONDecodeError:
                    ans = None
                if ans and int(ans.get("seq", -1)) == seq:
                    reply = str(ans.get("answer", ""))
                    answer_p.unlink(missing_ok=True)
                    pending_p.unlink(missing_ok=True)
                    msg = f"\n[supervisor] answering #{seq}: {reply!r}\n"
                    log.write(msg)
                    sys.stdout.write(msg)
                    os.write(master, (reply + "\n").encode())
                    buf, last_out, blocked_since = "", time.time(), None
                    continue

            if blocked_since and wait_limit and time.time() - blocked_since > wait_limit:
                msg = (f"\n[supervisor] no answer within {wait_limit:.0f}s — "
                       f"aborting the run\n")
                log.write(msg)
                sys.stdout.write(msg)
                os.write(master, b"abort\n")
                time.sleep(2)
                proc.terminate()
                break
    finally:
        try:
            os.close(master)
        except OSError:
            pass
        pending_p.unlink(missing_ok=True)
        code = proc.wait() if proc.poll() is None else proc.returncode
        log.write(f"\n[supervisor] exited with code {code}\n")
        log.close()
        print(f"\n[supervisor] exited with code {code}")
        return code or 0


def cmd_status(d: Path) -> None:
    pending = d / "pending.json"
    if not pending.exists():
        log = d / "session.log"
        tail = "\n".join(log.read_text(errors="replace").splitlines()[-15:]) if log.exists() else ""
        print(f"[{d.name}] not blocked — running or finished.\n\n{tail}")
        return
    p = json.loads(pending.read_text())
    print(f"[{d.name}] BLOCKED on prompt #{p['seq']} (since {p['asked_at']})")
    print(f"\nPROMPT: {p['prompt']}")
    print(f"SCREEN: {p.get('screen') or 'unavailable'}")
    print(f"\n--- last 40 lines ---\n{p['context']}")


def cmd_answer(d: Path, text: str, settle: float = 8.0) -> None:
    pending = d / "pending.json"
    if not pending.exists():
        sys.exit(f"[{d.name}] is not waiting for an answer right now.")
    seq = json.loads(pending.read_text())["seq"]
    (d / "answer.json").write_text(json.dumps({"seq": seq, "answer": text}))
    # Block until the supervisor has taken it, so a --status straight afterwards
    # never reports the prompt we just answered.
    deadline = time.time() + settle
    while time.time() < deadline:
        try:
            if not pending.exists() or json.loads(pending.read_text())["seq"] != seq:
                break
        except (json.JSONDecodeError, KeyError):
            break
        time.sleep(0.15)
    print(f"[{d.name}] answered #{seq}: {text!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run a FlowCast recording under a pty an agent can answer.")
    ap.add_argument("--workflow", type=Path, help="workflows/<slug>.md — starts a run")
    ap.add_argument("--step", type=int, default=None)
    ap.add_argument("--from-step", type=int, default=None)
    ap.add_argument("--narrate", action="store_true",
                    help="keep FlowCast's auto-narration (default passes --no-narrate)")
    ap.add_argument("--auto-safe", action="store_true",
                    help="auto-answer only the 'fix the workflow file? [y/N]' prompt, with N")
    ap.add_argument("--wait-limit", type=float, default=1800,
                    help="seconds to wait for an answer before aborting (0 = forever)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--answer", default=None)
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--run", default=None, help="run slug (default: most recent)")
    args = ap.parse_args()

    if args.status or args.answer is not None or args.stop:
        d = _run_dir(args.run) if args.run else _latest_run()
        if args.status:
            cmd_status(d)
        elif args.answer is not None:
            cmd_answer(d, args.answer)
        else:
            (d / "answer.json").write_text(json.dumps({"seq": -1, "answer": "abort"}))
            print(f"[{d.name}] abort requested — the run stops at its next prompt. "
                  f"To kill it outright: pkill -f 'main.py {d.name}'")
        return

    if not args.workflow:
        ap.error("--workflow is required to start a run")
    extra: list[str] = [] if args.narrate else ["--no-narrate"]
    if args.step:
        extra += ["--step", str(args.step)]
    if args.from_step:
        extra += ["--from-step", str(args.from_step)]
    sys.exit(supervise(args.workflow, extra, args.auto_safe, args.wait_limit))


if __name__ == "__main__":
    main()
