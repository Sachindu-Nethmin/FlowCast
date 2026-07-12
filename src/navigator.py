"""Screen-state awareness for FlowCast — perceive first, then act.

Instead of blindly replaying instructions from the beginning, this module:
  1. Reads what buttons / fields / labels are ACTUALLY visible right now
     (`describe_screen`, `is_target_visible`).
  2. Detects which workflow step the WSO2 Integrator is currently at
     (`find_resume_step`) so a run can resume mid-workflow.
  3. Detects actions whose effect is already applied — e.g. a value already
     typed into its field (`action_effect_applied`) — so they are skipped.

All checks reuse the cached OCR results from `detector`, so perception adds
almost no extra cost on top of normal detection.

Disable auto-resume with FLOWCAST_NO_RESUME=1 (or pass --from-step 1).
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np
from PIL import Image

from src import detector


# ── Perception ────────────────────────────────────────────────────────────────

def visible_texts(screenshot: Image.Image, min_conf: float = 0.3) -> list[str]:
    """All text blocks currently visible on screen (merged OCR lines)."""
    results = detector._read_ocr(np.array(screenshot))
    merged = detector._merge_ocr_results(results)
    return [t.strip() for _, t, c in merged if c >= min_conf and t.strip()]


def describe_screen(screenshot: Image.Image) -> dict:
    """Snapshot of the current UI: visible texts, input-field count, screen id."""
    texts = visible_texts(screenshot)
    arr = np.array(screenshot)
    try:
        boxes = detector._detect_input_boxes(arr, detector._is_light_mode(screenshot))
    except Exception:
        boxes = []
    screen = None
    try:
        screen = detector.identify_screen(screenshot)
    except Exception:
        pass
    return {"texts": texts, "input_count": len(boxes), "screen": screen}


import re as _re


def _clean(s: str) -> str:
    return _re.sub(r'[^\w\s]', '', s).lower().strip()


def is_target_visible(screenshot: Image.Image, target: str, strict: bool = False) -> bool:
    """Cheap OCR-only visibility check (no full find_element scoring).

    strict=True requires the WHOLE text block to match the target (cleaned
    equality or ≥0.85 whole-string similarity). Used for resume/skip
    decisions, where loose word-containment is dangerous — e.g. the target
    'Create' must NOT count as visible just because 'Create New Integration'
    is on screen.
    """
    if not target or len(target.strip()) <= 2:
        return False  # symbols like '+' need template matching, not OCR
    for t in visible_texts(screenshot):
        if strict:
            if _clean(t) == _clean(target) or detector._similarity_score(t, target) >= 0.85:
                return True
        else:
            if detector._fuzzy(t, target) or detector._similarity_score(t, target) >= 0.85:
                return True
    return False


def _action_target(action: dict[str, Any]) -> str | None:
    kind = action.get("action")
    if kind == "click":
        return action.get("target")
    if kind in ("type", "select", "search"):
        return action.get("field_target")
    return None


# ── Step resume ───────────────────────────────────────────────────────────────

def _step_targets(step) -> list[str]:
    return [t for a in step.actions
            if (t := _action_target(a)) and len(t.strip()) > 2]


def step_match_score(step, screenshot: Image.Image) -> tuple[bool, float, list[str]]:
    """How well the current screen matches a step.

    Returns (entry_visible, fraction_visible, visible_targets):
      entry_visible    — the step's FIRST text target is on screen (step is
                         ready to start)
      fraction_visible — share of ALL the step's text targets currently
                         visible (high mid-step or when its UI is open)
      visible_targets  — which of the step's targets are visible
    """
    targets = _step_targets(step)
    if not targets:
        return (False, 0.0, [])
    visible = [is_target_visible(screenshot, t, strict=True) for t in targets]
    vis_targets = [t for t, v in zip(targets, visible) if v]
    return (visible[0], sum(visible) / len(targets), vis_targets)


def _distinctive(targets: list[str]) -> bool:
    """Evidence strong enough to place the app mid-step WITHOUT its entry
    target: at least two of the step's targets visible, or one target that is
    distinctive on its own (multi-word or long). A lone generic word like
    'Create' or 'Run' is NOT enough — such text appears on many screens."""
    if len(targets) >= 2:
        return True
    return any(len(t.split()) >= 2 or len(t.strip()) >= 8 for t in targets)


def find_resume_step(steps: list, screenshot: Image.Image) -> int:
    """Return the 1-based index of the step matching the CURRENT UI state.

    Every step is scored against what is actually on screen — the app can be
    at ANY step, including the last one, and including mid-step (a step whose
    entry button is gone but whose later targets are visible still matches
    via fraction_visible). The LATEST plausible step wins, since earlier
    steps' UI (sidebars, headers) often stays visible after completion.
    Falls back to 1 when nothing matches.
    """
    if os.environ.get("FLOWCAST_NO_RESUME", "").strip() == "1":
        return 1

    candidates: list[int] = []
    for idx, step in enumerate(steps, 1):
        entry_visible, frac, vis_targets = step_match_score(step, screenshot)
        n = len(_step_targets(step))
        print(f"[navigator] step {idx}: entry={'✓' if entry_visible else '✗'} "
              f"targets_visible={frac:.0%} ({n} targets)"
              + (f" visible={vis_targets}" if vis_targets else ""))
        # Candidate if its entry target is on screen, OR (mid-step) enough of
        # its targets are visible AND the evidence is distinctive.
        if entry_visible or (frac >= 0.4 and _distinctive(vis_targets)):
            candidates.append(idx)

    if not candidates:
        print("[navigator] No step matches the current screen — starting at step 1")
        return 1
    best = max(candidates)
    if len(candidates) > 1:
        print(f"[navigator] Steps {candidates} match current screen — resuming at step {best}")
    return best


# ── Idempotency ───────────────────────────────────────────────────────────────

def action_effect_applied(screenshot: Image.Image, action: dict[str, Any]) -> bool:
    """True if the action's effect is already visible on screen.

    Currently detects: a 'type' action whose value already sits INSIDE an
    input-shaped box (so re-typing would duplicate text).
    """
    if action.get("action") != "type":
        return False
    value = (action.get("value") or "").strip()
    if len(value) < 3:
        return False

    arr = np.array(screenshot)
    try:
        boxes = detector._detect_input_boxes(arr, detector._is_light_mode(screenshot))
    except Exception:
        return False
    if not boxes:
        return False

    for bbox, text, conf in detector._read_ocr(arr):
        if conf < 0.3:
            continue
        if not (detector._fuzzy(text, value)
                or detector._similarity_score(text, value) >= 0.9):
            continue
        cx = sum(p[0] for p in bbox) / 4
        cy = sum(p[1] for p in bbox) / 4
        if any(b[0] < cx < b[2] and b[1] < cy < b[3] for b in boxes):
            print(f"[navigator] Value '{value}' already present in an input box — action already done")
            return True
    return False


def first_available_action(screenshot: Image.Image, actions: list,
                           start_index: int = 0) -> int | None:
    """Index of the first action at/after start_index whose target is
    ACTUALLY clickable/visible on the current screen.

    Used to decide what to do next based on what's really there: when the
    current action's target is missing, the UI may already be several actions
    ahead — fast-forward to the first later action whose target is visible.

    Stops scanning at an unverifiable action (symbol targets like '+', or
    hotkey/wait): we must not blindly skip past something we can't confirm.
    Returns None if no later action is verifiably available.
    """
    for j in range(start_index, len(actions)):
        target = _action_target(actions[j])
        if not target or len(target.strip()) <= 2:
            return None  # can't verify visually — don't skip past it
        if is_target_visible(screenshot, target, strict=True):
            return j
    return None


def next_action_available(screenshot: Image.Image, actions: list, current_index: int) -> bool:
    """True if a later action's target is already visible (see first_available_action)."""
    return first_available_action(screenshot, actions, current_index + 1) is not None
