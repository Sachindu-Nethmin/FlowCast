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


# ── Input field detection ────────────────────────────────────────────────────

def find_label_bbox_by_ocr(
    screenshot: Image.Image,
    target: str,
) -> Optional[tuple[int, int, int, int]]:
    """
    Find the label text via OCR and return its bounding box in *physical* pixels
    as (x_min, y_min, x_max, y_max).  Returns None if the label is not found.

    Prefers exact/close matches over partial substring matches to avoid matching
    toolbar or breadcrumb text. Also excludes the top 12% of the screen (toolbar area).
    """
    reader = _get_ocr_reader()
    scale = _get_scale_factor(screenshot)
    img_array = np.array(screenshot)
    results = reader.readtext(img_array)

    # Toolbar exclusion: top 12% of image height
    toolbar_cutoff = int(screenshot.height * 0.12)

    # Score matches: prefer exact > contains-target > target-contains-detected
    best_bbox = None
    best_score = -1

    target_lower = target.lower().strip()

    for bbox, text, conf in results:
        # Skip results in toolbar area
        y_center = (bbox[0][1] + bbox[2][1]) / 2
        if y_center < toolbar_cutoff:
            continue

        detected = text.lower().strip()
        score = -1

        # Exact match → highest priority
        if detected == target_lower:
            score = 3 + conf
        # Detected text contains full target
        elif target_lower in detected:
            score = 2 + conf
        # Target contains full detected text (but only if detected is substantial)
        elif detected in target_lower and len(detected) > len(target_lower) * 0.5:
            score = 1 + conf

        if score > best_score:
            best_score = score
            best_bbox = bbox

    # Multi-word fallback — also exclude toolbar
    if best_bbox is None:
        target_words = target_lower.split()
        if len(target_words) > 1:
            # Filter results to exclude toolbar area
            filtered = [(bbox, text, conf) for bbox, text, conf in results
                        if (bbox[0][1] + bbox[2][1]) / 2 >= toolbar_cutoff]
            best_bbox, _ = _find_multi_word(filtered, target_words)

    if best_bbox is None:
        return None

    xs = [pt[0] for pt in best_bbox]
    ys = [pt[1] for pt in best_bbox]
    return (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))


def _find_input_rect_below(
    screenshot: Image.Image,
    label_bbox: tuple[int, int, int, int],
) -> Optional[tuple[int, int]]:
    """
    Use OpenCV to find an empty input field rectangle below a label.

    WSO2 input fields have:
      - Distinct background from form (--vscode-input-background vs --vscode-editor-background)
      - 1px solid border
      - ~28px height (physical pixels scale with Retina)
      - Full width within their FieldGroup container

    Returns (cx, cy) in physical pixels, or None if no input rect found.
    """
    scale = _get_scale_factor(screenshot)
    lx_min, ly_min, lx_max, ly_max = label_bbox

    # Search region: below the label, extending down ~80px and wide enough
    # to capture the full input field
    img_w, img_h = screenshot.size
    search_top = ly_max
    search_bot = min(img_h, ly_max + int(80 * scale))
    # Extend horizontally — input fields are wider than labels
    search_left = max(0, lx_min - int(50 * scale))
    search_right = min(img_w, lx_max + int(400 * scale))

    crop = screenshot.crop((search_left, search_top, search_right, search_bot))
    gray = cv2.cvtColor(np.array(crop.convert("RGB")), cv2.COLOR_RGB2GRAY)

    # Edge detection to find rectangular borders
    edges = cv2.Canny(gray, 30, 100)

    # Find contours — input fields are rectangles
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Expected input height in physical pixels (~28px * scale, allow some tolerance)
    min_h = int(20 * scale)
    max_h = int(45 * scale)
    min_w = int(80 * scale)  # input fields are at least 80px wide

    best_rect = None
    best_area = 0

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if min_h <= h <= max_h and w >= min_w:
            area = w * h
            if area > best_area:
                best_area = area
                best_rect = (x, y, w, h)

    if best_rect is None:
        # Fallback: try horizontal line detection for input field borders
        # Look for pairs of horizontal edges that are ~28px apart
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (int(60 * scale), 1))
        h_lines = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, h_kernel)
        line_contours, _ = cv2.findContours(h_lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in line_contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if min_h <= h <= max_h and w >= min_w:
                area = w * h
                if area > best_area:
                    best_area = area
                    best_rect = (x, y, w, h)

    if best_rect is None:
        return None

    rx, ry, rw, rh = best_rect
    # Convert back to full-image physical coordinates
    phys_cx = search_left + rx + rw // 2
    phys_cy = search_top + ry + rh // 2
    return (phys_cx, phys_cy)


def find_input_field_by_label_ocr(
    screenshot: Image.Image,
    field_label: str,
    component_type: str | None = None,
    placeholder: str | None = None,
) -> Optional[DetectionResult]:
    """
    Find an input field using OCR label detection + WSO2 layout knowledge.

    WSO2 Integrator forms use a label-above-input vertical stack:
      Label text  (small, gray)
      [  input field  ]   (28px tall, directly below label)

    Strategy:
      1. Find the label via OCR to get its bounding box.
      2. Use OpenCV to detect the input rectangle below the label (works for empty fields).
      3. Fall back to computed offset if CV detection fails.
    """
    scale = _get_scale_factor(screenshot)
    bbox = find_label_bbox_by_ocr(screenshot, field_label)

    if bbox is None:
        # Try placeholder text as a fallback — the placeholder IS in the input field
        if placeholder:
            placeholder_bbox = find_label_bbox_by_ocr(screenshot, placeholder)
            if placeholder_bbox:
                px_cx = (placeholder_bbox[0] + placeholder_bbox[2]) // 2
                px_cy = (placeholder_bbox[1] + placeholder_bbox[3]) // 2
                cx = int(px_cx / scale)
                cy = int(px_cy / scale)
                print(f"[detector] OCR found placeholder '{placeholder}' at ({cx}, {cy})")
                return DetectionResult(center=(cx, cy), confidence=0.80, method="ocr_placeholder")
        return None

    x_min, y_min, x_max, y_max = bbox

    # Primary: use CV to find the actual input rectangle below the label
    cv_result = _find_input_rect_below(screenshot, bbox)
    if cv_result is not None:
        phys_cx, phys_cy = cv_result
        cx = int(phys_cx / scale)
        cy = int(phys_cy / scale)
        print(f"[detector] CV found input rect below '{field_label}' at ({cx}, {cy}) [method=cv_rect]")
        return DetectionResult(center=(cx, cy), confidence=0.85, method="cv_rect")

    # Fallback: computed offset from label bottom
    # (8px gap + 14px = half of 28px input height)
    input_cx = (x_min + x_max) // 2
    input_cy = y_max + int(22 * scale)

    cx = int(input_cx / scale)
    cy = int(input_cy / scale)
    print(f"[detector] OCR label '{field_label}' bbox bottom={y_max}, "
          f"computed input field at ({cx}, {cy}) [method=ocr_offset]")
    return DetectionResult(center=(cx, cy), confidence=0.70, method="ocr_offset")


def _find_input_field_cropped(
    screenshot: Image.Image,
    field_label: str,
    label_bbox: tuple[int, int, int, int],
    component_type: str | None = None,
) -> Optional[DetectionResult]:
    """
    Crop a tight region around the label and send ONLY that to Groq.
    Much more reliable than full-screen — Groq can't get confused by toolbar etc.

    Crop region: full-width strip from 10px above label to 80px below label bottom.
    Returns coordinates in logical pixels of the full screenshot.
    """
    import base64
    import re

    scale = _get_scale_factor(screenshot)
    lx_min, ly_min, lx_max, ly_max = label_bbox

    # Crop: full width of screen, generous vertical band around the label+field
    pad_above = int(20 * scale)
    pad_below = int(150 * scale)
    crop_x1 = 0
    crop_y1 = max(0, ly_min - pad_above)
    crop_x2 = screenshot.width
    crop_y2 = min(screenshot.height, ly_max + pad_below)

    crop = screenshot.crop((crop_x1, crop_y1, crop_x2, crop_y2))

    # Save debug crop
    try:
        debug_slug = re.sub(r'[^a-z0-9]', '_', field_label.lower())
        crop.save(os.path.join(os.getcwd(), f"debug_crop_{debug_slug}.png"))
    except Exception:
        pass

    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    image_b64 = base64.b64encode(buf.getvalue()).decode()

    model = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    cw = crop_x2 - crop_x1
    ch = crop_y2 - crop_y1

    component_hint = ""
    if component_type == "DirectorySelector":
        component_hint = "The field has a Browse button to its right. Target the text input area, not the button. "

    prompt = (
        f"This is a cropped WSO2 form screenshot ({cw}x{ch} physical pixels). "
        f"It shows the label '{field_label}' and the input field directly below it. "
        f"WSO2 input fields are ~28px tall rectangles with a 1px border and dark background. "
        f"The label text is near the TOP of this image. The input box is directly BELOW the label. "
        f"{component_hint}"
        f"Give me the 4 corner coordinates of the input field rectangle in THIS cropped image (physical pixels): "
        f"top-left (x1,y1), top-right (x2,y2), bottom-right (x3,y3), bottom-left (x4,y4). "
        f"Reply with ONLY 4 coordinate pairs in this exact format: x1,y1 x2,y2 x3,y3 x4,y4\n"
        f"If not found reply: NOT_FOUND"
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ]}],
        )
        text = response.choices[0].message.content.strip()
        if not text or text == "NOT_FOUND":
            return None

        # Parse 4 corner coordinate pairs: x1,y1 x2,y2 x3,y3 x4,y4
        corners = re.findall(r'(\d+)\s*,\s*(\d+)', text)
        if len(corners) >= 4:
            # Compute center as average of all 4 corners (physical pixels in crop)
            crop_px = sum(int(c[0]) for c in corners[:4]) // 4
            crop_py = sum(int(c[1]) for c in corners[:4]) // 4
        elif len(corners) == 1:
            # Fallback: single coordinate pair
            crop_px = int(corners[0][0])
            crop_py = int(corners[0][1])
        else:
            return None

        # Convert crop-relative physical coords → full-screenshot logical coords
        full_px = crop_x1 + crop_px
        full_py = crop_y1 + crop_py
        cx = int(full_px / scale)
        cy = int(full_py / scale)
        print(f"[detector] Groq (4-corner) found '{field_label}' input center at ({cx}, {cy})")
        return DetectionResult(center=(cx, cy), confidence=0.90, method="groq_cropped")
    except Exception as e:
        print(f"[detector] Groq cropped field error: {e}")
        return None


def find_input_field(
    screenshot: Image.Image,
    field_label: str,
    component_type: str | None = None,
    placeholder: str | None = None,
    label_region: tuple[int, int, int, int] | None = None,
) -> Optional[DetectionResult]:
    """
    Find the input field for a label.
    If label_region is known, crops to that area and sends a small focused image to Groq.
    Otherwise sends the full screen with WSO2-specific prompt.
    """
    import base64
    import re

    # Primary: if we have the label position, use focused crop — much more accurate
    if label_region is not None:
        result = _find_input_field_cropped(
            screenshot, field_label, label_region, component_type=component_type)
        if result is not None:
            return result
        print(f"[detector] Cropped Groq failed, falling back to full-screen...")

    scale = _get_scale_factor(screenshot)

    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    image_b64 = base64.b64encode(buf.getvalue()).decode()

    model = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    print(f"[detector] Asking Groq Vision to find input field for '{field_label}'...")

    # Save debug screenshot so we can see what Groq is seeing
    try:
        debug_slug = re.sub(r'[^a-z0-9]', '_', field_label.lower())
        debug_path = os.path.join(os.getcwd(), f"debug_field_{debug_slug}.png")
        screenshot.save(debug_path)
        print(f"[detector] Debug screenshot → {debug_path}")
    except Exception:
        pass

    import pyautogui as _pag
    sw, sh = _pag.size()

    # Build WSO2-specific prompt parts
    component_clause = ""
    if component_type == "DirectorySelector":
        component_clause = (
            "This field is a DirectorySelector: an input text box with a 'Browse' button "
            "to its right in a horizontal flex row. Click inside the text input, not the button. "
        )
    elif component_type == "Dropdown":
        component_clause = (
            "This field is a dropdown/select control with 4px border-radius. "
            "It may show the current selection value inside it. "
        )

    placeholder_clause = ""
    if placeholder:
        placeholder_clause = (
            f"The input may show gray placeholder text: '{placeholder}'. "
        )

    region_clause = ""
    if label_region:
        lx_min, ly_min, lx_max, ly_max = label_region
        # Convert physical to logical for the prompt
        l_cx = int((lx_min + lx_max) / 2 / scale)
        l_by = int(ly_max / scale)
        region_clause = (
            f"The label '{field_label}' was detected at approximately x={l_cx}, y_bottom={l_by}. "
            f"The input field is directly BELOW this label, roughly at y={l_by + 15} to y={l_by + 45}. "
            f"Focus your search in that region. "
        )

    toolbar_bottom = sh // 8   # top ~12% is toolbar/tab bar — ignore this area
    prompt = (
        f"This is a WSO2 Integrator screenshot (VSCode webview, dark theme, "
        f"logical screen size: {sw}x{sh} pixels). "
        f"I need to find the INPUT FIELD (text box) for the label '{field_label}'.\n\n"
        f"IMPORTANT EXCLUSION ZONE: The top {toolbar_bottom}px (y < {toolbar_bottom}) is the "
        f"application toolbar and tab bar — do NOT return any coordinates in that area.\n\n"
        f"WSO2 form layout rules:\n"
        f"- Labels appear ABOVE their input fields (vertical stack)\n"
        f"- Input fields are ~28px tall rectangles with 1px solid border, dark background, 2px border-radius\n"
        f"- There is a 4-8px gap between a label and its input field\n"
        f"- Forms appear in panels, dialogs, or side panels — NOT in the toolbar\n\n"
        f"{component_clause}{placeholder_clause}{region_clause}"
        f"Reply with ONLY the x,y coordinates of the CENTER of the input field in logical pixels. "
        f"If not found, reply: NOT_FOUND"
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
            print(f"[detector] Groq Vision: input field for '{field_label}' not found")
            return None

        coord_m = re.search(r'(\d+)\s*,\s*(\d+)', text)
        if not coord_m:
            print(f"[detector] Groq Vision: could not parse response: {text[:100]}")
            return None

        px_x = int(coord_m.group(1))
        px_y = int(coord_m.group(2))
        cx = int(px_x / scale)
        cy = int(px_y / scale)

        # Reject toolbar-area coordinates (top ~12% of screen)
        if cy < sh // 8:
            print(f"[detector] Groq returned toolbar coordinates ({cx}, {cy}) — rejecting (y < {sh // 8})")
            return None

        print(f"[detector] Groq Vision found input field for '{field_label}' at ({cx}, {cy})")
        return DetectionResult(center=(cx, cy), confidence=0.85, method="groq_field")
    except Exception as e:
        print(f"[detector] Groq vision field error: {e}")
        return None


def verify_text_in_region(
    screenshot: Image.Image,
    expected_text: str,
    region_center: tuple[int, int],
    region_radius: int = 80,
    before_screenshot: Image.Image | None = None,
) -> bool:
    """
    Verify that expected_text was entered by checking the region changed
    and/or the text is visible via OCR.

    Primary check: pixel-diff (before vs after) — did the region change at all?
    Secondary check: OCR — is the expected text readable in the region?
    Either passing is enough to confirm entry.
    """
    scale = _get_scale_factor(screenshot)
    phys_cx = int(region_center[0] * scale)
    phys_cy = int(region_center[1] * scale)
    phys_r = int(region_radius * scale)

    # Crop region (clamp to image bounds)
    x1 = max(0, phys_cx - phys_r * 2)  # wider horizontal crop for input fields
    y1 = max(0, phys_cy - phys_r)
    x2 = min(screenshot.width, phys_cx + phys_r * 2)
    y2 = min(screenshot.height, phys_cy + phys_r)

    # ── Primary: pixel-diff (fast, reliable — did anything change in the field area?) ──
    if before_screenshot is not None:
        crop_after = np.array(screenshot.crop((x1, y1, x2, y2)).convert("RGB"), dtype=np.float32)
        crop_before = np.array(before_screenshot.crop((x1, y1, x2, y2)).convert("RGB"), dtype=np.float32)
        diff = np.abs(crop_after - crop_before).mean()
        if diff > 3.0:
            print(f"[detector] Pixel-diff verification passed for '{expected_text}' (diff={diff:.1f})")
            return True
        print(f"[detector] Pixel-diff: no change detected (diff={diff:.1f}), trying OCR...")

    # ── Secondary: OCR on cropped region ──
    cropped = screenshot.crop((x1, y1, x2, y2))
    reader = _get_ocr_reader()
    results = reader.readtext(np.array(cropped))

    # Strip leading punctuation for matching (OCR often misses '/' or reads it as 'I')
    expected_clean = expected_text.lower().strip().lstrip('/')
    for _, text, conf in results:
        detected = text.lower().strip()
        # Exact or substring match
        if expected_text.lower() in detected or detected in expected_text.lower():
            print(f"[detector] OCR verification passed: found '{text}' matching '{expected_text}'")
            return True
        # Fuzzy: strip leading slash and compare
        if expected_clean and expected_clean in detected.lstrip('/'):
            print(f"[detector] OCR verification passed (fuzzy): '{text}' ~ '{expected_text}'")
            return True

    detected_texts = [t for _, t, _ in results]
    print(f"[detector] Verification FAILED: '{expected_text}' not found in region around "
          f"({region_center[0]}, {region_center[1]}). OCR saw: {detected_texts}")
    return False


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
