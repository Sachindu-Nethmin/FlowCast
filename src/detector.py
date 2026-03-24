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
    return d == t or t in d or (d in t and len(d) > 2)


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
    """Return the longest purely-alpha word from target for focused OCR matching.

    e.g. '+ Add Resources' → 'Resources'
         '+ Add Resouses'  → 'Resouses'
    """
    words = [w for w in target.split() if w.isalpha()]
    return max(words, key=len) if words else target


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

    real_words = [w for w in words if w.isalpha()]
    if real_words:
        keyword = max(real_words, key=len)
        kw_candidates: list[tuple[int, int, float, bool]] = []
        for bbox, text, conf in results:
            for ocr_word in text.lower().split():
                if not ocr_word.isalpha():
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

    buf = io.BytesIO()
    screenshot.save(buf, format="PNG")
    screenshot_b64 = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"

    icon_entry = _icon_entry_for(target)
    content: list[dict] = []

    if icon_entry:
        icon_b64 = icon_entry.get("icon_b64")
        prompt = icon_entry["groq_prompt"]

        if icon_b64:
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
    lx, ly = int(px / scale), int(py / scale)

    # Validate: if icon entry specifies canvas position, reject toolbar-zone results (y < 100)
    if icon_entry and icon_entry.get("position_hint", ""):
        hint_lower = icon_entry["position_hint"].lower()
        if any(kw in hint_lower for kw in ("canvas", "flow", "resource flow")) and ly < 100:
            print(f"[detector] Groq returned toolbar-zone y={ly} for canvas element '{target}' — rejecting")
            return None

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
    # For all other targets, try OCR first and fall back to Groq Vision.
    skip_ocr = len(target.strip()) <= 2 and _icon_entry_for(target) is not None

    if skip_ocr:
        print(f"[detector] '{target}' is a short symbol — skipping OCR, using Groq Vision")
    else:
        result = _find_ocr(screenshot, target)
        if result:
            print(f"[detector] OCR found '{target}' at {result}")
            return result
        print(f"[detector] OCR failed for '{target}', trying Groq Vision...")

    result = _find_groq(screenshot, target, hint)
    if result:
        print(f"[detector] Groq Vision found '{target}' at {result}")
        return result

    raise ElementNotFoundError(f"Cannot find element: '{target}'")
