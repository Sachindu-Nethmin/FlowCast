from __future__ import annotations

import base64
import io
import json
import os
import re
from pathlib import Path

import numpy as np
import pyautogui
from PIL import Image


class ElementNotFoundError(Exception):
    pass


_ocr_reader = None


def _ocr():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(["en"], gpu=False)
        print("[detector] EasyOCR ready")
    return _ocr_reader


def _scale(screenshot: Image.Image) -> float:
    logical_w, _ = pyautogui.size()
    return screenshot.width / logical_w


def _fuzzy(detected: str, target: str) -> bool:
    d, t = detected.lower().strip(), target.lower().strip()
    if d == t:
        return True
    # Require word-boundary match so "automation" in "myautomation" does NOT match
    if re.search(r'\b' + re.escape(t) + r'\b', d):
        return True
    # OCR may only capture part of a multi-word target — allow detected ⊂ target
    if d in t and len(d) > 2:
        return True
    return False


def _is_blue_background(arr: np.ndarray, bbox) -> bool:
    """Return True if the region around a bounding box has a blue-ish background.

    Buttons in WSO2 Integrator are typically blue — use this to prefer the
    correct match when OCR finds the same text in multiple places.
    """
    import cv2

    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    pad = 6
    x1 = max(0, int(min(xs)) - pad)
    y1 = max(0, int(min(ys)) - pad)
    x2 = min(arr.shape[1], int(max(xs)) + pad)
    y2 = min(arr.shape[0], int(max(ys)) + pad)
    region = arr[y1:y2, x1:x2]
    if region.size == 0:
        return False
    hsv = cv2.cvtColor(region, cv2.COLOR_RGB2HSV)
    # Blue hue in OpenCV HSV: ~100–135 (of 180)
    mask = cv2.inRange(hsv, np.array([100, 80, 80]), np.array([135, 255, 255]))
    blue_ratio = float(mask.sum()) / (255.0 * mask.size)
    return blue_ratio > 0.15


def _alpha_target(target: str) -> str:
    """Return the longest word that contains English letters, ignoring pure symbols.

    e.g. '+ Add Automation'  → 'Automation'
         '+ Add Resources'   → 'Resources'
         '+ WSO2 Integrator' → 'Integrator'
    """
    words = [w for w in target.split() if re.search(r'[a-zA-Z]', w)]
    if not words:
        return target
    return max(words, key=lambda w: sum(c.isalpha() for c in w))


def _find_ocr(screenshot: Image.Image, target: str) -> tuple[int, int] | None:
    arr = np.array(screenshot)
    results = _ocr().readtext(arr)
    scale = _scale(screenshot)

    # For multi-word targets, also try without non-alpha tokens (e.g. strip leading "+")
    clean_target = _alpha_target(target)

    # Collect all fuzzy matches, scoring blue-background ones higher
    # Try both original target and cleaned target (non-alpha tokens stripped)
    candidates: list[tuple[int, int, float, bool]] = []  # (cx, cy, conf, is_blue)
    for bbox, text, conf in results:
        if _fuzzy(text, target) or (clean_target and _fuzzy(text, clean_target)):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            cx = int((min(xs) + max(xs)) / 2 / scale)
            cy = int((min(ys) + max(ys)) / 2 / scale)
            candidates.append((cx, cy, conf, _is_blue_background(arr, bbox)))

    if candidates:
        # Prefer blue background, then highest confidence
        candidates.sort(key=lambda c: (c[3], c[2]), reverse=True)
        cx, cy, conf, is_blue = candidates[0]
        if len(candidates) > 1:
            print(f"[detector] OCR: {len(candidates)} matches for '{target}', picked {'blue' if is_blue else 'highest-conf'} at ({cx}, {cy})")
        return (cx, cy)

    # Multi-word merge: try adjacent OCR boxes using cleaned target
    merge_target = clean_target if clean_target != target else target
    words = merge_target.lower().split()
    if len(words) >= 2:
        for i, (bbox_i, text_i, _) in enumerate(results):
            combined = text_i
            last_bbox = bbox_i
            for bbox_j, text_j, _ in results[i + 1:]:
                gap = bbox_j[0][0] - last_bbox[1][0]
                if gap > 60:
                    break
                combined = combined + " " + text_j
                last_bbox = bbox_j
                if _fuzzy(combined, merge_target):
                    xs = [p[0] for p in bbox_i] + [p[0] for p in last_bbox]
                    ys = [p[1] for p in bbox_i] + [p[1] for p in last_bbox]
                    cx = int((min(xs) + max(xs)) / 2 / scale)
                    cy = int((min(ys) + max(ys)) / 2 / scale)
                    return (cx, cy)

    # Longest-word fallback: search for the most distinctive word in the target
    # Uses similarity matching so typos (e.g. "Resouses" → "Resources") still match
    from difflib import SequenceMatcher

    real_words = [w for w in words if re.search(r'[a-zA-Z]', w)]
    if real_words:
        keyword = max(real_words, key=lambda w: sum(c.isalpha() for c in w))
        kw_candidates: list[tuple[int, int, float, bool]] = []
        for bbox, text, conf in results:
            for ocr_word in text.lower().split():
                if not ocr_word.isalpha():
                    continue
                # Reject words significantly longer than the keyword —
                # prevents "myautomation" (len 12) matching "automation" (len 10).
                # Allow ±1 char for OCR typos (e.g. "Automatoin" still passes).
                if len(ocr_word) > len(keyword) + 1:
                    continue
                similarity = SequenceMatcher(None, keyword, ocr_word).ratio()
                if similarity >= 0.75:
                    xs = [p[0] for p in bbox]
                    ys = [p[1] for p in bbox]
                    cx = int((min(xs) + max(xs)) / 2 / scale)
                    cy = int((min(ys) + max(ys)) / 2 / scale)
                    kw_candidates.append((cx, cy, conf, _is_blue_background(arr, bbox)))
                    break
        if kw_candidates:
            kw_candidates.sort(key=lambda c: (c[3], c[2]), reverse=True)
            cx, cy, _, is_blue = kw_candidates[0]
            print(f"[detector] Longest-word '{keyword}' (~fuzzy) found for '{target}' at ({cx}, {cy}), blue={is_blue}")
            return (cx, cy)

    return None


# ── Knowledge base loaders ────────────────────────────────────────────────────

_KB_HINTS: dict | None = None
_ICON_DATA: dict | None = None


def _load_kb_hints() -> dict:
    global _KB_HINTS
    if _KB_HINTS is None:
        p = Path(__file__).parent.parent / "kb" / "ui_elements.json"
        raw = json.loads(p.read_text()).get("element_hints", {}) if p.exists() else {}
        _KB_HINTS = {k.lower(): v for k, v in raw.items()}
    return _KB_HINTS


def _load_icon_data() -> dict:
    global _ICON_DATA
    if _ICON_DATA is None:
        p = Path(__file__).parent.parent / "kb" / "icon_prompts.json"
        _ICON_DATA = json.loads(p.read_text()) if p.exists() else {}
    return _ICON_DATA


def _load_icon_prompts() -> list:
    return _load_icon_data().get("icons", [])


def _groq_vision_model() -> str:
    return _load_icon_data().get("groq_vision_model", "meta-llama/llama-4-scout-17b-16e-instruct")


def _find_green_play_button(screenshot: Image.Image) -> tuple[int, int] | None:
    """Find the green play/run button in the toolbar using HSV color detection.

    Searches the top toolbar strip for a green-colored icon cluster.
    """
    import cv2

    scale = _scale(screenshot)
    w_l = int(screenshot.width / scale)
    h_l = int(screenshot.height / scale)
    img = np.array(screenshot.resize((w_l, h_l), Image.LANCZOS))

    h, w = img.shape[:2]
    # Build a mask covering the top toolbar and right-side toolbar
    search_mask = np.zeros((h, w), dtype=np.uint8)
    search_mask[:80, :] = 255                # top toolbar strip
    search_mask[:, int(w * 0.6):] = 255     # right-side toolbar

    hsv_full = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)

    # Green hue range in HSV (covers VS Code run-button greens)
    lower = np.array([60, 60, 60])
    upper = np.array([165, 255, 255])
    green_mask = cv2.inRange(hsv_full, lower, upper)
    # Restrict to toolbar areas only
    mask = cv2.bitwise_and(green_mask, search_mask)

    # Find contours of green regions
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Pick the largest green blob
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 4:  # too small — noise
        return None

    M = cv2.moments(largest)
    if M["m00"] == 0:
        return None
    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])
    print(f"[detector] Green play button found at ({cx}, {cy}) via color detection")
    return (cx, cy)


def _find_template(screenshot: Image.Image, target: str, canvas_only: bool = False) -> tuple[int, int] | None:
    """OpenCV multi-scale template matching against the icon file in kb/icons/.

    Returns logical (x, y) of the best match center, or None if no confident match.
    """
    import cv2

    icon_entry = _icon_entry_for(target)
    if not icon_entry or not icon_entry.get("icon_file"):
        return None

    icons_dir = Path(__file__).parent.parent / "kb" / "icons"
    icon_file = icon_entry["icon_file"]
    stem = Path(icon_file).stem

    # Collect all size variants (e.g. play_green_16.png, play_green_18.png …)
    # plus the base file. More variants = better chance of matching screen size.
    candidate_paths = sorted(icons_dir.glob(f"{stem}_*.png")) + \
                      [icons_dir / Path(icon_file).with_suffix(".png"),
                       icons_dir / icon_file]
    icon_paths = [p for p in dict.fromkeys(candidate_paths) if p.exists()]
    if not icon_paths:
        return None

    scale = _scale(screenshot)
    # Work in logical-pixel space: downsample Retina screenshots
    w_l = int(screenshot.width / scale)
    h_l = int(screenshot.height / scale)
    screen_small = screenshot.resize((w_l, h_l), Image.LANCZOS)

    screen_gray = cv2.cvtColor(np.array(screen_small.convert("RGB")), cv2.COLOR_RGB2GRAY)

    # Restrict search area to canvas zone if requested
    x_offset, y_offset = 0, 0
    if canvas_only:
        x_offset = 400
        screen_gray = screen_gray[:, x_offset:]

    best_val, best_loc, best_tw, best_th = -1.0, (0, 0), 1, 1

    for icon_path in icon_paths:
        icon_img = Image.open(icon_path)
        has_alpha = icon_img.mode == "RGBA"
        tmpl_gray = cv2.cvtColor(np.array(icon_img.convert("RGB")), cv2.COLOR_RGB2GRAY)
        # Use alpha channel as mask so transparent pixels don't affect the match
        tmpl_mask = np.array(icon_img.split()[-1]) if has_alpha else None
        th, tw = tmpl_gray.shape[:2]

        for s in (0.5, 0.6, 0.75, 0.85, 1.0, 1.15, 1.25, 1.5):
            tw_s, th_s = max(1, int(tw * s)), max(1, int(th * s))
            if tw_s < 8 or th_s < 8:
                continue
            if tw_s > screen_gray.shape[1] or th_s > screen_gray.shape[0]:
                continue
            tmpl_r = cv2.resize(tmpl_gray, (tw_s, th_s))
            if tmpl_mask is not None:
                mask_r = cv2.resize(tmpl_mask, (tw_s, th_s))
                res = cv2.matchTemplate(screen_gray, tmpl_r, cv2.TM_CCOEFF_NORMED, mask=mask_r)
            else:
                res = cv2.matchTemplate(screen_gray, tmpl_r, cv2.TM_CCOEFF_NORMED)
            _, val, _, loc = cv2.minMaxLoc(res)
            if val > best_val:
                best_val, best_loc, best_tw, best_th = val, loc, tw_s, th_s

    threshold = icon_entry.get("match_threshold", 0.55) if icon_entry else 0.55
    if best_val < threshold:
        print(f"[detector] Template match for '{target}' confidence={best_val:.2f} — below threshold")
        return None

    cx = best_loc[0] + best_tw // 2 + x_offset
    cy = best_loc[1] + best_th // 2 + y_offset
    print(f"[detector] Template match '{target}' at ({cx}, {cy}) confidence={best_val:.2f}")
    return (cx, cy)


def _icon_entry_for(target: str) -> dict | None:
    t = target.lower().strip()
    for entry in _load_icon_prompts():
        label = entry.get("element_label", "").lower()
        if label == t:
            return entry
        # Only fuzzy-match labels that are 3+ chars to prevent short symbols
        # like "+" matching unrelated targets such as "+ Add Resources"
        if len(label) >= 3 and (label in t or t in label):
            return entry
    return None


def _kb_hint(target: str) -> str | None:
    hints = _load_kb_hints()
    t = target.lower().strip()
    # Exact match first
    if t in hints:
        return hints[t]
    # Fuzzy: hint key contained in target or target contained in hint key
    for key, val in hints.items():
        if key in t or t in key:
            return val
    # Word-level: any word from target matches a hint key word
    target_words = set(w for w in t.split() if w.isalpha() and len(w) > 3)
    for key, val in hints.items():
        key_words = set(w for w in key.split() if w.isalpha() and len(w) > 3)
        if target_words & key_words:
            return val
    return None


# ── Groq Vision ───────────────────────────────────────────────────────────────

def _find_groq(screenshot: Image.Image, target: str, hint: str | None) -> tuple[int, int] | None:
    from groq import Groq

    icon_entry = _icon_entry_for(target)

    # For canvas elements, crop to the canvas area (x > CANVAS_X_MIN) so Groq
    # physically cannot return a left-sidebar coordinate.
    CANVAS_X_MIN = 400
    canvas_x_offset = 0
    send_screenshot = screenshot
    if icon_entry and icon_entry.get("position_hint", ""):
        hint_lower = icon_entry["position_hint"].lower()
        is_canvas = any(kw in hint_lower for kw in ("canvas", "flow", "resource flow", "automation flow"))
        if is_canvas:
            w, h = screenshot.size
            canvas_x_offset = CANVAS_X_MIN
            send_screenshot = screenshot.crop((CANVAS_X_MIN, 0, w, h))
            print(f"[detector] Canvas element '{target}' — cropping screenshot to x>{CANVAS_X_MIN}")

    buf = io.BytesIO()
    send_screenshot.save(buf, format="PNG")
    screenshot_b64 = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"

    content: list[dict] = []

    if icon_entry:
        icon_b64 = icon_entry.get("icon_b64")
        prompt = icon_entry["groq_prompt"]

        # Groq Vision only accepts raster images (PNG/JPEG) — skip SVG data URIs
        is_raster_b64 = icon_b64 and not icon_b64.startswith("data:image/svg")
        if is_raster_b64:
            # Send the icon image first so Groq knows exactly what to look for
            content.append({"type": "image_url", "image_url": {"url": icon_b64}})
            content.append({"type": "text", "text": f"This is the icon I am looking for: '{target}'."})
            print(f"[detector] Sending icon image + screenshot to Groq for '{target}'")
        else:
            print(f"[detector] Using icon text prompt for '{target}'")

        content.append({"type": "image_url", "image_url": {"url": screenshot_b64}})
        content.append({"type": "text", "text": f"Now find this icon in the above screenshot of WSO2 Integrator. {prompt} Reply with ONLY: x,y"})
    else:
        # Generic fallback: text-only description
        kb = _kb_hint(target)
        prompt = f"In this screenshot of WSO2 Integrator, find the UI element: '{target}'."
        if kb:
            prompt += f" Location hint: {kb}."
        if hint:
            prompt += f" Additional context: {hint}."
        prompt += " Reply with ONLY the pixel coordinates of its center as: x,y (integers). Nothing else."
        content.append({"type": "image_url", "image_url": {"url": screenshot_b64}})
        content.append({"type": "text", "text": prompt})

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=_groq_vision_model(),
        messages=[{"role": "user", "content": content}],
        temperature=0,
    )
    raw = resp.choices[0].message.content.strip()
    m = re.search(r'(\d+)\s*,\s*(\d+)', raw)
    if not m:
        return None

    px, py = int(m.group(1)), int(m.group(2))
    scale = _scale(screenshot)
    lx, ly = int(px / scale) + canvas_x_offset, int(py / scale)

    return (lx, ly)


# ── Public API ────────────────────────────────────────────────────────────────

def _find_input_by_visual(screenshot: Image.Image, field_label: str) -> tuple[int, int] | None:
    """Locate an input field using its label position as an anchor.

    No external API calls — works entirely locally.
    Strategy:
      1. Find the field label via OCR → defines the search region below it.
      2. OpenCV contour detection in that region — find the widest input-shaped rect.
    """
    import cv2

    arr = np.array(screenshot)
    scale = _scale(screenshot)
    results = _ocr().readtext(arr)

    # ── Step 1: locate field label → defines the search region ───────────────
    label_pos: tuple[int, int] | None = None
    for bbox, text, conf in results:
        if _fuzzy(text, field_label):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            label_pos = (int((min(xs) + max(xs)) / 2), int(max(ys)))
            break

    if label_pos is None:
        return None

    lx, ly = label_pos
    sx1 = max(0, lx - 200)
    sy1 = ly + 2
    sx2 = min(arr.shape[1], lx + 600)
    sy2 = min(arr.shape[0], ly + 90)

    # ── Step 2: OpenCV contour detection in the label region ─────────────────
    region = arr[sy1:sy2, sx1:sx2]
    if region.size == 0:
        return None

    gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 30, 100)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best: tuple[int, int, int, int] | None = None
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w > 80 and 10 < h < 45 and w > h * 3:
            if best is None or w > best[2]:
                best = (x, y, w, h)

    if best:
        x, y, w, h = best
        cx = int((sx1 + x + w / 2) / scale)
        cy = int((sy1 + y + h / 2) / scale)
        print(f"[detector] Contour found input for '{field_label}' at ({cx}, {cy})")
        return (cx, cy)

    # ── Fallback: threshold scan for a lighter/darker input-box region ────────
    # Input boxes often have a slightly different brightness from the panel background.
    gray_region = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
    # Try both light-on-dark and dark-on-light input boxes
    for thresh_val, mode in [(180, cv2.THRESH_BINARY), (80, cv2.THRESH_BINARY_INV)]:
        _, thresh = cv2.threshold(gray_region, thresh_val, 255, mode)
        contours2, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best2 = None
        for cnt in contours2:
            x, y, w, h = cv2.boundingRect(cnt)
            if w > 80 and 10 < h < 45 and w > h * 3:
                if best2 is None or w > best2[2]:
                    best2 = (x, y, w, h)
        if best2:
            x, y, w, h = best2
            cx = int((sx1 + x + w / 2) / scale)
            cy = int((sy1 + y + h / 2) / scale)
            print(f"[detector] Threshold scan found input for '{field_label}' at ({cx}, {cy})")
            return (cx, cy)

    return None


def find_input_field(screenshot: Image.Image, field_label: str) -> tuple[int, int] | None:
    """Find where to click to focus a named input field.

    Tries local visual detection first (OCR + OpenCV), falls back to Groq Vision
    only when the local approach returns no result.
    """
    result = _find_input_by_visual(screenshot, field_label)
    if result:
        return result

    # ── Groq Vision fallback ──────────────────────────────────────────────────
    print(f"[detector] Visual detection failed for '{field_label}', falling back to Groq Vision...")
    from groq import Groq

    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    screenshot_b64 = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"

    kb = _kb_hint(field_label)
    prompt = (
        f"In this screenshot of WSO2 Integrator, I need to type a value into the '{field_label}' input field. "
        f"Where exactly should I click to focus that input box? "
        f"Point to the centre of the actual text input element, NOT its label. "
    )
    if kb:
        prompt += f"Hint: {kb}. "
    prompt += "Reply with ONLY the pixel coordinates as: x,y (integers). Nothing else."

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=_groq_vision_model(),
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": screenshot_b64}},
            {"type": "text", "text": prompt},
        ]}],
        temperature=0,
    )
    raw = resp.choices[0].message.content.strip()
    m = re.search(r'(\d+)\s*,\s*(\d+)', raw)
    if not m:
        print(f"[detector] Groq also failed for '{field_label}': {raw!r}")
        return None

    px, py = int(m.group(1)), int(m.group(2))
    scale = _scale(screenshot)
    coords = (int(px / scale), int(py / scale))
    print(f"[detector] Groq Vision found input for '{field_label}' at {coords}")
    return coords


def find_element(screenshot: Image.Image, target: str, hint: str | None = None) -> tuple[int, int]:
    # Skip OCR only for short symbols (e.g. '+') where OCR finds them in wrong places.
    # For all other targets, try OCR first and fall back to template match then Groq Vision.
    icon_entry = _icon_entry_for(target)
    # Skip OCR for short symbols or entries that explicitly prefer template matching
    skip_ocr = (len(target.strip()) <= 2 and icon_entry is not None) or \
               (icon_entry is not None and icon_entry.get("prefer_template", False))
    canvas_only = False
    if icon_entry and icon_entry.get("position_hint", ""):
        hint_lower = icon_entry["position_hint"].lower()
        canvas_only = any(kw in hint_lower for kw in ("canvas", "flow", "resource flow", "automation flow"))

    if skip_ocr:
        print(f"[detector] '{target}' — skipping OCR, using template match first")
    else:
        result = _find_ocr(screenshot, target)
        if result:
            print(f"[detector] OCR found '{target}' at {result}")
            return result
        print(f"[detector] OCR failed for '{target}', trying template match...")

    # For green play icons: HSV color detection avoids transparent-PNG false positives
    if icon_entry and "play_green" in icon_entry.get("icon_file", ""):
        result = _find_green_play_button(screenshot)
        if result:
            return result
        print(f"[detector] HSV color detection failed for '{target}', trying template match...")

    # Template matching: exact pixel comparison against the known icon file
    result = _find_template(screenshot, target, canvas_only=canvas_only)
    if result:
        print(f"[detector] Template match found '{target}' at {result}")
        return result

    print(f"[detector] Template match failed for '{target}', trying Groq Vision...")
    result = _find_groq(screenshot, target, hint)
    if result:
        print(f"[detector] Groq Vision found '{target}' at {result}")
        return result

    raise ElementNotFoundError(f"Could not find '{target}' via OCR, template match, or Groq Vision")


def get_location_from_groq(image_path: str, target: str) -> tuple[int, int] | None:
    """Find the specific location of a target object within a local image file using Groq Vision.

    This is useful for 'registering' new icons or finding their centers accurately.
    """
    from groq import Groq

    if not os.path.exists(image_path):
        print(f"[detector] Error: Image file not found at '{image_path}'")
        return None

    with open(image_path, "rb") as f:
        img_data = f.read()
        img_b64 = f"data:image/png;base64,{base64.b64encode(img_data).decode()}"

    prompt = (
        f"In this image, find the '{target}'. "
        "Reply with ONLY the pixel coordinates of its center as: x,y (integers). Nothing else."
    )

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=_groq_vision_model(),
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": img_b64}},
            {"type": "text", "text": prompt},
        ]}],
        temperature=0,
    )

    raw = resp.choices[0].message.content.strip()
    m = re.search(r'(\d+)\s*,\s*(\d+)', raw)
    if not m:
        print(f"[detector] Groq failed to find '{target}' in '{image_path}': {raw!r}")
        return None

    px, py = int(m.group(1)), int(m.group(2))
    print(f"[detector] Groq found '{target}' at ({px}, {py}) in file '{image_path}'")
    return (px, py)


if __name__ == "__main__":
    # Test block for provided icon
    test_path = "/Users/sachindu/Desktop/Repos/wso2/FlowCast/kb/icons/plus.png"
    if os.path.exists(test_path):
        print(f"Testing Groq detection for '+' in {test_path}...")
        res = get_location_from_groq(test_path, "+")
        print(f"Result: {res}")
    else:
        print(f"Test file not found at {test_path}")
