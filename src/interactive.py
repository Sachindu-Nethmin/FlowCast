"""Interactive terminal fallback for FlowCast — no separate teach mode.

Normal runs are unguided. When an action FAILS (element not found, UI didn't
change after a click, typed text ended up blue-selected), the run pauses and
waits on the terminal for natural-language guidance:

    what next> click create button
    what next> enter myfile in the file name field
    what next>                       ← press Enter to continue the workflow

Every successful user-directed action is recorded to the learned KB (under
BOTH the user's phrasing and the original workflow target), so the next run
handles the same spot unguided. Recovery actions are also screen-recorded so
the step's GIF stays complete.

When a guided fix succeeds, the workflow markdown is auto-updated so future
runs use the correct instruction directly (edit with 'edit' to preview changes
before saving, or they save automatically).

User inputs are saved to kb/user_inputs.json for reuse. When the same action
fails on a similar screen, saved inputs are suggested automatically.

Disabled automatically when stdin is not a terminal, or with FLOWCAST_NO_PROMPT=1.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pyautogui

from src import kb_learn, navigator, recorder, runner
from src.nl_commands import HELP_TEXT, parse_command

_USER_INPUTS_PATH = Path(__file__).parent.parent / "kb" / "user_inputs.json"


# ── User input persistence ────────────────────────────────────────────────────

def _load_user_inputs() -> dict:
    """Load saved user inputs from disk."""
    if _USER_INPUTS_PATH.exists():
        try:
            return json.loads(_USER_INPUTS_PATH.read_text())
        except Exception:
            pass
    return {"version": 1, "inputs": []}


def _save_user_inputs(data: dict) -> None:
    """Persist user inputs to disk."""
    _USER_INPUTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _USER_INPUTS_PATH.write_text(json.dumps(data, indent=2))


def save_user_input(workflow: str, step_title: str, action_index: int,
                    original_target: str, user_input: str,
                    screen_fp: str = "") -> None:
    """Record a successful user input for future reuse."""
    data = _load_user_inputs()
    data["inputs"].append({
        "workflow": workflow,
        "step": step_title,
        "action_index": action_index,
        "original_target": original_target,
        "user_input": user_input,
        "screen_fp": screen_fp,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "use_count": 0,
    })
    # Keep last 200 entries to avoid bloat
    data["inputs"] = data["inputs"][-200:]
    _save_user_inputs(data)
    print(f"   [user-input] Saved: '{user_input}' for step '{step_title}' action {action_index + 1}")


def lookup_user_input(workflow: str, step_title: str, action_index: int,
                      screen_fp: str = "") -> list[dict]:
    """Find saved user inputs for this exact situation.

    Returns matching inputs sorted by recency, most used first.
    """
    data = _load_user_inputs()
    matches = []
    for entry in data.get("inputs", []):
        if (entry.get("workflow") == workflow
                and entry.get("step") == step_title
                and entry.get("action_index") == action_index):
            # Screen fingerprint match is optional — same step+action is usually enough
            if screen_fp and entry.get("screen_fp") and entry["screen_fp"] != screen_fp:
                continue
            matches.append(entry)
    # Sort by use_count desc, then by timestamp desc
    matches.sort(key=lambda e: (-e.get("use_count", 0), e.get("timestamp", "")))
    return matches[:5]  # Return top 5


def increment_use_count(workflow: str, step_title: str, action_index: int,
                        user_input: str) -> None:
    """Bump the use count for a saved input when it's reused successfully."""
    data = _load_user_inputs()
    for entry in data.get("inputs", []):
        if (entry.get("workflow") == workflow
                and entry.get("step") == step_title
                and entry.get("action_index") == action_index
                and entry.get("user_input") == user_input):
            entry["use_count"] = entry.get("use_count", 0) + 1
            entry["last_used"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            break
    _save_user_inputs(data)


def available() -> bool:
    if os.environ.get("FLOWCAST_NO_PROMPT", "").strip() == "1":
        return False
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _describe() -> None:
    shot = runner._screenshot()
    fp, _ = kb_learn.screen_fingerprint(shot)
    desc = navigator.describe_screen(shot)
    known = kb_learn.known_targets(shot)
    print(f"\n   ── screen {fp} ──")
    print(f"   visible: " + ", ".join(desc["texts"][:15])
          + (" …" if len(desc["texts"]) > 15 else ""))
    print(f"   input boxes: {desc['input_count']}"
          + (f" | learned here: {', '.join(known)}" if known else ""))


def _target_of(a: dict) -> str:
    return a.get("target") or a.get("field_target", "") or a.get("action", "")


# ── Workflow markdown editing ─────────────────────────────────────────────────

def _user_action_to_markdown(action: dict) -> str:
    """Convert a parsed action dict back to a markdown instruction line."""
    kind = action.get("action", "click")
    target = action.get("target", "")
    field = action.get("field_target", "")
    value = action.get("value", "")
    hint = action.get("hint", "")

    if kind == "click":
        if hint:
            # e.g. "click + below Start" → "Select **+** next to **Start**"
            parts = hint.split(":", 1)
            rel = parts[0] if parts else ""
            anchor = parts[1] if len(parts) > 1 else ""
            rel_map = {"below": "under", "next_to": "next to", "right_of": "right of"}
            rel_word = rel_map.get(rel, rel)
            return f"Select **{target}** {rel_word} **{anchor}**"
        return f"Select **{target}**"
    if kind == "type":
        return f'Set **{field}** to `{value}`'
    if kind == "search":
        # NOTE: parser._parse_instructions treats "search **X** ..." as
        # X being the VALUE to search for (its "field for `value`" pattern
        # is unreachable dead code — the bold-value regex always matches
        # first). Match that behaviour here so this round-trips correctly.
        if hint:
            panel = hint.split(":", 1)[-1] if ":" in hint else hint
            return f"Search **{value}** from the {panel}"
        return f"Search **{value}**"
    if kind == "select":
        # Matches the established authoring convention for dropdown-style
        # fields (e.g. "Set **Authentication** to **Basic Authentication**")
        # which parser.py's bold-value "Set X to Y" rule round-trips
        # correctly. A literal "Select X from Y" phrasing has no matching
        # parser rule and would silently collapse to a bare click on X.
        return f"Set **{field}** to **{value}**"
    if kind == "hotkey":
        keys = "+".join(action.get("keys", []))
        return f"Press **{keys}**"
    if kind == "scroll":
        direction = "down" if action.get("clicks", 0) < 0 else "up"
        return f"Scroll {direction}"
    if kind == "wait":
        return f"Wait {action.get('seconds', 1)} seconds"
    if kind == "open_app":
        return f"Open {action.get('app_name') or 'the application'}"
    return f"Select **{target or field}**"


# Public alias — used by src/guide.py when authoring a brand-new workflow
# markdown file from a recorded guide session (not just patching an existing
# instruction line).
action_to_markdown = _user_action_to_markdown


def _update_workflow_instruction(workflow_path: Path, step_title: str,
                                  action_index: int, new_instruction: str,
                                  actions: list[dict]) -> bool:
    """Replace a failed instruction line in the workflow markdown.

    Finds the step block by title, locates the Nth instruction line,
    and replaces it with the corrected instruction.
    Returns True if the file was modified.
    """
    if not workflow_path.exists():
        return False

    content = workflow_path.read_text()
    lines = content.split("\n")

    # Find the step block by title
    step_pattern = re.compile(
        rf'^##\s+Step\s+\d+\s*[:\-–]?\s*{re.escape(step_title)}',
        re.IGNORECASE | re.MULTILINE,
    )
    step_match = step_pattern.search(content)
    if not step_match:
        print(f"   [workflow-edit] Could not find step '{step_title}' in {workflow_path.name}")
        return False

    # Find the line range for this step
    step_start = content[:step_match.start()].count("\n")
    # Find next step or end of file
    next_step = re.search(r'^##\s+Step', content[step_match.end():], re.MULTILINE)
    step_end = step_start + content[step_match.end():step_match.end() + next_step.start()].count("\n") + 1 if next_step else len(lines)

    # Find numbered instruction lines within this step (skip the ## header)
    instruction_lines = []
    for i in range(step_start + 1, step_end):
        line = lines[i]
        if re.match(r'^\s*\d+\.\s+', line):
            instruction_lines.append(i)

    if action_index >= len(instruction_lines):
        print(f"   [workflow-edit] Action index {action_index} out of range "
              f"(step has {len(instruction_lines)} instructions)")
        return False

    target_line_idx = instruction_lines[action_index]
    old_line = lines[target_line_idx].strip()

    # Generate the new instruction
    # Preserve the original list number
    m = re.match(r'^(\s*\d+\.)\s*', lines[target_line_idx])
    prefix = m.group(1) if m else f"{action_index + 1}."

    new_line = f"{prefix} {new_instruction}"

    if old_line == new_line:
        return False

    print(f"\n   [workflow-edit] Updating step '{step_title}', action {action_index + 1}:")
    print(f"     OLD: {old_line}")
    print(f"     NEW: {new_line}")

    lines[target_line_idx] = new_line
    workflow_path.write_text("\n".join(lines))
    print(f"   [workflow-edit] ✓ Saved to {workflow_path.name}")
    return True


def _execute(user_action: dict, tmp_dir: Path | None, clip_idx: int
             ) -> tuple[bool, Path | None, tuple[int, int] | None]:
    """Resolve + fire one user command, verify, learn.

    Returns (success, recorded_clip_or_None, position_or_None).
    Failed attempts' clips are discarded so GIFs only show correct actions.
    """
    target = _target_of(user_action)
    kind = user_action["action"]
    shot_before = runner._screenshot()

    if user_action.get("_direct"):
        resolved = dict(user_action)
    else:
        try:
            resolved = runner.resolve(user_action)
        except Exception as e:
            print(f"   ✗ cannot find '{target}': {e}")
            return False, None, None
    if resolved.get("_detection_failed"):
        print(f"   ✗ could not locate the field '{target}' — check the spelling "
              f"of the field name (see the 'visible:' list above)")
        return False, None, None
    if resolved.get("_skip"):
        print("   ○ nothing to do (auto-populated / not clickable)")
        return True, None, None

    clip_name = f"fix_{clip_idx:03d}"
    if tmp_dir is not None and kind not in ("wait", "hotkey"):
        runner.set_pre_move_callback(lambda n=clip_name: recorder.start(n, tmp_dir))

    try:
        runner.fire(resolved)
    except Exception as e:
        runner.set_pre_move_callback(None)
        if recorder._proc is not None:
            recorder.stop().unlink(missing_ok=True)
        print(f"   ✗ failed: {e}")
        return False, None, None

    if kind == "wait":
        return True, None, None

    # Verify against the PRE-ACTION screenshot so fast transitions that
    # already finished are still detected as a change.
    ui_changed = runner.wait_ui_change(timeout=4.0, baseline=shot_before)
    runner.wait_ui_settle()
    runner.set_pre_move_callback(None)
    clip = recorder.stop() if recorder._proc is not None else None

    x, y = resolved.get("x"), resolved.get("y")
    size = runner.screen_size()

    if runner.LAST_REPORT.get("blue_selection"):
        print("   ✗ typed text is blue-highlighted — wrong field focus. Undoing (cmd+z)…")
        pyautogui.hotkey("command", "z")
        time.sleep(0.4)
        if x is not None:
            kb_learn.record(shot_before, target, kind, (x, y), size, success=False)
        if clip:
            clip.unlink(missing_ok=True)
        return False, None, None

    if kind in ("click", "select") and not ui_changed:
        print("   ✗ UI did not change — probably a label / wrong place. "
              "Try another way, or type 'ok' if it actually worked.")
        if target.strip() == "+":
            print("   tip: tell me WHERE the + is, e.g. 'click + below Start' "
                  "or 'click + next to Query' — or exact spot: 'at 512,300'")
        if x is not None:
            kb_learn.record(shot_before, target, kind, (x, y), size, success=False)
        if clip:
            clip.unlink(missing_ok=True)
        return False, None, None

    pos = (x, y) if x is not None else None
    if pos and kind in ("click", "type", "select", "search"):
        kb_learn.record(shot_before, target, kind, pos, size, success=True)
    print(f"   ✓ {kind} '{target}' verified")
    return True, clip, pos


def recover(failed_action: dict, tmp_dir: Path | None = None,
            undo_first: bool = False, reason: str = "",
            on_unavailable: str = "abort",
            workflow_path: Path | None = None,
            step_title: str = "",
            action_index: int = 0,
            step_actions: list[dict] | None = None) -> tuple[str, list[Path]]:
    """Pause the run and ask the terminal what to do next.

    Returns (status, clips): status is 'ok' (recovered — continue workflow),
    'skip' (skip this action) or 'abort' (stop the run). clips are recovery
    recordings to append to the step's GIF.

    When workflow_path is provided and a fix is applied, the workflow markdown
    is auto-updated so future runs use the correct instruction directly.

    Saved user inputs are loaded and suggested when the same action fails again.
    """
    clips: list[Path] = []
    orig_target = _target_of(failed_action)
    orig_kind = failed_action.get("action", "click")

    if undo_first:
        pyautogui.hotkey("command", "z")
        time.sleep(0.4)

    if not available():
        print(f"[interactive] No terminal available — cannot ask for guidance "
              f"({on_unavailable}ing '{orig_target}')")
        return (on_unavailable, clips)

    # Look up saved inputs for this situation
    wf_name = workflow_path.name if workflow_path else ""
    shot_for_fp = runner._screenshot()
    fp, _ = kb_learn.screen_fingerprint(shot_for_fp)
    saved = lookup_user_input(wf_name, step_title, action_index, fp)

    print("\n" + "─" * 60)
    print(f"  NEED GUIDANCE: could not {orig_kind} '{orig_target}' automatically"
          + (f" — {reason}" if reason else ""))
    _describe()
    print("  Tell me what to do in plain language ('help' for examples).")
    print("  'skip' = skip this action | 'ok' = it's already done | 'abort' = stop run")
    if workflow_path:
        print("  'edit' = preview workflow changes before saving")
    if saved:
        print(f"\n  📋 Saved inputs for this step (type number to reuse):")
        for idx, s in enumerate(saved, 1):
            count = s.get("use_count", 0)
            label = f"    [{idx}] {s['user_input']}"
            if count > 0:
                label += f"  (used {count}x)"
            print(label)
        print(f"  Or type a new command to save it for next time.")
    print("─" * 60)

    n = 0
    shot_at_prompt = runner._screenshot()
    pending_fix: dict | None = None  # staged fix awaiting confirmation
    reused_from_saved = False  # track if current input came from saved list

    # Auto-apply a proven saved input (use_count > 0) to skip prompting
    auto_input = None
    if saved:
        best = max(saved, key=lambda s: s.get("use_count", 0))
        if best.get("use_count", 0) > 0:
            auto_input = best["user_input"]

    if auto_input:
        print(f"\n   ⚡ Auto-applying saved input: '{auto_input}'")
        increment_use_count(wf_name, step_title, action_index, auto_input)
        raw = auto_input
        reused_from_saved = True
        kind, payload = parse_command(raw)
        if kind != "error" and kind != "control":
            ok, clip, pos = _execute(payload, tmp_dir, n)
            n += 1
            if clip:
                clips.append(clip)
            if ok:
                save_user_input(wf_name, step_title, action_index,
                               orig_target, raw, fp)
                user_t = _target_of(payload)
                same_kind = payload.get("action") == orig_kind
                diff_label = bool(user_t and orig_target
                                  and user_t.lower() != orig_target.lower())
                if n == 1 and same_kind and diff_label and not payload.get("_direct"):
                    if orig_kind == "click":
                        kb_learn.record_alias(shot_at_prompt, orig_target, user_t)
                    elif pos:
                        kb_learn.record(shot_at_prompt, orig_target, orig_kind, pos,
                                        runner.screen_size(), success=True)
                    if workflow_path and step_title and step_actions is not None:
                        _update_workflow_instruction(
                            workflow_path, step_title, action_index,
                            _user_action_to_markdown(payload), step_actions)
                print("   ✓ continuing the workflow.")
                return ("ok", clips)
            else:
                print(f"   ⚡ Auto-applied input failed — falling back to manual prompt")
                auto_input = None

    while True:
        reused_from_saved = False  # reset each iteration; set True only on reuse
        try:
            raw = input("what next> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return ("abort", clips)

        if not raw:
            print("   (type a command, or 'skip' / 'ok' / 'abort')")
            continue

        # Check if user typed a number to reuse a saved input
        if saved and raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(saved):
                reuse_input = saved[idx]["user_input"]
                print(f"   ↻ Reusing saved input: '{reuse_input}'")
                increment_use_count(wf_name, step_title, action_index, reuse_input)
                raw = reuse_input
                reused_from_saved = True
            else:
                print(f"   ? Invalid number. Choose 1-{len(saved)} or type a new command.")
                continue

        kind, payload = parse_command(raw)
        if kind == "error":
            print(f"   ? {payload}")
            continue
        if kind == "control":
            if payload == "abort" or payload == "quit":
                return ("abort", clips)
            if payload == "skip":
                return ("skip", clips)
            if payload in ("ok", "done"):
                # If there's a pending fix, apply it now
                if pending_fix and workflow_path:
                    _update_workflow_instruction(
                        workflow_path, step_title,
                        pending_fix["action_index"],
                        pending_fix["instruction"],
                        pending_fix["actions"],
                    )
                return ("ok", clips)
            if payload == "help":
                print(HELP_TEXT)
                continue
            if payload == "where":
                _describe()
                continue
            if payload == "undo":
                pyautogui.hotkey("command", "z")
                time.sleep(0.4)
                print("   ↩ undo sent")
                continue
            if payload == "edit":
                if pending_fix:
                    print(f"\n   Proposed workflow update for step '{step_title}', "
                          f"action {pending_fix['action_index'] + 1}:")
                    print(f"     OLD: {pending_fix['old_instruction']}")
                    print(f"     NEW: {pending_fix['instruction']}")
                    print(f"   Type 'ok' to save, or give a different command to change it.")
                else:
                    print("   No pending fix to preview. Fix an action first.")
                continue
            continue

        ok, clip, pos = _execute(payload, tmp_dir, n)
        n += 1
        if clip:
            clips.append(clip)
        if ok:
            # Save this user input for future reuse (suggestion list only)
            save_user_input(wf_name, step_title, action_index,
                           orig_target, raw, fp)

            # CONFIRM before saving any mapping under the ORIGINAL target.
            # Auto-learning here poisoned the KB before: when a click silently
            # fails, the UI is one step BEHIND, so the user's fix is usually
            # the PREVIOUS action — recording that as "what '{orig}' means"
            # creates wrong aliases (e.g. 'Automation' → 'Add Artifact') that
            # misfire forever after. Only the user knows if this fix IS the
            # original instruction done correctly — so ask.
            # HOWEVER: if this input was reused from the saved list (the user
            # already confirmed it in a previous run), skip the prompt and
            # auto-save the mapping.
            user_t = _target_of(payload)
            same_kind = payload.get("action") == orig_kind
            diff_label = bool(user_t and orig_target
                              and user_t.lower() != orig_target.lower())
            if n == 1 and same_kind and diff_label and not payload.get("_direct"):
                if reused_from_saved:
                    print(f"   ⚡ Reused saved input — auto-recording alias "
                          f"'{orig_target}' → {orig_kind} '{user_t}'")
                    if orig_kind == "click":
                        kb_learn.record_alias(shot_at_prompt, orig_target, user_t)
                    elif pos:
                        kb_learn.record(shot_at_prompt, orig_target, orig_kind, pos,
                                        runner.screen_size(), success=True)
                    if workflow_path and step_title and step_actions is not None:
                        _update_workflow_instruction(
                            workflow_path, step_title, action_index,
                            _user_action_to_markdown(payload), step_actions)
                else:
                    try:
                        ans = input(
                            f"   Was that the correct way to do '{orig_target}'? "
                            f"Remember '{orig_target}' → {orig_kind} '{user_t}' on this "
                            f"screen and fix the workflow file? [y/N] ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        ans = "n"
                    if ans in ("y", "yes"):
                        if orig_kind == "click":
                            kb_learn.record_alias(shot_at_prompt, orig_target, user_t)
                        elif pos:
                            kb_learn.record(shot_at_prompt, orig_target, orig_kind, pos,
                                            runner.screen_size(), success=True)
                        if workflow_path and step_title and step_actions is not None:
                            _update_workflow_instruction(
                                workflow_path, step_title, action_index,
                                _user_action_to_markdown(payload), step_actions)
                    else:
                        print("   ○ not saved — this fix won't be generalized")

            # Recovered — hand control straight back to the workflow. If the
            # next automatic action fails, this prompt reappears.
            print("   ✓ continuing the workflow.")
            return ("ok", clips)
