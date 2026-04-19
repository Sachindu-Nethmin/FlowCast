from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import pyautogui
from PIL import Image

from src.detector import ElementNotFoundError, find_element, find_input_field, is_text_visible_near

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


def _get_kb_entry(label: str) -> dict:
    """Retrieve KB metadata for a label using case-insensitive matching."""
    kb = _kb()
    if label in kb:
        return kb[label] if isinstance(kb[label], dict) else {}
    
    # Fallback: Case-insensitive search
    l_lower = label.lower()
    for k, v in kb.items():
        if k.lower() == l_lower:
            return v if isinstance(v, dict) else {}
            
    return {}


def _is_autofocus(field_label: str) -> bool:
    for f in _kb().get("autofocus_fields", {}).get("fields", []):
        if f["label"].lower() == field_label.lower():
            return True
    return False


def _is_smart_input(field_label: str) -> bool:
    """Smart inputs are expression-editor fields opened by a prior click.
    For these, skip find_input_field and Set-button detection — just paste at current focus.
    """
    return any(
        field_label.lower() == s.lower()
        for s in _kb().get("smart_inputs", [])
    )


def _is_no_set_button(field_label: str) -> bool:
    """Fields that are plain textareas / inputs with no Set button (e.g. Instructions).
    Clicking them may cause a UI change (focus indicator) but should never trigger
    Set-button detection, which would accidentally open an expression editor.
    """
    return any(
        field_label.lower() == s.lower()
        for s in _kb().get("no_set_button_fields", [])
    )


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


def detect_theme() -> str:
    """Identify if the target app is in 'light' or 'dark' mode."""
    from src.detector import _is_light_mode
    screenshot = _screenshot()
    return "light" if _is_light_mode(screenshot) else "dark"


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
    print("[runner] WARNING: wait_ui_change - no change detected within timeout, continuing execution")
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

        # Check for OCR text with click offset (e.g. "Execute Cell" → find "[ ]", click above)
        kb = _kb().get("element_hints", {}).get(target, {})
        
        # PROACTIVE REVEAL: For '+' buttons that require a hover/click to appear (e.g. near Error Handler),
        # perform the reveal action BEFORE attempting to find the target.
        if target.strip() == "+" and isinstance(kb, dict) and "reveal_anchor" in kb:
            anchor = kb["reveal_anchor"]
            print(f"[runner] Proactively revealing '+' via anchor '{anchor}'...")
            try:
                # We need to find the anchor node first via OCR to get center coords for the reveal helper
                ax, ay = find_element(_screenshot(), anchor)
                result = _reveal_plus_on_error_handler(ax, ay)
                if result:
                    rx, ry = result
                    return {
                        **action,
                        "x": rx, "y": ry,
                        "_reveal_anchor_x": ax, "_reveal_anchor_y": ay,
                        "reveal_anchor": anchor,
                        "_needs_reveal_hover": False # Already revealed!
                    }
            except Exception as e:
                print(f"[runner] Proactive reveal failed: {e}. Falling back to normal detection.")

        # OCR text offset (e.g. Execute Cell -> find '[ ]', click above)
        if isinstance(kb, dict) and kb.get("type") == "ocr_text_offset":
            ocr_label = kb["label"]
            offset = kb.get("click_offset", {"x": 0, "y": 0})
            print(f"[runner] Finding '{ocr_label}' on screen for '{target}' (offset: {offset})")
            try:
                x, y = _find(ocr_label, action=action)
            except Exception:
                print(f"[runner] OCR failed for '{ocr_label}', trying icon template for '{target}'...")
                # Try template match for target name if OCR label failed
                x, y = _find(target, action=action)
            
            return {**action, "x": x + offset["x"], "y": y + offset["y"]}

        # Handle card elements (e.g., Automation, HTTP Service, API cards in picker)
        # Cards are larger clickable areas — find the text label and click on the card
        if isinstance(kb, dict) and kb.get("type") == "card":
            card_label = kb["label"]
            print(f"[runner] Finding card '{card_label}' for '{target}'")
            x, y = _find(card_label, action=action)
            # Card click is slightly offset to ensure we hit the card, not just the text
            offset = kb.get("click_offset", {"x": 0, "y": 0})
            return {**action, "x": x + offset["x"], "y": y + offset["y"]}

        # Verify clickability via WSO2 Integrator React source code
        from src.source_verifier import is_clickable
        if not is_clickable(target):
            print(f"[runner] WARNING: Source code check failed. '{target}' is unclickable text (e.g. input label). OpenCV might pick a wild field. Skipping click!")
            return {**action, "x": None, "y": None, "_needs_click": False, "_skip": True}

        x, y = None, None
        try:
            x, y = _find(target, action.get("hint"), action=action)
        except Exception:
            # Fallback check for hover-reveal items (like the '+' button revealed by Error Handler)
            if kb and isinstance(kb, dict) and "reveal_anchor" in kb:
                anchor = kb["reveal_anchor"]
                offset = kb.get("reveal_offset", {"x": 0, "y": 0})
                print(f"[runner] '{target}' not found. Attempting reveal via anchor '{anchor}'...")
                try:
                    ax, ay = _find(anchor, action=action)
                    # Return anchor position with flag and offset
                    return {
                        **action, 
                        "x": ax + offset["x"], 
                        "y": ay + offset["y"],
                        "_reveal_anchor_x": ax,
                        "_reveal_anchor_y": ay,
                        "reveal_anchor": anchor,
                        "reveal_offset": offset,
                        "_needs_reveal_hover": True
                    }
                except Exception as e:
                    print(f"[runner] Reveal fallback failed: anchor '{anchor}' also not found.")
                    raise e
        # Final pass: Apply any click offsets defined in KB (e.g. Execute Cell)
        if isinstance(kb, dict) and "click_offset" in kb:
            off = kb["click_offset"]
            x += off.get("x", 0)
            y += off.get("y", 0)

        return {**action, "x": x, "y": y}

    if kind == "type":
        field_target = action["field_target"]
        if _is_auto_populated(field_target):
            return {**action, "_skip": True}
        # Locate target input box
        result = find_input_field(_screenshot(), field_target)
        if result:
            # Smart inputs and plain textareas both skip Set-button detection.
            skip_set = _is_smart_input(field_target) or _is_no_set_button(field_target)
            return {**action, "x": result[0], "y": result[1], "_needs_click": True, "_skip_set_button": skip_set}
        print(f"[runner] ABORT: Could not locate input for '{field_target}' — skipping to prevent wrong-field write")
        return {**action, "_skip": True, "_detection_failed": True}

    if kind == "select":
        x, y = _find(action["field_target"])
        return {**action, "x": x, "y": y}

    if kind == "scroll":
        target = action.get("target", "")
        if target:
            x, y = _find(target)
            return {**action, "x": x, "y": y}
        return action

    if kind == "search":
        # Find the search input placeholder by field_target label
        from src.detector import find_search_field
        result = find_search_field(_screenshot(), action["field_target"], hint=action.get("hint"))
        if result:
            return {**action, "x": result[0], "y": result[1]}
        # Fallback: try find_element for the placeholder text
        try:
            x, y = _find(action["field_target"], action=action)
            return {**action, "x": x, "y": y}
        except ElementNotFoundError:
            print(f"[runner] Could not find search field '{action['field_target']}'")
            return {**action, "x": None, "y": None}

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
        if action.get("_needs_reveal_hover"):
            ax, ay = action["_reveal_anchor_x"], action["_reveal_anchor_y"]
            # Use reveal offset from KB if available, fallback to -35 (blue connector line)
            offset = action.get("reveal_offset", {"x": 0, "y": -35})
            reveal_x = ax + offset.get("x", 0)
            reveal_y = ay + offset.get("y", 0)

            print(f"[runner] Hover-to-reveal: targeting reveal point at ({reveal_x}, {reveal_y})")
            pyautogui.moveTo(reveal_x, reveal_y, duration=0.4)
            time.sleep(0.6)  # Wait for hover animation/popup to appear

            # Real-time visual scan for the newly revealed target (e.g. '+' button)
            target_label = action.get("target", "+")
            visual_found = False

            # SPECIAL CASE: For '+' button revealed by 'Error Handler', use the fixed 40px offset 
            # as requested to ensure absolute precision (every time, skip visual jitter).
            is_error_handler_plus = (target_label == "+" and action.get("reveal_anchor") == "Error Handler")

            if is_error_handler_plus:
                result = _reveal_plus_on_error_handler(ax, ay)
                if result:
                    x, y = result
                    visual_found = True
            else:
                detection_attempts = 0
                max_attempts = 3

                while detection_attempts < max_attempts:
                    try:
                        # Attempt visual re-detection with fresh screenshot
                        rx, ry = find_element(_screenshot(), target_label, action.get("hint"))
                        x, y = rx, ry
                        print(f"[runner] Visual scan found '{target_label}' at ({x}, {y}) on attempt {detection_attempts + 1}")
                        visual_found = True
                        break
                    except Exception as e:
                        detection_attempts += 1
                        if detection_attempts < max_attempts:
                            print(f"[runner] Visual scan attempt {detection_attempts} failed, retrying...")
                            time.sleep(0.2)

            if not visual_found:
                # Fallback: use the reveal offset from KB
                print(f"[runner] Visual scan exhausted ({max_attempts} attempts). Using predicted offset coordinates.")
                offset = action.get("reveal_offset", {"x": 0, "y": 0})
                x = ax + offset.get("x", 0)
                y = ay + offset.get("y", 0)
                print(f"[runner] Fallback to offset coordinates: ({x}, {y})")

        pyautogui.moveTo(x, y, duration=0.3)
        pyautogui.click(x, y)

    elif kind == "type":
        if x is not None and y is not None:
            _trigger_pre_move()
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click(x, y)
            ui_changed = wait_ui_change(timeout=2.0)

            # Only look for a "Set" button if the field click caused a UI change
            # (meaning the Set button may have appeared). If nothing changed, the
            # field is directly editable and there is no Set button to click.
            if ui_changed and not action.get("_skip_set_button"):
                set_pos = _find_set_button()
                if set_pos:
                    import math
                    if math.hypot(set_pos[0] - x, set_pos[1] - y) < 800:
                        pyautogui.moveTo(set_pos[0], set_pos[1], duration=0.2)
                        pyautogui.click(set_pos[0], set_pos[1])
                        wait_ui_change(timeout=2.0)
                    else:
                        print(f"[runner] Ignored 'Set' button at {set_pos} (too far from target field)")

        # Always select-all to clear any pre-filled content before pasting
        pyautogui.hotkey("command", "a")
        time.sleep(0.3)
        _paste(action["value"])

        # ─────────────────────────────────────────────────────────────────────
        
        # ── 3. Post-type dismissal (e.g. for dropdowns that cover Save) ──────
        # Fail-safe: Detect if this is Target Type or Response Type via string matching
        # as well as Knowledge Base lookup.
        label = action.get("field_target", "")
        kb_entry = _get_kb_entry(label)
        
        is_target_type = any(key in label.lower() for key in ["target type", "response type"])
        
        if label:
            offset_y = None
            if "post_type_click_offset" in kb_entry:
                offset_y = kb_entry["post_type_click_offset"].get("y")
            elif is_target_type:
                offset_y = -20 # Fallback default for known sticky dropdowns
                
            if offset_y is not None and x is not None and y is not None:
                dismiss_x = x
                dismiss_y = y + offset_y
                print(f"[runner] Targeted field '{label}' detected. Performing mandatory dismissal click at ({dismiss_x}, {dismiss_y})")
                pyautogui.click(dismiss_x, dismiss_y)
                time.sleep(0.3)
        # ─────────────────────────────────────────────────────────────────────

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
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.scroll(clicks, x=x, y=y)
        else:
            sw, sh = pyautogui.size()
            cx, cy = sw // 2, sh // 2
            _trigger_pre_move()
            pyautogui.moveTo(cx, cy, duration=0.3)
            pyautogui.scroll(clicks, x=cx, y=cy)

    elif kind == "search":
        _trigger_pre_move()
        if x is not None and y is not None:
            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click(x, y)
        else:
            # No coords — use find_search_field which tries the magnify icon first
            from src.detector import find_search_field
            field_label = action.get("field_target", "Search")
            result = find_search_field(_screenshot(), field_label, hint=action.get("hint"))
            if result:
                sx, sy = result
                pyautogui.moveTo(sx, sy, duration=0.2)
                pyautogui.click(sx, sy)
            else:
                print("[runner] Could not find search box — typing at current focus")
        time.sleep(0.2)
        # Clear any existing text, then type the search value
        pyautogui.hotkey("command", "a")
        time.sleep(0.1)
        _paste(action["value"])
        # Wait for search results to populate
        wait_ui_change(timeout=3.0)
        print(f"[runner] Searched for '{action['value']}' in '{action.get('field_target', 'Search')}'")

    elif kind == "wait":
        time.sleep(action.get("seconds", 1.0))

    else:
        print(f"[runner] Unknown action type: '{kind}'")

def _reveal_plus_on_error_handler(ax: int, ay: int) -> tuple[int, int] | None:
    """Specialized 2-step interaction to reveal and click the '+' button near an Error Handler node.
    
    Step 1: Locates the Error Handler icon (shield) via theme-aware template matching with a left-bias.
    Step 2: Clicks 40px above the shield to reveal the '+'.
    Step 3: Performs a visual scan for the '+' button in the revealed zone.
    """
    from src.detector import find_template_on_screen
    # Update screenshot for fresh detection
    screen = _screenshot()
    eh_pos = None
    icons_dir = Path(__file__).parent.parent / "kb" / "icons"
    
    # Biased search: EH icon is to the LEFT of the text.
    # Ensure we use a wide enough region to find the shield.
    search_region = (ax - 280, ay - 120, ax + 100, ay + 120)
    
    # Theme-aware detection: try both but prefer strict matching
    for icon_name in ["error_handler_dark.png", "error_handler_light.png"]:
        eh_pos = find_template_on_screen(screen, icons_dir / icon_name, threshold=0.65, search_region=search_region)
        if eh_pos:
            print(f"[runner] SUCCESS: Found EH icon ({icon_name}) at {eh_pos}")
            break
    
    if eh_pos:
        ex, ey = eh_pos
        # Step 1 Click: 40px above the shield (the blue connector line)
        # The blue line is centered above the shield icon, no extra x-offset needed.
        print(f"[runner] Reveal Step: Clicking 40px above EH Icon at ({ex}, {ey - 40})")
        pyautogui.click(ex, ey - 40)
        time.sleep(1.0) # Wait for animation
        
        # Step 2: Scan for revealed '+'
        # Use a slightly more relaxed threshold in the localized revealed zone
        plus_region = (ex - 60, ey - 90, ex + 60, ey - 10)
        plus_pos = find_template_on_screen(_screenshot(), icons_dir / "plus.png", threshold=0.55, search_region=plus_region)
        if plus_pos:
            print(f"[runner] SUCCESS: Found revealed '+' icon at {plus_pos}")
            return plus_pos
        else:
            print(f"[runner] '+' icon not seen after reveal. Using predicted coordinate ({ex}, {ey - 40}).")
            return (ex, ey - 40)
    else:
        # Fallback: OCR 'Error Handler' text is to the right of the icon.
        # Shifting ax by -80px to the left aligns the click with the icon/blue-line area.
        print(f"[runner] EH icon NOT found near anchor. Falls back to -80px offset from OCR text at ({ax-80}, {ay-40}).")
        return (ax - 80, ay - 40)
