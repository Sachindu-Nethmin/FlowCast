"""
runner.py — Single-pass executor: screenshot → Gemini detect → PyAutoGUI action.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pyautogui
from PIL import Image

from src import detector

pyautogui.FAILSAFE = True  # Move mouse to top-left corner to abort
pyautogui.PAUSE = 0.3        # 0.3s pause after every pyautogui call
pyautogui.MINIMUM_DURATION = 0.3   # minimum time for mouse moves

DEFAULT_TIMEOUT = 10.0   # seconds to wait for an element before raising
MAX_RETRIES = 3
RETRY_DELAY = 2.0

_log_path = Path(__file__).parent.parent / "logs" / "run_log.json"
_target_app: str = "WSO2 Integrator"
_target_pid: int | None = None   # when set, activate by PID instead of app name


class ElementNotFoundError(Exception):
    pass


def set_log_path(path: str | Path) -> None:
    """Redirect action logs to a custom path."""
    global _log_path
    _log_path = Path(path)


def set_target_app(name: str) -> None:
    """Set the app name used by _activate_target_app()."""
    global _target_app
    _target_app = name


def set_target_pid(pid: int | None) -> None:
    """Pin activation to a specific process PID (use for multi-instance apps)."""
    global _target_pid
    _target_pid = pid


def _activate_target_app() -> None:
    """Bring the target app to front before taking screenshots."""
    try:
        if _target_pid is not None:
            subprocess.run(
                ['osascript', '-e',
                 f'tell application "System Events" to set frontmost of '
                 f'(first process whose unix id is {_target_pid}) to true'],
                timeout=5, capture_output=True,
            )
        else:
            subprocess.run(
                ['osascript', '-e', f'activate application "{_target_app}"'],
                timeout=5, capture_output=True,
            )
        time.sleep(0.3)
    except Exception:
        pass


def _screenshot() -> Image.Image:
    _activate_target_app()
    shot = pyautogui.screenshot()
    if shot is None or shot.width < 100:
        raise PermissionError(
            "pyautogui.screenshot() returned a blank image.\n"
            "Grant Screen Recording permission to Terminal in:\n"
            "  System Settings → Privacy & Security → Screen Recording"
        )
    return shot


def _ui_changed(before: Image.Image, after: Image.Image, threshold: float = 0.001) -> bool:
    """Return True if more than `threshold` fraction of pixels changed between screenshots."""
    import numpy as np
    a = np.array(before.convert("RGB"), dtype=np.float32)
    b = np.array(after.convert("RGB"), dtype=np.float32)
    diff = np.abs(a - b).mean(axis=2)          # per-pixel mean RGB channel diff
    changed_fraction = float((diff > 10).mean())  # pixels that changed by >10/255
    return changed_fraction > threshold


def _find_element(target: str, timeout: float, hint: str | None = None) -> tuple[int, int]:
    """
    Retry up to MAX_RETRIES times to find the target on screen.
    Returns logical-pixel (x, y) center.
    """
    retries = max(1, int(timeout / (RETRY_DELAY + 1)))
    retries = min(retries, MAX_RETRIES)

    for attempt in range(retries):
        shot = _screenshot()
        result = detector.find(shot, target, hint=hint)
        if result is not None:
            return result.center
        if attempt < retries - 1:
            print(f"[runner] Retry {attempt + 1}/{retries} for '{target}'...")
            time.sleep(RETRY_DELAY)

    raise ElementNotFoundError(f"Element not found after {retries} attempts: '{target}'")



def _log_action(entry: dict[str, Any]) -> None:
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    if _log_path.exists():
        with _log_path.open() as f:
            log = json.load(f)
    else:
        log = []
    log.append(entry)
    with _log_path.open("w") as f:
        json.dump(log, f, indent=2)


def execute_single_action(action: dict[str, Any]) -> None:
    """
    Execute one action dict from the workflow.
    Supported action types: click, type, scroll, hotkey, shell
    """
    action_type = action["action"]
    target = action.get("target", "")
    timeout = action.get("timeout", DEFAULT_TIMEOUT)

    if action_type == "click":
        x, y = _find_element(target, timeout, hint=action.get("hint"))
        before = _screenshot()
        pyautogui.click(x, y, duration=0.4)
        time.sleep(2.0)
        after = _screenshot()

        if not _ui_changed(before, after):
            print(f"[runner] UI unchanged after clicking '{target}' at ({x}, {y}) — searching alternatives...")
            candidates = detector.find_all_by_ocr(_screenshot(), target)
            alternatives = [r.center for r in candidates if abs(r.center[0] - x) > 10 or abs(r.center[1] - y) > 10]

            clicked = False
            for ax, ay in alternatives:
                print(f"[runner] Trying alternative '{target}' at ({ax}, {ay})")
                pre = _screenshot()
                pyautogui.click(ax, ay, duration=0.4)
                time.sleep(1.0)
                if _ui_changed(pre, _screenshot()):
                    x, y = ax, ay
                    clicked = True
                    print(f"[runner] Alternative click worked at ({x}, {y})")
                    break

            if not clicked:
                print(f"[WARNING] No effective click found for '{target}' — continuing", file=sys.stderr)

        entry = {
            "action": "click",
            "target": target,
            "x": x,
            "y": y,
            "timestamp": datetime.now().isoformat(),
        }
        _log_action(entry)
        print(f"[runner] Clicked '{target}' at ({x}, {y})")

    elif action_type == "type":
        field_target = action.get("field_target", target)
        value = action.get("value", "")
        try:
            x, y = _find_element(field_target, timeout)
            # Triple-click: focus field and select all existing content within it
            pyautogui.click(x, y, clicks=3, interval=0.1)
            time.sleep(0.3)
        except ElementNotFoundError:
            print(f"[runner] '{field_target}' not found on screen — typing into focused field")
            x, y = pyautogui.position()
        # Use clipboard paste for full character support (spaces, /, etc.)
        import subprocess as _sp
        _sp.run(["pbcopy"], input=value.encode(), check=True)
        pyautogui.hotkey("command", "v")
        time.sleep(1.0)
        entry = {
            "action": "type",
            "target": field_target,
            "value": value,
            "x": x,
            "y": y,
            "timestamp": datetime.now().isoformat(),
        }
        _log_action(entry)
        print(f"[runner] Typed '{value}' into '{field_target}'")

    elif action_type == "scroll":
        x, y = _find_element(target, timeout)
        clicks = action.get("clicks", -3)
        pyautogui.scroll(clicks, x=x, y=y)
        time.sleep(1.0)
        entry = {
            "action": "scroll",
            "target": target,
            "clicks": clicks,
            "x": x,
            "y": y,
            "timestamp": datetime.now().isoformat(),
        }
        _log_action(entry)
        print(f"[runner] Scrolled at '{target}' ({x}, {y}) by {clicks}")

    elif action_type == "shell":
        command = action.get("command", "")
        wait = action.get("wait", 0)
        subprocess.run(command, shell=True, check=True)
        if wait:
            time.sleep(wait)
        else:
            time.sleep(1.0)
        entry = {
            "action": "shell",
            "command": command,
            "wait": wait,
            "timestamp": datetime.now().isoformat(),
        }
        _log_action(entry)
        print(f"[runner] Shell: {command}")

    elif action_type == "hotkey":
        keys = action.get("keys", [])
        wait = action.get("wait", 1.0)
        pyautogui.hotkey(*keys)
        time.sleep(wait)
        entry = {
            "action": "hotkey",
            "keys": keys,
            "wait": wait,
            "timestamp": datetime.now().isoformat(),
        }
        _log_action(entry)
        print(f"[runner] Hotkey {'+'.join(keys)}")

    else:
        raise ValueError(f"Unknown action type: '{action_type}'")


def resolve_action(action: dict[str, Any]) -> dict[str, Any]:
    """
    Detection-only phase: find the target element on screen and return the action
    dict with x/y coordinates filled in.  No pyautogui input is fired.
    Raises ElementNotFoundError if the element cannot be found.
    For shell/hotkey actions (no detection needed) the action is returned unchanged.
    """
    action_type = action["action"]
    timeout = action.get("timeout", DEFAULT_TIMEOUT)

    if action_type == "click":
        target = action.get("target", "")
        hint = action.get("hint")
        x, y = _find_element(target, timeout, hint=hint)
        off_x = action.get("offset_x", 0)
        off_y = action.get("offset_y", 0)
        if off_x or off_y:
            print(f"[runner] Applying offset ({off_x:+d}, {off_y:+d}) to click '{target}' → ({x + off_x}, {y + off_y})")
        x += off_x
        y += off_y
        # Store all candidates so fire_action can retry if the click has no effect
        all_candidates = [r.center for r in detector.find_all_by_ocr(_screenshot(), target)]
        return {**action, "x": x, "y": y, "_candidates": all_candidates}

    elif action_type == "type":
        field_target = action.get("field_target", action.get("target", ""))
        if action.get("skip_click"):
            # Field was pre-focused by a preceding offset-click — skip OCR and re-click entirely
            print(f"[runner] Type '{field_target}': field pre-focused, skipping click")
            x, y = pyautogui.position()
            field_found = False
        else:
            field_found = True
            try:
                x, y = _find_element(field_target, timeout)
            except ElementNotFoundError:
                print(f"[runner] '{field_target}' not found — will type into focused field")
                x, y = pyautogui.position()
                field_found = False
        return {**action, "x": x, "y": y, "field_target": field_target, "_field_found": field_found}

    elif action_type == "scroll":
        target = action.get("target", "")
        x, y = _find_element(target, timeout)
        return {**action, "x": x, "y": y}

    else:  # shell, hotkey — no detection needed
        return action


def fire_action(entry: dict[str, Any]) -> None:
    """
    Action-only phase: fire the pyautogui / shell input from a resolved entry.
    No element detection is performed — coordinates must already be set.
    Call this between recorder.start() and recorder.stop().
    """
    action_type = entry.get("action", "")
    x = entry.get("x")
    y = entry.get("y")

    if action_type == "click":
        target = entry.get("target", "")
        before = pyautogui.screenshot()
        pyautogui.click(x, y, duration=0.4)
        time.sleep(1.0)
        if not _ui_changed(before, pyautogui.screenshot()):
            print(f"[runner] UI unchanged after clicking '{target}' at ({x}, {y}) — trying alternatives...")
            candidates = entry.get("_candidates", [])
            alternatives = [(ax, ay) for ax, ay in candidates if abs(ax - x) > 10 or abs(ay - y) > 10]
            for ax, ay in alternatives:
                print(f"[runner] Trying alternative '{target}' at ({ax}, {ay})")
                pre = pyautogui.screenshot()
                pyautogui.click(ax, ay, duration=0.4)
                time.sleep(1.0)
                if _ui_changed(pre, pyautogui.screenshot()):
                    print(f"[runner] Alternative click worked at ({ax}, {ay})")
                    break

    elif action_type == "type":
        value = entry.get("value", "")
        if entry.get("_field_found", True):
            # Field was found by OCR — triple-click to focus and clear it.
            # Avoids Cmd+A which selects all canvas elements instead.
            pyautogui.click(x, y, clicks=3, interval=0.1)
            time.sleep(0.3)
        # else: field already focused by a preceding click action — don't move mouse
        subprocess.run(["pbcopy"], input=value.encode(), check=True)
        pyautogui.hotkey("command", "v")

    elif action_type == "scroll":
        clicks = entry.get("clicks", -3)
        pyautogui.scroll(clicks, x=x, y=y)

    elif action_type == "shell":
        command = entry.get("command", "")
        subprocess.run(command, shell=True, check=True)

    elif action_type == "hotkey":
        keys = entry.get("keys", [])
        pyautogui.hotkey(*keys)

    else:
        raise ValueError(f"Unknown action type: '{action_type}'")


def wait_ui_settle(timeout: float = 8.0, stable_for: float = 0.5, interval: float = 0.2) -> None:
    """
    Poll screenshots until the screen has been visually stable for `stable_for`
    seconds, or until `timeout` is reached.  Use this after fire_action() to let
    the recording capture the UI response before stopping.
    """
    deadline = time.time() + timeout
    stable_since: float | None = None
    prev = pyautogui.screenshot()

    while time.time() < deadline:
        time.sleep(interval)
        curr = pyautogui.screenshot()
        if _ui_changed(prev, curr):
            stable_since = None          # screen still animating — reset counter
        else:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= stable_for:
                break                    # stable long enough — done
        prev = curr


def replay_action(entry: dict[str, Any]) -> None:
    """
    Replay a single logged action using stored coordinates (no detection).
    Used to replay actions from the run log during recording.
    """
    _activate_target_app()   # keep guide window in front before every action
    action_type = entry.get("action", "")
    x = entry.get("x")
    y = entry.get("y")

    if action_type == "click":
        target = entry.get("target", "")
        pyautogui.click(x, y, duration=0.4)
        time.sleep(1.0)
        print(f"[replay] Clicked '{target}' at ({x}, {y})")

    elif action_type == "type":
        target = entry.get("target", "")
        value = entry.get("value", "")
        pyautogui.click(x, y, duration=0.4)
        time.sleep(0.3)
        pyautogui.hotkey("command", "a")
        # Use clipboard paste for full character support (matches execute_single_action)
        subprocess.run(["pbcopy"], input=value.encode(), check=True)
        pyautogui.hotkey("command", "v")
        time.sleep(1.0)
        print(f"[replay] Typed '{value}' into '{target}' at ({x}, {y})")

    elif action_type == "scroll":
        target = entry.get("target", "")
        clicks = entry.get("clicks", -3)
        pyautogui.scroll(clicks, x=x, y=y)
        time.sleep(1.0)
        print(f"[replay] Scrolled at '{target}' ({x}, {y}) by {clicks}")

    elif action_type == "shell":
        command = entry.get("command", "")
        wait = entry.get("wait", 0)
        subprocess.run(command, shell=True, check=True)
        if wait:
            time.sleep(wait)
        else:
            time.sleep(1.0)
        print(f"[replay] Shell: {command}")

    elif action_type == "hotkey":
        keys = entry.get("keys", [])
        pyautogui.hotkey(*keys)
        time.sleep(1.0)
        print(f"[replay] Hotkey {'+'.join(keys)}")

    else:
        raise ValueError(f"Unknown action type for replay: '{action_type}'")
