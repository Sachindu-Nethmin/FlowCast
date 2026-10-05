"""Guide mode for FlowCast — interactive step-by-step guided execution.

When --guide is passed with an existing workflow.md, FlowCast shows each
step's instructions, then loops on a "what next>" prompt.  Every command you
type is EXECUTED and RECORDED individually, building a knowledge base as it
goes.  Type 'ok' to finish the step and move to the next one.

When --guide is passed WITHOUT a workflow.md, run_guide_new() takes over:
it asks for a workflow name first, then lets you teach it step by step from
scratch (same "what next>" loop, but step titles are typed live too).  When
you finish, it writes a brand-new workflows/<slug>.md file and produces the
exact same outputs a normal run would: per-step GIF/MOV, full-<theme>.mov,
full_script-<theme>.py and a themed index.md — using src/artifacts.py so both
code paths stay in sync.

Usage (called from main.py):
    python main.py workflow.md --guide      # guide an existing workflow
    python main.py --guide                  # author a brand-new workflow
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

import pyautogui
from PIL import Image

from src import artifacts, kb_learn, navigator, recorder, runner
from src.interactive import action_to_markdown
from src.nl_commands import parse_command
from src.parser import Step, instruction_lines

_slug = artifacts.slug


def _plain(text: str) -> str:
    """Drop the markdown emphasis from an action label so the phone shows
    'Set Integration Name to HelloWorld', not 'Set **Integration Name** …'."""
    return re.sub(r'`([^`]+)`', r'\1', re.sub(r'\*\*([^*]+)\*\*', r'\1', text))


class WorkflowSwitchRequested(Exception):
    """Raised from the guide command loop when the user says/types something
    like 'continue the automation' that names a DIFFERENT workflow markdown
    file (e.g. workflows/quick-start-automation.md). Left uncaught here —
    it bubbles out of run_guide()/run_guide_new(); main.py catches it and
    switches from step-by-step guide mode into a normal, fully automatic
    run of the named workflow (same as `python main.py <file>.md` with no
    --guide) — no more per-action prompts."""
    def __init__(self, path: Path) -> None:
        super().__init__(f"switch to workflow: {path}")
        self.path = path


# "continue the automation" / "run sales data sync" / "do quick start file" —
# a leading trigger verb + a name that resolves to a workflows/*.md file.
# A bare "continue" (no name) never matches — it still means 'finish this
# step', handled earlier in the caller's loop.
_WORKFLOW_TRIGGER_RE = re.compile(
    r'^(?:continue|run|do|start|play|execute)\s+(?:with\s+)?(?:the\s+)?(.+?)'
    r'(?:\s+(?:workflow|automation|guide|markdown|md file|file))?$',
    re.IGNORECASE,
)
_WORKFLOW_TRIGGER_STOPWORDS = {"", "it", "this", "that", "guide", "workflow", "step", "here", "on"}


def _resolve_workflow_hint(hint: str, workflows_dir: Path) -> Path | None:
    """Fuzzy-match a spoken/typed hint ('automation', 'sales data sync', ...)
    against workflows/*.md filenames. An exact slug match wins outright;
    otherwise falls back to a substring match, preferring the shortest
    (closest) filename when more than one contains the hint."""
    hint_slug = _slug(hint)
    if not hint_slug or not workflows_dir.is_dir():
        return None
    partial: list[Path] = []
    for p in sorted(workflows_dir.glob("*.md")):
        stem_slug = _slug(p.stem)
        if hint_slug == stem_slug:
            return p
        if hint_slug in stem_slug or stem_slug in hint_slug:
            partial.append(p)
    return min(partial, key=lambda p: len(p.stem)) if partial else None


def _match_workflow_switch(raw: str, workflows_dir: Path) -> Path | None:
    """Detect a 'continue the automation' style command and resolve it to a
    workflows/*.md file. Returns None for everything else, so it never
    steals a normal click/type/select command."""
    m = _WORKFLOW_TRIGGER_RE.match(raw.strip())
    if not m:
        return None
    hint = m.group(1).strip()
    if hint.lower() in _WORKFLOW_TRIGGER_STOPWORDS:
        return None
    return _resolve_workflow_hint(hint, workflows_dir)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _screenshot() -> Image.Image:
    return runner._screenshot()


def _video_only() -> bool:
    """FlowCast Studio records for a video, and a video is made from the
    per-action clips in guid/. The docs extras — a GIF per step (30-90 s each),
    the joined tutorial and its GIF (~5 min) — are skipped, and each step's
    clips are joined in the background, so the next step is offered at once."""
    return os.environ.get("FLOWCAST_DOC_ARTIFACTS", "1") == "0"


_joins: list[threading.Thread] = []


def _describe_screen(shot: Image.Image) -> dict:
    return navigator.describe_screen(shot)


def _save_screenshot(shot: Image.Image, path: Path) -> None:
    shot.save(str(path))


def _stop_recording() -> Path | None:
    """Safely stop an active recording and return the clip path."""
    if recorder._proc is None:
        return None
    try:
        return recorder.stop()
    except Exception:
        return None


def _prompt_next(voice: bool, label: str = "what next") -> str:
    """Get the next command/title, either typed or (--voice) tone-cued listening.

    Every path returns the identical shape of string, so everything
    downstream (parse_command, control-word checks) is unaware of the
    source — the mode is purely an input-capture swap. A running phone
    server wins over --voice: you chose the phone by starting it.
    """
    from src import phone
    if phone.is_running():
        return phone.ask(label)
    if voice:
        from src import voice as voice_mod
        return voice_mod.listen(label)
    return input(f"{label}> ").strip()


def _speak_safe(text: str) -> None:
    """Best-effort spoken feedback — never lets a TTS hiccup break the loop."""
    try:
        from src import voice as voice_mod
        voice_mod.speak(text)
    except Exception as e:
        print(f"  [voice] speak failed: {e}")


_CONFIRM_YES = {"ok", "okay", "yes", "yeah", "yep", "confirm", "correct", "go", "right"}
_CONFIRM_NO  = {"edit", "no", "redo", "retry", "wrong", "cancel", "fix"}


def _voice_confirm(raw: str) -> bool:
    """Read the heard command back and ask the user to confirm it before
    anything gets clicked — a safety net against misheard commands (see
    src/voice.py's speak()). Returns True on 'ok'/'yes'/…, False on
    'edit'/'no'/… or anything unclear — the caller then just loops back to
    _prompt_next() for a fresh command rather than guessing what was meant.
    """
    from src import voice as voice_mod
    _speak_safe(f'You said: {raw}. Say ok to confirm, or edit to redo.')
    reply = voice_mod.listen("confirm (ok / edit)", duration=3.0).strip().lower()
    words = set(reply.split())
    if reply in _CONFIRM_YES or words & _CONFIRM_YES:
        return True
    if reply in _CONFIRM_NO or words & _CONFIRM_NO:
        print("  [confirm] edit — say/type the command again")
    elif reply:
        print(f"  [confirm] '{reply}' wasn't ok/edit — treating as edit, try again")
    else:
        print("  [confirm] heard nothing — treating as edit, try again")
    return False


# ── Execute one user command ─────────────────────────────────────────────────

class _Attempt:
    """Outcome of one resolve → fire → verify cycle."""
    def __init__(self) -> None:
        self.status: str = ""    # "ok" | "skip" | "resolve_error" | "fire_error" | "blue" | "no_change"
        self.error: str = ""
        self.clip: Path | None = None
        self.x: int | None = None
        self.y: int | None = None
        self.shot_before: object | None = None
        self.alt_positions: list[tuple[int, int]] = []


def _attempt(command: dict, clip_name: str, tmp_dir: Path) -> _Attempt:
    """One resolve → fire → verify cycle for a click/type/select/search
    command, with its own recording clip. Does NOT touch the knowledge base
    or decide retries — that's the caller's job, so it can try this same
    command again (e.g. after invalidating a bad learned position), or try
    a specific runner-up position via a.alt_positions."""
    a = _Attempt()
    target = command.get("target") or command.get("field_target", "")

    runner.set_pre_move_callback(lambda: recorder.start(clip_name, tmp_dir))
    # Capture starts now, while the target is found, so the first move is
    # filmed without waiting for ffmpeg to come up.
    recorder.prewarm(tmp_dir)
    a.shot_before = _screenshot()

    try:
        if command.get("_direct"):
            resolved = dict(command)  # already has x, y — e.g. a runner-up position
        else:
            resolved = runner.resolve(command)
    except Exception as e:
        runner.set_pre_move_callback(None)
        if recorder._proc is not None:
            recorder.stop().unlink(missing_ok=True)
        a.status, a.error = "resolve_error", str(e)
        return a

    if resolved.get("_skip"):
        runner.set_pre_move_callback(None)
        a.status = "skip"
        return a

    try:
        runner.fire(resolved)
    except Exception as e:
        runner.set_pre_move_callback(None)
        if recorder._proc is not None:
            recorder.stop().unlink(missing_ok=True)
        a.status, a.error = "fire_error", str(e)
        return a

    ui_changed = runner.wait_ui_change(timeout=4.0, baseline=a.shot_before)
    runner.wait_ui_settle()
    runner.set_pre_move_callback(None)
    a.clip = _stop_recording()
    a.x, a.y = resolved.get("x"), resolved.get("y")
    a.alt_positions = list(resolved.get("_alt_positions") or [])

    kind = command.get("action", "click")
    if runner.LAST_REPORT.get("blue_selection"):
        a.status = "blue"
        return a
    if kind == "click" and not ui_changed:
        a.status = "no_change"
        return a

    a.status = "ok"
    return a


def _execute_command(command: dict, tmp_dir: Path, clip_idx: int,
                     step_idx: int) -> tuple[bool, Path | None]:
    """Parse → fire → verify one user-typed command.  Returns (success, clip).

    Each command gets its own recording clip so the tutorial video shows
    every action the user taught. On a click that lands on nothing (no UI
    change), the bad position is unlearned and — instead of just giving up
    and asking the user for exact coordinates — resolution is retried once
    automatically: with the bad KB entry now invalidated, that retry falls
    through to fresh OCR detection and, if needed, the healer's escalating
    strategies (closest-OCR-match auto-correct), which is effectively
    "try other visible text" without hardcoding anything.
    """
    target = command.get("target") or command.get("field_target", "")
    kind = command.get("action", "click")

    # Skip / hotkey / wait — fire directly, no element to resolve on screen.
    if kind in ("wait", "hotkey", "shell") or command.get("_direct"):
        try:
            if command.get("_direct"):
                resolved = dict(command)
            else:
                resolved = runner.resolve(command)
        except Exception as e:
            print(f"  ✗ cannot resolve '{target}': {e}")
            return False, None
        if resolved.get("_skip"):
            print("  ○ nothing to do (auto-populated)")
            return True, None

        # A wait is the one action whose whole point is what happens on screen
        # while nothing is being clicked: a build finishing, a response
        # arriving. Recording normally starts on the runner's first mouse
        # move, and a wait never moves the mouse — so it filmed nothing, and
        # the result the step exists to show was never captured. Start the
        # recorder explicitly and hold it for the dwell.
        if kind == "wait":
            seconds = float(resolved.get("seconds", 1.0))
            clip_name = f"guide_{step_idx:02d}_{clip_idx:03d}"
            recorder.start(clip_name, tmp_dir)
            runner.fire(resolved)
            time.sleep(seconds)
            return True, _stop_recording()

        try:
            runner.fire(resolved)
        except Exception as e:
            print(f"  ✗ {e}")
            return False, None
        if kind == "hotkey":
            runner.wait_ui_settle()
        return True, None

    next_command = command
    retry_reason = ""
    for attempt_num in (1, 2):
        clip_name = f"guide_{step_idx:02d}_{clip_idx:03d}" + ("_retry" if attempt_num == 2 else "")
        a = _attempt(next_command, clip_name, tmp_dir)

        if a.status == "resolve_error":
            print(f"  ✗ cannot find '{target}': {a.error}")
            return False, None

        if a.status == "skip":
            print("  ○ nothing to do (auto-populated)")
            return True, None

        if a.status == "fire_error":
            print(f"  ✗ failed: {a.error}")
            return False, None

        if a.status == "blue":
            print("  ✗ blue-highlighted text — wrong field. Undoing…")
            pyautogui.hotkey("command", "z")
            time.sleep(0.4)
            if a.x is not None and kind in ("click", "type", "select", "search"):
                kb_learn.record(a.shot_before, target, kind, (a.x, a.y),
                                runner.screen_size(), success=False)
            if a.clip:
                a.clip.unlink(missing_ok=True)
            return False, None

        if a.status == "no_change":
            print(f"  ✗ UI did not change — '{target}' was clicked at "
                  f"({a.x}, {a.y}), probably the wrong spot.{retry_reason}")
            if a.x is not None:
                # Unlearn this position so it isn't reused (and re-fail) —
                # a later manual retry falls through to fresh detection
                # instead of the bad cache.
                kb_learn.record(a.shot_before, target, kind, (a.x, a.y),
                                runner.screen_size(), success=False)
            if a.clip:
                a.clip.unlink(missing_ok=True)

            if attempt_num == 1:
                if a.alt_positions:
                    # This label appeared more than once on screen (e.g. two
                    # "Automation" cards) — try the next-closest occurrence
                    # directly, at the exact position already found, rather
                    # than re-running detection blind.
                    ax, ay = a.alt_positions[0]
                    print(f"     trying the other occurrence of '{target}' at ({ax}, {ay})…")
                    next_command = {**command, "action": kind, "target": target,
                                    "x": ax, "y": ay, "_direct": True}
                    retry_reason = " (this was the other occurrence)"
                else:
                    print("     trying fresh detection instead of the cached position…")
                    next_command = command
                    retry_reason = " (after fresh detection)"
                continue  # one automatic retry

            print("     retry also missed — say/type 'at <x>,<y>' with the "
                  "correct pixel coordinates, or 'where' to see what's on screen.")
            return False, None

        # status == "ok"
        if a.x is not None and kind in ("click", "type", "select", "search"):
            kb_learn.record_later(a.shot_before, target, kind, (a.x, a.y),
                                  runner.screen_size(), success=True)
        if attempt_num == 2:
            print(f"  ✓ {kind} '{target}' — succeeded at ({a.x}, {a.y}) on retry")
        else:
            print(f"  ✓ {kind} '{target}'")
        return True, a.clip

    return False, None  # unreachable, keeps type-checkers happy


# ── Per-step guide loop ──────────────────────────────────────────────────────

def _guide_step(step: Step, step_idx: int, out_dir: Path,
                tmp_dir: Path, theme: str = "light",
                voice: bool = False,
                workflows_dir: Path = Path("workflows")) -> tuple[Path | None, dict]:
    """Guide one step: loop on 'what next>' until the user types 'ok'.

    Returns (step_mov, meta). meta also carries "actions" (the ordered list
    of action dicts taught this step) and "md_lines" (those actions rendered
    back to markdown instruction lines) so a brand-new workflow.md and a
    full_script.py can be assembled afterwards — see run_guide_new().

    Raises WorkflowSwitchRequested if the user names a different workflow
    markdown file ("continue the automation") — see that class's docstring.
    """
    clips: list[Path] = []
    step_out = out_dir / f"step-{step_idx:02d}"
    step_out.mkdir(parents=True, exist_ok=True)

    lines = instruction_lines(step.raw_instructions)
    print(f"\n{'═' * 60}")
    print(f"  Step {step_idx}: {step.title}")
    print(f"{'═' * 60}")
    if lines:
        print("  Instructions:")
        for ln in lines:
            print(f"    • {ln}")
    print()
    from src import phone
    # The phone lists the PARSED actions, not the prose, so a tap maps to
    # step.actions[n] by index with no re-parsing in between.
    action_labels = [action_to_markdown(a) for a in step.actions]
    phone.set_step(f"Step {step_idx}: {step.title}",
                   [_plain(lbl) for lbl in action_labels] or lines)

    # ── Before screenshot ─────────────────────────────────────────────────
    # Every step starts from the same geometry, so a window nudged out of
    # place mid-run cannot make one step's frames a different size.
    runner.ensure_fullscreen(force=True)
    shot_before = _screenshot()
    _save_screenshot(shot_before, step_out / "before.png")
    fp_before, texts_before = kb_learn.screen_fingerprint(shot_before)
    desc_before = _describe_screen(shot_before)
    print(f"  [state] screen {fp_before}: {', '.join(desc_before['texts'][:8])}")

    # ── Command loop ──────────────────────────────────────────────────────
    n_actions = 0
    executed_commands: list[dict] = []
    # Indices of step.actions that have run. Only tapped lines count: a typed
    # correction is not one of the listed actions, so it must not push the
    # step over the line into "finished".
    done_actions: set[int] = set()
    tapped_index: int | None = None

    while True:
        try:
            raw = _prompt_next(voice)
        except (EOFError, KeyboardInterrupt):
            print()
            return None, {"status": "aborted"}

        if not raw:
            print("  (type a command, or 'ok' / 'skip' / 'abort' / 'where')")
            continue

        # ── Named-workflow handoff ("continue the automation") ─────────────
        # Checked before anything else so it can't be shadowed by the bare
        # "continue" control word (finish-step) or misread as a click target.
        switch_target = _match_workflow_switch(raw, workflows_dir)
        if switch_target:
            print(f"  [switch] '{raw}' → leaving guide mode, running "
                  f"'{switch_target.name}' automatically, start to finish")
            raise WorkflowSwitchRequested(switch_target)

        low = raw.lower()

        # ── Control words ─────────────────────────────────────────────────
        if low in ("ok", "done", "finish", "continue", "next"):
            break
        if low in ("back", "previous", "prev"):
            print(f"  [back] leaving step {step_idx} to redo the previous one")
            return None, {"status": "back"}
        if low == "skip":
            print(f"  [skip] step {step_idx} skipped")
            return None, {"status": "skipped"}
        if low == "abort":
            print("  [abort] stopping guide")
            return None, {"status": "aborted"}
        if low in ("where", "look", "screen"):
            shot = _screenshot()
            desc = _describe_screen(shot)
            fp, _ = kb_learn.screen_fingerprint(shot)
            print(f"  [state] screen {fp}: {', '.join(desc['texts'][:12])}")
            print(f"  input boxes: {desc['input_count']}")
            known = kb_learn.known_targets(shot)
            if known:
                print(f"  learned here: {', '.join(known)}")
            continue
        if low in ("help", "?"):
            from src.nl_commands import HELP_TEXT
            print(HELP_TEXT)
            continue
        if low == "undo":
            pyautogui.hotkey("command", "z")
            time.sleep(0.4)
            print("  ↩ undo sent")
            continue

        # ── Parse and execute ─────────────────────────────────────────────
        if raw.startswith(phone.ACTION_TAP_PREFIX):
            # Tapped on the phone: run that exact parsed action. Going back
            # through parse_command here would turn "Set Integration Name to
            # HelloWorld" into a click on that sentence, which is how the
            # name ended up typed into nothing.
            try:
                tapped_index = int(raw[len(phone.ACTION_TAP_PREFIX):])
                payload = dict(step.actions[tapped_index])
            except (ValueError, IndexError):
                print(f"  ? no such action in this step: {raw}")
                tapped_index = None
                continue
            kind, raw = "action", action_to_markdown(payload)
            print(f"  [tap] {raw}")
        else:
            tapped_index = None
            kind, payload = parse_command(raw)
            if kind == "error":
                print(f"  ? {payload}")
                if voice:
                    _speak_safe("Sorry, I didn't get that command. What's next?")
                continue
            if kind == "control":
                # e.g. "retry" — not a real control, treat as click
                payload = {"action": "click", "target": payload}

        # ── Voice confirm-or-edit — a safety net against misheard commands.
        # Typed input skips this (already exact); read it back for voice only.
        if voice:
            if not _voice_confirm(raw):
                continue

        n_actions += 1
        print(f"  [{n_actions}] executing: {raw}")
        ok, clip = _execute_command(payload, tmp_dir, n_actions, step_idx)
        if clip:
            # Copy individual clip to persistent guide folder
            guide_clips_dir = out_dir / "guid"
            guide_clips_dir.mkdir(parents=True, exist_ok=True)
            clip_name = f"step{step_idx:02d}_action{n_actions:03d}_{_slug(raw[:40])}.mov"
            dest = guide_clips_dir / clip_name
            shutil.copy2(str(clip), str(dest))
            print(f"  [clip] saved → {dest.name}")
            clips.append(clip)
        if ok:
            executed_commands.append({"command": raw, "action": payload})
            phone.notify(f"Done: {_plain(raw)}")
            if voice:
                _speak_safe("Done. What's next?")
            if tapped_index is not None:
                done_actions.add(tapped_index)
                # The LAST listed action is the one that commits the step, so
                # reaching it ends the step even when earlier lines were never
                # tapped. Workflows routinely carry actions this build of the
                # UI does not present (a Browse button that is not shown, an
                # "open the app" line for an app already running), and waiting
                # for all of them would mean the step never finishes by itself.
                finished = (tapped_index == len(step.actions) - 1
                            or len(done_actions) >= len(step.actions))
                if step.actions and finished:
                    # Every listed action has run, so there is nothing left to
                    # ask about. Ending here also means the step is finished
                    # properly rather than skipped, which is what produces the
                    # assembled clip and the after.png the docs tool uses.
                    print(f"  [auto] step {step_idx} complete — moving to the next one")
                    phone.notify("Step complete — moving on")
                    print()
                    break
        else:
            phone.notify(f"That didn't work: {_plain(raw)}")
            if voice:
                _speak_safe("Sorry, that didn't work. What's next?")
        print()

    # ── After screenshot ──────────────────────────────────────────────────
    time.sleep(0.3)
    shot_after = _screenshot()
    _save_screenshot(shot_after, step_out / "after.png")
    fp_after, texts_after = kb_learn.screen_fingerprint(shot_after)
    desc_after = _describe_screen(shot_after)
    print(f"  [state] screen → {fp_after}: {', '.join(desc_after['texts'][:8])}")

    # ── Combine clips into step video (+ GIF, matching a normal run) ──────
    step_mov = None
    step_gif = None
    title_slug = _slug(step.title)
    if clips:
        step_mov = out_dir / f"step-{step_idx:02d}-{title_slug}-{theme}.mov"
        combined = tmp_dir / f"combined_{step_idx}.mov"

        def join(clips=list(clips), combined=combined, step_mov=step_mov) -> None:
            recorder.combine(clips, combined)
            shutil.move(str(combined), str(step_mov))
            print(f"  [video] step {step_idx} → {step_mov.name}")

        if _video_only():
            t = threading.Thread(target=join)
            t.start()
            _joins.append(t)
        else:
            join()
            step_gif = out_dir / artifacts.gif_name(step_idx, title_slug, theme)
            recorder.to_gif(step_mov, step_gif)
            print(f"  [gif]   step {step_idx} → {step_gif.name}")

    # Actions actually taught this step (in order), reflected back to
    # markdown instruction lines for the new workflow.md / index.md.
    actions = [ec["action"] for ec in executed_commands]
    md_lines = [action_to_markdown(a) for a in actions]

    meta = {
        "step": step_idx,
        "title": step.title,
        "instructions": lines,
        "executed_commands": executed_commands,
        "actions": actions,
        "md_lines": md_lines,
        "actions_count": n_actions,
        "screen_before": fp_before,
        "screen_after": fp_after,
        "texts_before": texts_before[:12],
        "texts_after": texts_after[:12],
        "status": "recorded",
        "gif": str(step_gif) if step_gif else None,
    }
    return step_mov, meta


# ── Shared: metadata → Step objects / workflow markdown ─────────────────────

def _numbered_instructions(md_lines: list[str]) -> str:
    """Turn a list of markdown instruction phrases into a numbered block,
    the same shape parser.py expects inside a '## Step N: Title' section."""
    out = []
    for i, ln in enumerate(md_lines, 1):
        if ln and not ln.rstrip().endswith((".", "?", "!", "`", "**")):
            ln = f"{ln}."
        out.append(f"{i}. {ln}")
    return "\n".join(out)


def _meta_to_steps(all_meta: list[dict]) -> list[Step]:
    """Build parser.Step objects from recorded guide metadata — only steps
    that were actually taught (status == 'recorded' with >=1 action)."""
    steps: list[Step] = []
    for m in all_meta:
        if m.get("status") != "recorded" or not m.get("actions"):
            continue
        title = m["title"]
        steps.append(Step(
            title=title,
            gif_filename=f"{_slug(title)}.gif",
            actions=m["actions"],
            raw_instructions=_numbered_instructions(m.get("md_lines", [])),
        ))
    return steps


def write_workflow_markdown(path: Path, steps: list[Step]) -> None:
    """Write a brand-new, parser-compatible workflow markdown file."""
    blocks = []
    for idx, step in enumerate(steps, 1):
        blocks.append(f"## Step {idx}: {step.title}\n\n{step.raw_instructions}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(blocks).rstrip() + "\n")
    print(f"  [workflow] markdown saved → {path}")


def _save_guide_meta_and_kb(out_dir: Path, slug: str, theme: str,
                             total_steps: int, all_meta: list[dict]) -> None:
    guide_meta = {
        "version": 1,
        "slug": slug,
        "theme": theme,
        "total_steps": total_steps,
        "recorded_steps": sum(1 for m in all_meta if m.get("status") == "recorded"),
        "steps": all_meta,
    }
    meta_path = out_dir / "guide_metadata.json"
    meta_path.write_text(json.dumps(guide_meta, indent=2))
    print(f"  [meta] guide metadata → {meta_path}")

    kb_snapshot = out_dir / "learned_actions_snapshot.json"
    kb_data = kb_learn._load()
    kb_snapshot.write_text(json.dumps(kb_data, indent=2))
    print(f"  [kb] knowledge base snapshot → {kb_snapshot}")


# ── Main entry point (guide an EXISTING workflow) ────────────────────────────

def run_guide(steps: list[Step], out_dir: Path, slug: str, theme: str,
              voice: bool = False, workflows_dir: Path = Path("workflows")) -> None:
    """Walk through every step, executing + recording each command.

    Raises WorkflowSwitchRequested (uncaught here — see main.py) if the user
    names a different workflow markdown file mid-session.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="guide_"))

    print(f"\n{'═' * 60}")
    print(f"  GUIDE MODE  |  {len(steps)} steps  |  theme: {theme}"
          + ("  |  🎙  VOICE" if voice else ""))
    print(f"  Output: {out_dir}")
    print(f"{'═' * 60}")
    if voice:
        from src import voice as voice_mod
        print(f"  For each step, wait for the tone then speak what to do "
              f"(e.g. 'click Create') — you get {int(voice_mod.LISTEN_SECONDS)}s.")
        print(f"  FlowCast reads it back — say 'ok' to run it or 'edit' to redo, "
              f"then tells you if it worked before asking what's next.")
        print(f"  Say 'ok' when the step is done. Esc at any prompt to type instead.")
    else:
        print(f"  For each step, type what to do (e.g. 'click Create').")
        print(f"  Type 'ok' when the step is done to move to the next one.")
    print(f"  Commands: next / back / skip / abort / where / undo / help")
    print(f"{'═' * 60}")

    runner.ensure_fullscreen(force=True)

    # Index-based rather than a for-loop: 'back' has to revisit a step that
    # has already been yielded, which enumerate() cannot do.
    recorded: list[tuple[Path | None, dict]] = []
    idx = 1
    while idx <= len(steps):
        mov, meta = _guide_step(steps[idx - 1], idx, out_dir, tmp_dir, theme,
                                voice, workflows_dir)
        if meta.get("status") == "back":
            if idx > 1:
                recorded = recorded[:idx - 2]   # drop the step we are redoing
                idx -= 1
                print(f"\n  ← back to step {idx}: {steps[idx - 1].title}")
            else:
                print("  (already at the first step)")
            continue
        recorded.append((mov, meta))
        if meta.get("status") == "aborted":
            print(f"\n  Guide aborted at step {idx}")
            break
        idx += 1

    step_movs = [m for m, _ in recorded if m]
    all_meta = [meta for _, meta in recorded]
    for t in _joins:                  # step videos joined in the background
        t.join()
    _joins.clear()
    kb_learn.flush()

    # ── Assemble full tutorial video (raw teaching-session recording) ─────
    full_mov = None
    if step_movs and not _video_only():
        full_mov = out_dir / f"tutorial-{theme}.mov"
        recorder.combine(step_movs, full_mov, keep_inputs=True)
        print(f"\n  [tutorial] full video → {full_mov}")

        gif_path = out_dir / f"tutorial-{theme}.gif"
        recorder.to_gif(full_mov, gif_path)

    # ── Produce the SAME outputs a normal run would ────────────────────────
    # (full_script / themed index.md / full-<theme>.mov built from what was
    # actually taught this session, not the possibly-stale source markdown)
    taught_steps = _meta_to_steps(all_meta)
    if taught_steps:
        artifacts.build_full_script(taught_steps, out_dir, theme)
        artifacts.build_themed_markdown(taught_steps, out_dir, slug)
        if not _video_only():
            artifacts.build_full_video(out_dir, theme)

    _save_guide_meta_and_kb(out_dir, slug, theme, len(steps), all_meta)

    # ── Summary ───────────────────────────────────────────────────────────
    recorded = sum(1 for m in all_meta if m.get("status") == "recorded")
    total_actions = sum(m.get("actions_count", 0) for m in all_meta)
    print(f"\n{'═' * 60}")
    print(f"  Guide complete — {recorded}/{len(steps)} steps, "
          f"{total_actions} actions taught")
    if full_mov:
        print(f"  Tutorial video → {full_mov}")
    if taught_steps:
        print(f"  Full video      → {out_dir / f'full-{theme}.mov'}")
        print(f"  Full script     → {out_dir / f'full_script-{theme}.py'}")
        print(f"  Themed markdown → {out_dir / 'index.md'}")
    print(f"  Output folder   → {out_dir}")
    print(f"{'═' * 60}")


# ── New entry point (author a BRAND-NEW workflow from scratch) ──────────────

def run_guide_new(workflows_dir: Path, output_root: Path, voice: bool = False) -> None:
    """Ask for a workflow name, then teach steps from scratch.

    Uses the same "what next>" command loop as run_guide(), but step titles
    are entered live (say/type 'done' once the whole workflow is taught).
    When finished, writes workflows/<slug>.md and produces the same outputs
    a normal run would (per-step GIF/MOV, full-<theme>.mov,
    full_script-<theme>.py, themed index.md), using the knowledge base
    (kb_learn / user_inputs) the same way run() and run_guide() already do
    via runner.resolve().

    With voice=True, step titles and "what next>" commands are captured via
    tone-cued timed listening (src/voice.listen) instead of input(). The
    workflow name itself is always typed — it becomes a filename, so it
    needs to be exact rather than dictated.
    """
    print(f"\n{'═' * 60}")
    print(f"  GUIDE MODE — new workflow" + ("  |  🎙  VOICE" if voice else ""))
    print(f"{'═' * 60}")

    # ── 1. Ask for the workflow name FIRST, before touching the screen ────
    # (always typed — this becomes a filename, so it must be exact)
    while True:
        try:
            name = input("workflow name> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  [abort] no name given — nothing created")
            return
        if not name:
            print("  (please type a name for this workflow, e.g. 'Create a REST API')")
            continue
        wf_slug = _slug(name)
        if not wf_slug:
            print("  (name must contain at least one letter or number)")
            continue
        md_path = workflows_dir / f"{wf_slug}.md"
        if md_path.exists():
            resp = input(f"  '{md_path.name}' already exists — overwrite? (y/N) ").strip().lower()
            if resp != "y":
                continue  # ask for a different name
        break

    out_dir = output_root / wf_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="guide_new_"))

    # ── 2. Get the app on screen + detect theme before recording ──────────
    runner.ensure_fullscreen(force=True)
    theme = runner.detect_theme()
    print(f"  Theme identified: {theme.upper()}")

    print(f"\n{'═' * 60}")
    print(f"  Teaching '{name}'  →  {md_path}")
    if voice:
        from src import voice as voice_mod
        print(f"  For each step: give it a title, wait for the tone, then speak")
        print(f"  what to do (e.g. 'click Create') — you get {int(voice_mod.LISTEN_SECONDS)}s. Say 'ok' to finish the step.")
        print(f"  FlowCast reads each command back — say 'ok' to run it or 'edit' to redo, "
              f"then tells you if it worked.")
        print(f"  Say 'done' at the step-title prompt to finish the workflow,")
        print(f"  'abort' to cancel without saving, or press Esc at any prompt to type.")
    else:
        print(f"  For each step: give it a title, then type what to do")
        print(f"  (e.g. 'click Create'). Type 'ok' to finish the step.")
        print(f"  Type 'done' at the step-title prompt to finish the workflow,")
        print(f"  or 'abort' to cancel without saving anything.")
    print(f"{'═' * 60}")

    all_meta: list[dict] = []
    step_movs: list[Path] = []
    idx = 0

    while True:
        try:
            title = _prompt_next(voice, label=f"step {idx + 1} title (or say 'done')")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        low = title.lower()
        if low in ("done", "finish"):
            break
        if low == "abort":
            print("  [abort] discarding this workflow — nothing saved")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return
        if not title:
            print("  (give a step title, say/type 'done' to finish, or 'abort' to cancel)")
            continue

        switch_target = _match_workflow_switch(title, workflows_dir)
        if switch_target:
            print(f"  [switch] '{title}' → discarding this in-progress workflow, running "
                  f"'{switch_target.name}' automatically, start to finish")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise WorkflowSwitchRequested(switch_target)

        idx += 1
        placeholder = Step(title=title, gif_filename=f"{_slug(title)}.gif",
                            actions=[], raw_instructions="")
        try:
            mov, meta = _guide_step(placeholder, idx, out_dir, tmp_dir, theme, voice, workflows_dir)
        except WorkflowSwitchRequested:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        all_meta.append(meta)
        if mov:
            step_movs.append(mov)
        if meta.get("status") == "aborted":
            print(f"\n  [abort] discarding this workflow — nothing saved")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return
        if meta.get("status") == "skipped":
            idx -= 1  # step wasn't kept — don't leave a gap in numbering

    taught_steps = _meta_to_steps(all_meta)
    if not taught_steps:
        print("\n  No steps were taught — nothing saved.")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    # ── 3. Write the workflow markdown + build the standard outputs ───────
    write_workflow_markdown(md_path, taught_steps)
    artifacts.build_full_script(taught_steps, out_dir, theme)
    artifacts.build_themed_markdown(taught_steps, out_dir, wf_slug)
    full_mov = artifacts.build_full_video(out_dir, theme)

    _save_guide_meta_and_kb(out_dir, wf_slug, theme, len(all_meta), all_meta)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Summary ─────────────────────────────────────────────────────────
    total_actions = sum(m.get("actions_count", 0) for m in all_meta)
    print(f"\n{'═' * 60}")
    print(f"  Workflow created — {len(taught_steps)} step(s), {total_actions} actions taught")
    print(f"  Workflow markdown → {md_path}")
    for idx, step in enumerate(taught_steps, 1):
        gif = out_dir / artifacts.gif_name(idx, _slug(step.title), theme)
        if gif.exists():
            print(f"    {gif}")
    if full_mov:
        print(f"  Full video       → {full_mov}")
    print(f"  Full script      → {out_dir / f'full_script-{theme}.py'}")
    print(f"  Themed markdown  → {out_dir / 'index.md'}")
    print(f"  Output folder    → {out_dir}")
    print(f"{'═' * 60}")
