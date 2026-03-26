"""Self-healing loop for FlowCast.

When an element cannot be found or a click produces no UI change, this module
diagnoses whether the problem is in the .md instructions (typo / wrong name)
or in the detection code, then retries with escalating strategies.

Strategies (in order):
  1. cache_winner  — previously successful strategy for this element
  2. ocr_exact     — standard OCR fuzzy match
  3. ocr_longest   — longest alpha word from target, similarity-matched
# (Strategies 1-3 only)

Diagnosis:
  MD_ERROR   — similar text exists on screen but does not match target → probable typo
  CODE_ERROR — target text absent from screen entirely → detection/state issue
  AMBIGUOUS  — multiple near-matches, unclear cause
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any

_CACHE_PATH = Path(__file__).parent.parent / "kb" / "strategy_cache.json"
_DEBUG_DIR = Path(__file__).parent.parent / "output" / "heal_debug"
_MAX_PHASES = 4
_SIMILARITY_MD_THRESHOLD = 0.75   # above this → likely MD typo
_SIMILARITY_ABSENT_THRESHOLD = 0.5  # below this → element not on screen


class HealingAbortedError(Exception):
    """Raised when healing determines the .md instructions are the likely cause."""


class DiagnosisKind(Enum):
    MD_ERROR = "md_error"
    CODE_ERROR = "code_error"
    AMBIGUOUS = "ambiguous"


@dataclass
class DiagnosisResult:
    kind: DiagnosisKind
    closest_match: str | None = None
    similarity: float = 0.0
    message: str = ""


@dataclass
class HealContext:
    action: dict[str, Any]
    screenshot: Any          # PIL Image
    ocr_results: list        # raw EasyOCR results
    step_title: str = ""
    action_index: int = 0


# ── Per-session guard ──────────────────────────────────────────────────────────
_healed_this_session: set[str] = set()


def reset_session() -> None:
    """Call at the start of each step to reset the per-session guard."""
    _healed_this_session.clear()


# ── Cache I/O ──────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text())
        except Exception:
            pass
    return {"version": 1, "entries": {}}


def _save_cache(cache: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=2))


def _cache_key(target: str) -> str:
    return target.lower().strip()


def record_win(target: str, strategy: str) -> None:
    """Record a successful detection strategy for future runs."""
    cache = _load_cache()
    key = _cache_key(target)
    entry = cache["entries"].setdefault(key, {"winner": None, "fail_counts": {}, "last_seen": None})
    entry["winner"] = strategy
    entry["last_seen"] = datetime.now(timezone.utc).isoformat()
    _save_cache(cache)


def get_winner(target: str) -> str | None:
    """Return the previously successful strategy for this target, or None."""
    cache = _load_cache()
    entry = cache["entries"].get(_cache_key(target))
    if not entry:
        return None
    winner = entry.get("winner")
    # If it has failed twice since winning, invalidate
    fail_count = entry.get("fail_counts", {}).get(winner, 0)
    if fail_count >= 2:
        return None
    return winner


def record_fail(target: str, strategy: str) -> None:
    """Increment fail count for a strategy; invalidate cache if threshold reached."""
    cache = _load_cache()
    key = _cache_key(target)
    entry = cache["entries"].setdefault(key, {"winner": None, "fail_counts": {}, "last_seen": None})
    fails = entry.setdefault("fail_counts", {})
    fails[strategy] = fails.get(strategy, 0) + 1
    if entry.get("winner") == strategy and fails[strategy] >= 2:
        print(f"[healer] Cache invalidated for '{target}' (strategy '{strategy}' failed {fails[strategy]}x)")
        entry["winner"] = None
    _save_cache(cache)


# ── Diagnosis ──────────────────────────────────────────────────────────────────

def _best_ocr_similarity(target: str, ocr_results: list) -> tuple[str, float]:
    best_text, best_ratio = "", 0.0
    t = target.lower().strip()
    for _, text, _ in ocr_results:
        for word in text.lower().split():
            ratio = SequenceMatcher(None, t, word).ratio()
            if ratio > best_ratio:
                best_ratio, best_text = ratio, text
        # Also check the full OCR string
        ratio = SequenceMatcher(None, t, text.lower()).ratio()
        if ratio > best_ratio:
            best_ratio, best_text = ratio, text
    return best_text, best_ratio


def diagnose(target: str, ocr_results: list, screenshot: Any | None = None) -> DiagnosisResult:
    """Analyse why an element was not found."""
    # Use longest alpha word as the representative token (same as detector)
    words = [w for w in target.split() if w.isalpha()]
    keyword = max(words, key=len) if words else target

    best_text, best_ratio = _best_ocr_similarity(keyword, ocr_results)

    if best_ratio >= _SIMILARITY_MD_THRESHOLD:
        return DiagnosisResult(
            kind=DiagnosisKind.MD_ERROR,
            closest_match=best_text,
            similarity=best_ratio,
            message=(
                f"Possible typo in .md: target='{target}', "
                f"closest OCR match='{best_text}' (similarity={best_ratio:.2f}). "
                f"Consider correcting the .md."
            ),
        )

    if best_ratio < _SIMILARITY_ABSENT_THRESHOLD:
        return DiagnosisResult(
            kind=DiagnosisKind.CODE_ERROR,
            closest_match=best_text or None,
            similarity=best_ratio,
            message=(
                f"Element '{target}' not visible on screen "
                f"(best OCR similarity={best_ratio:.2f}). "
                f"App may be in wrong state or prior step failed."
            ),
        )

    return DiagnosisResult(
        kind=DiagnosisKind.AMBIGUOUS,
        closest_match=best_text,
        similarity=best_ratio,
        message=(
            f"Ambiguous failure for '{target}': "
            f"closest='{best_text}' (sim={best_ratio:.2f})."
        ),
    )


def _save_debug_screenshot(target: str, screenshot: Any) -> Path:
    _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    slug = target.lower().replace(" ", "_").replace("+", "plus")[:40]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _DEBUG_DIR / f"{slug}_{ts}.png"
    screenshot.save(str(path))
    return path


# ── Healing entry point ────────────────────────────────────────────────────────

def heal(ctx: HealContext) -> tuple[int, int] | None:
    """Try escalating strategies to locate an element.

    Returns (x, y) on success, or raises HealingAbortedError / ElementNotFoundError.
    """
    from src.detector import (
        ElementNotFoundError,
        _find_ocr,
        _scale,
        _ocr,
    )
    import numpy as np

    target = ctx.action.get("target") or ctx.action.get("field_target", "")
    key = _cache_key(target)

    if key in _healed_this_session:
        raise ElementNotFoundError(f"'{target}' already attempted healing this session — aborting")
    _healed_this_session.add(key)

    print(f"[healer] Healing '{target}'...")

    # ── Phase 0: try cached winner first ──────────────────────────────────────
    winner = get_winner(target)
    # (Strategy 0: check cached winner)

    # ── Phase 1: fresh OCR ────────────────────────────────────────────────────
    time.sleep(0.5)
    result = _find_ocr(ctx.screenshot, target)
    if result:
        print(f"[healer] Phase 1 OCR found '{target}' at {result}")
        record_win(target, "ocr_exact")
        return result

    # ── Phase 2: wait + retry OCR ─────────────────────────────────────────────
    print(f"[healer] Phase 2: waiting 1.5s then retrying OCR for '{target}'")
    time.sleep(1.5)
    import pyautogui
    fresh_screenshot = pyautogui.screenshot()
    arr = np.array(fresh_screenshot)
    fresh_ocr = _ocr().readtext(arr)

    result = _find_ocr(fresh_screenshot, target)
    if result:
        print(f"[healer] Phase 2 OCR-after-wait found '{target}' at {result}")
        record_win(target, "ocr_after_wait")
        return result

    # ── Phase 3: diagnose + auto-correct ─────────────────────────────────────
    diag = diagnose(target, fresh_ocr, fresh_screenshot)
    print(f"[healer] Diagnosis: {diag.message}")

    if diag.kind == DiagnosisKind.MD_ERROR and diag.closest_match:
        # .md has a typo — retry OCR using the corrected text from screen
        corrected = diag.closest_match.strip()
        print(f"[healer] Auto-correcting target: '{target}' → '{corrected}'")
        result = _find_ocr(fresh_screenshot, corrected)
        if result:
            print(f"[healer] Corrected OCR found '{corrected}' at {result}")
            record_win(target, "ocr_corrected")
            return result

    # ── Phase 4: All strategies failed ─────────────────────────────────────────
    debug_path = _save_debug_screenshot(target, fresh_screenshot)
    raise ElementNotFoundError(
        f"All healing strategies failed for '{target}'. "
        f"Debug screenshot: {debug_path}"
    )
