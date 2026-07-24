"""Learned knowledge base for FlowCast.

Stores what was learned during guided (teach-mode) sessions and successful
runs: for each SCREEN (fingerprinted by its distinctive visible texts), which
TARGET was clicked/typed WHERE, and how often that worked.

File: kb/learned_actions.json
{
  "version": 1,
  "screens": {
    "<fingerprint>": {
      "name": "...",                     # human-readable guess
      "texts": ["Create New Integration", ...],
      "targets": {
        "create": {
          "kind": "click",
          "pos_rel": [0.52, 0.61],       # relative to logical screen size
          "label": "Create",
          "wins": 3, "fails": 0,
          "last_used": "2026-07-12T10:00:00Z"
        }
      }
    }
  }
}

Future unguided runs consult this FIRST: same screen + known target →
use the learned position (verified via OCR near that point before clicking).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

_KB_PATH = Path(__file__).parent.parent / "kb" / "learned_actions.json"


def _load() -> dict:
    if _KB_PATH.exists():
        try:
            return json.loads(_KB_PATH.read_text())
        except Exception:
            pass
    return {"version": 1, "screens": {}}


def _save(data: dict) -> None:
    _KB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _KB_PATH.write_text(json.dumps(data, indent=2))


def _norm(s: str) -> str:
    return re.sub(r'[^\w\s]', '', s).lower().strip()


# ── Screen fingerprinting ─────────────────────────────────────────────────────

# Texts too generic to identify a screen
_GENERIC = {"create", "cancel", "ok", "save", "close", "back", "next", "run",
            "open", "file", "edit", "view", "help", "search", "settings"}


def screen_fingerprint(screenshot: Image.Image) -> tuple[str, list[str]]:
    """Stable fingerprint of the current screen from its distinctive texts.

    Uses the longest / most distinctive visible texts (sorted, normalized) so
    the fingerprint survives OCR jitter, theme changes, and cursor position.
    Returns (fingerprint_hash, texts_used).
    """
    from src import navigator
    texts = navigator.visible_texts(screenshot)
    distinctive = sorted({
        _norm(t) for t in texts
        if len(_norm(t)) >= 8 and _norm(t) not in _GENERIC
        and not _norm(t).isdigit()
    })
    # Cap to the 12 longest for stability across minor UI changes
    distinctive = sorted(distinctive, key=len, reverse=True)[:12]
    distinctive.sort()
    fp = hashlib.sha1("|".join(distinctive).encode()).hexdigest()[:16]
    return fp, distinctive


def match_screen(screenshot: Image.Image) -> tuple[str | None, dict | None]:
    """Find the stored screen best matching the current one.

    Exact fingerprint first; then fuzzy overlap (≥60% of stored distinctive
    texts visible) so small UI differences don't orphan learned knowledge.
    Returns (fingerprint, screen_entry) or (None, None).
    """
    data = _load()
    fp, texts = screen_fingerprint(screenshot)
    if fp in data["screens"]:
        return fp, data["screens"][fp]

    current = set(texts)
    best_fp, best_entry, best_overlap = None, None, 0.0
    for sfp, entry in data["screens"].items():
        stored = set(entry.get("texts", []))
        if not stored:
            continue
        overlap = len(stored & current) / len(stored)
        if overlap >= 0.6 and overlap > best_overlap:
            best_fp, best_entry, best_overlap = sfp, entry, overlap
    return best_fp, best_entry


# ── Recording & lookup ────────────────────────────────────────────────────────

def record(screenshot: Image.Image, target: str, kind: str,
           pos: tuple[int, int], screen_size: tuple[int, int],
           success: bool, screen_name: str = "") -> None:
    """Record an executed action's outcome against the current screen."""
    data = _load()
    fp, texts = screen_fingerprint(screenshot)
    screen = data["screens"].setdefault(fp, {"name": screen_name or "", "texts": texts, "targets": {}})
    if screen_name and not screen.get("name"):
        screen["name"] = screen_name
    key = _norm(target)
    entry = screen["targets"].setdefault(key, {
        "kind": kind, "label": target, "wins": 0, "fails": 0, "pos_rel": None,
    })
    if success:
        entry["wins"] += 1
        entry["pos_rel"] = [round(pos[0] / screen_size[0], 4),
                            round(pos[1] / screen_size[1], 4)]
    else:
        entry["fails"] += 1
    entry["last_used"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save(data)
    state = "win" if success else "fail"
    print(f"[kb_learn] Recorded {state}: '{target}' ({kind}) on screen {fp}"
          + (f" at rel {entry['pos_rel']}" if success else ""))


def record_alias(screenshot: Image.Image, target: str, alias: str,
                 screen_name: str = "") -> None:
    """Learn that on this screen, *target* actually means clicking *alias*.

    An alias is more robust than a stored position: the alias label is
    re-resolved by OCR on every future run, so it survives window resizes,
    theme changes, and layout shifts. Used when the user's guided fix clicks
    a DIFFERENT label than the instruction named (doc vs UI mismatch, e.g.
    'Get Started' → 'Skip for now').
    """
    # Validate: alias must be meaningful UI text, not a command word or too short
    _VERBS = {"click", "press", "tap", "hit", "push", "enter", "type",
              "fill", "input", "put", "write", "select", "choose", "pick",
              "search", "scroll", "wait", "undo", "ok", "skip", "abort",
              "done", "continue", "help", "where", "retry"}
    clean = alias.strip().lower().rstrip('.')
    if len(clean) < 3 or clean in _VERBS or clean.startswith(('at ', 'click ')):
        print(f"[kb_learn] Skipping invalid alias: '{target}' → '{alias}' (too short or command word)")
        return

    data = _load()
    fp, texts = screen_fingerprint(screenshot)
    screen = data["screens"].setdefault(fp, {"name": screen_name or "", "texts": texts, "targets": {}})
    entry = screen["targets"].setdefault(_norm(target), {
        "kind": "click", "label": target, "wins": 0, "fails": 0, "pos_rel": None,
    })
    entry["alias"] = alias
    entry["wins"] += 1
    entry["last_used"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save(data)
    print(f"[kb_learn] Learned alias: '{target}' → click '{alias}' on screen {fp}")


def lookup_alias(screenshot: Image.Image, target: str) -> str | None:
    """Learned alias label for *target* on the current screen, or None.

    EXACT screen fingerprint only — no fuzzy matching. An alias is a
    screen-specific redirect ('Get Started' → 'Skip for now'); applying it on
    a merely-similar screen clicks the wrong element with total confidence.
    """
    data = _load()
    fp, _ = screen_fingerprint(screenshot)
    entry = data["screens"].get(fp)
    if not entry:
        return None
    t = entry.get("targets", {}).get(_norm(target))
    if not t or not t.get("alias"):
        return None
    if t.get("wins", 0) <= t.get("fails", 0):
        return None
    return t["alias"]


def lookup(screenshot: Image.Image, target: str,
           screen_size: tuple[int, int]) -> tuple[int, int] | None:
    """Learned position for *target* on the current screen, or None.

    Only returns positions with a positive track record (wins > fails).
    """
    _, entry = match_screen(screenshot)
    if not entry:
        return None
    t = entry.get("targets", {}).get(_norm(target))
    if not t or not t.get("pos_rel"):
        return None
    if t.get("wins", 0) <= t.get("fails", 0):
        return None
    rx, ry = t["pos_rel"]
    pos = (int(rx * screen_size[0]), int(ry * screen_size[1]))
    print(f"[kb_learn] Learned position for '{target}': {pos} "
          f"(wins={t['wins']}, fails={t['fails']})")
    return pos


def known_targets(screenshot: Image.Image) -> list[str]:
    """Labels this KB knows how to reach from the current screen."""
    _, entry = match_screen(screenshot)
    if not entry:
        return []
    return [t.get("label", k) for k, t in entry.get("targets", {}).items()
            if t.get("wins", 0) > t.get("fails", 0)]
