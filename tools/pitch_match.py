#!/usr/bin/env python3
"""
pitch_match.py — hold every cloned line at one pitch.

Chatterbox reproduces a reference voice well on short lines and drifts upward
on longer ones: measured against a 155 Hz male reference, the opening line came
back at 155 Hz while the intro hook reached 174 Hz. Within one video that
inconsistency is what makes a voice read as someone else — a listener notices
the wobble long before they notice the absolute pitch.

This measures each clip's median fundamental and shifts it onto a single target
with rubberband, which moves pitch without touching tempo, so the narration
timing built around these durations is unaffected.

    python tools/pitch_match.py --dir output/recordings/<slug>/vo-sync
    ... --target 140          # deeper than the reference
    ... --reference assets/voice/reference.wav   # target = the sample's own pitch
    ... --dry-run             # report what it would do

Shifts beyond +/-25% are skipped and reported: past that rubberband starts to
sound artificial, and a clip that far out usually means the measurement failed
rather than that the voice really moved that much.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.tts_clone import MAX_PITCH_SHIFT as MAX_SHIFT  # noqa: E402
from src.tts_clone import median_f0                     # noqa: E402
from src.tts_clone import pitch_shift as shift          # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, required=True, help="folder of synthesized .wav lines")
    ap.add_argument("--target", type=float, default=None, help="target median F0 in Hz")
    ap.add_argument("--reference", type=Path, default=None,
                    help="take the target from this sample's own pitch")
    ap.add_argument("--glob", default="*.wav")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH")

    target = args.target
    if target is None:
        if not args.reference:
            sys.exit("pass --target HZ or --reference sample.wav")
        target, n = median_f0(args.reference)
        print(f"reference {args.reference.name}: {target:.1f} Hz ({n} voiced frames)\n")

    files = sorted(p for p in args.dir.glob(args.glob) if not p.name.startswith("_"))
    if not files:
        sys.exit(f"no {args.glob} under {args.dir}")

    backup = args.dir / "unpitched"
    moved = skipped = 0
    print(f"{'file':>16} {'was':>8} {'ratio':>7}  {'now':>8}")
    for p in files:
        f0, frames = median_f0(p)
        if not np.isfinite(f0) or frames < 8:
            print(f"{p.name:>16} {'--':>8} {'skip':>7}  too little voiced audio")
            skipped += 1
            continue
        ratio = target / f0
        if abs(ratio - 1) > MAX_SHIFT:
            print(f"{p.name:>16} {f0:8.1f} {ratio:7.3f}  SKIPPED — beyond +/-{MAX_SHIFT:.0%}")
            skipped += 1
            continue
        if args.dry_run:
            print(f"{p.name:>16} {f0:8.1f} {ratio:7.3f}  (dry run)")
            continue
        backup.mkdir(exist_ok=True)
        if not (backup / p.name).exists():
            shutil.copy2(p, backup / p.name)
        tmp = p.with_suffix(".shift.wav")
        shift(p, tmp, ratio)
        tmp.replace(p)
        after, _ = median_f0(p)
        print(f"{p.name:>16} {f0:8.1f} {ratio:7.3f}  {after:8.1f}")
        moved += 1

    if not args.dry_run:
        print(f"\n{moved} shifted, {skipped} left alone. Originals in {backup}")


if __name__ == "__main__":
    main()
