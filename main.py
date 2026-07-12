#!/usr/bin/env python3
"""
FlowCast — Convert WSO2 Integrator documentation steps into GIF recordings.

Usage:
  uv run python main.py workflow.md
  uv run python main.py workflow.md --step 2
  uv run python main.py workflow.md --guide
  uv run python main.py --guide              # author a brand-new workflow

Outputs (inside output/recordings/<workflow-slug>/):
  step-01-<slug>-<theme>.gif   — per-step animated GIF
  step-01-<slug>-<theme>.mov   — per-step video (kept permanently)
  full-<theme>.mov             — all recorded steps concatenated in order
  full_script-<theme>.py       — runnable Python script for all steps
  index.md                     — themed (light/dark) markdown for docs

Guide mode (--guide) with an existing workflow.md:
  Walks through each step interactively, records the screen while you perform
  the action, and builds a knowledge base + tutorial video from the session.
  Also (re)generates the same full/gif/script/index.md outputs as a normal
  run, reflecting whatever was actually taught this session.

Guide mode (--guide) with NO workflow.md:
  Asks for a workflow name first, then lets you teach it step by step from
  scratch using the same interactive loop. When done, writes a brand-new
  workflows/<slug>.md and produces the full set of outputs above.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from src import healer, interactive, navigator, recorder, runner
from src.artifacts import build_full_script, build_full_video, build_themed_markdown, slug as _slug
from src.healer import HealingAbortedError
from src.parser import Step, parse_markdown
from src.runner import ElementNotFoundError

OUTPUT_DIR = Path("output") / "recordings"


# ── Per-step recording ────────────────────────────────────────────────────────

def _run_step(step_index: int, step: Step, out_dir: Path, theme: str,
              is_last_step: bool = False,
              workflow_path: Path | None = None) -> tuple[Path, Path] | None:
    """Record one step. Returns (gif_path, mov_path) or None on failure."""
    print(f"\n── Step {step_index}: {step.title} ──")
    print(f"   {len(step.actions)} actions → {step.gif_filename}")

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"fc_{step_index}_"))
    clips: list[Path] = []
    healer.reset_session()

    # Perceive before acting: full screen + report what's actually on screen.
    runner.ensure_fullscreen(force=True)
    shot = runner._screenshot()
    desc = navigator.describe_screen(shot)
    preview = ", ".join(desc["texts"][:12])
    print(f"   [perceive] {len(desc['texts'])} texts, {desc['input_count']} input boxes visible")
    if preview:
        print(f"   [perceive] on screen: {preview}")
    if desc.get("screen"):
        print(f"   [perceive] screen identified: {desc['screen'].get('name', desc['screen'])}")

    try:
        skip_until = -1  # fast-forward marker: skip actions below this index
        for i, action in enumerate(step.actions):
            kind   = action["action"]
            target = action.get("target") or action.get("field_target", "")

            if i < skip_until:
                print(f"   [skip  {i+1}] fast-forward — '{target}' already done per screen state")
                continue

            print(f"   [resolve {i+1}/{len(step.actions)}] {kind}: {target}")

            # Skip actions whose effect is already visible (e.g. value typed)
            shot = runner._screenshot()
            if navigator.action_effect_applied(shot, action):
                print(f"   [skip  {i+1}] effect already applied — not repeating")
                continue

            try:
                resolved = runner.resolve(action)
            except (ElementNotFoundError, HealingAbortedError) as e:
                # Target missing — check what IS on screen: if a later action's
                # target is visible, the UI is already past this point. Jump to
                # the first action that is actually available (may skip several).
                shot = runner._screenshot()
                j = navigator.first_available_action(shot, step.actions, i + 1)
                if j is not None:
                    nxt = step.actions[j].get("target") or step.actions[j].get("field_target", "")
                    print(f"   [skip  {i+1}] '{target}' not found but action {j+1} "
                          f"('{nxt}') is available on screen — jumping there")
                    skip_until = j
                    continue
                # Unguided detection failed → ask the terminal what to do next
                # and LEARN the answer for future runs.
                print(f"[WARN] Cannot find element: {e}", file=sys.stderr)
                status, fix_clips = interactive.recover(
                    action, tmp_dir, reason="element not found", on_unavailable="abort",
                    workflow_path=workflow_path, step_title=step.title,
                    action_index=i, step_actions=step.actions)
                clips.extend(fix_clips)
                if status == "abort":
                    return None
                continue  # 'ok' or 'skip' — move on to the next action

            if resolved.get("_skip"):
                print(f"   [skip  {i+1}] auto-populated field")
                continue
            if resolved["action"] == "wait":
                runner.fire(resolved)
                continue

            print(f"   [fire  {i+1}/{len(step.actions)}] {kind}: {target}")
            clip_name = f"clip_{i:03d}"
            runner.set_pre_move_callback(lambda n=clip_name: recorder.start(n, tmp_dir))
            try:
                runner.fire(resolved)
                # Verify against the PRE-ACTION screenshot: fast transitions
                # that finish before polling starts still count as a change.
                ui_changed = runner.wait_ui_change(baseline=shot)
                runner.wait_ui_settle()

                # Learn from the outcome so future runs need no guidance:
                # success → remember position; no UI change / blue-selected
                # text → remember as failure (label click / wrong field).
                rx, ry = resolved.get("x"), resolved.get("y")
                if rx is not None and kind in ("click", "type", "select", "search"):
                    from src import kb_learn
                    blue = runner.LAST_REPORT.get("blue_selection", False)
                    failed = blue or (not ui_changed and kind == "click")
                    if failed and kind == "click" and not blue:
                        # Second opinion before bothering the user: if the NEXT
                        # action's target is now on screen, the click worked.
                        check = runner._screenshot()
                        if navigator.first_available_action(check, step.actions, i + 1) == i + 1:
                            print(f"   [verify] next action's target appeared — click actually worked")
                            failed = False
                    kb_learn.record(shot, target, kind, (rx, ry),
                                    runner.screen_size(), success=not failed)
                    if failed:
                        # Discard the bad clip, undo a wrong-field paste, and
                        # ask the terminal what to do next (learning the answer).
                        runner.set_pre_move_callback(None)
                        if recorder._proc is not None:
                            bad = recorder.stop()
                            bad.unlink(missing_ok=True)
                        reason = ("typed text is blue-selected (wrong field)" if blue
                                  else "UI did not change (label / wrong place)")
                        print(f"   [verify] '{target}' failed: {reason}")
                        status, fix_clips = interactive.recover(
                            action, tmp_dir, undo_first=blue, reason=reason,
                            on_unavailable="skip",
                            workflow_path=workflow_path, step_title=step.title,
                            action_index=i, step_actions=step.actions)
                        clips.extend(fix_clips)
                        if status == "abort":
                            return None
                        continue  # next action

                # Hold recording open for any extra seconds requested by the action
                post_delay = resolved.get("post_delay", 0.0)
                if is_last_step and i == len(step.actions) - 1 and not post_delay:
                    post_delay = 1.0  # default trailing delay on last step
                if post_delay:
                    print(f"   [extra] Holding recording open for {post_delay}s")
                    time.sleep(post_delay)
            except Exception as e:
                runner.set_pre_move_callback(None)
                if recorder._proc is not None:
                    recorder.stop()
                print(f"[WARN] Action {i+1} failed: {e}", file=sys.stderr)
                status, fix_clips = interactive.recover(
                    action, tmp_dir, reason=str(e), on_unavailable="abort",
                    workflow_path=workflow_path, step_title=step.title,
                    action_index=i, step_actions=step.actions)
                clips.extend(fix_clips)
                if status == "abort":
                    return None
                continue
            # Only stop if recording was actually started by the callback
            if recorder._proc is not None:
                clips.append(recorder.stop())

        if not clips:
            print(f"[WARN] No clips recorded for step {step_index}")
            return None

        # Combine clips → step MOV (kept permanently) → GIF
        combined_tmp = tmp_dir / "combined.mov"
        recorder.combine(clips, combined_tmp)

        step_mov = out_dir / f"step-{step_index:02d}-{_slug(step.title)}-{theme}.mov"
        shutil.move(str(combined_tmp), str(step_mov))

        gif_name = f"{Path(step.gif_filename).stem}-{theme}.gif"
        gif = out_dir / gif_name
        recorder.to_gif(step_mov, gif)
        print(f"   GIF saved → {gif}")
        print(f"   MOV saved → {step_mov.name}")
        return gif, step_mov

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage: python main.py workflow.md [--step N] [--guide]", file=sys.stderr)
        print("       python main.py --guide           (author a brand-new workflow)",
              file=sys.stderr)
        sys.exit(1)

    only_step: int | None = None
    from_step: int | None = None   # --from-step N  → record steps N, N+1, …
    guide_mode: bool = False       # --guide → interactive tutorial recording
    md_path:   Path | None = None
    i = 0
    while i < len(args):
        if args[i] == "--step" and i + 1 < len(args):
            only_step = int(args[i + 1])
            i += 2
        elif args[i] == "--from-step" and i + 1 < len(args):
            from_step = int(args[i + 1])
            i += 2
        elif args[i] == "--guide":
            guide_mode = True
            i += 1
        else:
            md_path = Path(args[i])
            i += 1

    # ── --guide with no workflow.md: author a brand-new workflow ──────────
    if md_path is None:
        if not guide_mode:
            print("Usage: python main.py workflow.md [--step N] [--guide]", file=sys.stderr)
            print("       python main.py --guide           (author a brand-new workflow)",
                  file=sys.stderr)
            sys.exit(1)
        from src.guide import run_guide_new
        run_guide_new(Path("workflows"), OUTPUT_DIR)
        return

    if not md_path.exists():
        print(f"[ERROR] File not found: {md_path}", file=sys.stderr)
        sys.exit(1)

    steps   = parse_markdown(md_path)
    slug    = _slug(md_path.stem)
    
    # Make the app full screen BEFORE any screenshot/theme detection
    runner.ensure_fullscreen(force=True)

    # Identify theme before creating output directory
    theme = runner.detect_theme()
    print(f"  Theme identified: {theme.upper()}")

    # Perceive current UI state: instead of always starting at step 1, detect
    # which step the WSO2 Integrator is at right now and resume from there.
    # (Explicit --step / --from-step always wins; FLOWCAST_NO_RESUME=1 disables.)
    if only_step is None and from_step is None:
        shot = runner._screenshot()
        resume = navigator.find_resume_step(steps, shot)
        if resume > 1:
            print(f"  Current UI matches step {resume} — resuming there "
                  f"(use --from-step 1 to force a full run)")
            from_step = resume


    out_dir = OUTPUT_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Guide mode: interactive tutorial recording ────────────────────────
    if guide_mode:
        from src.guide import run_guide
        run_guide(steps, out_dir, slug, theme)
        return

    # Always regenerate artifacts (script, themed markdown) early so they 
    # reflect the latest markdown even if the recording loop below fails.
    full_script = build_full_script(steps, out_dir, theme)
    themed_md   = build_themed_markdown(steps, out_dir, slug)

    print(f"\n{'='*60}")
    print(f"  FlowCast  |  {md_path.name}  |  {len(steps)} steps")
    print(f"  Output: {out_dir}")
    print(f"{'='*60}")

    saved_gifs: list[Path] = []
    for idx, step in enumerate(steps, 1):
        if only_step is not None and idx != only_step:
            continue
        if from_step is not None and idx < from_step:
            continue
        is_last = (idx == len(steps))
        result = _run_step(idx, step, out_dir, theme, is_last_step=is_last,
                           workflow_path=md_path)
        if result:
            gif, _ = result
            saved_gifs.append(gif)

    # Always regenerate full video from all existing step MOVs (including any
    # recorded in previous runs so individual --step runs accumulate correctly).
    full_mov = build_full_video(out_dir, theme)

    print(f"\n{'='*60}")
    print(f"  Done — {len(saved_gifs)}/{len(steps)} GIFs recorded this run")
    for p in saved_gifs:
        print(f"    {p}")
    if full_mov:
        print(f"  Full video  → {full_mov}")
    print(f"  Full script → {full_script}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
