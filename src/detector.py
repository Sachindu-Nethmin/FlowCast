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
    t_clean = re.sub(r'[^\w\s]', '', t).strip()
    d_clean = re.sub(r'[^\w\s]', '', d).strip()
    if not t_clean: return False
    if t_clean in d_clean:
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


def _is_contained_in_card(arr: np.ndarray, bbox) -> bool:
    """Detect if the element is inside a WSO2 'ButtonCard' container.
    
    Identifies rectangles with ~4px border-radius and specific aspect ratios (1:1 or 4:1).
    """
    import cv2
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 30, 150)
    
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    pt = (int(np.mean(xs)), int(np.mean(ys)))
    
    contours, hierarchy = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None: return False
    
    for i, cnt in enumerate(contours):
        # 1. Geometry: Perimeter and Area
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        
        # 2. Rectangularity: Approx size for cards in WSO2 UI
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 100 or h < 40: continue
        
        aspect_ratio = w / float(h)
        # Large Card (e.g. Automation) is typically wide (~4:1)
        # Small Card (Square) is ~1:1
        is_card_shape = (0.8 < aspect_ratio < 1.2) or (2.5 < aspect_ratio < 6.0)
        
        if is_card_shape:
            # 3. Containment Check
            if x < pt[0] < x + w and y < pt[1] < y + h:
                # 4. Complexity Check: Buttons/Cards usually have internal icons/text (children)
                has_child = hierarchy[0][i][2] != -1
                return True if has_child else False
    return False


def _alpha_target(target: str) -> str:
    """Return the longest word that contains English letters, ignoring pure symbols.

    e.g. '+ Add Automation'  → 'Automation'
         '+ Add Resources'   → 'Resources'
         '+ WSO2 Integrator' → 'Integrator'
    """
    words = [w for w in target.split() if re.search(r'[a-zA-Z]', w)]
    if not words:
        return target
    # Prefer non-generic words if possible. 'Service' is too common.
    # If the target starts with 'HTTP', that's a very strong keyword.
    for w in words:
        if len(w) >= 3 and w.lower() not in ("add", "new", "service"):
            return w
    return max(words, key=lambda w: sum(c.isalpha() for c in w))


def _find_ocr(screenshot: Image.Image, target: str) -> tuple[int, int] | None:
    arr = np.array(screenshot)
    results = _ocr().readtext(arr)
    scale = _scale(screenshot)
    h, w = arr.shape[:2]

    # For 'Automation', we know it's a card in the central workspace.
    clean_target = _alpha_target(target)
    candidates: list[dict] = []
    
    for bbox, text, conf in results:
        if _fuzzy(text, target) or (clean_target and _fuzzy(text, clean_target)):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            cx_img = int((min(xs) + max(xs)) / 2)
            cy_img = int((min(ys) + max(ys)) / 2)
            
            # Centrality: 20-80% width is the 'workspace' area
            in_workspace = (0.2 * w < cx_img < 0.8 * w)
            dist_from_v_center = abs(cy_img - h/2) / (h/2)
            centrality_score = (15 if in_workspace else 0) + (10 * (1 - dist_from_v_center))
            
            # Card Check: Professional UI cards have higher score
            is_card = _is_contained_in_card(arr, bbox)
            card_score = 30 if is_card else 0
            
            # Blue Check: Highlighter for active elements
            is_blue = _is_blue_background(arr, bbox)
            blue_score = 10 if is_blue else 0
            
            # 4. Exact Match Bonus: Favor complete strings over partials
            is_exact = (text.strip().lower() == target.lower())
            exact_score = 50 if is_exact else 0
            
            total_score = centrality_score + card_score + blue_score + exact_score + (conf * 5)
            candidates.append({
                "pos": (int(cx_img / scale), int(cy_img / scale)),
                "score": total_score,
                "bbox": bbox,
                "text": text,
                "is_card": is_card,
                "is_blue": is_blue,
                "is_exact": is_exact,
                "debug": f"cent:{centrality_score:.1f} card:{card_score} blue:{blue_score} exact:{exact_score} conf:{conf:.2f} text='{text}'"
            })

    if candidates:
        # Heavily prioritize cards in the workspace
        candidates.sort(key=lambda c: c["score"], reverse=True)
        best = candidates[0]
        if len(candidates) > 1:
            print(f"[detector] OCR matching '{target}': Picked score {best['score']:.1f} at {best['pos']} ({best['debug']})")
        return best["pos"]

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


def _kb_entry(label: str) -> dict | None:
    """Find a field entry in kb/ui_elements.json by label.

    Searches across all screens in the knowledge base.
    """
    p = Path(__file__).parent.parent / "kb" / "ui_elements.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    l_target = label.lower().strip()
    for screen in data.get("screens", {}).values():
        for field in screen.get("fields", []):
            l_field = field.get("label", "").lower().strip()
            if l_field == l_target or (len(l_field) > 3 and l_field in l_target):
                return field
                
    # Fallback to element_hints if no proper field definition found
    hints = data.get("element_hints", {})
    for hint_label, hint_text in hints.items():
        if hint_label.lower().strip() == l_target:
            return {"label": hint_label, "hint": hint_text}
            
    return None


def _find_plus_below_node(screenshot: Image.Image, anchor_text: str = "Start") -> tuple[int, int] | None:
    """Find the + connector button below a named flow node using OCR anchor + template match.

    Finds the anchor node via OCR, then searches for the + icon in the region
    directly below it inside the canvas area.
    """
    import cv2

    arr = np.array(screenshot)
    scale = _scale(screenshot)
    results = _ocr().readtext(arr)

    # Find anchor node position
    anchor_pos = None
    for bbox, text, conf in results:
        if text.strip().lower() == anchor_text.lower():
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            anchor_pos = (
                int((min(xs) + max(xs)) / 2 / scale),
                int((min(ys) + max(ys)) / 2 / scale),
            )
            break

    if anchor_pos is None:
        print(f"[detector] Anchor '{anchor_text}' not found via OCR")
        return None

    ax, ay = anchor_pos
    print(f"[detector] Anchor '{anchor_text}' at ({ax}, {ay}), searching for + below")

    # Search region: below anchor, within canvas (x > 400)
    icon_path = Path(__file__).parent.parent / "kb" / "icons" / "plus.png"
    if not icon_path.exists():
        return None

    w_l = int(screenshot.width / scale)
    h_l = int(screenshot.height / scale)
    screen_small = screenshot.resize((w_l, h_l), Image.LANCZOS)
    screen_bgr = cv2.cvtColor(np.array(screen_small.convert("RGB")), cv2.COLOR_RGB2BGR)

    # Crop to region below anchor node (±200px wide, 20–200px below)
    x1 = max(400, ax - 200)
    x2 = min(w_l, ax + 200)
    y1 = ay + 20
    y2 = min(h_l, ay + 300)
    region = screen_bgr[y1:y2, x1:x2]
    if region.size == 0:
        return None

    icon_img = Image.open(icon_path).convert("RGB")
    tmpl = cv2.cvtColor(np.array(icon_img), cv2.COLOR_RGB2BGR)
    th, tw = tmpl.shape[:2]

    best_val, best_loc, best_tw, best_th = -1.0, (0, 0), tw, th
    for s in (0.5, 0.6, 0.75, 0.85, 1.0, 1.15, 1.25):
        tw_s, th_s = max(1, int(tw * s)), max(1, int(th * s))
        if tw_s > region.shape[1] or th_s > region.shape[0]:
            continue
        tmpl_r = cv2.resize(tmpl, (tw_s, th_s))
        res = cv2.matchTemplate(region, tmpl_r, cv2.TM_CCOEFF_NORMED)
        _, val, _, loc = cv2.minMaxLoc(res)
        if val > best_val:
            best_val, best_loc, best_tw, best_th = val, loc, tw_s, th_s

    if best_val < 0.4:
        print(f"[detector] + below '{anchor_text}' not found (confidence={best_val:.2f})")
        return None

    cx = x1 + best_loc[0] + best_tw // 2
    cy = y1 + best_loc[1] + best_th // 2
    print(f"[detector] + below '{anchor_text}' found at ({cx}, {cy}) confidence={best_val:.2f}")
    return (cx, cy)


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

    screen_arr = np.array(screen_small.convert("RGB"))
    screen_gray = cv2.cvtColor(screen_arr, cv2.COLOR_RGB2GRAY)
    screen_bgr  = cv2.cvtColor(screen_arr, cv2.COLOR_RGB2BGR)

    # Restrict search area to canvas zone if requested
    x_offset, y_offset = 0, 0
    if canvas_only:
        x_offset = 400
        screen_gray = screen_gray[:, x_offset:]
        screen_bgr  = screen_bgr[:, x_offset:]

    best_val, best_loc, best_tw, best_th = -1.0, (0, 0), 1, 1

    for icon_path in icon_paths:
        icon_img  = Image.open(icon_path)
        has_alpha = icon_img.mode == "RGBA"

        if has_alpha:
            # Transparent icon: grayscale + alpha mask (only glyph pixels match)
            tmpl_gray = cv2.cvtColor(np.array(icon_img.convert("RGB")), cv2.COLOR_RGB2GRAY)
            tmpl_mask = np.array(icon_img.split()[-1])
            screen_match = screen_gray
        else:
            # Opaque icon: full color matching preserves distinctive colors (e.g. blue +)
            tmpl_gray = cv2.cvtColor(np.array(icon_img.convert("RGB")), cv2.COLOR_RGB2BGR)
            tmpl_mask = None
            screen_match = screen_bgr

        th, tw = tmpl_gray.shape[:2]

        for s in (0.5, 0.6, 0.75, 0.85, 1.0, 1.15, 1.25, 1.5):
            tw_s, th_s = max(1, int(tw * s)), max(1, int(th * s))
            if tw_s < 8 or th_s < 8:
                continue
            if tw_s > screen_match.shape[1] or th_s > screen_match.shape[0]:
                continue
            tmpl_r = cv2.resize(tmpl_gray, (tw_s, th_s))
            if tmpl_mask is not None:
                mask_r = cv2.resize(tmpl_mask, (tw_s, th_s))
                res = cv2.matchTemplate(screen_match, tmpl_r, cv2.TM_CCOEFF_NORMED, mask=mask_r)
            else:
                res = cv2.matchTemplate(screen_match, tmpl_r, cv2.TM_CCOEFF_NORMED)
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

# (Groq Vision functions removed)


# ── Public API ────────────────────────────────────────────────────────────────

_DEBUG_SAVE_DIR: Path | None = None


def set_debug_dir(path: str | Path | None) -> None:
    global _DEBUG_SAVE_DIR
    if path is None:
        _DEBUG_SAVE_DIR = None
    else:
        _DEBUG_SAVE_DIR = Path(path)
        _DEBUG_SAVE_DIR.mkdir(parents=True, exist_ok=True)


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

    label_candidates = []
    
    # Check for direct matches
    for bbox, text, conf in results:
        if _fuzzy(text, field_label):
            label_candidates.append((bbox, text, conf))
    
    # Try anchor_label from KB if no direct matches or if it is more reliable
    kb = _kb_entry(field_label)
    if kb and "anchor_label" in kb:
        anchor = kb["anchor_label"]
        for bbox, text, conf in results:
            if _fuzzy(text, anchor):
                label_candidates.append((bbox, text, conf))

    if not label_candidates:
        return None
        
    # Preference: Prefer labels that are NOT on a blue background (likely links)
    label_candidates.sort(key=lambda c: (_is_blue_background(arr, c[0]), -c[2]))

    for cand_bbox, cand_text, cand_conf in label_candidates:
        lx1 = min(p[0] for p in cand_bbox)
        ly1 = min(p[1] for p in cand_bbox)
        lx2 = max(p[0] for p in cand_bbox)
        ly2 = max(p[1] for p in cand_bbox)

        # Regions relative to THIS candidate
        sy2_buffer = 100
        dx_buffer_left = 100
        dx_buffer_right = 2000
        
        kb = _kb_entry(field_label)
        if kb and "search_region" in kb:
            sr = kb["search_region"]
            sy2_buffer = sr.get("height", sy2_buffer)
            dx_buffer_left = sr.get("x_offset_left", dx_buffer_left)
            dx_buffer_right = sr.get("x_offset_right", dx_buffer_right)

        rs_below = (max(0, lx1 - dx_buffer_left), ly2 + 2, min(arr.shape[1], lx1 + dx_buffer_right), min(arr.shape[0], ly2 + sy2_buffer))
        rs_right = (lx2 + 5, ly1 - 10, min(arr.shape[1], lx2 + 1200), ly2 + 10)

        best: tuple[int, int, int, int] | None = None
        best_region_origin: tuple[int, int] = (0, 0)

        # ── Branch A: Contour detection ────────────────────────────────────────
        for sx1, sy1, sx2, sy2 in [rs_below, rs_right]:
            region = arr[sy1:sy2, sx1:sx2]
            if region.size == 0: continue
            gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 30, 100)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                if 150 < w < 2000 and 8 < h < 80 and w > h * 1.5:
                    # Preference Logic: PROXIMITY to label
                    # 1. Prefer vertically CLOSEST boxes (within 5px fuzzy zone)
                    # 2. Prefer WIDEST boxes among those at similar height
                    if best is None or y < best[1] - 5 or (abs(y - best[1]) <= 5 and w > best[2]):
                        best = (x, y, w, h)
                        best_region_origin = (sx1, sy1)
            if best:
                break # Exit the region loop if a best candidate is found in this branch

        # ── Branch B: Threshold scan (fallback for THIS candidate) ─────────────
        if best: break # If best was found in Branch A, skip Branch B for this candidate

        for sx1, sy1, sx2, sy2 in [rs_below, rs_right]:
            region = arr[sy1:sy2, sx1:sx2]
            if region.size == 0: continue
            gray_region = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
            for thresh_val, mode in [(180, cv2.THRESH_BINARY), (80, cv2.THRESH_BINARY_INV)]:
                _, thresh = cv2.threshold(gray_region, thresh_val, 255, mode)
                contours2, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                best2 = None
                for cnt in contours2:
                    x, y, w, h = cv2.boundingRect(cnt)
                    if 150 < w < 2000 and 8 < h < 80 and w > h * 1.5:
                        if best2 is None or y < best2[1] - 5 or (abs(y - best2[1]) <= 5 and w > best2[2]):
                            best2 = (x, y, w, h)
                if best2:
                    best = (x, y, w, h)
                    best_region_origin = (sx1, sy1)
                    break
            if best: break
        if best: break

    if _DEBUG_SAVE_DIR:
        # Save a "scan" image with all labels found, highlighting matches
        from PIL import ImageDraw
        debug_img = screenshot.copy()
        draw = ImageDraw.Draw(debug_img)
        
        # Draw all labels first (small gray)
        for bbox, text, _ in results:
            lx1, ly1 = min(p[0] for p in bbox), min(p[1] for p in bbox)
            lx2, ly2 = max(p[0] for p in bbox), max(p[1] for p in bbox)
            draw.rectangle([lx1, ly1, lx2, ly2], outline="#CCCCCC", width=1)
            
        # Draw target/anchor labels in Red
        for cand_bbox, cand_text, _ in label_candidates:
            lx1, ly1, lx2, ly2 = min(p[0] for p in cand_bbox), min(p[1] for p in cand_bbox), max(p[0] for p in cand_bbox), max(p[1] for p in cand_bbox)
            draw.rectangle([lx1, ly1, lx2, ly2], outline="red", width=3)
            # Draw the search region in green
            sy2_buf = 100
            if kb and "search_region" in kb:
                sy2_buf = kb["search_region"].get("height", sy2_buf)
            draw.rectangle([lx1 - 100, ly2 + 2, lx1 + 2000, ly2 + sy2_buf], outline="green", width=2)

        # Draw the selected field in Cyan if found
        if best:
            rx, ry = best_region_origin
            x, y, w, h = best
            draw.rectangle([rx + x, ry + y, rx + x + w, ry + y + h], outline="cyan", width=4)
            offset_pct = 0.3 if w > 200 else 0.5
            cx = (rx + x + w * offset_pct) / scale
            cy = (ry + y + h / 2) / scale
            draw.ellipse([cx * scale - 10, cy * scale - 10, cx * scale + 10, cy * scale + 10], fill="yellow", outline="black")

        status = "match" if best else "fail"
        fname = f"{status}_{field_label.replace('*', '')}.png"
        debug_img.save(_DEBUG_SAVE_DIR / fname)

    if best:
        rx, ry = best_region_origin
        x, y, w, h = best
        offset_pct = 0.3 if w > 200 else 0.5
        cx = int((rx + x + w * offset_pct) / scale)
        cy = int((ry + y + h / 2) / scale)
        return (cx, cy)

    return None


def _find_input_by_index(screenshot: Image.Image, anchor_label: str, field_index: int) -> tuple[int, int] | None:
    """Find the Nth input box below or near a stable anchor label."""
    import cv2
    arr = np.array(screenshot)
    scale = _scale(screenshot)
    results = _ocr().readtext(arr)

    anchor_bbox = None
    for bbox, text, conf in results:
        if _fuzzy(text, anchor_label):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            anchor_bbox = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
            break

    if anchor_bbox is None:
        print(f"[detector] Anchor '{anchor_label}' not found for indexed search")
        return None

    # Define a tall column region starting from the anchor
    ax1, ay1, ax2, ay2 = anchor_bbox
    # Search in a wider X range and a much taller Y range
    sx1, sy1 = max(0, ax1 - 100), ay2 + 5
    sx2, sy2 = min(arr.shape[1], ax2 + 500), min(arr.shape[0], ay2 + 600)
    region = arr[sy1:sy2, sx1:sx2]
    
    if region.size == 0:
        return None

    gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 30, 100)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        # Input fields are typically short, wide rectangles
        if 80 < w < 600 and 10 < h < 60 and w > h * 1.5:
            candidates.append((x, y, w, h))

    # Sort boxes by Y coordinate (top to bottom)
    candidates.sort(key=lambda c: c[1])
    
    if len(candidates) > field_index:
        x, y, w, h = candidates[field_index]
        # Same Smart Offset logic for indexed search
        offset_pct = 0.3 if w > 200 else 0.5
        cx = int((sx1 + x + w * offset_pct) / scale)
        cy = int((sy1 + y + h / 2) / scale)
        print(f"[detector] Indexed search found box {field_index} below '{anchor_label}' at ({cx}, {cy}) (w={w})")
        return (cx, cy)

    print(f"[detector] Only found {len(candidates)} boxes below '{anchor_label}', needed index {field_index}")
    return None


def find_input_field(screenshot: Image.Image, field_label: str) -> tuple[int, int] | None:
    """Find where to click to focus a named input field."""
    # Try direct visual detection first
    result = _find_input_by_visual(screenshot, field_label)
    if result:
        return result

    # Try indexed fallback if metadata exists
    kb = _kb_entry(field_label)
    if kb and "field_index" in kb and "anchor_label" in kb:
        print(f"[detector] Direct visual failed for '{field_label}', trying indexed search using anchor '{kb['anchor_label']}'...")
        result = _find_input_by_index(screenshot, kb["anchor_label"], kb["field_index"])
        if result:
            return result

    print(f"[detector] Visual detection failed for '{field_label}'.")
    return None


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

    # For canvas + button: anchor to Start node for reliable position
    if target.strip() == "+" and canvas_only:
        result = _find_plus_below_node(screenshot, anchor_text="Start")
        if result:
            return result
        print(f"[detector] Anchor-based + detection failed, falling back to template match...")

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

    raise ElementNotFoundError(f"Could not find '{target}' via OCR or template match.")


# (Groq functions removed)


if __name__ == "__main__":
    # Test block for provided icon
    test_path = "/Users/sachindu/Desktop/Repos/wso2/FlowCast/kb/icons/plus.png"
    if os.path.exists(test_path):
        print(f"Skipping Groq test — Groq removed.")
    else:
        print(f"Test file not found at {test_path}")
