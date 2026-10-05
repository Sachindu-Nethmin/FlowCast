"""Progress lines for FlowCast Studio — what is happening now, and how far along.

Stage tools print these on stdout as `@@studio {json}` (the same channel as
tools/studio.py's events), and the app turns them into the progress bar, the
"now" line and the time left, on the Mac and on the phone:

    unit(done, total, task)   the stage's countable units: voice lines, render
                              phases. `done` units are finished; `task` is the
                              one starting now.
    part(fraction)            how far into the current unit — a take of a voice
                              line, the final encode.

The app times the units itself, so nothing here needs a clock.
"""
from __future__ import annotations

import json


def _emit(event: str, **data) -> None:
    print("@@studio " + json.dumps({"event": event, **data}), flush=True)


def unit(done: int, total: int, task: str, **extra) -> None:
    """extra: e.g. lines=N — the first N units are voice lines (the app times
    those apart from the quick steps that follow)."""
    _emit("progress", done=done, total=total, task=task, **extra)


def part(fraction: float) -> None:
    _emit("part", fraction=round(max(0.0, min(1.0, fraction)), 3))
