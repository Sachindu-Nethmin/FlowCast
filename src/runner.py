from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import pyautogui
from PIL import Image

from src.detector import (ElementNotFoundError, find_element, find_element_candidates,
                          find_input_field, is_text_visible_near)

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

# Outcome report of the last fire() call. Keys:
#   blue_selection — typed text ended up blue-highlighted (wrong field focus)
LAST_REPORT: dict = {}


# Enable visual debugging for input detection
from src import detector, fastcap
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
    # Nearly always WSO2 Integrator is in front already; AppleScript plus the
    # settle pause cost ~0.5 s before every screenshot for nothing.
    if fastcap.front_app() == _TARGET_APP:
        return
    subprocess.run(
        ["osascript", "-e", f'activate application "{_TARGET_APP}"'],
        capture_output=True, timeout=5,
    )
    time.sleep(0.3)


# Every screenshot in the recording loop (the UI change / settle checks take
# several per action) goes through Quartz: 0.05 s instead of 0.45 s.
_slow_screenshot = pyautogui.screenshot


def _quick_screenshot(*args, **kwargs):
    if not args and not kwargs:
        shot = fastcap.screenshot()
        if shot is not None:
            return shot
    return _slow_screenshot(*args, **kwargs)


pyautogui.screenshot = _quick_screenshot


def _select_all() -> None:
    """⌘A as separate key events with pauses. pyautogui.hotkey sometimes lands
    as a plain "a" while the Mac is busy recording — a field holding "/tmp"
    became "/tmpa/tmp"."""
    pyautogui.keyDown("command")
    time.sleep(0.06)
    pyautogui.press("a")
    time.sleep(0.06)
    pyautogui.keyUp("command")
    time.sleep(0.2)


def _field_words(x: int, y: int) -> list[str] | None:
    """Words read by OCR along the input at (x, y) — None when nothing is read.
    A value sits left-aligned in its box, so the whole band is read."""
    try:
        time.sleep(0.15)
        shot = pyautogui.screenshot()
        sw, _ = screen_size()
        k = shot.width / sw
        box = (max(0, int((x - 380) * k)), max(0, int((y - 20) * k)),
               min(shot.width, int((x + 380) * k)), min(shot.height, int((y + 20) * k)))
        band = shot.crop(box).convert("RGB")
        # Enlarged: OCR on a thin strip of small text misreads ("/tmp" → "/tmo").
        band = band.resize((band.width * 2, band.height * 2), Image.LANCZOS)
        from src.ocr_engine import read_text
        # A focused field shows the text cursor, which OCR reads as "|".
        words = [str(t).strip().strip("|").strip() for _b, t, c in read_text(band)
                 if c >= 0.3 and str(t).strip().strip("|").strip()]
    except Exception:
        return None
    return words or None


def _holds(words: list[str] | None, value: str) -> bool:
    return bool(words) and value.strip() in words


def _mangled(words: list[str] | None, value: str) -> bool:
    """The value is there but with something else stuck to it ("/tmpa/tmp")."""
    v = value.strip()
    return bool(words) and v not in words and any(v in w and w != v for w in words)


def _notch_px() -> int:
    """Height of the black strip a notched display keeps above a full-screen
    app (its safe-area inset), in screen pixels — 0 without a notch."""
    try:
        from AppKit import NSScreen
        s = NSScreen.mainScreen()
        return int(round(s.safeAreaInsets().top * s.backingScaleFactor()))
    except Exception:
        return 0


def _set_menu_crop(native: bool) -> None:
    """The recorder crops the menu bar off the top of every frame. In native
    full screen there is no menu bar — only, on a notched MacBook, a black
    strip beside the notch, which is cropped instead (it showed as a black bar
    across the top of the video). Restored when we fall back to a window."""
    from src import recorder
    recorder.MENU_BAR_H = _notch_px() if native else recorder.DEFAULT_MENU_BAR_H


def ensure_fullscreen(force: bool = False) -> None:
    """ALWAYS make sure the WSO2 Integrator window is up and fills the screen.

    Un-hides the app and un-minimises its windows FIRST: a run that was
    aborted during the between-step prompt (src/step_input.py) leaves the
    window in the Dock, and nothing else would bring it back — the next run
    would happily record an empty desktop. Then sets position+size on the
    largest window. Never gives up — always retries on every call.

    Without `force`, a window that is already within ~10% of the screen is
    left where it is, which keeps the common case cheap. That tolerance is
    wrong at the START of a run: a 1400x900 window on a 1512x982 screen
    passes it, so every recording comes out a slightly different size.
    `force=True` skips the check and always sets position+size.
    """
    _activate()
    w, h = pyautogui.size()
    # force → always resize; otherwise only when the window is visibly smaller.
    # Leave a strip free on the right for an iPhone Mirroring window, so one
    # screen recording can show the phone and the app it is driving. Native
    # full screen takes over its own Space and cannot share the screen with
    # anything, so asking for an inset turns it off.
    inset = max(0, int(os.environ.get("FLOWCAST_WINDOW_INSET_RIGHT", "0") or 0))
    target_w = max(600, w - inset)
    size_is_wrong = "true" if force else (
        f"(item 1 of s) < {int(target_w * 0.90)} or (item 2 of s) < {int(h * 0.85)}")
    # Setting position+size only fills the *usable* desktop: macOS keeps the
    # window clear of the menu bar and Dock, which cost ~98px of a 982px
    # screen. Native full screen (AXFullScreen) hides both and is what the
    # recordings should show. Set FLOWCAST_NATIVE_FULLSCREEN=0 to opt out.
    want_native = ("true" if force and not inset and os.environ.get(
        "FLOWCAST_NATIVE_FULLSCREEN", "1") != "0" else "false")
    if inset:
        print(f"[runner] Reserving {inset}px on the right — window {target_w}x{h}, "
              f"native full screen off")

    # IMPORTANT: target the LARGEST window, not "window 1". VS Code-based apps
    # keep tiny auxiliary windows (tooltips/panels — e.g. a 1512x33 strip) that
    # can be "window 1"; resizing that one loops forever while the real window
    # is untouched. Also: coerce AppleScript numbers with "as integer as text"
    # — `(item 1 of s) & "x"` builds a LIST ("1512, x…"), which broke parsing.
    script = f'''
    tell application "System Events" to tell process "{_TARGET_APP}"
        set visible to true
        set didRestore to false
        repeat with win in windows
            try
                if value of attribute "AXMinimized" of win is true then
                    set value of attribute "AXMinimized" of win to false
                    set didRestore to true
                end if
            end try
        end repeat
        -- Only pay for the un-minimise animation when there was one.
        if didRestore then delay 0.9
        set best to missing value
        set bestArea to 0
        repeat with win in windows
            set s to size of win
            set a to (item 1 of s) * (item 2 of s)
            if a > bestArea then
                set bestArea to a
                set best to win
            end if
        end repeat
        if best is missing value then return "nowin"
        -- Already in native full screen: report it on EVERY call. The light
        -- per-action check used to fall through to "ok", which reset the
        -- recorder to cropping a menu bar that is not there — every clip but
        -- a step's first lost the top of the app.
        try
            if value of attribute "AXFullScreen" of best is true then
                set sf to size of best
                return "full:" & ((item 1 of sf) as integer as text) & "x" & ((item 2 of sf) as integer as text)
            end if
        end try
        if {want_native} then
            try
                if value of attribute "AXFullScreen" of best is not true then
                    set value of attribute "AXFullScreen" of best to true
                    delay 1.6
                end if
                set sf to size of best
                return "full:" & ((item 1 of sf) as integer as text) & "x" & ((item 2 of sf) as integer as text)
            end try
        end if
        set s to size of best
        if {size_is_wrong} then
            set position of best to {{0, 0}}
            delay 0.2
            set size of best to {{{target_w}, {h}}}
            delay 0.2
            set s2 to size of best
            return "resized:" & ((item 1 of s2) as integer as text) & "x" & ((item 2 of s2) as integer as text)
        end if
        return "ok:" & ((item 1 of s) as integer as text) & "x" & ((item 2 of s) as integer as text)
    end tell'''
    # A VS Code window does not always accept the new size on the first try —
    # it can still be settling from a space change or an un-minimise. Setting
    # it once and printing a warning left the run recording a half-size window,
    # so `force` now checks the result and tries again.
    attempts = 3 if force else 1
    size = "?"
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run(["osascript", "-e", script],
                                    capture_output=True, text=True, timeout=10)
        except Exception as e:
            print(f"[runner] Fullscreen enforcement failed: {e}")
            return
        if result.returncode != 0:
            print(f"[runner] Fullscreen enforcement failed: {result.stderr.strip()}")
            return
        out = result.stdout.strip()
        if out == "nowin":
            print("[runner] Fullscreen: no window found for the app")
            return

        size = out.split(":", 1)[1] if ":" in out else "?"
        if out.startswith("full:"):
            _set_menu_crop(native=True)
            print(f"[runner] Window is full screen at {size}")
            return
        _set_menu_crop(native=False)
        if out.startswith("resized:"):
            print(f"[runner] Window was not full screen — maximized to {size}")
            time.sleep(0.5)
        try:
            nw, nh = (int(v) for v in size.split("x"))
        except ValueError:
            return
        # The menu bar keeps a window a little short of the full height, so
        # compare against the same tolerance the lazy path uses.
        if nw >= int(target_w * 0.90) and nh >= int(h * 0.85):
            return
        if attempt < attempts:
            print(f"[runner] Window stuck at {size} — retrying")
            time.sleep(0.6)

    print(f"[runner] WARNING: main window stuck at {size} (wanted {target_w}x{h}) — "
          f"check Stage Manager, Split View, or a second display")


def minimize_window() -> bool:
    """Get the WSO2 Integrator window off the screen so a terminal prompt is
    reachable — used between recorded steps (see src/step_input.py).

    Tries AXMinimized on the real (largest) window first; a window sitting in
    a native full-screen space cannot be minimized, so that is dropped out of
    full screen first. If the accessibility route fails at all, the app is
    hidden instead (same visible effect, and it always works).
    Returns True if the window is no longer on screen.
    """
    script = f'''
    tell application "System Events" to tell process "{_TARGET_APP}"
        set best to missing value
        set bestArea to 0
        repeat with win in windows
            set s to size of win
            set a to (item 1 of s) * (item 2 of s)
            if a > bestArea then
                set bestArea to a
                set best to win
            end if
        end repeat
        if best is missing value then return "nowin"
        try
            if value of attribute "AXFullScreen" of best is true then
                set value of attribute "AXFullScreen" of best to false
                delay 1.2
            end if
        end try
        try
            set value of attribute "AXMinimized" of best to true
            return "minimized"
        on error errMsg
            return "failed:" & errMsg
        end try
    end tell'''
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=15)
        out = r.stdout.strip()
        if out == "minimized":
            time.sleep(0.6)
            return True
        if out == "nowin":
            return False          # app not running yet — nothing to move
        print(f"[runner] Could not minimize the window ({out or r.stderr.strip()}) "
              f"— hiding the app instead")
    except Exception as e:
        print(f"[runner] Minimize failed ({e}) — hiding the app instead")

    # Fallback: hide the application (cmd+H equivalent).
    try:
        subprocess.run(
            ["osascript", "-e",
             f'tell application "System Events" to set visible of process "{_TARGET_APP}" to false'],
            capture_output=True, text=True, timeout=10)
        time.sleep(0.5)
        return True
    except Exception as e:
        print(f"[runner] Could not hide {_TARGET_APP}: {e}")
        return False


def restore_window() -> None:
    """Undo minimize_window(): bring the window back, full screen, ready to
    record. ensure_fullscreen() does the un-hiding and un-minimising itself,
    so this is just it plus time for the window to actually settle."""
    ensure_fullscreen(force=True)
    time.sleep(0.6)


def detect_theme() -> str:
    """Identify if the target app is in 'light' or 'dark' mode."""
    from src.detector import _is_light_mode
    screenshot = _screenshot()
    return "light" if _is_light_mode(screenshot) else "dark"


def screen_size() -> tuple[int, int]:
    return pyautogui.size()


def _find(target: str, hint: str | None = None, action: dict | None = None,
          step_title: str = "", action_index: int = 0) -> tuple[int, int]:
    screenshot = _screenshot()

    # Element hints FIRST: hardcoded positions/icons take priority over
    # learned KB positions (which can be wrong from bad past runs).
    # Case-insensitive lookup: "play" matches "Play".
    hints = _kb().get("element_hints", {})
    kb = hints.get(target, {})
    if not kb:
        target_low = target.lower().strip()
        for k, v in hints.items():
            if k.lower().strip() == target_low:
                kb = v
                break
    if isinstance(kb, dict) and kb.get("type") == "icon" and "position" in kb:
        pos = kb["position"]
        print(f"[runner] Icon '{target}' at hardcoded position ({pos['x']}, {pos['y']})")
        return (pos["x"], pos["y"])

    # Learned KB: if a previous run already learned what this target
    # means on THIS screen, use it.
    #   1. Alias (doc label → actual UI label, e.g. 'Get Started' → 'Skip for
    #      now'): re-resolved by OCR each run — robust to layout changes.
    #   2. Position (verified via nearby OCR for text targets; symbols like
    #      '+' trust the learned point directly).
    try:
        from src import kb_learn
        alias = kb_learn.lookup_alias(screenshot, target)
        if alias:
            try:
                pos = find_element(screenshot, alias, hint)
                print(f"[runner] Learned alias: '{target}' → '{alias}' at {pos}")
                return pos
            except ElementNotFoundError:
                print(f"[runner] Alias '{alias}' not on screen — trying other strategies")
        learned = kb_learn.lookup(screenshot, target, screen_size())
        if learned:
            if len(target.strip()) <= 2 or is_text_visible_near(
                    screenshot, target, learned[0], learned[1], radius=150):
                print(f"[runner] Using learned position for '{target}': {learned}")
                return learned
            print(f"[runner] Learned position for '{target}' failed OCR verification — re-detecting")
    except Exception:
        pass

    try:
        return find_element(screenshot, target, hint)
    except ElementNotFoundError:
        pass

    # OCR failed — hand off to healer for diagnosis + escalating retry
    from src import healer
    import numpy as np
    from src.detector import _read_ocr
    arr = np.array(screenshot)
    ocr_results = _read_ocr(arr)
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


def wait_ui_change(timeout: float = 5.0, baseline: Image.Image | None = None) -> bool:
    """Wait until the screen visually changes.

    Returns True if a change was detected, False if timeout elapsed with no change.

    IMPORTANT: pass the PRE-ACTION screenshot as *baseline* when verifying an
    action. Without it, the baseline is captured NOW — after the action — so a
    fast UI transition that already finished looks like "no change" (false
    failure). With a pre-action baseline, an already-completed transition is
    detected immediately.
    """
    if baseline is None:
        baseline = pyautogui.screenshot()
    else:
        # The transition may have already happened — check instantly first.
        if _ui_changed(baseline, pyautogui.screenshot()):
            return True
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

    # Always make the app full screen before any change (30s-memoized, no-op
    # when the window is already maximized).
    if kind not in ("wait", "hotkey", "command", "shell"):
        ensure_fullscreen()

    if kind == "click":
        target = action["target"]

        # Check for OCR text with click offset (e.g. "Execute Cell" → find "[ ]", click above)
        # Case-insensitive lookup
        hints = _kb().get("element_hints", {})
        kb = hints.get(target, {})
        if not kb:
            target_low = target.lower().strip()
            for k, v in hints.items():
                if k.lower().strip() == target_low:
                    kb = v
                    break

        # ICON ELEMENT: If KB has a hardcoded position, use it directly.
        if isinstance(kb, dict) and kb.get("type") == "icon" and "position" in kb:
            pos = kb["position"]
            print(f"[runner] Icon '{target}' at hardcoded position ({pos['x']}, {pos['y']})")
            return {**action, "x": pos["x"], "y": pos["y"]}
        
        # PROACTIVE REVEAL: For '+' buttons that require a hover/click to appear (e.g. near Error Handler),
        # perform the reveal action BEFORE attempting to find the target.
        # Skipped when the action carries a spatial hint (below:/next_to:/...) —
        # the hint names WHERE the '+' is, which beats the KB reveal guess.
        if target.strip() == "+" and isinstance(kb, dict) and "reveal_anchor" in kb \
                and not action.get("hint"):
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
            x, y = x + offset["x"], y + offset["y"]

            # Best-effort: this label can legitimately appear MORE THAN ONCE on
            # screen (e.g. two "Automation" cards). Surface the runner-up
            # position(s) so a caller whose click on (x, y) turns out to be the
            # wrong occurrence can try the other one directly, instead of
            # re-running full detection from scratch. Never lets a detection
            # hiccup here break the primary click above.
            alt_positions: list[tuple[int, int]] = []
            try:
                offset_pos = (x, y)
                candidates = find_element_candidates(_screenshot(), card_label, max_results=3)
                for cx, cy in candidates:
                    cand = (cx + offset["x"], cy + offset["y"])
                    if cand != offset_pos and all(
                            ((cand[0] - p[0]) ** 2 + (cand[1] - p[1]) ** 2) ** 0.5 > 20
                            for p in [offset_pos, *alt_positions]):
                        alt_positions.append(cand)
            except Exception as e:
                print(f"[runner] (non-fatal) could not compute alt positions for '{card_label}': {e}")

            return {**action, "x": x, "y": y, "_alt_positions": alt_positions}

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

        # Never return a click with no coordinates — firing would click at the
        # CURRENT mouse position (a phantom click on a random spot).
        if x is None or y is None:
            raise ElementNotFoundError(f"Could not find '{target}' — refusing blind click")

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

    # Reset the outcome report for this action (read by callers/teach mode)
    LAST_REPORT.clear()

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

        value = str(action["value"])
        if x is not None and y is not None and _holds(_field_words(x, y), value):
            # Already holds it (a form's default, e.g. Path = /tmp): typing
            # again is noise in the video, and a slip could double it.
            print(f"[runner] '{action.get('field_target')}' already set to {value!r} — left as is")
        else:
            # Clear any pre-filled content, paste, and check what landed.
            _select_all()
            _paste(value)
            if x is not None and y is not None:
                now = _field_words(x, y)
                if _mangled(now, value):
                    print(f"[runner] field reads {now}, wanted {value!r} — clearing and pasting again")
                    _select_all()
                    _paste(value)

        # ── Wrong-field detection: blue selection band after typing ──────────
        # If the typed text (or surrounding text) is fully blue-highlighted,
        # the value was entered without the correct field focused.
        try:
            from src.detector import is_text_selected_blue
            time.sleep(0.3)
            if x is not None and y is not None and \
                    is_text_selected_blue(pyautogui.screenshot(), x, y):
                LAST_REPORT["blue_selection"] = True
                print("[runner] WARNING: blue selection detected after typing — "
                      "value likely went to the wrong place")
        except Exception:
            pass

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

    elif kind == "shell":
        cmd = action["command"]
        print(f"[runner] shell: {cmd}")
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        out = (r.stdout or r.stderr).strip()
        if out:
            print(f"[runner]   → {out[:200]}")
        if r.returncode != 0:
            raise RuntimeError(f"shell command exited {r.returncode}: {out[:200]}")

    elif kind == "command":
        _trigger_pre_move()
        from src import command_input
        workflow = action.get("_workflow") or ""
        step_title = action.get("_step_title") or ""
        action_index = action.get("_action_index", 0)

        # Auto-replay a previously learned command (no prompting).
        learned = command_input.get_learned(workflow, step_title, action_index) \
            if workflow else None
        if learned:
            print(f"[command_input] Replaying learned command: '{learned}'")
            command_input._run_command_background(learned)
            action["_command_status"] = "replayed"
        else:
            cmd, status = command_input.prompt_for_command(
                action, None, step_title, action_index)
            if status == "skip" or not cmd:
                print("[command_input] Command skipped — no action taken.")
                action["_command_status"] = "skipped"
            else:
                command_input._run_command_background(cmd)
                if workflow:
                    command_input.save_learned(workflow, step_title, action_index, cmd)
                action["_command_status"] = "ran"

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
        # Step 1 Click: 60px above the shield (on the blue connector line)
        # EH node height is ~80px, so 60px above center ensures we hit the line, not the node.
        print(f"[runner] Reveal Step: Clicking 60px above EH Icon at ({ex}, {ey - 60})")
        pyautogui.click(ex, ey - 60)
        time.sleep(1.0) # Wait for animation
        
        # Step 2: Scan for revealed '+'
        # Use a significantly taller search region (250px above EH) to handle sparse flows.
        plus_region = (ex - 80, ey - 250, ex + 80, ey - 30)
        from src.detector import _is_light_mode
        is_light = _is_light_mode(_screenshot())
        plus_icon = "plus_light.png" if is_light else "plus.png"
        
        plus_pos = find_template_on_screen(_screenshot(), icons_dir / plus_icon, threshold=0.4, search_region=plus_region)
        if plus_pos:
            print(f"[runner] SUCCESS: Found revealed '+' icon ({plus_icon}) at {plus_pos}")
            return plus_pos
        else:
            # Fallback coordinate: move slightly higher if icon not seen
            print(f"[runner] '+' icon not seen after reveal in region {plus_region}. Using predicted coordinate ({ex}, {ey - 80}).")
            return (ex, ey - 80)
    else:
        # Fallback: EH icon template not found — use OCR anchor with offsets.
        # The '+' is 220px above and 100px left of the 'Error Handler' OCR text.
        # Fallback: 80px above.
        from src.detector import _is_light_mode
        is_light = _is_light_mode(_screenshot())
        plus_icon = "plus_light.png" if is_light else "plus.png"
        icons_dir = Path(__file__).parent.parent / "kb" / "icons"

        # Attempt 1: 200px above + 90px left of OCR text
        x1, y1 = ax - 90, ay - 200
        search1 = (x1 - 60, y1 - 60, x1 + 60, y1 + 60)
        plus_pos = find_template_on_screen(_screenshot(), icons_dir / plus_icon, threshold=0.4, search_region=search1)
        if plus_pos:
            print(f"[runner] SUCCESS: Found '+' at 220px above + 100px left of OCR at {plus_pos}")
            return plus_pos

        # Attempt 2: 80px above OCR text
        y2 = ay - 80
        search2 = (ax - 120, y2 - 60, ax + 120, y2 + 60)
        plus_pos = find_template_on_screen(_screenshot(), icons_dir / plus_icon, threshold=0.4, search_region=search2)
        if plus_pos:
            print(f"[runner] SUCCESS: Found '+' at 80px above OCR at {plus_pos}")
            return plus_pos

        # Attempt 3: coordinate guess at 200px above + 90px left
        print(f"[runner] '+' icon not found via template. Clicking at ({x1}, {y1}).")
        return (x1, y1)
