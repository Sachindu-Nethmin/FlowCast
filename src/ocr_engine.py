"""Unified OCR engine for FlowCast.

Provides a single `read_text()` entry point that all detection code shares.

Engines (selected via env var FLOWCAST_OCR, default "auto"):
  vision   — Apple Vision framework (VNRecognizeTextRequest). Native macOS OCR,
             dramatically more accurate than EasyOCR on small anti-aliased UI
             text: correct word grouping, casing, and punctuation.
  easyocr  — legacy EasyOCR engine (kept as fallback / for benchmarking).
  auto     — Vision if available, otherwise EasyOCR.

All engines return results in the EasyOCR format so existing detector code
works unchanged:  list of (bbox_4pts, text, confidence) where bbox_4pts is
[[x1,y1],[x2,y1],[x2,y2],[x1,y2]] in *image pixel* coordinates.

Results are cached per-image (hash of pixel bytes) so the many detection
methods that inspect the same screenshot only pay the OCR cost once. This also
makes the fallback chain deterministic: every method sees identical results.
"""
from __future__ import annotations

import io
import os
import zlib

import numpy as np
from PIL import Image

_ENGINE_ENV = "FLOWCAST_OCR"

# ── Per-image result cache ────────────────────────────────────────────────────
# Small LRU keyed by (engine, shape, crc32 of pixel bytes). Screenshots during a
# single resolve/heal cycle are byte-identical, so this collapses the 5-15
# repeated readtext calls per action into one.
_CACHE_MAX = 8
_cache: dict[tuple, list] = {}
_cache_order: list[tuple] = []

_easyocr_reader = None
_vision_available: bool | None = None


def _to_array(image) -> np.ndarray:
    if isinstance(image, Image.Image):
        return np.array(image)
    return np.asarray(image)


def _cache_key(arr: np.ndarray, engine: str) -> tuple:
    data = arr.tobytes()
    return (engine, arr.shape, zlib.crc32(data))


def engine_name() -> str:
    """Resolve the active engine name ('vision' or 'easyocr')."""
    pref = os.environ.get(_ENGINE_ENV, "auto").lower().strip()
    if pref == "easyocr":
        return "easyocr"
    if pref == "vision":
        return "vision"
    # auto: prefer Vision when importable (macOS)
    return "vision" if _check_vision() else "easyocr"


def _check_vision() -> bool:
    global _vision_available
    if _vision_available is None:
        try:
            import Vision  # noqa: F401
            import Quartz  # noqa: F401
            _vision_available = True
        except Exception:
            _vision_available = False
    return _vision_available


# ── EasyOCR backend ───────────────────────────────────────────────────────────

def _easyocr():
    global _easyocr_reader
    if _easyocr_reader is None:
        from pathlib import Path
        import easyocr
        model_dir = Path(__file__).parent.parent / ".easyocr_models"
        model_dir.mkdir(parents=True, exist_ok=True)
        user_network_dir = model_dir / "user_network"
        user_network_dir.mkdir(parents=True, exist_ok=True)
        print(f"[ocr] Initializing EasyOCR (models in {model_dir})...")
        _easyocr_reader = easyocr.Reader(
            ["en"], gpu=False,
            model_storage_directory=str(model_dir),
            user_network_directory=str(user_network_dir),
        )
        print("[ocr] EasyOCR ready")
    return _easyocr_reader


def _read_easyocr(arr: np.ndarray) -> list:
    return _easyocr().readtext(arr)


# ── Apple Vision backend ──────────────────────────────────────────────────────

def _read_vision(arr: np.ndarray) -> list:
    """OCR via Apple Vision framework. Returns EasyOCR-format results.

    Vision returns line-level observations with normalized bounding boxes
    (origin bottom-left). We convert to pixel coords with origin top-left.
    Line-level grouping is an accuracy win: labels like "Integration Name"
    arrive as ONE block instead of fragmented/merged word soup.
    """
    import Quartz
    import Vision
    from Foundation import NSData

    h, w = arr.shape[:2]

    # Encode as PNG in memory → CGImage (robust across pixel formats)
    img = Image.fromarray(arr) if not isinstance(arr, Image.Image) else arr
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    ns_data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    src = Quartz.CGImageSourceCreateWithData(ns_data, None)
    if src is None:
        raise RuntimeError("CGImageSourceCreateWithData failed")
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    if cg_image is None:
        raise RuntimeError("CGImageSourceCreateImageAtIndex failed")

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    # UI labels are not prose — language correction would "fix" identifiers
    # like "Untitled1" or "HTTP" into dictionary words. Keep raw.
    request.setUsesLanguageCorrection_(False)
    try:
        request.setRecognitionLanguages_(["en-US"])
    except Exception:
        pass

    ok = handler.performRequests_error_([request], None)
    # pyobjc may return bool or (bool, error) depending on version
    if isinstance(ok, tuple):
        ok = ok[0]
    if not ok:
        raise RuntimeError("VNImageRequestHandler.performRequests failed")

    results = []
    for obs in (request.results() or []):
        candidates = obs.topCandidates_(1)
        if not candidates or candidates.count() == 0:
            continue
        top = candidates.objectAtIndex_(0)
        text = str(top.string())
        conf = float(top.confidence())
        bb = obs.boundingBox()  # normalized, origin bottom-left
        # Cast to int — downstream detector code uses these for array slicing
        x1 = int(bb.origin.x * w)
        y1 = int((1.0 - bb.origin.y - bb.size.height) * h)
        x2 = int(x1 + bb.size.width * w)
        y2 = int(y1 + bb.size.height * h)
        bbox = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        results.append((bbox, text, conf))
    return results


# ── Public API ────────────────────────────────────────────────────────────────

def read_text(image) -> list:
    """OCR an image (PIL Image or numpy array) with caching.

    Returns EasyOCR-format results: [(bbox_4pts, text, confidence), ...].
    """
    arr = _to_array(image)
    engine = engine_name()
    key = _cache_key(arr, engine)
    if key in _cache:
        return _cache[key]

    if engine == "vision":
        try:
            results = _read_vision(arr)
        except Exception as e:
            print(f"[ocr] Vision OCR failed ({e}); falling back to EasyOCR")
            global _vision_available
            _vision_available = False
            results = _read_easyocr(arr)
    else:
        results = _read_easyocr(arr)

    _cache[key] = results
    _cache_order.append(key)
    while len(_cache_order) > _CACHE_MAX:
        old = _cache_order.pop(0)
        _cache.pop(old, None)
    return results


def clear_cache() -> None:
    _cache.clear()
    _cache_order.clear()
