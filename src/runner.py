from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import pyautogui
from PIL import Image

from src.detector import ElementNotFoundError, find_element, find_input_field

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

_MAX_RETRIES = 3
_RETRY_DELAY = 2.0
_TARGET_APP = "WSO2 Integrator"
_APP_PATH = "/Users/sachindu/Applications/WSO2 Integrator.app"

_KB: dict | None = None


def _kb() -> dict:
    global _KB
    if _KB is None:
        p = Path(__file__).parent.parent / "kb" / "ui_elements.json"
        _KB = json.loads(p.read_text()) if p.exists() else {}
    return _KB


def _is_autofocus(field_label: str) -> bool:
    for f in _kb().get("autofocus_fields", {}).get("fields", []):
        if f["label"].lower() == field_label.lower():
            return True
    return False


def _is_auto_populated(field_label: str) -> bool:
    for f in _kb().get("auto_populated_fields", {}).get("fields", []):
        if f["label"].lower() == field_label.lower():
            return True
    return False


def _screenshot() -> Image.Image:
    _activate()
    return pyautogui.screenshot()


def _activate() -> None:
    subprocess.run(
        ["osascript", "-e", f'activate application "{_TARGET_APP}"'],
        capture_output=True, timeout=5,
    )
    time.sleep(0.3)


def _find(target: str, hint: str | None = None) -> tuple[int, int]:
    for attempt in range(_MAX_RETRIES):
        try:
            return find_element(_screenshot(), target, hint)
        except ElementNotFoundError:
            if attempt < _MAX_RETRIES - 1:
                print(f"[runner] Retry {attempt + 1} for '{target}'...")
                time.sleep(_RETRY_DELAY)
    raise ElementNotFoundError(f"'{target}' not found after {_MAX_RETRIES} attempts")


def _paste(value: str) -> None:
    subprocess.run(["pbcopy"], input=value.encode(), check=True)
    pyautogui.hotkey("command", "v")
    time.sleep(0.5)


def _ui_changed(before: Image.Image, after: Image.Image) -> bool:
    a = np.array(before.convert("RGB"), dtype=np.float32)
    b = np.array(after.convert("RGB"), dtype=np.float32)
    return float((np.abs(a - b).mean(axis=2) > 10).mean()) > 0.001


def wait_ui_change(timeout: float = 5.0) -> bool:
    """Wait until the screen visually changes from its current state.

    Returns True if a change was detected, False if timeout elapsed with no change.
    Use this after firing an action to confirm the UI has actually responded
    before moving on to detect/fire the next action.
    """
    baseline = pyautogui.screenshot()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.1)
        curr = pyautogui.screenshot()
        if _ui_changed(baseline, curr):
            return True
    print("[runner] wait_ui_change: no change detected within timeout")
    return False


def wait_ui_settle(timeout: float = 6.0, stable_for: float = 0.4) -> None:
    """Poll until screen is visually stable or timeout."""
    deadline = time.time() + timeout
    stable_since: float | None = None
    prev = pyautogui.screenshot()
    while time.time() < deadline:
        time.sleep(0.15)
        curr = pyautogui.screenshot()
        if _ui_changed(prev, curr):
            stable_since = None
        else:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= stable_for:
                break
        prev = curr


def resolve(action: dict[str, Any]) -> dict[str, Any]:
    """
    Detection-only phase: find element coordinates without firing any input.
    Returns action dict with x, y filled in (or unchanged for shell/hotkey/wait).
    """
    kind = action["action"]

    if kind == "open_app":
        return action

    if kind == "click":
        target = action["target"]
        x, y = _find(target, action.get("hint"))
        return {**action, "x": x, "y": y}

    if kind == "type":
        field_target = action["field_target"]
        if _is_auto_populated(field_target):
            return {**action, "_skip": True}
        # Autofocus fields are already focused — no click needed, just clear + paste
        if _is_autofocus(field_target):
            return {**action, "x": None, "y": None, "_needs_click": False}
        # Ask Groq Vision where to click to focus the actual input box
        result = find_input_field(_screenshot(), field_target)
        if result:
            return {**action, "x": result[0], "y": result[1], "_needs_click": True}
        print(f"[runner] Could not locate input for '{field_target}' — will type into focused element")
        return {**action, "x": None, "y": None, "_needs_click": False}

    if kind == "select":
        x, y = _find(action["field_target"])
        return {**action, "x": x, "y": y}

    if kind == "scroll":
        target = action.get("target", "")
        if target:
            x, y = _find(target)
            return {**action, "x": x, "y": y}
        return action

    return action  # hotkey, wait — no detection needed


def fire(action: dict[str, Any]) -> None:
    """
    Execution-only phase: perform the pyautogui/shell action using pre-resolved coords.
    Call this while recording is active.
    """
    if action.get("_skip"):
        print(f"[runner] Skipping auto-populated field: '{action.get('field_target')}'")
        return

    kind = action["action"]
    x, y = action.get("x"), action.get("y")

    if kind == "open_app":
        app_path = action.get("app_path", "") or _APP_PATH
        subprocess.run(["open", app_path], check=True)
        time.sleep(3.0)
        _activate()
        subprocess.run([
            "osascript", "-e",
            f'tell application "System Events" to tell process "{action.get("app_name", _TARGET_APP)}" '
            f'to set value of attribute "AXFullScreen" of window 1 to true',
        ], capture_output=True)
        time.sleep(1.0)

    elif kind == "click":
        pyautogui.moveTo(x, y, duration=0.3)
        pyautogui.click(x, y)

    elif kind == "type":
        if action.get("_needs_click") and x is not None and y is not None:
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click(x, y)
            wait_ui_change(timeout=2.0)
        # Always select-all to clear any pre-filled content before pasting
        pyautogui.hotkey("command", "a")
        time.sleep(0.1)
        _paste(action["value"])

    elif kind == "select":
        pyautogui.moveTo(x, y, duration=0.2)
        pyautogui.click(x, y)
        time.sleep(0.4)
        # Option will be found live during fire since dropdown just opened
        try:
            ox, oy = find_element(pyautogui.screenshot(), action["value"])
            pyautogui.click(ox, oy)
        except ElementNotFoundError:
            print(f"[runner] Select option '{action['value']}' not found after opening dropdown")

    elif kind == "hotkey":
        pyautogui.hotkey(*action["keys"])

    elif kind == "scroll":
        clicks = action.get("clicks", -3)
        if x is not None:
            pyautogui.scroll(clicks, x=x, y=y)
        else:
            pyautogui.scroll(clicks)

    elif kind == "wait":
        time.sleep(action.get("seconds", 1.0))

    else:
        print(f"[runner] Unknown action type: '{kind}'")
