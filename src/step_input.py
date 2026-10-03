"""Between-step input for FlowCast — decide what happens AFTER a step records.

A documentation workflow rarely maps one-to-one onto the UI. Between two doc
steps the app often puts something in the way — a "Skip for now" on a welcome
card, a "Continue" on a dialog, a project that must be picked — and none of
that is written in the doc. This module is the pause where you say what that
something is:

    ── Step 2 recorded ──  anything before step 3?
      [1] click Skip for now                      (on screen)
      [2] click Continue                          (on screen)
      [3] Add an automation artifact              (doc · step 3)
      [4] click Add Artifact                      (learned · used 3x)
    next>

Type a number, type a command in plain language, `paste` a block of WSO2 doc
or knowledge-base text, or press Enter to move straight on to the next step.

Where the suggestions come from — before the first step is recorded,
ensure_doc_context() asks ONCE for the documentation page these steps came
from (paste it, give a file path, or answer `none`; the answer is remembered
per workflow). Every instruction-shaped line of that page is parsed, and at
each prompt the ones whose target is actually on screen are offered. That is
what turns a 200-line page into three relevant suggestions instead of noise.
Without a page, suggestions still come from the gate buttons visible on
screen, the next documented step and the knowledge base.

Window handling — the WSO2 window is full screen while recording, which
buries the terminal. So the window is minimised for the prompt, restored to
full screen to run and RECORD what you entered, then minimised again for the
next question. The recording therefore only ever shows the app, never this
prompt.

Training — every command that runs successfully is written to
kb/step_inputs.json, keyed by (workflow, step). The next run replays it
automatically with no prompt at all, so a workflow only has to be taught its
gaps once. `use_count` tracks how often a trained entry has paid off.

Off switch: FLOWCAST_STEP_INPUT=0 (or main.py --no-step-input).
Re-teach a position: FLOWCAST_STEP_INPUT=retrain (or main.py --retrain-steps).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import interactive, kb_learn, navigator, runner
from src.nl_commands import parse_command

_PATH = Path(__file__).parent.parent / "kb" / "step_inputs.json"
_DOC_PATH = Path(__file__).parent.parent / "kb" / "doc_pages.json"

# Buttons that typically stand between two documented steps. Matched against
# what OCR actually sees, so a suggestion is only offered when it is on screen.
_GATE_LABELS = [
    # NB: no bare "Start" — the design canvas has a Start node, and matching
    # it here suggested clicking the flow instead of a gate button.
    "Skip for now", "Skip", "Continue", "Next", "Get Started",
    "Got it", "Done", "Finish", "Close", "Dismiss", "Not now", "Later",
    "OK", "Save", "Open", "Allow", "Trust", "Yes, I trust the authors",
]

_MAX_SUGGESTIONS = 9


# ── Trained-input persistence (kb/step_inputs.json) ──────────────────────────

def _load() -> dict:
    if _PATH.exists():
        try:
            return json.loads(_PATH.read_text())
        except Exception:
            pass
    return {"version": 1, "entries": {}}


def _save(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2))


def _key(workflow: str, step_index: int) -> str:
    return f"{workflow}::after-step-{step_index}"


def get_trained(workflow: str, step_index: int) -> dict | None:
    return _load().get("entries", {}).get(_key(workflow, step_index))


def save_trained(workflow: str, step_index: int, step_title: str,
                 commands: list[str], screen_fp: str = "") -> None:
    """Remember the commands taught after this step so the next run is unattended."""
    data = _load()
    entries = data.setdefault("entries", {})
    k = _key(workflow, step_index)
    prev = entries.get(k, {})
    entries[k] = {
        "workflow": workflow,
        "step": step_index,
        "step_title": step_title,
        "commands": commands,
        "screen_fp": screen_fp,
        "use_count": prev.get("use_count", 0),
        "taught_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save(data)
    print(f"   [step-input] trained: after step {step_index} → {commands}")


def bump_use(workflow: str, step_index: int) -> None:
    data = _load()
    entry = data.get("entries", {}).get(_key(workflow, step_index))
    if not entry:
        return
    entry["use_count"] = entry.get("use_count", 0) + 1
    entry["last_used"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save(data)


def forget(workflow: str, step_index: int) -> None:
    data = _load()
    if data.get("entries", {}).pop(_key(workflow, step_index), None) is not None:
        _save(data)
        print(f"   [step-input] forgot the trained input after step {step_index}")


# ── The doc page (asked once per workflow) ───────────────────────────────────

def _load_docs() -> dict:
    if _DOC_PATH.exists():
        try:
            return json.loads(_DOC_PATH.read_text())
        except Exception:
            pass
    return {"version": 1, "pages": {}}


def _save_docs(data: dict) -> None:
    _DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DOC_PATH.write_text(json.dumps(data, indent=2))


def get_doc_page(workflow: str) -> str:
    return (_load_docs().get("pages", {}).get(workflow) or {}).get("text", "")


def save_doc_page(workflow: str, text: str) -> None:
    """Store the page (empty text = the user said 'none'; never ask again)."""
    data = _load_docs()
    data.setdefault("pages", {})[workflow] = {
        "text": text,
        "lines": len(text.splitlines()),
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save_docs(data)


def ensure_doc_context(workflow_path: Path | None, force: bool = False) -> str:
    """Ask ONCE, before recording starts, for the WSO2 doc page this workflow
    came from — then reuse it for every between-step suggestion.

    The workflow markdown only holds the numbered steps. The page around them
    names the buttons, cards and dialogs that appear BETWEEN those steps, which
    is exactly what the `next>` prompt has to guess at otherwise. With the page
    loaded, a suggestion is offered whenever something the doc mentions is
    actually on screen.

    Answering 'none' (or just Enter) is remembered too, so the question is
    asked once per workflow, not once per run. --retrain-steps asks again.
    """
    if _mode() == "off":
        return ""
    workflow = workflow_path.name if workflow_path else ""
    if not workflow:
        return ""

    entry = _load_docs().get("pages", {}).get(workflow)
    if entry is not None and not force and _mode() != "retrain":
        text = entry.get("text", "")
        if text:
            print(f"  [step-input] doc page loaded for {workflow} "
                  f"({entry.get('lines', 0)} lines) — used for between-step hints")
        return text

    if not interactive.available():
        return entry.get("text", "") if entry else ""

    try:
        _step_aside()
        print("\n" + "─" * 60)
        print(f"  DOC PAGE TEXT for {workflow}  (asked once per workflow)")
        print("\n  Paste the WSO2 documentation page these steps came from.")
        print("  It is used ONLY to suggest what to do between steps — the")
        print("  'Skip for now' cards, dialogs and buttons the page mentions")
        print("  but the numbered steps do not.")
        print("\n  Paste it, then end with a blank line or '.'")
        print("  Or give a file path to read it from.")
        print("  Or type 'none' (or just press Enter) to skip — suggestions")
        print("  then come from the screen, the next step and the KB only.")
        print("─" * 60)

        try:
            first = input("docs> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            first = "none"

        if not first or first.lower() in ("none", "no", "skip", "n", "-"):
            save_doc_page(workflow, "")
            print("  [step-input] no doc page — suggestions come from the screen, "
                  "the next step and the KB")
            return ""

        candidate = Path(first).expanduser()
        if candidate.exists() and candidate.is_file():
            try:
                text = candidate.read_text(errors="replace")
                save_doc_page(workflow, text)
                print(f"  [step-input] doc page read from {candidate} "
                      f"({len(text.splitlines())} lines)")
                return text
            except Exception as e:
                print(f"  [step-input] could not read {candidate}: {e}")
                return ""

        lines = [first]
        while True:
            try:
                ln = input("     | ")
            except (EOFError, KeyboardInterrupt):
                break
            if ln.strip() in (".", "end", "eof"):
                break
            if not ln.strip():
                break
            lines.append(ln)
        text = "\n".join(lines)
        save_doc_page(workflow, text)
        usable = len(_doc_candidates(text))
        print(f"  [step-input] doc page saved ({len(lines)} lines, "
              f"{usable} usable action hints)")
        return text
    finally:
        _come_back()


# ── Mode ─────────────────────────────────────────────────────────────────────

def _mode() -> str:
    """'off' | 'retrain' | 'on' — from FLOWCAST_STEP_INPUT."""
    v = os.environ.get("FLOWCAST_STEP_INPUT", "").strip().lower()
    if v in ("0", "off", "no", "false"):
        return "off"
    if v in ("retrain", "reteach", "force"):
        return "retrain"
    return "on"


# ── Action ⇄ command text ────────────────────────────────────────────────────

def _action_to_command(a: dict[str, Any]) -> str:
    """Render an action dict as a command string parse_command() reads back.

    Round-tripping matters: what gets stored in kb/step_inputs.json is replayed
    through parse_command() on later runs, so the phrasing has to survive it.
    """
    kind = a.get("action", "click")
    target = a.get("target", "")
    field = a.get("field_target", "")
    value = a.get("value", "")
    hint = a.get("hint") or ""
    if kind == "click":
        if hint and ":" in hint:
            rel, anchor = hint.split(":", 1)
            rel_word = {"below": "below", "next_to": "next to",
                        "right_of": "right of"}.get(rel, rel)
            if anchor:
                return f"click {target} {rel_word} {anchor}"
        return f"click {target}"
    if kind == "type":
        return f"enter {value} in {field}"
    if kind == "select":
        return f"select {value} from {field}"
    if kind == "search":
        return f"search for {value}"
    if kind == "hotkey":
        return "press " + "+".join(a.get("keys", []))
    if kind == "scroll":
        clicks = a.get("clicks", -3)
        return f"scroll {'up' if clicks > 0 else 'down'} {abs(clicks)}"
    if kind == "wait":
        return f"wait {a.get('seconds', 1)}"
    return f"click {target or field}"


def _describe_action(a: dict[str, Any]) -> str:
    return _action_to_command(a)


def _parse_line(line: str) -> dict[str, Any] | None:
    """Parse one line as either a WSO2 doc instruction or an NL command."""
    line = line.strip()
    if not line:
        return None
    # Doc phrasing first ("Select **X**", "Set **X** to `Y`", "1. Add …") —
    # this is what a copy-paste out of the WSO2 docs looks like.
    try:
        from src.parser import _parse_instructions
        acts = _parse_instructions(line)
        if acts:
            return acts[0]
    except Exception:
        pass
    kind, payload = parse_command(line)
    if kind == "action":
        return payload
    return None


def _parse_block(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse pasted doc / knowledge-base text into (label, action) pairs."""
    out: list[tuple[str, dict[str, Any]]] = []
    for raw in text.splitlines():
        act = _parse_line(raw)
        if act and act.get("action") not in (None, "open_app"):
            out.append((raw.strip(), act))
    return out


# ── Suggestions ──────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _screen_suggestions(shot) -> list[dict]:
    """Gate buttons ("Skip for now", "Continue", …) actually visible right now."""
    try:
        texts = navigator.describe_screen(shot).get("texts", [])
    except Exception:
        return []
    seen, out = set(), []
    for t in texts:
        clean = t.strip()
        if not clean or len(clean) > 40:
            continue
        for label in _GATE_LABELS:
            if _norm(clean) == _norm(label) or _norm(label) in _norm(clean):
                if _norm(clean) in seen:
                    break
                seen.add(_norm(clean))
                out.append({"command": f"click {clean}", "source": "on screen"})
                break
    return out


# A doc page is mostly prose. Only lines that read like an instruction are
# worth parsing — everything else would come back as a bogus "click <prose>".
_DOC_VERB = re.compile(
    r'^(?:select|click|choose|press|tap|set|enter|type|fill|add|search|open|'
    r'navigate|go\s+to|pick|toggle|check|expand)\b', re.I)

# The same imperative buried in a sentence: "When the welcome page appears,
# click Skip for now to go straight to the design view."
_INLINE_VERB = re.compile(
    r'\b(?:click|select|choose|press|tap)\s+(?:on\s+)?(?:the\s+)?'
    r'([\*`"\u2018\u2019\u201c\u201d\w][^,;.]{2,60})', re.I)

# Where a target stops being a target and turns back into prose.
_CLAUSE = re.compile(
    r'\s+(?:and|then|from|to|into|in|on|for|with|if|when|so|which|that|'
    r'button|option|card|icon|tab)\b|[,;:]|\s+\(', re.I)


def _clean_doc_line(raw: str) -> str:
    """Strip list markers and trailing punctuation off a doc line."""
    line = re.sub(r'^\s*(?:\d+[.)]|[-*+•])\s+', '', raw.strip())
    return line.rstrip(" .:;")


def _tighten_target(target: str) -> str:
    """Cut a click target back to the label the UI actually shows.

    "Add Artifact and choose Automation from the list" → "Add Artifact".
    Bold or backticked text wins outright — that is the doc's own markup for
    "this is a UI label".
    """
    t = target.strip().strip('"\u201c\u201d\u2018\u2019').strip()
    m = re.search(r'\*\*(.+?)\*\*|`(.+?)`', t)
    if m:
        t = (m.group(1) or m.group(2) or "").strip()
    else:
        t = _CLAUSE.split(t)[0].strip()
    t = t.strip(' .,:;*`"').strip()
    return t if 2 < len(t) <= 40 else ""


def _doc_candidates(doc_text: str) -> list[tuple[str, dict]]:
    """Instruction-shaped lines of the doc page, parsed to actions."""
    out: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for raw in doc_text.splitlines():
        line = _clean_doc_line(raw)
        if not line or len(line) > 240:
            continue

        act = None
        if "**" in line or "`" in line or _DOC_VERB.match(line):
            act = _parse_line(line)
        if act and act.get("action") == "click":
            tight = _tighten_target(act.get("target", ""))
            act = {**act, "target": tight} if tight else None
        if act is None:
            # An imperative inside a sentence — the doc's asides ("click Skip
            # for now…") are exactly the between-step gaps this prompt exists for.
            m = _INLINE_VERB.search(line)
            tight = _tighten_target(m.group(1)) if m else ""
            act = {"action": "click", "target": tight} if tight else None
        if not act or act.get("action") in ("open_app", "command", "wait"):
            continue

        anchor = (act.get("target") or act.get("field_target") or "").strip()
        if not 2 < len(anchor) <= 60:
            continue
        key = _norm(f"{act['action']}|{anchor}|{act.get('value', '')}")
        if key in seen:
            continue
        seen.add(key)
        out.append((line, act))
    return out


def _snap_to_screen(anchor: str, texts: list[str]) -> str | None:
    """Match a doc target to the label the screen is ACTUALLY showing.

    Doc prose has to be cut somewhere ("click Skip for now to go straight to
    the design view" → "Skip"), and the cut is often short of the real button.
    Snapping to the on-screen text fixes that — "Skip" becomes "Skip for now",
    "Yes" becomes "Yes, I trust the authors" — and doubles as the relevance
    test: no match on screen, no suggestion.
    """
    a = _norm(anchor).strip("+ ").strip()
    if not 3 <= len(a) <= 40:
        return None
    best = None
    for t in texts:
        tn = _norm(t)
        if len(tn) < 3:
            continue
        if tn == a:
            return t.strip()
        if a in tn or tn in a:
            # Shortest containing label — the button, not the paragraph.
            if best is None or len(tn) < len(_norm(best)):
                best = t.strip()
    return best


def _doc_page_suggestions(texts: list[str], doc_text: str,
                          limit: int = 5) -> list[dict]:
    """Doc-page instructions whose target is on screen RIGHT NOW.

    The on-screen test is what makes this useful rather than noisy: of a
    200-line page, only the handful of things you can actually act on at this
    moment are offered.
    """
    if not doc_text:
        return []
    out: list[dict] = []
    for _line, act in _doc_candidates(doc_text):
        key = "target" if act.get("target") else "field_target"
        snapped = _snap_to_screen(act.get(key, ""), texts)
        if not snapped:
            continue
        act = {**act, key: snapped}
        out.append({"command": _action_to_command(act),
                    "source": "doc page", "action": act})
        if len(out) >= limit:
            break
    return out


def _kb_suggestions(shot) -> list[dict]:
    try:
        return [{"command": f"click {t}", "source": "knowledge base"}
                for t in kb_learn.known_targets(shot)[:6]]
    except Exception:
        return []


def _learned_suggestions(workflow: str, step_title: str) -> list[dict]:
    """Guidance already given by hand elsewhere in this workflow/step."""
    out = []
    try:
        data = interactive._load_user_inputs()
    except Exception:
        return out
    for e in reversed(data.get("inputs", [])):
        if e.get("workflow") != workflow or e.get("step") != step_title:
            continue
        cmd = (e.get("user_input") or "").strip()
        if not cmd:
            continue
        n = e.get("use_count", 0)
        out.append({"command": cmd,
                    "source": f"learned{f' · used {n}x' if n else ''}"})
        if len(out) >= 4:
            break
    return out


def _doc_suggestions(next_step) -> list[dict]:
    """The first actions of the NEXT documented step — the WSO2 doc itself."""
    if next_step is None:
        return []
    out = []
    for a in (getattr(next_step, "actions", None) or [])[:4]:
        if a.get("action") in ("open_app", "command"):
            continue
        out.append({"command": _action_to_command(a),
                    "source": f"doc · {next_step.title}",
                    "action": a})
    return out


def build_suggestions(shot, workflow: str, step_title: str,
                      next_step, trained: dict | None,
                      doc_text: str = "") -> list[dict]:
    try:
        texts = navigator.describe_screen(shot).get("texts", [])
    except Exception:
        texts = []

    groups: list[dict] = []
    if trained:
        for c in trained.get("commands", []):
            groups.append({"command": c,
                           "source": f"trained · used {trained.get('use_count', 0)}x"})
    groups += _screen_suggestions(shot)
    groups += _doc_page_suggestions(texts, doc_text)
    groups += _doc_suggestions(next_step)
    groups += _learned_suggestions(workflow, step_title)
    groups += _kb_suggestions(shot)

    seen, out = set(), []
    for s in groups:
        k = _norm(s["command"])
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
        if len(out) >= _MAX_SUGGESTIONS:
            break
    return out


# ── Screen / terminal juggling ───────────────────────────────────────────────

def _focus_prompt_app() -> None:
    """Bring the terminal that is running FlowCast forward, so the prompt is
    visible once the WSO2 window steps aside."""
    app = os.environ.get("FLOWCAST_PROMPT_APP", "").strip()
    if not app:
        app = {"Apple_Terminal": "Terminal", "iTerm.app": "iTerm",
               "vscode": "Visual Studio Code",
               }.get(os.environ.get("TERM_PROGRAM", ""), "")
    if not app:
        return
    try:
        subprocess.run(["osascript", "-e", f'tell application "{app}" to activate'],
                       capture_output=True, timeout=5)
        time.sleep(0.3)
    except Exception:
        pass


def _notify(message: str) -> None:
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{message}" with title "FlowCast"'],
                       capture_output=True, timeout=5)
    except Exception:
        pass


def _step_aside() -> None:
    # With the prompt on a phone the Mac screen is never in the way, so there
    # is nothing to hide — and leaving the window alone keeps the recording
    # continuous between steps.
    from src import phone
    if phone.is_running():
        return
    runner.minimize_window()
    _focus_prompt_app()


def _come_back() -> None:
    from src import phone
    if phone.is_running():
        return
    runner.restore_window()


# ── Execution ────────────────────────────────────────────────────────────────

def _run_one(command: str, action: dict[str, Any] | None, tmp_dir: Path,
             clip_index: int) -> tuple[bool, Path | None]:
    """Bring the window back full screen, then run + record one command.

    The window is left up on purpose — the caller re-reads the screen for
    fresh suggestions before minimising again. The clip is renamed into the
    step's own `clip_NNN` series so the per-action narration data lines up
    with the actions list main.py extends.
    """
    act = action if action is not None else _parse_line(command)
    if act is None:
        print(f"   ? could not understand '{command}' — type 'help' for examples")
        return False, None

    _come_back()
    try:
        ok, clip, _pos = interactive._execute(act, tmp_dir, clip_index)
    except Exception as e:  # noqa: BLE001 — a bad command must not kill the run
        print(f"   ✗ failed to run '{command}': {e}")
        return False, None

    if clip is not None:
        dest = clip.with_name(f"clip_{clip_index:03d}{clip.suffix}")
        try:
            clip.rename(dest)
            clip = dest
        except OSError:
            pass
    return ok, clip


# ── Replay of a trained entry ────────────────────────────────────────────────

def _replay(trained: dict, workflow: str, step_index: int, tmp_dir: Path,
            action_offset: int) -> tuple[list[Path], list[dict], bool]:
    """Run a trained entry unattended. Returns (clips, actions, complete)."""
    commands = trained.get("commands", [])
    print(f"\n   [step-input] replaying {len(commands)} trained command(s) after "
          f"step {step_index} (taught {trained.get('taught_at', '?')})")
    clips: list[Path] = []
    actions: list[dict] = []
    for k, cmd in enumerate(commands):
        print(f"   [step-input] {k + 1}/{len(commands)}: {cmd}")
        act = _parse_line(cmd)
        ok, clip = _run_one(cmd, act, tmp_dir, action_offset + len(clips))
        if not ok:
            print(f"   [step-input] trained command failed: '{cmd}'")
            return clips, actions, False
        if clip:
            clips.append(clip)
            if act:
                actions.append(act)
    bump_use(workflow, step_index)
    return clips, actions, True


# ── The prompt ───────────────────────────────────────────────────────────────

def _print_menu(step_index: int, next_step, suggestions: list[dict],
                doc_text: str = "") -> None:
    nxt = (f"step {step_index + 1}: {next_step.title}" if next_step
           else "the end of the workflow")
    print("\n" + "─" * 60)
    print(f"  STEP {step_index} RECORDED — anything to do before {nxt}?")
    if doc_text:
        print(f"  (suggestions include the doc page — "
              f"{len(doc_text.splitlines())} lines loaded)")
    if suggestions:
        print("\n  Suggestions (type the number to run it):")
        for i, s in enumerate(suggestions, 1):
            print(f"    [{i}] {s['command']:<44} ({s['source']})")
    print("\n  Enter        → skip for now, go on to the next step")
    print("  <command>    → e.g. 'click Skip for now', 'enter demo in Name'")
    print("  paste        → paste WSO2 doc / knowledge-base text to run NOW")
    print("  docpage      → load/replace the doc page behind the suggestions")
    print("  where        → describe what is on screen right now")
    print("  help         → command examples")
    print("  forget       → drop the trained input for this position")
    print("  abort        → stop the run")
    print("─" * 60)


def _read_pasted_block() -> str:
    print("\n  Paste the doc / knowledge-base text. End with a blank line or '.':")
    lines: list[str] = []
    while True:
        try:
            ln = input("  | ")
        except (EOFError, KeyboardInterrupt):
            break
        if ln.strip() in (".", "end", "eof"):
            break
        if not ln.strip() and lines:
            break
        if ln.strip():
            lines.append(ln)
    return "\n".join(lines)


def after_step(step_index: int, step, next_step, tmp_dir: Path,
               workflow_path: Path | None,
               action_offset: int) -> tuple[list[Path], list[dict], str]:
    """Ask what to do after a recorded step; run and record the answer.

    Returns (clips, actions, status) — status is 'ok' or 'abort'. clips are
    extra recordings to append to this step's video; actions are the matching
    action dicts, so per-action narration keeps its labels.

    Whatever happens in here, the window goes back full screen on the way out:
    the next step starts recording immediately, and a window left minimised
    would record the desktop.
    """
    if _mode() == "off":
        return [], [], "ok"
    try:
        return _ask(step_index, step, next_step, tmp_dir, workflow_path,
                    action_offset)
    finally:
        _come_back()


def _ask(step_index: int, step, next_step, tmp_dir: Path,
         workflow_path: Path | None,
         action_offset: int) -> tuple[list[Path], list[dict], str]:
    """The prompt itself — see after_step(), which guarantees the window is
    full screen again when this returns."""
    mode = _mode()
    workflow = workflow_path.name if workflow_path else ""
    step_title = getattr(step, "title", "")
    trained = get_trained(workflow, step_index)

    clips: list[Path] = []
    actions: list[dict] = []

    # Trained and proven → replay unattended. That is the whole point of
    # teaching it once.
    if trained and mode != "retrain":
        clips, actions, complete = _replay(trained, workflow, step_index,
                                           tmp_dir, action_offset)
        if complete:
            return clips, actions, "ok"
        if not interactive.available():
            return clips, actions, "ok"
        print("   [step-input] re-teaching this position")

    if not interactive.available():
        if not trained:
            print("   [step-input] no terminal to ask on — moving to the next step")
        return clips, actions, "ok"

    # Asked once per workflow, before recording started — see
    # ensure_doc_context(). Empty when the user answered 'none'.
    doc_text = get_doc_page(workflow)

    # The app is still on screen from the recording — read it before hiding it.
    def _look() -> tuple[list[dict], str]:
        shot = runner._screenshot()
        try:
            fp, _ = kb_learn.screen_fingerprint(shot)
        except Exception:
            fp = ""
        sugg = build_suggestions(shot, workflow, step_title, next_step,
                                 trained if mode == "retrain" else None,
                                 doc_text=doc_text)
        return sugg, fp

    suggestions, screen_fp = _look()
    _step_aside()
    _notify(f"Step {step_index} recorded — what next?")
    entered: list[str] = []

    while True:
        _print_menu(step_index, next_step, suggestions, doc_text)
        try:
            from src import phone
            raw = (phone.ask("next") if phone.is_running()
                   else input("next> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        low = raw.lower()
        if not raw or low in ("skip", "s", "n", "no", "done", "ok", "continue"):
            break
        if low == "abort":
            return clips, actions, "abort"
        if low in ("help", "?"):
            from src.nl_commands import HELP_TEXT
            print(HELP_TEXT)
            continue
        if low in ("where", "look", "screen"):
            _come_back()
            interactive._describe()
            suggestions, screen_fp = _look()
            _step_aside()
            continue
        if low == "forget":
            forget(workflow, step_index)
            trained = None
            continue
        if low in ("docpage", "docs", "page"):
            doc_text = ensure_doc_context(workflow_path, force=True)
            suggestions, screen_fp = _look()
            _step_aside()
            continue

        # ── Pasted WSO2 doc / knowledge-base text ─────────────────────────
        if low in ("paste", "kb"):
            parsed = _parse_block(_read_pasted_block())
            if not parsed:
                print("   ? nothing runnable in that text")
                continue
            print(f"\n   Parsed {len(parsed)} action(s):")
            for i, (src_line, act) in enumerate(parsed, 1):
                print(f"    {i}. {_describe_action(act)}   ← {src_line[:60]}")
            try:
                go = input("   Run them all? [Y/n] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                continue
            if go in ("n", "no"):
                continue
            for _src, act in parsed:
                cmd = _action_to_command(act)
                ok, clip = _run_one(cmd, act, tmp_dir, action_offset + len(clips))
                if not ok:
                    print(f"   ✗ stopped at '{cmd}'")
                    break
                entered.append(cmd)
                if clip:
                    clips.append(clip)
                    actions.append(act)
            suggestions, screen_fp = _look()
            _step_aside()
            continue

        # ── A numbered suggestion ─────────────────────────────────────────
        chosen_action = None
        if raw.isdigit() and suggestions:
            idx = int(raw) - 1
            if not (0 <= idx < len(suggestions)):
                print(f"   ? no suggestion [{raw}]")
                continue
            picked = suggestions[idx]
            raw = picked["command"]
            chosen_action = picked.get("action")
            print(f"   ↻ {raw}   ({picked['source']})")

        ok, clip = _run_one(raw, chosen_action, tmp_dir, action_offset + len(clips))
        if ok:
            entered.append(raw)
            if clip:
                clips.append(clip)
                act = chosen_action or _parse_line(raw)
                actions.append(act or {"action": "click", "target": raw})
        suggestions, screen_fp = _look()
        _step_aside()

    # ── Train ─────────────────────────────────────────────────────────────
    if entered:
        save_trained(workflow, step_index, step_title, entered, screen_fp)

    return clips, actions, "ok"
