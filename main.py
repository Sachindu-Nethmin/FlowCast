#!/usr/bin/env python3
"""
FlowCast — Convert WSO2 Integrator documentation steps into GIF recordings.

Usage:
  uv run python main.py workflow.md
  uv run python main.py workflow.md --step 2

Outputs (inside output/recordings/<workflow-slug>/):
  step-01-<slug>.gif        — per-step animated GIF
  step-01-<slug>.mov        — per-step video (kept permanently)
  full.mov                  — all recorded steps concatenated in order
  full_script.py            — runnable Python script for all steps
"""
from __future__ import annotations

import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

<<<<<<< HEAD
<<<<<<< HEAD
from src import healer, recorder, runner
from src.healer import HealingAbortedError
=======
from src import recorder, runner
>>>>>>> 7d1f240 (improved text files)
=======
from src import healer, recorder, runner
from src.healer import HealingAbortedError
>>>>>>> b856107 (1.0)
from src.parser import Step, parse_markdown
from src.runner import ElementNotFoundError

OUTPUT_DIR = Path("output") / "recordings"


def _slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


# ── Per-step recording ────────────────────────────────────────────────────────

<<<<<<< HEAD
def _run_step(step_index: int, step: Step, out_dir: Path, theme: str, is_last_step: bool = False) -> tuple[Path, Path] | None:
=======
def _run_step(step_index: int, step: Step, out_dir: Path) -> tuple[Path, Path] | None:
>>>>>>> 9e44480 (Light (#6))
    """Record one step. Returns (gif_path, mov_path) or None on failure."""
    print(f"\n── Step {step_index}: {step.title} ──")
    print(f"   {len(step.actions)} actions → {step.gif_filename}")

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"fc_{step_index}_"))
    clips: list[Path] = []
<<<<<<< HEAD
<<<<<<< HEAD
    healer.reset_session()
=======
>>>>>>> 7d1f240 (improved text files)
=======
    healer.reset_session()
>>>>>>> b856107 (1.0)

    try:
        for i, action in enumerate(step.actions):
            kind   = action["action"]
            target = action.get("target") or action.get("field_target", "")
            print(f"   [resolve {i+1}/{len(step.actions)}] {kind}: {target}")

            try:
                resolved = runner.resolve(action)
            except ElementNotFoundError as e:
                print(f"[ERROR] Cannot find element: {e}", file=sys.stderr)
                return None

            if resolved.get("_skip"):
                print(f"   [skip  {i+1}] auto-populated field")
                continue
            if resolved["action"] == "wait":
                runner.fire(resolved)
                continue

            print(f"   [fire  {i+1}/{len(step.actions)}] {kind}: {target}")
<<<<<<< HEAD
<<<<<<< HEAD
            clip_name = f"clip_{i:03d}"
            runner.set_pre_move_callback(lambda n=clip_name: recorder.start(n, tmp_dir))
=======
            recorder.start(f"clip_{i:03d}", tmp_dir)
>>>>>>> 7d1f240 (improved text files)
=======
            clip_name = f"clip_{i:03d}"
            runner.set_pre_move_callback(lambda n=clip_name: recorder.start(n, tmp_dir))
>>>>>>> 6e2f95f (add image indentification)
            try:
                runner.fire(resolved)
                runner.wait_ui_change()
                runner.wait_ui_settle()
<<<<<<< HEAD

                # If this is the last action of the last step, add extra time to show output
                if is_last_step and i == len(step.actions) - 1:
                    print("   [extra] Adding 1s delay to show output in last step")
                    time.sleep(1.0)
            except Exception as e:
                runner.set_pre_move_callback(None)
                if recorder._proc is not None:
                    recorder.stop()
                print(f"[ERROR] Action {i+1} failed: {e}", file=sys.stderr)
                return None
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

=======
            except Exception as e:
<<<<<<< HEAD
<<<<<<< HEAD
                runner.set_pre_move_callback(None)
                if recorder._proc is not None:
                    recorder.stop()
=======
                recorder.stop()
>>>>>>> 7d1f240 (improved text files)
=======
                runner.set_pre_move_callback(None)
                if recorder._proc is not None:
                    recorder.stop()
>>>>>>> 6e2f95f (add image indentification)
                print(f"[ERROR] Action {i+1} failed: {e}", file=sys.stderr)
                return None
            # Only stop if recording was actually started by the callback
            if recorder._proc is not None:
                clips.append(recorder.stop())

        if not clips:
            print(f"[WARN] No clips recorded for step {step_index}")
            return None

        # Combine clips → step MOV (kept permanently) → GIF
        combined_tmp = tmp_dir / "combined.mov"
        recorder.combine(clips, combined_tmp)

        step_mov = out_dir / f"step-{step_index:02d}-{_slug(step.title)}.mov"
        shutil.move(str(combined_tmp), str(step_mov))

        gif = out_dir / step.gif_filename
        recorder.to_gif(step_mov, gif)
        print(f"   GIF saved → {gif}")
        print(f"   MOV saved → {step_mov.name}")
        return gif, step_mov

<<<<<<< HEAD
>>>>>>> 9e44480 (Light (#6))
=======
<<<<<<< HEAD
=======
        if not clips:
            print(f"[WARN] No clips recorded for step {step_index}")
            return None

        # Combine clips → step MOV (kept permanently) → GIF
        combined_tmp = tmp_dir / "combined.mov"
        recorder.combine(clips, combined_tmp)

        step_mov = out_dir / f"step-{step_index:02d}-{_slug(step.title)}.mov"
        shutil.move(str(combined_tmp), str(step_mov))

        gif = out_dir / step.gif_filename
        recorder.to_gif(step_mov, gif)
        print(f"   GIF saved → {gif}")
        print(f"   MOV saved → {step_mov.name}")
        return gif, step_mov

>>>>>>> 7d1f240 (improved text files)
>>>>>>> ee262bc (improved text files)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Full-video assembly ───────────────────────────────────────────────────────

<<<<<<< HEAD
def _build_full_video(out_dir: Path, theme: str) -> Path | None:
    """Combine all existing step MOVs (sorted by step number) into full.mov."""
    step_movs = sorted(out_dir.glob(f"step-*-{theme}.mov"))
    if not step_movs:
        return None

    full_mov = out_dir / f"full-{theme}.mov"
=======
def _build_full_video(out_dir: Path) -> Path | None:
    """Combine all existing step MOVs (sorted by step number) into full.mov."""
    step_movs = sorted(out_dir.glob("step-*.mov"))
    if not step_movs:
        return None

    full_mov = out_dir / "full.mov"
>>>>>>> 9e44480 (Light (#6))
    recorder.combine(step_movs, full_mov, keep_inputs=True)
    print(f"   Full video → {full_mov}")
    return full_mov


# ── Python script generation ──────────────────────────────────────────────────

<<<<<<< HEAD
def _build_themed_markdown(steps: list[Step], out_dir: Path, slug: str) -> Path:
    """Generate a markdown file with <ThemedImage> components linking light/dark GIFs."""
    lines = []
    for idx, step in enumerate(steps, 1):
        lines.append(f"## Step {idx}: {step.title}")
        lines.append("")
        
        # Add original instructions
        for instr in step.raw_instructions.splitlines():
            if instr.strip():
                lines.append(instr.strip())
            
        lines.append("")
        gif_stem = Path(step.gif_filename).stem
        
        themed_img = [
            "<ThemedImage",
            f'    alt="{step.title}"',
            "    sources={{",
            f"        light: '/img/get-started/{slug}/{gif_stem}-light.gif',",
            f"        dark: '/img/get-started/{slug}/{gif_stem}-dark.gif',",
            "    }}",
            "/>",
            ""
        ]
        lines.extend(themed_img)

    md_file = out_dir / "index.md"
    md_file.write_text("\n".join(lines))
    print(f"   Themed Markdown saved → {md_file}")
    return md_file


def _build_full_script(steps: list[Step], out_dir: Path, theme: str) -> Path:
=======
def _build_full_script(steps: list[Step], out_dir: Path) -> Path:
>>>>>>> 9e44480 (Light (#6))
    """Write a runnable full_script.py containing all steps' actions."""
    lines = [
        "#!/usr/bin/env python3",
        '"""Auto-generated by FlowCast — run to replay all steps without recording."""',
        "from __future__ import annotations",
        "import sys",
        "from pathlib import Path",
        "",
        "# Allow running from the output directory",
        "sys.path.insert(0, str(Path(__file__).parent.parent.parent))",
        "",
        "from dotenv import load_dotenv",
        "load_dotenv()",
        "",
        "from src import runner",
        "",
        "",
        "def _run(action):",
        "    resolved = runner.resolve(action)",
        "    if resolved.get('_skip'):",
        "        return",
        "    runner.fire(resolved)",
        "    if resolved['action'] not in ('open_app', 'wait', 'hotkey'):",
        "        runner.wait_ui_change()",
        "    runner.wait_ui_settle()",
        "",
        "",
    ]

    for idx, step in enumerate(steps, 1):
        sep = "─" * 58
        lines.append(f"# {sep}")
        lines.append(f"# Step {idx}: {step.title}")
        lines.append(f"# {sep}")
        for action in step.actions:
            lines.append(f"_run({action!r})")
        lines.append("")

<<<<<<< HEAD
    script = out_dir / f"full_script-{theme}.py"
=======
    script = out_dir / "full_script.py"
>>>>>>> 9e44480 (Light (#6))
    script.write_text("\n".join(lines))
    print(f"   Script saved → {script}")
    return script


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage: python main.py workflow.md [--step N]", file=sys.stderr)
        sys.exit(1)

    only_step: int | None = None
    md_path:   Path | None = None
    i = 0
    while i < len(args):
        if args[i] == "--step" and i + 1 < len(args):
            only_step = int(args[i + 1])
            i += 2
        else:
            md_path = Path(args[i])
            i += 1

    if not md_path or not md_path.exists():
        print(f"[ERROR] File not found: {md_path}", file=sys.stderr)
        sys.exit(1)

    steps   = parse_markdown(md_path)
    slug    = _slug(md_path.stem)
<<<<<<< HEAD
    
    # Identify theme before creating output directory
    theme = runner.detect_theme()
    print(f"  Theme identified: {theme.upper()}")
    
=======
>>>>>>> 9e44480 (Light (#6))
    out_dir = OUTPUT_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  FlowCast  |  {md_path.name}  |  {len(steps)} steps")
    print(f"  Output: {out_dir}")
    print(f"{'='*60}")

    saved_gifs: list[Path] = []
    for idx, step in enumerate(steps, 1):
        if only_step is not None and idx != only_step:
            continue
<<<<<<< HEAD
        is_last = (idx == len(steps))
        result = _run_step(idx, step, out_dir, theme, is_last_step=is_last)
=======
        result = _run_step(idx, step, out_dir)
>>>>>>> 9e44480 (Light (#6))
        if result:
            gif, _ = result
            saved_gifs.append(gif)

    # Always regenerate full video from all existing step MOVs (including any
    # recorded in previous runs so individual --step runs accumulate correctly).
<<<<<<< HEAD
    full_mov = _build_full_video(out_dir, theme)

    # Always regenerate the script from all parsed steps so every step's code
    # is present even when only one step was executed this run.
    full_script = _build_full_script(steps, out_dir, theme)

    # Generate the final themed markdown file (index.md)
    themed_md = _build_themed_markdown(steps, out_dir, slug)
=======
    full_mov = _build_full_video(out_dir)

    # Always regenerate the script from all parsed steps so every step's code
    # is present even when only one step was executed this run.
    full_script = _build_full_script(steps, out_dir)
>>>>>>> 9e44480 (Light (#6))

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
