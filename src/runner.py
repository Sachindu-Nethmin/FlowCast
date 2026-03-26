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

# One-shot callback: called right before cursor movement begins in fire().
# main.py sets this before each fire() call so recording starts at cursor move.
_pre_move_cb: callable | None = None


def set_pre_move_callback(cb: callable | None) -> None:
    global _pre_move_cb
    _pre_move_cb = cb


def _trigger_pre_move() -> None:
    global _pre_move_cb
    if _pre_move_cb is not None:
        _pre_move_cb()
        _pre_move_cb = None  # one-shot


_MAX_RETRIES = 3
_RETRY_DELAY = 2.0
_TARGET_APP = "WSO2 Integrator"
_APP_PATH = "/Users/sachindu/Applications/WSO2 Integrator.app"

_KB: dict | None = None


# Enable visual debugging for input detection
from src import detector
detector.set_debug_dir(Path(__file__).parent.parent / "output" / "debug_detection")


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


def _find(target: str, hint: str | None = None, action: dict | None = None,
          step_title: str = "", action_index: int = 0) -> tuple[int, int]:
    screenshot = _screenshot()
    try:
        return find_element(screenshot, target, hint)
    except ElementNotFoundError:
        pass

    # OCR failed — hand off to healer for diagnosis + escalating retry
    from src import healer
    import numpy as np
    from src.detector import _ocr
    arr = np.array(screenshot)
    ocr_results = _ocr().readtext(arr)
    ctx = healer.HealContext(
        action=action or {"target": target},
        screenshot=screenshot,
        ocr_results=ocr_results,
        step_title=step_title,
        action_index=action_index,
    )
    return healer.heal(ctx)  # raises HealingAbortedError or ElementNotFoundError on total failure


def _find_set_button(near_x: int | None = None, near_y: int | None = None) -> tuple[int, int] | None:
    """Use OpenCV template matching to find the Set button on screen.
    
    If near_x/near_y provided, filters for matches near those coordinates.
    """
    import cv2
    from pathlib import Path as _Path

    icon_path = _Path(__file__).parent.parent / "kb" / "icons" / "Set.png"
    if not icon_path.exists():
        return None

    screenshot = pyautogui.screenshot()
    screen_arr = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    tmpl = cv2.cvtColor(cv2.imread(str(icon_path)), cv2.COLOR_BGR2GRAY)
    
    # Left panel avoidance (ignore left 20% for "Set" buttons)
    left_boundary = int(screenshot.width * 0.2)

    best_val, best_loc, best_tw, best_th = -1.0, (0, 0), 1, 1
    th, tw = tmpl.shape[:2]
    
    # Scale search to handle different OS scaling / app zoom levels
    for s in (0.75, 0.85, 1.0, 1.15, 1.25):
        tw_s, th_s = max(1, int(tw * s)), max(1, int(th * s))
        t_resized = cv2.resize(tmpl, (tw_s, th_s))
        res = cv2.matchTemplate(screen_arr, t_resized, cv2.TM_CCOEFF_NORMED)
        
        # We might have multiple set buttons — find all above threshold and pick nearest
        locs = np.where(res >= 0.65)
        for loc_y, loc_x in zip(*locs):
            val = res[loc_y, loc_x]
            cx = loc_x + tw_s // 2
            cy = loc_y + th_s // 2
            
            # Left panel avoidance
            if cx < left_boundary:
                continue
                
            # If coordinates provided, require proximity (within ~150px horizontally, ~100px vertically)
            if near_x is not None and near_y is not None:
                dx, dy = abs(cx - near_x), abs(cy - near_y)
                if dx > 150 or dy > 100:
                    continue
            
            if val > best_val:
                best_val, best_loc = val, (cx, cy)
                best_tw, best_th = tw_s, th_s

    if best_val < 0.6:
        return None

    cx, cy = best_loc
    print(f"[runner] Set button found at ({cx}, {cy}) confidence={best_val:.2f}")
    return (cx, cy)


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
    print(f"[runner] Waiting for UI change (timeout={timeout}s)...", end="", flush=True)
    baseline = pyautogui.screenshot()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.1)
        curr = pyautogui.screenshot()
        if _ui_changed(baseline, curr):
            print(" detected.")
            return True
    print(" timeout.")
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
        x, y = _find(target, action.get("hint"), action=action)
        return {**action, "x": x, "y": y}

    if kind == "type":
        field_target = action["field_target"]
        kb = detector.get_kb_entry(field_target) or {}
        requires_set = kb.get("requires_set_button", False)

        if _is_auto_populated(field_target):
            return {**action, "_skip": True}
        # Autofocus fields are already focused — no click needed, just clear + paste
        if _is_autofocus(field_target):
            return {**action, "x": None, "y": None, "_needs_click": False, "requires_set_button": requires_set}
        # Locate target input box
        result = find_input_field(_screenshot(), field_target)
        if result:
            return {**action, "x": result[0], "y": result[1], "_needs_click": True, "requires_set_button": requires_set}
        print(f"[runner] Could not locate input for '{field_target}' — will type into focused element")
        return {**action, "x": None, "y": None, "_needs_click": False, "requires_set_button": requires_set}

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
        _trigger_pre_move()
        pyautogui.moveTo(x, y, duration=0.3)
        time.sleep(0.3)  # wait for hover-reveal buttons (e.g. flow canvas +)
        pyautogui.click(x, y)

    elif kind == "type":
        # If a "Set" button is visible and required, click it FIRST to activate the input field
        if action.get("requires_set_button"):
            set_pos = _find_set_button(near_x=x, near_y=y)
            if set_pos:
                _trigger_pre_move()
                pyautogui.moveTo(set_pos[0], set_pos[1], duration=0.2)
                pyautogui.click(set_pos[0], set_pos[1])
                wait_ui_change(timeout=2.0)
        
        # Then click the target input field (always, to ensure focus before typing)
        if action.get("_needs_click") and x is not None and y is not None:
            _trigger_pre_move()
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click(x, y)
            wait_ui_change(timeout=2.0)
            
        # Always select-all to clear any pre-filled content before pasting
        pyautogui.hotkey("command", "a")
        time.sleep(0.1)
        _paste(action["value"])

    elif kind == "select":
        _trigger_pre_move()
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
        _trigger_pre_move()
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
