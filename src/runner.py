from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import pyautogui
from PIL import Image

<<<<<<< HEAD
from src.detector import ElementNotFoundError, find_element, find_input_field, is_text_visible_near
=======
from src.detector import ElementNotFoundError, find_element, find_input_field
<<<<<<< HEAD
>>>>>>> 9e44480 (Light (#6))
=======
<<<<<<< HEAD
>>>>>>> ee262bc (improved text files)

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


<<<<<<< HEAD
def detect_theme() -> str:
    """Identify if the target app is in 'light' or 'dark' mode."""
    from src.detector import _is_light_mode
    screenshot = _screenshot()
    return "light" if _is_light_mode(screenshot) else "dark"


=======
>>>>>>> 9e44480 (Light (#6))
def _find(target: str, hint: str | None = None, action: dict | None = None,
          step_title: str = "", action_index: int = 0) -> tuple[int, int]:
    screenshot = _screenshot()
    try:
        return find_element(screenshot, target, hint)
    except ElementNotFoundError:
        pass

    # OCR failed — hand off to healer for diagnosis + escalating retry
    from src import healer
=======
>>>>>>> 7d1f240 (improved text files)

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


<<<<<<< HEAD
def _ui_changed(before: Image.Image, after: Image.Image, threshold: float = 0.001) -> bool:
    """Return True if more than `threshold` fraction of pixels changed between screenshots."""
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


def _find_set_button() -> tuple[int, int] | None:
    """Use OpenCV template matching to find the Set button on screen."""
    import cv2
    from pathlib import Path as _Path

    icon_path = _Path(__file__).parent.parent / "kb" / "icons" / "Set.png"
    if not icon_path.exists():
        return None

    screenshot = pyautogui.screenshot()
    screen_arr = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    tmpl = cv2.cvtColor(cv2.imread(str(icon_path)), cv2.COLOR_BGR2GRAY)

    best_val, best_loc = -1.0, (0, 0)
    th, tw = tmpl.shape[:2]
    for s in (1.0, 0.75, 1.25):
        tw_s, th_s = max(1, int(tw * s)), max(1, int(th * s))
        t_resized = cv2.resize(tmpl, (tw_s, th_s))
        res = cv2.matchTemplate(screen_arr, t_resized, cv2.TM_CCOEFF_NORMED)
        _, val, _, loc = cv2.minMaxLoc(res)
        if val > best_val:
            best_val, best_loc = val, loc
            best_tw, best_th = tw_s, th_s

    if best_val < 0.6:
        return None

    cx = best_loc[0] + best_tw // 2
    cy = best_loc[1] + best_th // 2
    print(f"[runner] Set button found at ({cx}, {cy}) confidence={best_val:.2f}")
    return (cx, cy)
<<<<<<< HEAD
=======
def _activate() -> None:
    subprocess.run(
        ["osascript", "-e", f'activate application "{_TARGET_APP}"'],
        capture_output=True, timeout=5,
    )
    time.sleep(0.3)


<<<<<<< HEAD
def _find(target: str, hint: str | None = None) -> tuple[int, int]:
    for attempt in range(_MAX_RETRIES):
        try:
            return find_element(_screenshot(), target, hint)
        except ElementNotFoundError:
            if attempt < _MAX_RETRIES - 1:
                print(f"[runner] Retry {attempt + 1} for '{target}'...")
                time.sleep(_RETRY_DELAY)
    raise ElementNotFoundError(f"'{target}' not found after {_MAX_RETRIES} attempts")
>>>>>>> 7d1f240 (improved text files)
=======
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
>>>>>>> b856107 (1.0)
=======
>>>>>>> 6e2f95f (add image indentification)


<<<<<<< HEAD

=======
>>>>>>> 9e44480 (Light (#6))
def _paste(value: str) -> None:
    subprocess.run(["pbcopy"], input=value.encode(), check=True)
    pyautogui.hotkey("command", "v")
    time.sleep(0.5)


def _ui_changed(before: Image.Image, after: Image.Image) -> bool:
    a = np.array(before.convert("RGB"), dtype=np.float32)
    b = np.array(after.convert("RGB"), dtype=np.float32)
    return float((np.abs(a - b).mean(axis=2) > 10).mean()) > 0.001
<<<<<<< HEAD


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
    diff = np.abs(a - b).mean(axis=2)          # per-pixel mean RGB channel diff
    changed_fraction = float((diff > 10).mean())  # pixels that changed by >10/255
    return changed_fraction > threshold
=======
>>>>>>> 7d1f240 (improved text files)


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


<<<<<<< HEAD

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
        search_hints = action.get("_search_hints", [])
        component_type = action.get("_component_type")
        placeholder = action.get("_placeholder")
        default_value = action.get("_default_value")

        if action.get("skip_click"):
            # Field was pre-focused by a preceding offset-click — skip detection
            print(f"[runner] Type '{field_target}': field pre-focused, skipping click")
            x, y = pyautogui.position()
            field_found = False
        else:
            field_found = False
            shot = _screenshot()

            # ── Strategy 1: OCR for default_value or placeholder inside the field ──
            # If KB tells us the field has a pre-filled value or placeholder,
            # OCR for that text — it IS inside the field, so clicking it = clicking the field.
            field_content_texts = []
            if default_value and len(default_value) > 1:
                field_content_texts.append(default_value)
            if placeholder and len(placeholder) > 1:
                field_content_texts.append(placeholder)

            for content_text in field_content_texts:
                content_bbox = detector.find_label_bbox_by_ocr(shot, content_text)
                if content_bbox is not None:
                    scale = detector._get_scale_factor(shot)
                    cx = int((content_bbox[0] + content_bbox[2]) / 2 / scale)
                    cy = int((content_bbox[1] + content_bbox[3]) / 2 / scale)
                    x, y = cx, cy
                    field_found = True
                    print(f"[runner] OCR found field content '{content_text}' at ({x}, {y}) — clicking field directly")
                    break

            # ── Strategy 2: Groq Vision 4-corner detection ──
            if not field_found:
                label_bbox = detector.find_label_bbox_by_ocr(shot, field_target)
                groq_result = detector.find_input_field(
                    shot, field_target,
                    component_type=component_type,
                    placeholder=placeholder,
                    label_region=label_bbox,
                )
                if groq_result is not None:
                    x, y = groq_result.center
                    field_found = True
                    print(f"[runner] Groq Vision found input for '{field_target}' at ({x}, {y})")

            # ── Fallback: type into focused field ──
            if not field_found:
                print(f"[runner] '{field_target}' not found — will type into focused field")
                x, y = pyautogui.position()

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
        field_target = entry.get("field_target", "")
        component_type = entry.get("_component_type")
        placeholder = entry.get("_placeholder")
        default_value = entry.get("_default_value")

        def _type_into(fx: int, fy: int) -> None:
            """Clear all content in the field at (fx, fy), then paste value.

            Uses KB default_value knowledge:
            - If the value starts with the default, move to end and type the remainder
            - Otherwise, select all and replace with full value
            """
            # Click to focus
            pyautogui.click(fx, fy)
            time.sleep(0.2)

            # Read current field content via clipboard
            pyautogui.hotkey("end")
            time.sleep(0.05)
            pyautogui.hotkey("shift", "home")
            time.sleep(0.05)
            pyautogui.hotkey("command", "c")
            time.sleep(0.2)
            current_content = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout

            if current_content:
                print(f"[runner] Field contains: '{current_content}'")

            # Decide what to type based on current content and desired value
            type_value = value
            if current_content and value.startswith(current_content) and current_content != value:
                # Value starts with what's already in the field — just append the rest
                type_value = value[len(current_content):]
                pyautogui.hotkey("end")  # deselect, move cursor to end
                time.sleep(0.1)
                print(f"[runner] Appending '{type_value}' after existing '{current_content}'")
            elif current_content and current_content != value:
                # Different content — delete it and type full value
                pyautogui.press("delete")
                time.sleep(0.2)
                print(f"[runner] Cleared '{current_content}', entering '{value}'")
            elif not current_content and default_value and value.startswith(default_value):
                # Field appears empty but KB says it has a default — check if default is still there
                # (placeholder text won't be selected, but default values will be)
                pyautogui.hotkey("end")
                time.sleep(0.05)
                type_value = value[len(default_value):]
                print(f"[runner] Field likely has default '{default_value}', appending '{type_value}'")
            else:
                # Replace selected content
                pass

            subprocess.run(["pbcopy"], input=type_value.encode(), check=True)
            pyautogui.hotkey("command", "v")
            time.sleep(1.0)

        def _type_and_verify(fx: int, fy: int) -> bool:
            """Clear field at (fx, fy), paste value, OCR the field region to verify."""
            import re as _re

            # Take before screenshot for pixel-diff comparison
            before_shot = pyautogui.screenshot()
            _type_into(fx, fy)

            # Take after screenshot
            after_shot = pyautogui.screenshot()

            # Region around the field for verification
            scale = detector._get_scale_factor(after_shot)
            region_radius = 120  # logical px
            phys_cx = int(fx * scale)
            phys_cy = int(fy * scale)
            phys_r = int(region_radius * scale)
            x1 = max(0, phys_cx - phys_r * 2)
            y1 = max(0, phys_cy - phys_r)
            x2 = min(after_shot.width, phys_cx + phys_r * 2)
            y2 = min(after_shot.height, phys_cy + phys_r)

            # Primary: pixel-diff — did the field region change after typing?
            import numpy as _np2
            crop_before = _np2.array(before_shot.crop((x1, y1, x2, y2)).convert("RGB"), dtype=_np2.float32)
            crop_after = _np2.array(after_shot.crop((x1, y1, x2, y2)).convert("RGB"), dtype=_np2.float32)
            diff = _np2.abs(crop_after - crop_before).mean()
            if diff > 3.0:
                print(f"[runner] Pixel-diff verified value entered at ({fx}, {fy}) (diff={diff:.1f})")
                return True

            # Secondary: OCR — look for the exact value text (not just a substring word)
            cropped = after_shot.crop((x1, y1, x2, y2))
            reader = detector._get_ocr_reader()
            results = reader.readtext(_np2.array(cropped))
            # Strip leading punctuation from value for matching
            check_value = _re.sub(r'^[^a-zA-Z0-9]+', '', value).lower()
            for _, txt, conf in results:
                detected = txt.lower().strip()
                # Exact match or detected text IS the value (not a larger word containing it)
                if detected == value.lower() or detected == check_value:
                    print(f"[runner] OCR exact match '{txt}' near ({fx}, {fy}) — verified")
                    return True
                # Value is detected as standalone (not substring of a longer word like HelloWorld)
                if check_value and _re.search(r'\b' + _re.escape(check_value) + r'\b', detected):
                    print(f"[runner] OCR word match '{txt}' near ({fx}, {fy}) — verified")
                    return True

            print(f"[runner] Verification failed: value '{value}' not detected at ({fx}, {fy}) (diff={diff:.1f})")
            return False

        # First attempt — type at detected coordinates
        if not _type_and_verify(x, y):
            # Ask Groq fresh for the field location and retry
            print(f"[runner] Asking Groq for field location of '{field_target}'...")
            fresh_shot = pyautogui.screenshot()
            label_bbox = detector.find_label_bbox_by_ocr(fresh_shot, field_target)
            groq_result = detector.find_input_field(
                fresh_shot, field_target,
                component_type=component_type,
                placeholder=placeholder,
                label_region=label_bbox,
            )
            if groq_result:
                nx, ny = groq_result.center
                print(f"[runner] Groq found field at ({nx}, {ny}) — retrying")
                if not _type_and_verify(nx, ny):
                    print(f"[WARNING] Could not verify '{value}' in field '{field_target}' — continuing")
            else:
                print(f"[WARNING] Groq could not locate '{field_target}' — continuing")

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


=======
>>>>>>> 7d1f240 (improved text files)
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
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD

        # Check for OCR text with click offset (e.g. "Execute Cell" → find "[ ]", click above)
        kb = _kb().get("element_hints", {}).get(target, {})
        if isinstance(kb, dict) and kb.get("type") == "ocr_text_offset":
            ocr_label = kb["label"]
            offset = kb.get("click_offset", {"x": 0, "y": 0})
            print(f"[runner] Finding '{ocr_label}' on screen for '{target}'")
            x, y = _find(ocr_label, action=action)
            return {**action, "x": x + offset["x"], "y": y + offset["y"]}

=======
=======
>>>>>>> ee262bc (improved text files)
=======
>>>>>>> 59739ff (1.0)
=======
=======
>>>>>>> 1b41d5a (feat: implement static source clickability verifier and fix detection issues)
>>>>>>> e68c878 (feat: implement static source clickability verifier and fix detection issues)
        
>>>>>>> 9e44480 (Light (#6))
        # Verify clickability via WSO2 Integrator React source code
        from src.source_verifier import is_clickable
        if not is_clickable(target):
            print(f"[runner] WARNING: Source code check failed. '{target}' is unclickable text (e.g. input label). OpenCV might pick a wild field. Skipping click!")
            return {**action, "x": None, "y": None, "_needs_click": False, "_skip": True}
<<<<<<< HEAD

=======
            
>>>>>>> 9e44480 (Light (#6))
        x, y = _find(target, action.get("hint"), action=action)
=======
        x, y = _find(target, action.get("hint"))
>>>>>>> 7d1f240 (improved text files)
=======
        x, y = _find(target, action.get("hint"), action=action)
>>>>>>> b856107 (1.0)
        return {**action, "x": x, "y": y}

    if kind == "type":
        field_target = action["field_target"]
        if _is_auto_populated(field_target):
            return {**action, "_skip": True}
        # Autofocus fields are already focused — no click needed, just clear + paste
        if _is_autofocus(field_target):
            return {**action, "x": None, "y": None, "_needs_click": False}
<<<<<<< HEAD
<<<<<<< HEAD
        # Locate target input box
=======
        # Ask Groq Vision where to click to focus the actual input box
>>>>>>> 7d1f240 (improved text files)
=======
        # Locate target input box
>>>>>>> 4d665b4 (1.1)
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

<<<<<<< HEAD
    if kind == "search":
        # Find the search input placeholder by field_target label
        from src.detector import find_search_field
        result = find_search_field(_screenshot(), action["field_target"])
        if result:
            return {**action, "x": result[0], "y": result[1]}
        # Fallback: try find_element for the placeholder text
        try:
            x, y = _find(action["field_target"], action=action)
            return {**action, "x": x, "y": y}
        except ElementNotFoundError:
            print(f"[runner] Could not find search field '{action['field_target']}'")
            return {**action, "x": None, "y": None}

=======
>>>>>>> 9e44480 (Light (#6))
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
<<<<<<< HEAD
<<<<<<< HEAD
=======
>>>>>>> 6e2f95f (add image indentification)
        _trigger_pre_move()
<<<<<<< HEAD
        pyautogui.moveTo(x, y, duration=0.3)  # wait for hover-reveal buttons (e.g. flow canvas +)
        pyautogui.click(x, y)

    elif kind == "type":
        # ── NEW: Idempotent Typing (Idempotency) ───────────────────────
        # Skip typing if the value is already present in the field.
        _idemp_x = x if x is not None else 0
        _idemp_y = y if y is not None else 0
        _idemp_token = action["value"].split()[0] if action["value"].split() else action["value"][:12]
        if _idemp_x and _idemp_y and _idemp_token:
            if is_text_visible_near(pyautogui.screenshot(), _idemp_token, _idemp_x, _idemp_y):
                print(f"[runner] Skipping type: '{_idemp_token}' is already visible near ({_idemp_x}, {_idemp_y})")
                return 
        # ───────────────────────────────────────────────────────────────

=======
        pyautogui.moveTo(x, y, duration=0.3)
        time.sleep(0.3)  # wait for hover-reveal buttons (e.g. flow canvas +)
<<<<<<< HEAD
=======
        pyautogui.moveTo(x, y, duration=0.3)
>>>>>>> 7d1f240 (improved text files)
=======
>>>>>>> 32def20 (Enhance UI interaction reliability with click delays, improve icon detection using OCR-anchored template matching and color-aware matching, and add a strategy cache.)
        pyautogui.click(x, y)

    elif kind == "type":
>>>>>>> 9e44480 (Light (#6))
        if action.get("_needs_click") and x is not None and y is not None:
<<<<<<< HEAD
<<<<<<< HEAD
=======
>>>>>>> 6e2f95f (add image indentification)
            _trigger_pre_move()
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click(x, y)
            wait_ui_change(timeout=2.0)
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD

=======
=======
>>>>>>> 7edd6ac (add image indentification)
=======
=======
>>>>>>> 1b41d5a (feat: implement static source clickability verifier and fix detection issues)
>>>>>>> e68c878 (feat: implement static source clickability verifier and fix detection issues)
            
>>>>>>> 9e44480 (Light (#6))
            # If a "Set" button is visible, click it to activate the input field
            set_pos = _find_set_button()
            if set_pos:
                # Prevent wild set clicks by enforcing proximity to the clicked field
                import math
                if math.hypot(set_pos[0] - x, set_pos[1] - y) < 800:
                    pyautogui.moveTo(set_pos[0], set_pos[1], duration=0.2)
                    pyautogui.click(set_pos[0], set_pos[1])
                    wait_ui_change(timeout=2.0)
                else:
                    print(f"[runner] Ignored 'Set' button at {set_pos} (too far from target field)")

<<<<<<< HEAD
=======
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click(x, y)
            wait_ui_change(timeout=2.0)
>>>>>>> 7d1f240 (improved text files)
=======
        # If a "Set" button is visible, click it to activate the input field first
        set_pos = _find_set_button()
        if set_pos:
            _trigger_pre_move()
            pyautogui.moveTo(set_pos[0], set_pos[1], duration=0.2)
            pyautogui.click(set_pos[0], set_pos[1])
            wait_ui_change(timeout=2.0)
>>>>>>> 6e2f95f (add image indentification)
=======
>>>>>>> 1b41d5a (feat: implement static source clickability verifier and fix detection issues)
        # Always select-all to clear any pre-filled content before pasting
        pyautogui.hotkey("command", "a")
        time.sleep(0.1)
        _paste(action["value"])

<<<<<<< HEAD
        # ── Verify the typed text is actually visible in the field ──────────
        # If the first token of the value is not visible near (x, y), the click
        # may not have focused the field.  Reset focus by clicking another field,
        # then re-find and retype.
        _verify_x = x if x is not None else 0
        _verify_y = y if y is not None else 0
        _check_token = action["value"].split()[0] if action["value"].split() else action["value"][:12]
        time.sleep(0.3)
        if _check_token and not is_text_visible_near(pyautogui.screenshot(), _check_token, _verify_x, _verify_y):
            print(f"[runner] Typed text '{_check_token}' not visible near ({_verify_x}, {_verify_y}) — retrying with focus-reset")
            # Click a different field: move to a neutral Y offset above the field
            # (likely hits a label/title area — non-interactive) to reset focus state
            _alt_y = max(50, _verify_y - 120)
            pyautogui.click(_verify_x, _alt_y)
            time.sleep(0.4)
            # Re-detect the field from a fresh screenshot
            field_target = action.get("field_target", "")
            if field_target:
                _retry_pos = find_input_field(pyautogui.screenshot(), field_target)
                if _retry_pos:
                    _rx, _ry = _retry_pos
                    pyautogui.moveTo(_rx, _ry, duration=0.2)
                    pyautogui.click(_rx, _ry)
                    time.sleep(0.3)
                    _set_pos2 = _find_set_button()
                    if _set_pos2:
                        import math as _math
                        if _math.hypot(_set_pos2[0] - _rx, _set_pos2[1] - _ry) < 800:
                            pyautogui.click(_set_pos2[0], _set_pos2[1])
                            time.sleep(0.3)
            pyautogui.hotkey("command", "a")
            time.sleep(0.1)
            _paste(action["value"])
            print(f"[runner] Retry paste complete for '{field_target}'")
        # ─────────────────────────────────────────────────────────────────────

    elif kind == "select":
<<<<<<< HEAD
<<<<<<< HEAD
        _trigger_pre_move()
=======
>>>>>>> 7d1f240 (improved text files)
=======
        _trigger_pre_move()
>>>>>>> 6e2f95f (add image indentification)
        pyautogui.moveTo(x, y, duration=0.2)
        pyautogui.click(x, y)
        time.sleep(0.4)
        # Option will be found live during fire since dropdown just opened
        try:
            ox, oy = find_element(pyautogui.screenshot(), action["value"])
            pyautogui.click(ox, oy)
        except ElementNotFoundError:
            print(f"[runner] Select option '{action['value']}' not found after opening dropdown")

=======
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

>>>>>>> 9e44480 (Light (#6))
    elif kind == "hotkey":
<<<<<<< HEAD
<<<<<<< HEAD
        _trigger_pre_move()
=======
>>>>>>> 7d1f240 (improved text files)
=======
        _trigger_pre_move()
>>>>>>> 6e2f95f (add image indentification)
        pyautogui.hotkey(*action["keys"])

    elif kind == "scroll":
        clicks = action.get("clicks", -3)
        if x is not None:
            pyautogui.scroll(clicks, x=x, y=y)
        else:
            pyautogui.scroll(clicks)

<<<<<<< HEAD
    elif kind == "search":
        _trigger_pre_move()
        if x is not None and y is not None:
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click(x, y)
        else:
            # No coords — try to click a visible search placeholder
            try:
                sx, sy = find_element(pyautogui.screenshot(), "Search")
                pyautogui.moveTo(sx, sy, duration=0.2)
                pyautogui.click(sx, sy)
            except ElementNotFoundError:
                print("[runner] Could not find search box — typing at current focus")
        time.sleep(0.2)
        # Clear any existing text, then type the search value
        pyautogui.hotkey("command", "a")
        time.sleep(0.1)
        _paste(action["value"])
        # Wait for search results to populate
        wait_ui_change(timeout=3.0)
        print(f"[runner] Searched for '{action['value']}' in '{action.get('field_target', 'Search')}'")

=======
>>>>>>> 9e44480 (Light (#6))
    elif kind == "wait":
        time.sleep(action.get("seconds", 1.0))

    else:
        print(f"[runner] Unknown action type: '{kind}'")
