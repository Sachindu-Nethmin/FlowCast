import base64
import io
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import cv2
import easyocr
import numpy as np
import pyautogui
from PIL import Image, ImageChops, ImageStat


class ElementNotFoundError(Exception):
    pass


# ── Source-derived field dimensions ───────────────────────────────────────────
# Confirmed from product-integrator/wi/wi-webviews/src/components/DirectorySelector/DirectorySelector.tsx
#   `height: 28px;`  (Input and BrowseButton components)
_FIELD_HEIGHT_PX = 28

# Approximate height of a description/helper-text block below a label.
# From form.styles.ts: font-size:12px + margin-top/bottom ~8px → ~48px accommodates multi-line info.
_DESCRIPTION_ZONE_PX = 48
# ──────────────────────────────────────────────────────────────────────────────

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
    """Case-sensitive fuzzy match between OCR-detected text and a target label."""
    d, t = detected.strip(), target.strip()
    if d == t:
        return True

    # Require word-boundary match so "automation" in "myautomation" does NOT match
    t_clean = re.sub(r'[^\w\s]', '', t).strip()
    d_clean = re.sub(r'[^\w\s]', '', d).strip()
    if not t_clean: return False

    # Direct containment check for cleaned versions
    if t_clean == d_clean:
        return True

    # Word-level matching
    d_words = d_clean.split()
    t_words = t_clean.split()

    # If target has multiple words, require a significant portion of the entire string to match
    if len(t_words) > 1:
        # Check if detected string contains a sequence of target words
        if d_clean in t_clean and len(d_clean) > (len(t_clean) * 0.4):
            return True
        # Or if target contains detected string
        if t_clean in d_clean and len(t_clean) > (len(d_clean) * 0.4):
            return True
        return False

    # If target is a single word and detected is multiple words, check if target is one of them
    if len(t_words) == 1 and len(d_words) > 1:
        if t_words[0] in d_words:
            return True

    # If detected is a single word, it should match one of the target's words exactly
    # (prevents "Service" matching "URL of the target service" unless it was intended)
    if len(d_words) == 1 and len(t_words) > 1:
        if d_words[0] in t_words and len(d_words[0]) > 3:
            return True

    # OCR may only capture part of a multi-word target — allow detected ⊂ target
    # But ONLY if it's a significant portion (e.g. "integrator" in "wso2 integrator")
    if d in t and len(d) > 4:
        return True

    return False


def _merge_ocr_results(results: list) -> list:
    """Combine horizontally aligned and nearby OCR text blocks.
    
    OCR often splits a single label (e.g., 'Service Base Path') into multiple blocks.
    This merges blocks that are on the same line and close to each other.
    """
    if not results:
        return []

    # Sort primarily by y (top) and secondarily by x
    sorted_res = sorted(results, key=lambda r: (min(p[1] for p in r[0]), min(p[0] for p in r[0])))
    
    merged = []
    if not sorted_res:
        return merged
        
    current_bbox, current_text, current_conf = sorted_res[0]
    
    for next_bbox, next_text, next_conf in sorted_res[1:]:
        # Get bounds
        c_x1 = min(p[0] for p in current_bbox)
        c_y1 = min(p[1] for p in current_bbox)
        c_x2 = max(p[0] for p in current_bbox)
        c_y2 = max(p[1] for p in current_bbox)
        c_h = c_y2 - c_y1
        
        n_x1 = min(p[0] for p in next_bbox)
        n_y1 = min(p[1] for p in next_bbox)
        n_x2 = max(p[0] for p in next_bbox)
        n_y2 = max(p[1] for p in next_bbox)
        
        # Check if same line (overlap in Y) and close in X
        y_overlap = min(c_y2, n_y2) - max(c_y1, n_y1)
        is_same_line = y_overlap > (c_h * 0.5)
        is_close_x = (n_x1 - c_x2) < (c_h * 2.0) # threshold for space between words
        
        if is_same_line and is_close_x:
            # Merge
            new_bbox = [
                [min(c_x1, n_x1), min(c_y1, n_y1)],
                [max(c_x2, n_x2), min(c_y1, n_y1)],
                [max(c_x2, n_x2), max(c_y2, n_y2)],
                [min(c_x1, n_x1), max(c_y2, n_y2)]
            ]
            current_bbox = new_bbox
            current_text = f"{current_text} {next_text}".strip()
            current_conf = (current_conf + next_conf) / 2
        else:
            merged.append((current_bbox, current_text, current_conf))
            current_bbox, current_text, current_conf = next_bbox, next_text, next_conf
            
    merged.append((current_bbox, current_text, current_conf))
    return merged


def _is_light_mode(screenshot: Image.Image) -> bool:
    """Return True if the screenshot appears to be from a Light Theme.
    
    Calculates the average luminance of the image.
    """
    gray = screenshot.convert("L")
    stat = ImageStat.Stat(gray)
    luminance = stat.mean[0]
    is_light = luminance > 120  # Threshold for 'light' theme
    return is_light


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
    
    # In Light Mode, blue buttons might be lighter/less saturated.
    # We relax the Saturation and Value floors slightly if needed.
    is_light = _is_light_mode(Image.fromarray(arr))
    s_floor = 60 if is_light else 80
    v_floor = 60 if is_light else 80
    
    # Blue hue in OpenCV HSV: ~100–135 (of 180)
    mask = cv2.inRange(hsv, np.array([100, s_floor, v_floor]), np.array([135, 255, 255]))
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
            is_case_match = (text.strip() == target)
            exact_score = 50 if is_exact else 0
            case_bonus = 20 if is_case_match else 0
            
            # Sidebar Suppression: Penalize the leftmost 25% of the screen
            sidebar_penalty = -50 if min(xs) < (w * 0.25) else 0
            
            total_score = centrality_score + card_score + blue_score + exact_score + case_bonus + (conf * 5) + sidebar_penalty
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
    for hint_label, val in hints.items():
        if hint_label.lower().strip() == l_target:
            if isinstance(val, dict):
                return {**val, "label": hint_label}
            return {"label": hint_label, "hint": val}

    # Check top-level field_placeholders
    fp = data.get("field_placeholders", {}).get("fields", {})
    if label in fp:
        return {"label": label, "placeholder": fp[label]}

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
    is_light = _is_light_mode(screenshot)
    theme_suffix = "_light" if is_light else ""
    icon_path = Path(__file__).parent.parent / "kb" / "icons" / f"plus{theme_suffix}.png"
    if not icon_path.exists():
        icon_path = Path(__file__).parent.parent / "kb" / "icons" / "plus.png"
    if not icon_path.exists():
        return None

    w_l = int(screenshot.width / scale)
    h_l = int(screenshot.height / scale)
    screen_small = screenshot.resize((w_l, h_l), Image.LANCZOS)
    screen_bgr = cv2.cvtColor(np.array(screen_small.convert("RGB")), cv2.COLOR_RGB2BGR)

    # Crop to region below anchor node (±200px wide, 20–300px below)
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
    # Use expanded scales for Retina-to-logical consistency
    factors = (0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 1.0, 1.15, 1.25, 1.4, 1.6)
    for s in factors:
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
    print(f"[detector] + found below '{anchor_text}' at ({cx}, {cy}) (confidence={best_val:.2f})")
    return (cx, cy)


def _find_plus_right_of_label(screenshot: Image.Image, anchor_text: str) -> tuple[int, int] | None:
    """Find the + button to the right of a named label using OpenCV cross-kernel matching.

    Used for instructions like "Select + next to the Query section".
    Strategy:
      1. OCR the full screenshot to locate the anchor label's bounding box.
      2. Crop to the row strip to the right of the label.
      3. Threshold the crop (theme-aware) to isolate bright pixels.
      4. Build a programmatic cross-shaped kernel and template-match it.
      5. Return the best match centre in logical screen coordinates.
    """
    import cv2

    arr = np.array(screenshot)
    scale = _scale(screenshot)
    results = _ocr().readtext(arr)

    # ── Step 1: locate anchor label via OCR ──────────────────────────────────
    anchor_box = None
    for bbox, text, conf in results:
        if _fuzzy(text, anchor_text):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            anchor_box = (
                int(min(xs) / scale),  # lx1
                int(min(ys) / scale),  # ly1
                int(max(xs) / scale),  # lx2
                int(max(ys) / scale),  # ly2
            )
            break

    if anchor_box is None:
        print(f"[detector] Anchor '{anchor_text}' not found via OCR")
        return None

    lx1, ly1, lx2, ly2 = anchor_box
    label_h = max(ly2 - ly1, 1)
    padding = max(label_h, 12)
    print(f"[detector] Anchor '{anchor_text}' at ({lx1},{ly1})-({lx2},{ly2}), searching for + via OpenCV")

    # ── Step 2: crop to the row strip right of the anchor ────────────────────
    w_l = int(screenshot.width / scale)
    h_l = int(screenshot.height / scale)
    rx1 = lx2 + 2
    rx2 = w_l
    ry1 = max(0, ly1 - padding)
    ry2 = min(h_l, ly2 + padding)

    crop_px = screenshot.crop((rx1 * scale, ry1 * scale, rx2 * scale, ry2 * scale))
    crop_gray = cv2.cvtColor(np.array(crop_px.convert("RGB")), cv2.COLOR_RGB2GRAY)

    # ── Step 3: threshold — isolate bright pixels in dark mode, dark in light ─
    is_light = _is_light_mode(screenshot)
    if is_light:
        # Light theme: + is dark on light background → invert so + becomes bright
        crop_thresh = cv2.bitwise_not(crop_gray)
    else:
        crop_thresh = crop_gray.copy()
    _, crop_bin = cv2.threshold(crop_thresh, 100, 255, cv2.THRESH_BINARY)

    # ── Step 4: build cross-shaped kernels and template-match ─────────────────
    best_val, best_cx, best_cy = -1.0, None, None
    # Try several arm-lengths to handle different icon sizes / Retina scaling
    for arm in (3, 4, 5, 6, 8, 10, 12):
        size = arm * 2 + 1
        tmpl = np.zeros((size, size), dtype=np.uint8)
        mid = arm
        tmpl[mid, :] = 255   # horizontal bar
        tmpl[:, mid] = 255   # vertical bar

        if tmpl.shape[0] > crop_bin.shape[0] or tmpl.shape[1] > crop_bin.shape[1]:
            continue

        res = cv2.matchTemplate(crop_bin, tmpl, cv2.TM_CCOEFF_NORMED)
        _, val, _, loc = cv2.minMaxLoc(res)
        if val > best_val:
            best_val = val
            # loc is top-left of template in crop; centre it
            cx_crop = loc[0] + arm
            cy_crop = loc[1] + arm
            # Convert crop-relative pixel coords → logical screen coords
            best_cx = int(cx_crop / scale) + rx1
            best_cy = int(cy_crop / scale) + ry1

    threshold = 0.35
    if best_val < threshold:
        print(f"[detector] + right of '{anchor_text}' not found via OpenCV (best={best_val:.2f})")
        best_cx = best_cy = None

    # ── Debug image ───────────────────────────────────────────────────────────
    if _DEBUG_SAVE_DIR:
        from PIL import ImageDraw
        debug_img = screenshot.copy()
        draw = ImageDraw.Draw(debug_img)
        for bbox, text, _ in results:
            bx1 = min(p[0] for p in bbox)
            by1 = min(p[1] for p in bbox)
            bx2 = max(p[0] for p in bbox)
            by2 = max(p[1] for p in bbox)
            draw.rectangle([bx1, by1, bx2, by2], outline="#CCCCCC", width=1)
        # Anchor in red
        draw.rectangle([lx1 * scale, ly1 * scale, lx2 * scale, ly2 * scale], outline="red", width=3)
        # Search band in green
        draw.rectangle([rx1 * scale, ry1 * scale, rx2 * scale, ry2 * scale], outline="green", width=2)
        # Result as yellow dot
        if best_cx is not None:
            px, py = best_cx * scale, best_cy * scale
            draw.ellipse([px - 10, py - 10, px + 10, py + 10], fill="yellow", outline="black")
        status = "match" if best_cx is not None else "fail"
        save_dir = _DEBUG_SAVE_DIR / "next_to"
        save_dir.mkdir(parents=True, exist_ok=True)
        debug_img.save(save_dir / f"{status}_{anchor_text.replace(' ', '_')}.png")

    if best_cx is None:
        return None

    print(f"[detector] + found right of '{anchor_text}' at ({best_cx}, {best_cy}) (confidence={best_val:.2f})")
    return (best_cx, best_cy)


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
    is_light = _is_light_mode(screenshot)
    s_floor = 50 if is_light else 60
    v_floor = 50 if is_light else 60
    
    lower = np.array([60, s_floor, v_floor])
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


def _find_template(screenshot: Image.Image, target: str, canvas_only: bool = False, search_region: tuple[int, int, int, int] | None = None) -> tuple[int, int] | None:
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
    
    # Theme-aware matching: if in Light Mode, prefer *_light.png
    is_light = _is_light_mode(screenshot)
    theme_suffix = "_light" if is_light else ""
    
    # Build list of candidates, prioritized by theme
    candidate_paths = []
    if theme_suffix:
        candidate_paths += sorted(icons_dir.glob(f"{stem}{theme_suffix}_*.png"))
        candidate_paths += [icons_dir / f"{stem}{theme_suffix}.png"]
    
    candidate_paths += sorted(icons_dir.glob(f"{stem}_*.png"))
    candidate_paths += [icons_dir / Path(icon_file).with_suffix(".png"),
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
    elif search_region:
        x1, y1, x2, y2 = search_region
        x_offset, y_offset = int(max(0, x1)), int(max(0, y1))
        # Protect against out-of-bounds crop
        x2, y2 = min(screen_gray.shape[1], int(x2)), min(screen_gray.shape[0], int(y2))
        if x2 > x_offset and y2 > y_offset:
            screen_gray = screen_gray[y_offset:y2, x_offset:x2]
            screen_bgr = screen_bgr[y_offset:y2, x_offset:x2]

    best_val, best_loc, best_tw, best_th = -1.0, (0, 0), 1, 1

    for icon_path in icon_paths:
        icon_path = Path(icon_path)
        if not icon_path.exists() or icon_path.suffix.lower() == ".svg":
            continue
        
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

        # Expanded scale range to handle Retina-to-logical mismatches (e.g. 80px -> 30px)
        factors = (0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 1.0, 1.15, 1.25, 1.4, 1.6)
        for s in factors:
            tw_s, th_s = max(1, int(tw * s)), max(1, int(th * s))
            if tw_s < 10 or th_s < 10:
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




# ── Public API ────────────────────────────────────────────────────────────────

_DEBUG_SAVE_DIR: Path | None = None


def set_debug_dir(path: str | Path | None) -> None:
    global _DEBUG_SAVE_DIR
    if path is None:
        _DEBUG_SAVE_DIR = None
    else:
        _DEBUG_SAVE_DIR = Path(path)
        _DEBUG_SAVE_DIR.mkdir(parents=True, exist_ok=True)


def _load_screens() -> dict:
    """Load the screens section from kb/ui_elements.json."""
    p = Path(__file__).parent.parent / "kb" / "ui_elements.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text()).get("screens", {})


def _load_field_placeholders() -> dict:
    """Load field placeholder mappings from kb/ui_elements.json."""
    p = Path(__file__).parent.parent / "kb" / "ui_elements.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    return data.get("field_placeholders", {}).get("fields", {})


def identify_screen(screenshot: Image.Image) -> dict | None:
    """Identify which screen is currently displayed and return its metadata.

    Runs OCR on the screenshot and scores each known screen from the KB by
    counting how many of its distinctive element labels and field labels are
    visible.  Returns the best-matching screen dict augmented with a
    ``screen_key`` field, or None if no screen scores above threshold.

    Return format::

        {
            "screen_key": "bi_creation",
            "name": "Create BI Integration Screen",
            "confidence": 0.75,
            "matched_elements": ["Back", "Create Integration"],
            "matched_fields": ["Integration Name", "Package Name", "Select Path"],
            "fields": [ ... full field defs from KB ... ],
            "elements": [ ... ]
        }
    """
    arr = np.array(screenshot)
    results = _ocr().readtext(arr)
    merged_results = _merge_ocr_results(results)

    screens = _load_screens()
    if not screens:
        return None

    best_screen = None
    best_score = 0
    best_info = {}

    for key, screen in screens.items():
        matched_elements = []
        matched_fields = []

        # Score element labels
        for elem in screen.get("elements", []):
            label = elem.get("label", "").lower()
            if not label:
                continue
            for _, dt, _ in merged_results:
                if _fuzzy(dt, label):
                    matched_elements.append(elem["label"])
                    break

        # Score field labels (heavier weight — fields are more distinctive)
        for field in screen.get("fields", []):
            label = field.get("label", "").lower()
            if not label:
                continue
            # Skip conditional fields — they may not be visible
            if field.get("conditional", False):
                continue
            for _, dt, _ in merged_results:
                if _fuzzy(dt, label):
                    matched_fields.append(field["label"])
                    break

        # Also check for placeholder text in fields
        placeholders = _load_field_placeholders()
        for field in screen.get("fields", []):
            fl = field.get("label", "")
            ph = field.get("placeholder") or placeholders.get(fl)
            if ph and fl not in [f for f in matched_fields]:
                for _, dt, _ in merged_results:
                    if _fuzzy(dt, ph):
                        matched_fields.append(fl)
                        break

        # Weighted score: fields count double since they're more screen-specific
        total_possible = len([e for e in screen.get("elements", [])]) + \
                         2 * len([f for f in screen.get("fields", []) if not f.get("conditional", False)])
        score = len(matched_elements) + 2 * len(matched_fields)
        confidence = score / total_possible if total_possible > 0 else 0

        if score > best_score:
            best_score = score
            best_screen = key
            best_info = {
                "screen_key": key,
                "name": screen.get("name", key),
                "confidence": round(confidence, 2),
                "matched_elements": matched_elements,
                "matched_fields": matched_fields,
                "fields": screen.get("fields", []),
                "elements": screen.get("elements", []),
            }

    if best_screen and best_info.get("confidence", 0) >= 0.25:
        print(f"[detector] Screen identified: '{best_info['name']}' "
              f"(confidence={best_info['confidence']}, "
              f"elements={best_info['matched_elements']}, "
              f"fields={best_info['matched_fields']})")
        return best_info

    print(f"[detector] Could not identify screen (best score={best_score})")
    return None


def _find_input_by_placeholder(screenshot: Image.Image, field_label: str) -> tuple[int, int] | None:
    """Locate an input field by finding its placeholder text via OCR.

    Placeholder text appears inside the input box itself, so the OCR hit
    position is already *inside* the field — just click there.
    """
    placeholders = _load_field_placeholders()
    placeholder = placeholders.get(field_label)

    # Also check KB entry for a placeholder
    kb = _kb_entry(field_label)
    if not placeholder and kb:
        placeholder = kb.get("placeholder")
    if not placeholder:
        return None

    arr = np.array(screenshot)
    scale = _scale(screenshot)
    results = _ocr().readtext(arr)
    merged_results = _merge_ocr_results(results)

    for bbox, text, conf in merged_results:
        if _fuzzy(text, placeholder):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            cx = int((min(xs) + max(xs)) / 2 / scale)
            cy = int((min(ys) + max(ys)) / 2 / scale)
            print(f"[detector] Placeholder '{placeholder}' found for '{field_label}' at ({cx}, {cy})")
            return (cx, cy)

    return None


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
    # Merge Fragmented Labels
    merged_results = _merge_ocr_results(results)

    label_candidates = []
    kb = _kb_entry(field_label)
    skip_primary = kb.get("skip_primary_detection", False) if kb else False

    # Check for direct matches (skip if configured)
    if not skip_primary:
        for bbox, text, conf in merged_results:
            if _fuzzy(text, field_label):
                # Reject label bounding boxes that are unreasonably wide (>300px)
                # OCR sometimes includes the entire input field in the label bbox
                bbox_width = max(p[0] for p in bbox) - min(p[0] for p in bbox)
                if bbox_width > 300:
                    print(f"[detector] Rejecting '{text}' label: bbox too wide ({bbox_width}px > 300px). Likely OCR artifact.")
                    continue
                label_candidates.append((bbox, text, conf, False))
    else:
        print(f"[detector] Skipping primary detection for '{field_label}' (skip_primary_detection=true). Using anchor only.")
    
    # Try anchor_label from KB as a fallback when primary label detection fails
    # Use raw (unmerged) OCR results for anchor lookup to avoid merge artifacts
    is_smart = (kb.get("type") == "smart_input" if kb else False)
    if kb and "anchor_label" in kb:
        anchor = kb["anchor_label"]
        for bbox, text, conf in results:  # raw results, not merged
            if _fuzzy(text, anchor):
                bbox_width = max(p[0] for p in bbox) - min(p[0] for p in bbox)
                if bbox_width > 300:
                    print(f"[detector] Rejecting '{text}' anchor: bbox too wide ({bbox_width}px > 300px). Likely OCR artifact.")
                    continue
                label_candidates.append((bbox, text, conf, True))

    if not label_candidates:
        return None
        
    # Preference: 
    # 1. PRIMARY EXACT CASE MATCH (e.g. "Url") comes first
    # 2. PRIMARY EXACT INSENSITIVE MATCH comes second
    # 3. ANCHOR EXACT CASE MATCH comes third
    # 4. ANCHOR EXACT INSENSITIVE MATCH comes fourth
    # 5. Right-side bias (ignore sidebar)
    # 6. Higher OCR confidence
    def _cand_sort(c):
        p_text = c[1].strip()
        is_primary_case = p_text == field_label
        is_primary_exact = p_text.lower() == field_label.lower()
        
        is_anchor_case = False
        is_anchor_exact = False
        if c[3]: # is_anchor
            kb = _kb_entry(field_label)
            if kb and "anchor_label" in kb:
                anchor_target = kb["anchor_label"]
                is_anchor_case = p_text == anchor_target
                is_anchor_exact = p_text.lower() == anchor_target.lower()
        
        # Priority: (not primary_case), (not primary_exact), (not anchor_case), (not anchor_exact), (is_left_25), (is_blue_bg), (neg_confidence)
        screen_w = arr.shape[1]
        lx1 = min(p[0] for p in c[0])
        is_left_25 = lx1 < screen_w * 0.25
        return (not is_primary_case, not is_primary_exact, not is_anchor_case, not is_anchor_exact, is_left_25, _is_blue_background(arr, c[0]), -c[2])

    label_candidates.sort(key=_cand_sort)

    for cand_bbox, cand_text, cand_conf, is_anchor in label_candidates:
        lx1 = min(p[0] for p in cand_bbox)
        ly1 = min(p[1] for p in cand_bbox)
        lx2 = max(p[0] for p in cand_bbox)
        ly2 = max(p[1] for p in cand_bbox)

        # Regions relative to THIS candidate
        # Increased search area (1000px deep) to capture fields with very long descriptions (e.g. Target Type)
        sy2_buffer = 1000
        dx_buffer_left = 60
        dx_buffer_right = 800
        
        kb = _kb_entry(field_label)
        if kb and "search_region" in kb:
            sr = kb["search_region"]
            sy2_buffer = sr.get("height", sy2_buffer)
            dx_buffer_left = sr.get("x_offset_left", dx_buffer_left)
            dx_buffer_right = sr.get("x_offset_right", dx_buffer_right)

        # DIRECT SEARCH: Look immediately below the label (no description skipping)
        search_start_y = ly2 + 2

        rs_below = (max(0, lx1 - dx_buffer_left), search_start_y, min(arr.shape[1], lx1 + dx_buffer_right), min(arr.shape[0], search_start_y + sy2_buffer))
        rs_right = (lx2 + 5, ly1 - 10, min(arr.shape[1], lx2 + 1200), ly2 + 10)

        best: tuple[int, int, int, int] | None = None
        best_region_origin: tuple[int, int] = (0, 0)

        # ── Branch A: Contour detection ────────────────────────────────────────
        for sx1, sy1, sx2, sy2 in [rs_below, rs_right]:
            region = arr[sy1:sy2, sx1:sx2]
            if region.size == 0: continue
            gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
            
            # Light Mode contour robustness: lower thresholds for subtler edges
            is_light = _is_light_mode(screenshot)
            t1 = 10 if is_light else 15
            t2 = 40 if is_light else 50
            edges = cv2.Canny(gray, t1, t2)
            
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)

                # ── Skip edge-of-region artifacts (label borders, window chrome) ──
                # Only skip thin lines at the edge, not full-height input fields that
                # happen to start at y=0 (e.g. a field immediately below its label).
                if (x == 0 and w < 100) or (y == 0 and h < 15):
                    continue

                # ── Minimum height gate: ignore thin lines / decorative borders ──
                if h < 25:
                    continue

                if not (150 < w < 2000 and h < 80 and w > h * 1.5):
                    continue

                # ── Standard WSO2 height match (~32px smart-input, ~49px textarea) ──
                exact_h = (kb.get('exact_height') if kb else None) or _FIELD_HEIGHT_PX
                wso2_heights = {32, 49}
                h_match = abs(h - exact_h) <= 3
                wso2_match = any(abs(h - wh) <= 3 for wh in wso2_heights)
                # Height bonus: capped at 60, only awarded when height is close
                height_bonus = 60 if h_match else (40 if wso2_match else 0)

                # ── Continuous proximity score ────────────────────────────────
                # Vertical distance from label bottom to candidate top (pixel space).
                # Closer always beats farther unless the height difference is major.
                # Score = 200 - distance, clamped to [0, 200].  A box 0px away scores
                # 200; one 200+px away scores 0.  This dominates the height bonus (max
                # 60) so a nearer field wins unless it is implausibly thin/tall.
                abs_x1 = sx1 + x
                abs_y1 = sy1 + y
                vert_dist = max(0, abs_y1 - ly2)          # px below label bottom
                prox_score = max(0, 200 - vert_dist)       # continuous, range [0,200]

                # Score Breakdown:
                # 1. Proximity stays dominant (max 200)
                # 2. Lateral alignment (max 100): Strongly prefer alignment with label.
                # 3. Height match (max 60)
                # 4. Centrality (max 20): Weight by distance from label-aligned center, not region center.
                score = 0
                score += prox_score                                          # dominant: proximity
                score += height_bonus                                        # secondary: height match
                
                # REVISED Lateral alignment (dominant secondary)
                horiz_dist = abs(abs_x1 - lx1)
                lateral_score = max(0, 100 - horiz_dist)                     # up to +100 for perfect label alignment
                score += lateral_score

                # REVISED Centrality: Reward being "near the label" horizontally, avoid the far right.
                # Target center is lx1 + (typical field width / 2)
                target_center_x = lx1 + 250
                centrality_score = max(0, 20 - abs((abs_x1 + w/2) - target_center_x) // 10)
                score += centrality_score

                score += 30 if w > (best[2] * 1.2 if best else 300) else 0  # full-width input
                if is_anchor:
                    score += 20                                              # anchor sub-label bonus

                # Penalize boxes that contain unrelated text (not a placeholder or pre-filled value)
                for r_bbox, r_text, _rc in results:
                    rx1_o = min(p[0] for p in r_bbox)
                    ry1_o = min(p[1] for p in r_bbox)
                    rx2_o = max(p[0] for p in r_bbox)
                    ry2_o = max(p[1] for p in r_bbox)
                    if abs_x1 < (rx1_o + rx2_o) / 2 < abs_x1 + w and \
                       abs_y1 < (ry1_o + ry2_o) / 2 < abs_y1 + h:
                        clean_t = r_text.strip().lower()
                        kb_placeholder = (kb.get("placeholder", "").lower() if kb else "")
                        # A short single-word text without label markers (* :) is likely a
                        # pre-filled default value (e.g. "Untitled", "Default") — don't penalize
                        looks_like_prefilled = (
                            "*" not in r_text and ":" not in r_text and
                            len(r_text.strip().split()) <= 2 and len(r_text.strip()) <= 20
                        )
                        is_placeholder = (
                            looks_like_prefilled or
                            _fuzzy(r_text, field_label) or
                            (kb_placeholder and _fuzzy(r_text, kb_placeholder)) or
                            any(w_ in clean_t for w_ in ["enter", "type", "select", "path", "http"])
                        )
                        if not is_placeholder and len(r_text.strip()) > 2:
                            score -= 100
                            break

                if best is None:
                    best = (x, y, w, h)
                    best_region_origin = (sx1, sy1)
                    best_score = score
                    print(f"[detector]   Candidate: ({x},{y} w={w} h={h}) score={score}")
                elif score > best_score:
                    best = (x, y, w, h)
                    best_region_origin = (sx1, sy1)
                    best_score = score
                    print(f"[detector]   Candidate: ({x},{y} w={w} h={h}) score={score} ✓")
                elif score == best_score and y < best[1] - 5:
                    best = (x, y, w, h)
                    best_region_origin = (sx1, sy1)

            if best and best_score > 0:
                break  # high-quality candidate found

        # ── Branch B: Threshold scan (fallback) ───────────────────────────────
        if best:
            break

        for sx1, sy1, sx2, sy2 in [rs_below, rs_right]:
            region = arr[sy1:sy2, sx1:sx2]
            if region.size == 0:
                continue
            gray_region = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
            for thresh_val, mode in [(30, cv2.THRESH_BINARY), (60, cv2.THRESH_BINARY),
                                     (180, cv2.THRESH_BINARY), (80, cv2.THRESH_BINARY_INV)]:
                _, thresh = cv2.threshold(gray_region, thresh_val, 255, mode)
                contours2, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                best2 = None
                for cnt in contours2:
                    x, y, w, h = cv2.boundingRect(cnt)
                    if h < 25:
                        continue
                    if not (150 < w < 2000 and h < 80 and w > h * 1.5):
                        continue
                    abs_x1 = sx1 + x
                    abs_y1 = sy1 + y
                    directly_below = abs_y1 <= (ly2 + 80)
                    if best2 is None:
                        best2 = (x, y, w, h)
                    else:
                        is_wider = w > best2[2] * 1.2
                        is_close = abs(y - best2[1]) < 150
                        is_higher = y < best2[1] - 5
                        region_center = thresh.shape[1] / 2
                        dist_a = abs((best2[0] + best2[2] / 2) - region_center)
                        dist_b = abs((x + w / 2) - region_center)
                        is_more_central = dist_b < dist_a - 100
                        prefer = (directly_below and is_close) or \
                                 (is_wider and is_close) or \
                                 (is_more_central and is_close) or \
                                 (not is_wider and not is_more_central and is_higher)
                        if prefer:
                            best2 = (x, y, w, h)
                if best2:
                    best = best2
                    best_region_origin = (sx1, sy1)
                    break
            if best:
                break
        if best:
            break

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
        for cand_bbox, cand_text, _, _is_anc in label_candidates:
            lx1, ly1, lx2, ly2 = min(p[0] for p in cand_bbox), min(p[1] for p in cand_bbox), max(p[0] for p in cand_bbox), max(p[1] for p in cand_bbox)
            draw.rectangle([lx1, ly1, lx2, ly2], outline="red", width=3)
            # Draw the actual search regions used (rs_below and rs_right)
            draw.rectangle([rs_below[0], rs_below[1], rs_below[2], rs_below[3]], outline="green", width=2)
            draw.rectangle([rs_right[0], rs_right[1], rs_right[2], rs_right[3]], outline="green", width=1)

        # Draw the selected field in Cyan if found
        if best:
            rx, ry = best_region_origin
            x, y, w, h = best
            draw.rectangle([rx + x, ry + y, rx + x + w, ry + y + h], outline="cyan", width=4)
            cx = (rx + x + w / 2) / scale
            cy = (ry + y + h / 2) / scale
            draw.ellipse([cx * scale - 10, cy * scale - 10, cx * scale + 10, cy * scale + 10], fill="yellow", outline="black")

        status = "match" if best else "fail"
        fname = f"{status}_{field_label.replace('*', '')}.png"
        debug_img.save(_DEBUG_SAVE_DIR / fname)

    if best:
        rx, ry = best_region_origin
        x, y, w, h = best
        cx = int((rx + x + w / 2) / scale)
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
        cx = int((sx1 + x + w / 2) / scale)
        cy = int((sy1 + y + h / 2) / scale)
        print(f"[detector] Indexed search found box {field_index} below '{anchor_label}' at ({cx}, {cy}) (w={w})")
        return (cx, cy)

    print(f"[detector] Only found {len(candidates)} boxes below '{anchor_label}', needed index {field_index}")
    return None


def is_text_visible_near(screenshot: Image.Image, text: str, cx: int, cy: int, radius: int = 250) -> bool:
    """Return True if *text* (or a fuzzy match) is visible within *radius* logical pixels of (cx, cy).

    Used for idempotent typing and verification. 
    Searches broadly to the right to handle long input fields.
    """
    arr = np.array(screenshot)
    scale = _scale(screenshot)
    # Convert logical → pixel
    px, py = int(cx * scale), int(cy * scale)
    
    # Asymmetric search region: WSO2 fields are wide and left-aligned.
    # We must search far enough to the left AND right of the click point.
    x1 = max(0, px - int(800 * scale)) # Search up to 800px LEFT to catch URL start
    y1 = max(0, py - int(45 * scale))
    x2 = min(arr.shape[1], px + int(1200 * scale)) # Search up to 1200px RIGHT
    y2 = min(arr.shape[0], py + int(45 * scale))
    
    region = arr[y1:y2, x1:x2]
    if region.size == 0:
        return False
        
    found_tokens = []
    matches = False
    for _, found_text, _ in _ocr().readtext(region):
        found_tokens.append(found_text)
        if _fuzzy(found_text, text):
            matches = True
            break
            
    if not matches and found_tokens:
        # Also check if the 'text' is a substring of the concatenated tokens (with spaces)
        combined = " ".join(found_tokens).lower()
        # Clean both for better matching (URL fragments can be tricky)
        clean_text = text.lower().replace(" ", "")
        clean_combined = combined.replace(" ", "")
        
        if clean_text in clean_combined or clean_combined in clean_text:
            matches = True
            
    if matches:
        return True
    else:
        # Debug trace (always helpful for idempotency)
        if found_tokens:
            print(f"[detector]   Idempotent check for '{text}' at ({cx}, {cy}): False. Saw: {found_tokens}")
        else:
            print(f"[detector]   Idempotent check for '{text}': No text found in region.")
        return False


def _find_input_below_description(screenshot: Image.Image, field_label: str) -> tuple[int, int] | None:
    """Click slightly below the last word of the field's description text.

    Strategy:
      1. Find the field label (or its anchor_label) via OCR.
      2. Scan OCR results for description text that sits immediately below the label
         (within _DESCRIPTION_ZONE_PX pixels).
      3. Return a click coordinate a small fixed offset below the bottom of that
         description block — which lands inside the 28px input field.
    """
    arr = np.array(screenshot)
    scale = _scale(screenshot)
    results = _ocr().readtext(arr)

    # ── Step 1: find the label bbox ─────────────────────────────────────────
    label_bbox = None
    for bbox, text, conf in results:
        if _fuzzy(text, field_label) and not _is_blue_background(arr, bbox):
            label_bbox = bbox
            break

    # Fall back to anchor_label from KB
    kb = _kb_entry(field_label)
    if label_bbox is None and kb and "anchor_label" in kb:
        anchor = kb["anchor_label"]
        for bbox, text, conf in results:
            if _fuzzy(text, anchor):
                label_bbox = bbox
                break

    if label_bbox is None:
        return None

    lx1 = min(p[0] for p in label_bbox)
    ly2 = max(p[1] for p in label_bbox)

    # ── Step 2: collect description OCR boxes below the label ───────────────
    desc_bottom = None   # lowest y-pixel of any description line found
    for bbox, text, conf in results:
        ry1 = min(p[1] for p in bbox)
        ry2 = max(p[1] for p in bbox)
        rx1 = min(p[0] for p in bbox)
        # Must appear immediately below the label and share its left margin
        if ly2 + 2 <= ry1 <= ly2 + _DESCRIPTION_ZONE_PX and rx1 >= lx1 - 50:
            if desc_bottom is None or ry2 > desc_bottom:
                desc_bottom = ry2
                print(f"[detector] Description-anchor: '{text}' ends at pixel y={ry2}")

    if desc_bottom is None:
        # Click ~40px below the label as a blind guess for the input field box
        return (int(lx1 / scale) + 20, int(ly2 / scale) + 40)

    # ── Step 3: click at the description bottom ──────────────────────────────
    # desc_bottom is either the bottom of description text above the field,
    # or placeholder text inside the field. In both cases, clicking directly
    # at this y-position lands on or inside the input field — no offset needed.
    click_x = int(lx1 / scale) + 50           # 50 logical px right of label edge
    click_y = int(desc_bottom / scale)
    logical_offset = 0
    
    if _DEBUG_SAVE_DIR:
        from PIL import ImageDraw
        debug_img = screenshot.copy()
        draw = ImageDraw.Draw(debug_img)
        # All OCR
        for bbox, text, _ in results:
            dx1, dy1 = min(p[0] for p in bbox), min(p[1] for p in bbox)
            dx2, dy2 = max(p[0] for p in bbox), max(p[1] for p in bbox)
            draw.rectangle([dx1, dy1, dx2, dy2], outline="#CCCCCC", width=1)
        # Target label
        tx1, ty1, tx2, ty2 = min(p[0] for p in label_bbox), min(p[1] for p in label_bbox), max(p[0] for p in label_bbox), max(p[1] for p in label_bbox)
        draw.rectangle([tx1, ty1, tx2, ty2], outline="red", width=3)
        # Description lowest line
        draw.line([lx1, desc_bottom, lx1 + 200, desc_bottom], fill="blue", width=4)
        # Click point
        cx, cy = click_x * scale, click_y * scale
        draw.ellipse([cx-10, cy-10, cx+10, cy+10], fill="yellow", outline="black")
        
        fname = f"match_{field_label.replace('*', '')}.png"
        debug_img.save(_DEBUG_SAVE_DIR / fname)

    print(f"[detector] Description-anchor click at ({click_x}, {click_y}) "
          f"(desc_bottom={desc_bottom}px / scale={scale:.1f} → logical y "
          f"{int(desc_bottom/scale)}, offset=+{logical_offset})")
    return (click_x, click_y)


def find_input_field(screenshot: Image.Image, field_label: str) -> tuple[int, int] | None:
    """Find where to click to focus a named input field."""
    # Try direct visual detection first (label + contour)
    result = _find_input_by_visual(screenshot, field_label)
    if result:
        return result

    # Fall back to description-anchor method: locate the field's helper text and
    # click just below its last line — most reliable when a description is present.
    result = _find_input_below_description(screenshot, field_label)
    if result:
        return result

    # Try finding by placeholder text inside the input box
    result = _find_input_by_placeholder(screenshot, field_label)
    if result:
        return result

    # Try indexed fallback if metadata exists
    kb = _kb_entry(field_label)
    if kb and "field_index" in kb and "anchor_label" in kb:
        print(f"[detector] Direct visual failed for '{field_label}', trying indexed search using anchor '{kb['anchor_label']}'...")
        result = _find_input_by_index(screenshot, kb["anchor_label"], kb["field_index"])
        if result:
            return result

    # Try blind-click fallback if anchor and offset are provided
    if kb and "anchor_label" in kb and "click_offset" in kb:
        print(f"[detector] Direct visual failed for '{field_label}', attempting blind-click using anchor '{kb['anchor_label']}'...")
        anchor_pos = _find_ocr(screenshot, kb["anchor_label"])
        if anchor_pos:
            cx, cy = anchor_pos
            off_x, off_y = kb["click_offset"].get("x", 0), kb["click_offset"].get("y", 0)
            print(f"[detector]   Blind-click at {cx + off_x, cy + off_y} (offset: {off_x}, {off_y})")
            return (cx + off_x, cy + off_y)

    print(f"[detector] Visual detection failed for '{field_label}'.")
    return None


def find_element(screenshot: Image.Image, target: str, hint: str | None = None) -> tuple[int, int]:
    # "next_to:" hint: OCR-only search for + to the right of the named label.
    # Short-circuit everything else — no Start node, no template matching.
    if target.strip() == "+" and hint and hint.startswith("next_to:"):
        anchor = hint[len("next_to:"):].strip()
        result = _find_plus_right_of_label(screenshot, anchor_text=anchor)
        if result:
            return result
        raise ElementNotFoundError(f"Could not find '+' to the right of '{anchor}' via OCR.")

    # Skip OCR only for short symbols (e.g. '+') where OCR finds them in wrong places.
    # For all other targets, try OCR first and fall back to template match.
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



def find_search_field(screenshot: Image.Image, field_label: str = "Search") -> tuple[int, int] | None:
    """Locate a search input box by its placeholder text or label.

    Strategy:
      1. OCR the screenshot for the exact placeholder text (e.g. 'Search', 'Search connectors').
      2. If found, return the center of the detected region — that IS the clickable input.
      3. Fallback: look for a contour-shaped search box in the upper half of the screen.

    Returns logical (x, y) to click, or None if not found.
    """
    arr = np.array(screenshot)
    scale = _scale(screenshot)
    results = _ocr().readtext(arr)

    # Common search placeholder variants to look for
    search_variants = [field_label.lower()]
    if field_label.lower() == "search":
        search_variants += ["search connectors", "search...", "search…", "search for"]

    candidates = []
    for bbox, text, conf in results:
        t = text.strip().lower()
        if any(t == v or t.startswith(v) for v in search_variants):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            cx = int((min(xs) + max(xs)) / 2 / scale)
            cy = int((min(ys) + max(ys)) / 2 / scale)
            candidates.append((cx, cy, conf))

    if candidates:
        # Pick highest confidence match
        candidates.sort(key=lambda c: -c[2])
        x, y, _ = candidates[0]
        print(f"[detector] Search field '{field_label}' found via OCR at ({x}, {y})")
        return (x, y)

    # Fallback: find a wide, short input-shaped contour in the top 40% of screen
    # (search boxes are usually at the top of panels/dialogs)
    h_l = int(screenshot.height / scale)
    w_l = int(screenshot.width / scale)
    search_region = screenshot.crop((0, 0, screenshot.width, int(screenshot.height * 0.5)))
    region_arr = np.array(search_region)
    gray = cv2.cvtColor(region_arr, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 20, 80)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    search_box = None
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        # Search boxes: wide relative to height, reasonable size
        if 200 < w < 1200 and 15 < h < 50 and w > h * 4:
            if search_box is None or w > search_box[2]:
                search_box = (x, y, w, h)

    if search_box:
        x, y, w, h = search_box
        cx = int((x + w / 2) / scale)
        cy = int((y + h / 2) / scale)
        print(f"[detector] Search field found via contour at ({cx}, {cy})")
        return (cx, cy)

    print(f"[detector] Search field '{field_label}' not found")
    return None
