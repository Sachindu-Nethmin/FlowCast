#!/usr/bin/env python3
"""
dub_natural.py — natural AI voiceover for FlowCast tutorial recordings.

Thin CLI over src/narrate.py. Turns the silent recordings FlowCast produces
(step-NN-*.mov) into a narrated, YouTube-tutorial-style video using macOS's
built-in `say` with an ENHANCED / PREMIUM neural voice — free, offline, and
free to use commercially. Default voice is a young male Enhanced voice (Evan).

Usage (run on your Mac, from the repo root):
    python tools/dub_natural.py                      # dubs quick-start-automation
    python tools/dub_natural.py --dir output/recordings/<workflow>
    python tools/dub_natural.py --voice "Evan (Enhanced)"
    python tools/dub_natural.py --rate 165 --lead-in 0.5
    python tools/dub_natural.py --list-voices        # show installed voices

Output: full-<theme>-narrated.mov (+ per-step -narrated.mov) next to the
originals. Source recordings are never modified.

Requirements: macOS, ffmpeg + ffprobe (`brew install ffmpeg`), and an
Enhanced/Premium voice installed (see tools/README-dub-natural.md).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as `python tools/dub_natural.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import narrate  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Natural AI voiceover for FlowCast recordings.")
    ap.add_argument("--dir", default="output/recordings/quick-start-automation",
                    help="recordings directory (default: quick-start-automation)")
    ap.add_argument("--voice", default=None, help='exact voice name, e.g. "Evan (Enhanced)"')
    ap.add_argument("--rate", type=int, default=172, help="words per minute (default 172)")
    ap.add_argument("--lead-in", type=float, default=0.35,
                    help="start each line this many seconds BEFORE its action (default 0.35)")
    ap.add_argument("--tail", type=float, default=0.35,
                    help="silence after the last line per step, seconds (default 0.35)")
    ap.add_argument("--sync", choices=["scene", "even", "start"], default="scene",
                    help="how to time lines: scene=align to on-screen changes (default), "
                         "even=spread evenly, start=all at clip start (old behaviour)")
    ap.add_argument("--scene-threshold", type=float, default=0.3,
                    help="scene-change sensitivity 0..1, lower = more anchors (default 0.3)")
    ap.add_argument("--no-wait", action="store_true",
                    help="disable per-action mode (don't split each action into its own "
                         "waiting clip); overlay the voice on the continuous clip instead")
    ap.add_argument("--list-voices", action="store_true", help="list installed voices and exit")
    args = ap.parse_args()

    if args.list_voices:
        installed = narrate.list_installed_voices()
        enhanced = [v for v in installed if "(" in v]
        print("Enhanced / Premium voices installed:")
        print("  " + ("\n  ".join(enhanced) if enhanced else "(none — see README to install some)"))
        print(f"\nAuto-selected default would be: {narrate.pick_voice(None, installed)}")
        print("\nAll installed voices:")
        print("  " + "\n  ".join(installed))
        return

    try:
        narrate.narrate_workflow(
            Path(args.dir), voice=args.voice, rate=args.rate,
            lead_in=args.lead_in, tail=args.tail,
            sync=args.sync, scene_threshold=args.scene_threshold,
            per_action=not args.no_wait)
    except RuntimeError as e:
        raise SystemExit(f"[dub] {e}")


if __name__ == "__main__":
    main()
