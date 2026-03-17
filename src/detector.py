"""
detector.py — UI element detection via EasyOCR (primary) + Groq Vision (fallback).
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import cv2  # New dependency for template matching
from PIL import Image


@dataclass
class DetectionResult:
    center: tuple[int, int]
    confidence: float
    method: str


# ── EasyOCR (local, accurate for text-based elements) ──────────────────────

_ocr_reader = None


def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        _ocr_reader = easyocr.Reader(["en"], gpu=False)
        print("[detector] EasyOCR reader initialised")
    return _ocr_reader


def _get_scale_factor(screenshot: Image.Image) -> float:
    """Compute HiDPI/Retina scale factor (logical → physical pixels)."""
    try:
        import pyautogui
        logical_w, _ = pyautogui.size()
        physical_w = screenshot.width
        return physical_w / logical_w
    except Exception:
        return 1.0


def _fuzzy_match(detected: str, target: str) -> bool:
    """Check if detected text matches the target (case-insensitive, substring)."""
    detected_lower = detected.lower().strip()
    target_lower = target.lower().strip()
    # Exact match
    if detected_lower == target_lower:
        return True
    # Target is contained in detected text
    if target_lower in detected_lower:
        return True
    # Detected text is a significant part of target
    if detected_lower in target_lower and len(detected_lower) > 2:
        return True
    return False


def _is_icon_target(target: str) -> bool:
    """Return True if target contains no alphabetic characters (symbol/icon like '+')."""
    return not any(c.isalpha() for c in target)


def find_by_ocr(screenshot: Image.Image, target: str) -> Optional[DetectionResult]:
    """Use EasyOCR to find a text-based UI element. Returns the highest-confidence match."""
    reader = _get_ocr_reader()
    scale = _get_scale_factor(screenshot)

    img_array = np.array(screenshot)
    results = reader.readtext(img_array)

    best_match = None
    best_confidence = 0.0

    for bbox, text, conf in results:
        if _fuzzy_match(text, target) and conf > best_confidence:
            best_match = bbox
            best_confidence = conf

    # Multi-word fallback
    if best_match is None:
        target_words = target.lower().split()
        if len(target_words) > 1:
            best_match, best_confidence = _find_multi_word(results, target_words)

    if best_match is None:
        print(f"[detector] OCR: '{target}' not found on screen")
        return None

    xs = [pt[0] for pt in best_match]
    ys = [pt[1] for pt in best_match]
    cx = int((min(xs) + max(xs)) / 2 / scale)
    cy = int((min(ys) + max(ys)) / 2 / scale)

    print(f"[detector] OCR found '{target}' at ({cx}, {cy}) [confidence={best_confidence:.2f}]")
    return DetectionResult(center=(cx, cy), confidence=best_confidence, method="ocr")


def _find_multi_word(results, target_words: list[str]) -> tuple[Optional[list], float]:
    """
    Try to find adjacent OCR boxes that together spell out the target phrase.
    Returns (combined_bbox, avg_confidence) or (None, 0).
    """
    # Sort results by vertical then horizontal position
    sorted_results = sorted(results, key=lambda r: (
        (r[0][0][1] + r[0][2][1]) / 2,  # y center
        (r[0][0][0] + r[0][2][0]) / 2,  # x center
    ))

    for i in range(len(sorted_results)):
        matched_boxes = []
        matched_confs = []
        word_idx = 0

        for j in range(i, min(i + len(target_words) + 2, len(sorted_results))):
            text = sorted_results[j][1].lower().strip()
            if word_idx < len(target_words) and target_words[word_idx] in text:
                matched_boxes.append(sorted_results[j][0])
                matched_confs.append(sorted_results[j][2])
                word_idx += 1
            if word_idx == len(target_words):
                break

        if word_idx == len(target_words) and matched_boxes:
            # Combine bounding boxes
            all_xs = [pt[0] for box in matched_boxes for pt in box]
            all_ys = [pt[1] for box in matched_boxes for pt in box]
            combined = [
                [min(all_xs), min(all_ys)],
                [max(all_xs), min(all_ys)],
                [max(all_xs), max(all_ys)],
                [min(all_xs), max(all_ys)],
            ]
            return combined, sum(matched_confs) / len(matched_confs)

    return None, 0.0


# ── Groq Vision (fallback for non-text / icon elements) ────────────────────

_groq_client = None


def _get_groq_client():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY not set in .env")
        _groq_client = Groq(api_key=api_key)
    return _groq_client


def find_by_groq(
    screenshot: Image.Image,
    target: str,
    candidates: list[tuple[int, int]] | None = None,
    hint: str | None = None,
) -> Optional[DetectionResult]:
    """Ask Groq Vision to locate the element. Returns logical-pixel coords.

    candidates: when OCR found multiple matches, pass their (x, y) logical-pixel
    coordinates so Groq can pick the correct one rather than searching from scratch.
    hint: natural-language description of where the element is (e.g. "between Start
    and Error Handler nodes"), injected into the prompt for better disambiguation.
    """
    import base64

    scale = _get_scale_factor(screenshot)

    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    image_b64 = base64.b64encode(buf.getvalue()).decode()

    model = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    print(f"[detector] Sending screenshot to Groq ({model})...")

    if candidates:
        import pyautogui as _pag
        sw, sh = _pag.size()
        coord_list = "; ".join(f"({x}, {y})" for x, y in candidates)
        prompt = (
            f"Look at this screenshot (logical screen size: {sw}x{sh} pixels). "
            f"There are multiple '{target}' elements at these logical-pixel coordinates: {coord_list}. "
            f"I need the one that is inside the MAIN CANVAS or DIAGRAM AREA — the large central "
            f"working area of the application. "
            f"EXCLUDE any element that is: in a toolbar or header at the top of the screen "
            f"(y < {sh // 5}), in a sidebar panel on the left or right edge "
            f"(x < {sw // 6} or x > {sw * 5 // 6}), or in a status bar at the bottom. "
            f"The correct element is typically near the vertical center of the screen "
            f"(y between {sh // 4} and {sh * 3 // 4}). "
            "Reply with ONLY two integers: the x then y coordinate of the correct one, "
            "separated by a comma. If none qualify, reply: NOT_FOUND"
        )
    else:
        hint_clause = f" More specifically: {hint}." if hint else ""
        prompt = (
            f"Look at this screenshot carefully. I need to find a '{target}' symbol "
            f"that is drawn INSIDE A BLUE CIRCLE in the center of the screen — it is part of a "
            f"flowchart or node diagram in the main working area.{hint_clause} "
            f"This BLUE circle with '{target}' inside it is used to add a new node to the diagram. "
            f"It sits roughly in the CENTER of the screen, NOT in any toolbar at the top, "
            f"NOT in any sidebar, and NOT in any panel header. "
            f"Ignore any '{target}' that is NOT inside a blue circle. "
            f"Give me the pixel coordinates of the CENTER of that blue circle. "
            "Reply with ONLY two integers: x then y, separated by a comma. "
            "If you cannot see a blue circle with that symbol in the diagram, reply: NOT_FOUND"
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        text = response.choices[0].message.content.strip()
        if not text or text == "NOT_FOUND":
            return None
        parts = text.split(",")
        if len(parts) != 2:
            return None
        px_x = int(parts[0].strip())
        px_y = int(parts[1].strip())
        cx = int(px_x / scale)
        cy = int(px_y / scale)
        print(f"[detector] Groq found '{target}' at ({cx}, {cy})")
        return DetectionResult(center=(cx, cy), confidence=0.85, method="groq")
    except Exception as e:
        print(f"[detector] Groq vision error: {e}")
        return None


# ── All-matches OCR scan ────────────────────────────────────────────────────

def find_all_by_ocr(screenshot: Image.Image, target: str) -> list[DetectionResult]:
    """Return every OCR match for target on screen (all instances, sorted by confidence)."""
    reader = _get_ocr_reader()
    scale = _get_scale_factor(screenshot)
    img_array = np.array(screenshot)
    results = reader.readtext(img_array)

    matches = []
    for bbox, text, conf in results:
        if _fuzzy_match(text, target):
            xs = [pt[0] for pt in bbox]
            ys = [pt[1] for pt in bbox]
            px_cx = int((min(xs) + max(xs)) / 2)
            px_cy = int((min(ys) + max(ys)) / 2)
            cx = int(px_cx / scale)
            cy = int(px_cy / scale)
            matches.append(DetectionResult(center=(cx, cy), confidence=conf, method="ocr"))

    matches.sort(key=lambda r: r.confidence, reverse=True)
    return matches


# ── Blue circle icon detection (color-based, no API) ───────────────────────

def find_blue_circle_icon(screenshot: Image.Image) -> Optional[DetectionResult]:
    """
    Locate the blue-filled '+' circle icon in the canvas.

    Strategy:
    1. Build a mask of BRIGHT blue pixels (filters out white '+' icons and dark dots).
    2. Restrict search to the middle 50% of the screen.
    3. Find all connected blue blobs and keep only those in the size range of the
       '+' circle (eliminates tiny connector dots and large blue panels).
    4. Among qualifying blobs, pick the centroid closest to the screen centre.
    """
    scale = _get_scale_factor(screenshot)

    img = np.array(screenshot.convert("RGB"))
    r = img[:, :, 0].astype(float)
    g = img[:, :, 1].astype(float)
    b = img[:, :, 2].astype(float)

    # Bright blue only — the '+' circle has strong blue channel.
    # White '+' buttons fail because B ≈ R ≈ G (no channel dominance).
    # Dark connector dots fail because B < 150.
    blue_mask = ((b > 150) & (b > r * 1.5) & (b > g * 1.2)).astype(np.uint8)

    # Restrict to middle 50% of screen
    h, w = blue_mask.shape
    top    = int(h / 4)
    bottom = int(h * 3 / 4)
    left   = int(w / 4)
    right  = int(w * 3 / 4)
    search = blue_mask.copy()
    search[:top, :]    = 0
    search[bottom:, :] = 0
    search[:, :left]   = 0
    search[:, right:]  = 0

    if search.max() == 0:
        return None

    # Label connected blue blobs using a simple flood approach via scipy if
    # available, otherwise fall back to column-run labelling via numpy.
    try:
        from scipy import ndimage as ndi
        labeled, num = ndi.label(search)
        sizes = ndi.sum(search, labeled, range(1, num + 1))
        # The '+' circle is typically 200–5000 physical pixels in area.
        # Tiny dots (<100) and large panels (>8000) are excluded.
        valid = [i + 1 for i, s in enumerate(sizes) if 100 <= s <= 8000]
    except ImportError:
        # Fallback: treat every blue pixel as its own candidate — centre-bias
        # will pick the best one.
        valid = None

    cx_screen, cy_screen = w / 2, h / 2
    best_cx, best_cy, best_dist = None, None, float("inf")

    if valid:
        for label_id in valid:
            ys_blob, xs_blob = np.where(labeled == label_id)
            blob_cx = xs_blob.mean()
            blob_cy = ys_blob.mean()
            dist = ((blob_cx - cx_screen) ** 2 + (blob_cy - cy_screen) ** 2) ** 0.5
            if dist < best_dist:
                best_dist = dist
                best_cx = int(blob_cx)
                best_cy = int(blob_cy)
    else:
        # No scipy — find all blue pixel positions and pick closest to centre
        ys_all, xs_all = np.where(search > 0)
        dists = ((xs_all - cx_screen) ** 2 + (ys_all - cy_screen) ** 2) ** 0.5
        idx = dists.argmin()
        best_cx, best_cy = int(xs_all[idx]), int(ys_all[idx])

    if best_cx is None:
        return None

    cx = int(best_cx / scale)
    cy = int(best_cy / scale)
    print(f"[detector] Blue circle icon found at ({cx}, {cy})")

    # Save annotated debug image so we can verify the detected point visually
    try:
        import os
        from PIL import ImageDraw
        debug_img = screenshot.copy()
        draw = ImageDraw.Draw(debug_img)
        r = 20
        draw.ellipse([best_cx - r, best_cy - r, best_cx + r, best_cy + r], outline="red", width=4)
        draw.line([best_cx - r * 2, best_cy, best_cx + r * 2, best_cy], fill="red", width=3)
        draw.line([best_cx, best_cy - r * 2, best_cx, best_cy + r * 2], fill="red", width=3)
        debug_path = os.path.join(os.getcwd(), "debug_blue_detection.png")
        debug_img.save(debug_path)
        print(f"[detector] Debug image saved → {debug_path}")
    except Exception as e:
        print(f"[detector] Debug image save failed: {e}")

    return DetectionResult(center=(cx, cy), confidence=0.95, method="color")


# ── Template Matching (robust for specific icons like '+') ────────────────

ICON_TEMPLATES = {
    "+": "assets/icons/blue_plus.png",
}


def find_by_template(screenshot: Image.Image, target: str) -> Optional[DetectionResult]:
    """Find an icon on screen using template matching."""
    template_path = ICON_TEMPLATES.get(target)
    if not template_path:
        return None

    abs_template_path = os.path.join(os.getcwd(), template_path)
    if not os.path.exists(abs_template_path):
        print(f"[detector] Template '{template_path}' not found at {abs_template_path}")
        return None

    scale = _get_scale_factor(screenshot)
    img_gray = cv2.cvtColor(np.array(screenshot.convert("RGB")), cv2.COLOR_RGB2GRAY)
    template = cv2.imread(abs_template_path, cv2.IMREAD_GRAYSCALE)

    if template is None:
        print(f"[detector] Failed to load template image: {abs_template_path}")
        return None

    # Use multi-scale template matching if needed, but start with simple match
    res = cv2.matchTemplate(img_gray, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

    # Threshold for template matching
    threshold = 0.8
    if max_val >= threshold:
        h, w = template.shape
        cx = int((max_loc[0] + w // 2) / scale)
        cy = int((max_loc[1] + h // 2) / scale)
        print(f"[detector] Template match found '{target}' at ({cx}, {cy}) [confidence={max_val:.2f}]")
        return DetectionResult(center=(cx, cy), confidence=max_val, method="template")

    return None


# ── Green toolbar button detection (top-right area) ────────────────────────

def find_green_toolbar_button(screenshot: Image.Image) -> Optional[DetectionResult]:
    """
    Locate the green triangle Run button in the top-right toolbar by finding
    the densest green pixel blob restricted to the top toolbar strip.
    Green: G channel dominant, bright (G > 120, G > R * 1.3, G > B * 1.3).
    """
    from PIL import ImageFilter

    scale = _get_scale_factor(screenshot)

    img = np.array(screenshot.convert("RGB"))
    r = img[:, :, 0].astype(float)
    g = img[:, :, 1].astype(float)
    b = img[:, :, 2].astype(float)

    green_mask = ((g > 120) & (g > r * 1.3) & (g > b * 1.3)).astype(np.uint8)

    h, w = green_mask.shape
    # Restrict to top toolbar strip (top 10%) and right half of screen
    toolbar_bottom = int(h * 0.10)
    right_half     = int(w * 0.50)
    search = green_mask.copy()
    search[toolbar_bottom:, :] = 0   # keep only top 10%
    search[:, :right_half]     = 0   # keep only right half

    if search.max() == 0:
        return None

    try:
        from scipy import ndimage as ndi
        labeled, num = ndi.label(search)
        if num == 0:
            return None
        sizes = ndi.sum(search, labeled, range(1, num + 1))
        # Pick largest blob (the play button should be the biggest green area)
        best_label = int(np.argmax(sizes)) + 1
        ys_blob, xs_blob = np.where(labeled == best_label)
    except ImportError:
        ys_blob, xs_blob = np.where(search > 0)

    cx = int(xs_blob.mean() / scale)
    cy = int(ys_blob.mean() / scale)
    print(f"[detector] Green toolbar button found at ({cx}, {cy})")
    return DetectionResult(center=(cx, cy), confidence=0.90, method="color")


# ── Public API: OCR first, Groq Vision fallback ─────────────────────────────

def find(screenshot: Image.Image, target: str, hint: str | None = None) -> Optional[DetectionResult]:
    """
    Find a UI element on screen.

    Text targets → OCR picks the highest-confidence match. If the click doesn't
      change the UI, runner.py will automatically try the other OCR candidates.
    Icon/symbol targets (no letters, e.g. '+') → color-based blue circle detection
      first (fast, no API); falls back to Groq Vision if the blue circle is not found.
    """
    if not _is_icon_target(target):
        # Text element — OCR first
        result = find_by_ocr(screenshot, target)
        if result is not None:
            return result
        # Fallback: color-based detection for known graphical buttons
        if target.lower() == "run":
            print(f"[detector] OCR missed 'Run' — trying green toolbar button detection...")
            return find_green_toolbar_button(screenshot)
        return None

    # Icon/symbol path — try template matching first (accurate), then color, then Groq
    print(f"[detector] Icon target '{target}' — using specialized detection...")
    
    # 1. Template matching (most specific)
    result = find_by_template(screenshot, target)
    if result:
        return result

    # 2. Color-based blue circle detection (heuristic)
    result = find_blue_circle_icon(screenshot)
    if result is not None:
        return result

    # 3. Fallback to Groq Vision (AI)
    print(f"[detector] Specialized detection failed, falling back to Groq...")
    return find_by_groq(screenshot, target, hint=hint)
