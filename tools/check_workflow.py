#!/usr/bin/env python3
"""
check_workflow.py — dry-run a workflow markdown file through FlowCast's parser.

Runs NO automation and never touches the screen: it only shows what
src/parser.py makes of each instruction line, so a workflow authored from a
documentation page can be corrected BEFORE a recording session takes over the
Mac for several minutes.

Usage:
    python tools/check_workflow.py workflows/<slug>.md
    python tools/check_workflow.py workflows/<slug>.md --quiet   # errors only

Exit status is 1 when any actionable line parsed to zero actions — those are
the lines FlowCast would silently skip while recording.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parser import _parse_instructions, parse_markdown  # noqa: E402

# Lines that carry no UI action by design — narration/verification/context.
_INFORMATIONAL = re.compile(
    r'^\s*(keep|confirm|verify|check that|note|the |this |you |your |a |an )',
    re.IGNORECASE)


def _describe(action: dict) -> str:
    kind = action.get("action", "?")
    if kind == "type" or kind == "select":
        return f"{kind:<9} {action.get('field_target')!r} = {action.get('value')!r}"
    if kind == "search":
        return f"{kind:<9} in {action.get('field_target')!r} for {action.get('value')!r}"
    if kind == "hotkey":
        return f"{kind:<9} {'+'.join(action.get('keys', []))}"
    if kind == "open_app":
        return f"{kind:<9} {action.get('app_name')!r}"
    if kind == "wait":
        return f"{kind:<9} {action.get('seconds')}s"
    if kind == "scroll":
        return f"{kind:<9} {action.get('clicks')} clicks"
    hint = f"  ({action['hint']})" if action.get("hint") else ""
    return f"{kind:<9} {action.get('target')!r}{hint}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Dry-run a FlowCast workflow markdown file.")
    ap.add_argument("workflow", type=Path)
    ap.add_argument("--quiet", action="store_true", help="only print problems")
    args = ap.parse_args()

    if not args.workflow.exists():
        print(f"[check] no such file: {args.workflow}", file=sys.stderr)
        return 2

    steps = parse_markdown(args.workflow)
    problems: list[str] = []
    total_actions = 0

    for idx, step in enumerate(steps, 1):
        if not args.quiet:
            print(f"\n── Step {idx}: {step.title} ──")
        total_actions += len(step.actions)

        for raw in step.raw_instructions.splitlines():
            line = re.sub(r'^\s*\d+\.\s*', '', raw).strip()
            line = re.sub(r'^\s*[-*]\s*', '', line).strip()
            if not line or line.startswith("<"):
                continue

            acts = _parse_instructions(line)
            if acts:
                if not args.quiet:
                    print(f"  ✓ {line}")
                    for a in acts:
                        print(f"      → {_describe(a)}")
            elif _INFORMATIONAL.match(line):
                if not args.quiet:
                    print(f"  · {line}\n      → (informational — no UI action, kept for docs)")
            else:
                problems.append(f"step {idx}: {line}")
                print(f"  ✗ {line}\n      → NO ACTION PARSED — FlowCast will skip this line")

        if not step.actions:
            problems.append(f"step {idx}: '{step.title}' has no actions at all")

    print(f"\n{'='*66}")
    print(f"  {len(steps)} step(s), {total_actions} action(s) parsed")
    if problems:
        print(f"  {len(problems)} line(s) need rewording:")
        for p in problems:
            print(f"    ✗ {p}")
        print("  See .claude/skills/doc-to-youtube/reference/workflow-grammar.md")
        print(f"{'='*66}")
        return 1
    print("  No unparsed lines — safe to record.")
    print(f"{'='*66}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
