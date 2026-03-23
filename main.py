#!/usr/bin/env python3
"""
FlowCast — Convert human instructions to GIFs.

Usage:
  # From a workflow .md file:
  uv run python main.py path/to/workflow.md
  uv run python main.py path/to/workflow.md --step N

  # From a simple prompt (generates MD → runs → records GIFs → codegen):
  uv run python main.py --prompt "create hello world automation"

  # Generate workflow .md only (no execution):
  uv run python main.py --prompt "create hello world automation" --dry-run
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src import runner, recorder
from src.doc_parser import parse_doc
from src.nl_parser import parse_text_with_meta

OUTPUT_DIR = Path("output") / "recordings"


def _run_step(
    step_index: int,
    instructions: str,
    gif_filename: str,
    gif_output_dir: Path,
    app_name: str,
    title: str = "",
    collect_actions: list | None = None,
) -> Path | None:
    gif_stem = Path(gif_filename).stem

    print(f"\n{'=' * 60}")
    print(f"  Step {step_index}: {gif_filename}")
    print(f"{'=' * 60}")
    print(f"\n[doc] Instructions:\n{instructions[:300]}{'...' if len(instructions) > 300 else ''}\n")

    instructions_filled = instructions.replace("{project_name}", title if title else "Guide")
    prefixed = f"app: {app_name}\n\n{instructions_filled}" if app_name else instructions_filled
    actions, _ = parse_text_with_meta(prefixed)

    if not actions:
        print(f"[doc] No actions parsed for {gif_filename} — skipping")
        return None

    if app_name:
        runner.set_target_app(app_name)

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"rec_{gif_stem}_"))
    clips: list[Path] = []
    resolved_actions: list[dict] = []

    try:
        for i, action in enumerate(actions):
            print(f"\n── Action {i + 1}/{len(actions)}: {action['action']} ──")

            try:
                resolved = runner.resolve_action(action)
            except runner.ElementNotFoundError as e:
                print(f"[WARNING] Element not found: {e}", file=sys.stderr)
                return None

            resolved_actions.append(resolved)

            recorder.start(f"clip_{i:03d}", output_dir=tmp_dir, raw=True)
            try:
                runner.fire_action(resolved)
                runner.wait_ui_settle()
            except Exception as e:
                recorder.stop()
                print(f"[WARNING] Error on action {i + 1}: {e}", file=sys.stderr)
                return None
            clips.append(recorder.stop())

        print(f"\n  Combining {len(clips)} clip(s) → {gif_output_dir / gif_filename}")
        gif_path = recorder.combine(clips, gif_output_dir / gif_filename)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Collect resolved actions for codegen
    if collect_actions is not None:
        collect_actions.extend(resolved_actions)

    print(f"[doc] GIF saved → {gif_path}")
    return gif_path


def _run_from_prompt(prompt: str, dry_run: bool = False) -> None:
    """Generate a workflow from a prompt, then optionally execute it."""
    from src.workflow_gen import generate_workflow

    print("=" * 60)
    print(f"  FlowCast — Prompt Mode")
    print(f"  Task: {prompt}")
    print("=" * 60)

    # Step 1: Generate the workflow .md
    md_path = generate_workflow(prompt)
    print(f"\n[prompt] Generated workflow: {md_path}")

    if dry_run:
        print(f"\n[prompt] Dry run — workflow saved to {md_path}")
        print(f"[prompt] To execute: uv run python main.py {md_path}")
        return

    # Step 2: Parse and run the generated workflow
    title, folder_slug, steps, meta = parse_doc(md_path)
    gif_output_dir = OUTPUT_DIR / folder_slug
    gif_output_dir.mkdir(parents=True, exist_ok=True)

    app_name = meta.get("app", "")

    print(f"\n[prompt] Running workflow: {title}")
    print(f"[prompt] Steps: {len(steps)}  |  Output: {gif_output_dir}")

    if not steps:
        print("[ERROR] No GIF references found in the generated workflow.", file=sys.stderr)
        print(f"[prompt] Check the generated file: {md_path}")
        sys.exit(1)

    saved = []
    all_step_actions: dict[str, list[dict]] = {}

    for i, (instructions, gif_filename) in enumerate(steps, 1):
        step_actions: list[dict] = []
        result = _run_step(
            i, instructions, gif_filename, gif_output_dir,
            app_name, title, collect_actions=step_actions,
        )
        if result:
            saved.append(result)
            step_name = Path(gif_filename).stem
            all_step_actions[step_name] = step_actions

    # Step 3: Generate PyAutoGUI replay scripts
    if all_step_actions:
        from src.codegen import generate_all_scripts

        scripts_dir = gif_output_dir / "scripts"
        scripts = generate_all_scripts(all_step_actions, scripts_dir)
        print(f"\n[prompt] Generated {len(scripts)} PyAutoGUI script(s) in {scripts_dir}")

    # Summary
    print("\n" + "=" * 60)
    print(f"  FlowCast — Complete")
    print(f"  Workflow: {md_path}")
    print(f"  GIFs: {len(saved)}/{len(steps)} recorded → {gif_output_dir}")
    if all_step_actions:
        print(f"  Scripts: {scripts_dir}")
    print("=" * 60)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(
            "Usage:\n"
            "  uv run python main.py path/to/workflow.md [--step N]\n"
            "  uv run python main.py --prompt \"create hello world automation\"\n"
            "  uv run python main.py --prompt \"task\" --dry-run",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse flags
    only_step: int | None = None
    prompt: str | None = None
    dry_run = False
    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] == "--step" and i + 1 < len(args):
            only_step = int(args[i + 1])
            i += 2
        elif args[i] == "--prompt" and i + 1 < len(args):
            prompt = args[i + 1]
            i += 2
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        else:
            filtered_args.append(args[i])
            i += 1
    args = filtered_args

    # Prompt mode: generate → run → record → codegen
    if prompt:
        _run_from_prompt(prompt, dry_run=dry_run)
        return

    # File mode: run existing workflow .md
    if not args:
        print("[ERROR] No workflow file or --prompt provided.", file=sys.stderr)
        sys.exit(1)

    doc_path = Path(args[0])
    if not doc_path.exists():
        print(f"[ERROR] File not found: {doc_path}", file=sys.stderr)
        sys.exit(1)

    title, folder_slug, steps, meta = parse_doc(doc_path)
    gif_output_dir = Path(args[1]) if len(args) >= 2 else OUTPUT_DIR / folder_slug
    gif_output_dir.mkdir(parents=True, exist_ok=True)

    app_name = meta.get("app", "")

    print("=" * 60)
    print(f"  FlowCast")
    print(f"  Workflow: {doc_path.name}  |  Title: {title}")
    print(f"  Steps: {len(steps)}  |  Output: {gif_output_dir}")
    print("=" * 60)

    if not steps:
        print("[ERROR] No GIF references found in the workflow.", file=sys.stderr)
        sys.exit(1)

    saved = []
    for i, (instructions, gif_filename) in enumerate(steps, 1):
        if only_step is not None and i != only_step:
            continue
        result = _run_step(i, instructions, gif_filename, gif_output_dir, app_name, title)
        if result:
            saved.append(result)

    print("\n" + "=" * 60)
    print(f"  Done — {len(saved)}/{len(steps)} GIFs recorded")
    for p in saved:
        print(f"    {p}")
    print("=" * 60)


if __name__ == "__main__":
    main()
