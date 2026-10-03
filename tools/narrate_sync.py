#!/usr/bin/env python3
"""
narrate_sync.py — put one spoken line on each recorded action, then assemble.

FlowCast records a clip per action. The obvious thing is to narrate a whole step
at once, but then the voice finishes early and the rest of the step plays in
silence. This speaks each line over the action it describes.

    python tools/narrate_sync.py --dir output/recordings/<slug> --script narration.txt

The script file is plain text: a `# step N` header, then one line per action, in
order. Blank lines and `#` comments are ignored.

    # step 1
    Skip the sign in for now.
    Choose Create New Integration.

    # step 2
    Open the integration.

Line count must match the action clips recorded for that step — a mismatch is
reported rather than guessed at, because a silent off-by-one shifts every
remaining line onto the wrong action.

Voice settings come from the environment and are worth setting:

    FLOWCAST_TTS=chatterbox
    FLOWCAST_VOICE_REF=assets/voice/reference.wav
    FLOWCAST_VOICE_PITCH_HZ=reference   # hold every line at one pitch
    FLOWCAST_VOICE_TAKES=3              # keep the take closest to the reference

Timing rules, all tunable:
  * each line starts --lead after its action begins
  * an action whose line outruns it holds on its last frame until the voice ends
  * the FINAL action is cut to the line plus --end-hold, so a long recorded
    dwell does not leave the video sitting in silence
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STEP_RE = re.compile(r"^#\s*step\s+(\d+)\s*$", re.IGNORECASE)
FPS = 30
# Every segment is encoded alike — size, pixel format, frame rate, encoder —
# because the joins below are stream copies. Clips come from the recorder as
# lossless x264 (a different profile and entropy coder from an encoded
# segment), and a different height if the menu-bar crop changed mid-run;
# copy-joining those decodes as garbage, and the master then drops frames and
# ends seconds before the voice does.
ENCODE = ["-c:v", "libx264", "-crf", "14", "-preset", "fast", "-pix_fmt", "yuv420p",
          "-r", str(FPS), "-an"]


def size(p: Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True).stdout.strip()
    w, h = (int(v) for v in out.split(",")[:2])
    return w, h


def dur(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(p)],
                         capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


def silence(seconds: float, out: Path, rate: int, ch: int) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"anullsrc=r={rate}:cl={'mono' if ch == 1 else 'stereo'}",
                    "-t", f"{seconds:.3f}", str(out)], check=True)


def parse_script(path: Path) -> dict[int, list[str]]:
    """`# step N` headers, then one line per action."""
    steps: dict[int, list[str]] = {}
    current: int | None = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        m = STEP_RE.match(line)
        if m:
            current = int(m.group(1))
            steps[current] = []
            continue
        if not line or line.startswith("#"):
            continue
        if current is None:
            sys.exit(f"{path}: a line appears before any '# step N' header: {line!r}")
        steps[current].append(line)
    return steps


def action_clips(guid: Path, step: int, since: float) -> list[Path]:
    """This step's clips, oldest first. `since` filters out earlier attempts —
    the folder accumulates across runs, and a stray clip from a failed attempt
    shifts every line onto the wrong action."""
    got = [p for p in guid.glob(f"step{step:02d}_action*.mov")
           if p.stat().st_mtime >= since]
    return sorted(got, key=lambda p: p.stat().st_mtime)


def run_start(guid: Path) -> float:
    """Start of the most recent contiguous run: walk back from the newest clip
    while gaps stay under an hour."""
    clips = sorted(guid.glob("step*_action*.mov"), key=lambda p: p.stat().st_mtime)
    if not clips:
        return 0.0
    start = clips[-1].stat().st_mtime
    for a, b in zip(reversed(clips[:-1]), reversed(clips[1:])):
        if b.stat().st_mtime - a.stat().st_mtime > 3600:
            break
        start = a.stat().st_mtime
    return start - 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, required=True, help="output/recordings/<slug>")
    ap.add_argument("--script", type=Path, required=True, help="the narration text file")
    ap.add_argument("--titles", type=Path, default=None,
                    help="JSON {step: slug} for output filenames; else derived from clips")
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--lead", type=float, default=0.25)
    ap.add_argument("--tail", type=float, default=0.45)
    ap.add_argument("--end-hold", type=float, default=2.0,
                    help="seconds the final result stays up after the last word")
    ap.add_argument("--since", type=float, default=None,
                    help="ignore clips older than this epoch (default: newest run only)")
    ap.add_argument("--dry-run", action="store_true", help="check counts and timings only")
    args = ap.parse_args()

    rec = args.dir if args.dir.is_absolute() else ROOT / args.dir
    guid = rec / "guid"
    if not guid.is_dir():
        sys.exit(f"no action clips under {guid}")

    from src import tts_clone

    script = parse_script(args.script)
    since = args.since if args.since is not None else run_start(guid)
    vo = rec / "vo-sync"
    vo.mkdir(exist_ok=True)

    # ── check every step lines up before synthesizing anything ──────────────
    plan: dict[int, list[tuple[Path, str]]] = {}
    problems = []
    for step in sorted(script):
        clips = action_clips(guid, step, since)
        lines = script[step]
        if len(clips) != len(lines):
            problems.append(f"  step {step}: {len(clips)} clip(s) but {len(lines)} line(s)")
            for c in clips:
                problems.append(f"      {c.name}")
            continue
        plan[step] = list(zip(clips, lines))
    if problems:
        print("script does not match the recording:\n" + "\n".join(problems), file=sys.stderr)
        sys.exit(1)

    titles = json.loads(args.titles.read_text()) if args.titles else {}
    total_actions = sum(len(v) for v in plan.values())
    print(f"{len(plan)} step(s), {total_actions} action(s)\n")
    if args.dry_run:
        for step, items in plan.items():
            print(f"  step {step}")
            for clip, line in items:
                print(f"    {dur(clip):5.1f}s  {clip.name[:44]:46} {line[:44]}")
        return

    # ── speak every line ───────────────────────────────────────────────────
    from src import progress
    units = total_actions + len(plan)          # every line, then every step assembled
    k = 0
    for step, items in plan.items():
        for i, (_clip, line) in enumerate(items):
            short = line if len(line) <= 60 else line[:57] + "…"
            progress.unit(k, units, f"Voicing line {k + 1} of {total_actions}: “{short}”",
                          lines=total_actions)
            tts_clone.synthesize(line, vo / f"s{step}_a{i:02d}.wav")
            k += 1
        print(f"  step {step}: {len(items)} line(s) spoken", flush=True)

    rate, ch = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=sample_rate,channels", "-of", "csv=p=0",
         str(vo / f"s{min(plan)}_a00.wav")],
        capture_output=True, text=True).stdout.strip().split(",")
    rate, ch = int(rate), int(ch)

    # ── one picture size for the whole video ─────────────────────────────────
    sizes = {clip: size(clip) for items in plan.values() for clip, _ in items}
    W = min(w for w, _ in sizes.values())
    H = min(h for _, h in sizes.values())
    if len(set(sizes.values())) > 1:
        print(f"clips differ in size ({sorted(set(sizes.values()))}) — fitting all to {W}x{H}, "
              "trimming the top (where a menu-bar crop differs)")

    def fit(clip: Path) -> str:
        w, h = sizes[clip]
        f = []
        if w != W:
            f.append(f"scale={W}:-2")
        if h != H or w != W:
            f.append(f"crop={W}:{H}:0:ih-{H}")
        return ",".join(f + [f"fps={FPS}"])

    # ── build each step from its actions ───────────────────────────────────
    last_step = max(plan)
    narrated: list[Path] = []
    print(f"\n{'step':>4} {'act':>4} {'clip':>7} {'voice':>7} {'held':>6} {'final':>7}")
    for j, (step, items) in enumerate(plan.items()):
        progress.unit(total_actions + j, units, f"Putting the voice on step {step} of {len(plan)}",
                      lines=total_actions)
        segs, auds = [], []
        for i, (clip, _line) in enumerate(items):
            wav = vo / f"s{step}_a{i:02d}.wav"
            speech, clip_len = dur(wav), dur(clip)
            final = (step == last_step and i == len(items) - 1)
            seg = vo / f"seg{step}_{i:02d}.mov"
            held = 0.0
            vf = fit(clip)
            if final:
                # The last line is never cut: hold the last frame if the clip is shorter.
                want = args.lead + speech + args.end_hold
                if want > clip_len + 0.05:
                    held = want - clip_len
                    vf += f",tpad=stop_mode=clone:stop_duration={held:.3f}"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-vf", vf,
                                "-t", f"{want:.3f}", *ENCODE, str(seg)], check=True)
            elif args.lead + speech + args.tail - clip_len > 0.05:
                held = args.lead + speech + args.tail - clip_len
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-vf",
                                f"{vf},tpad=stop_mode=clone:stop_duration={held:.3f}",
                                *ENCODE, str(seg)], check=True)
            else:
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-vf", vf,
                                *ENCODE, str(seg)], check=True)
            seg_len = dur(seg)
            segs.append(seg)

            lead_wav = vo / f"_l{step}_{i:02d}.wav"
            silence(args.lead, lead_wav, rate, ch)
            auds += [lead_wav, wav]
            pad = seg_len - args.lead - speech
            if pad > 0.01:
                tail_wav = vo / f"_t{step}_{i:02d}.wav"
                silence(pad, tail_wav, rate, ch)
                auds.append(tail_wav)
            print(f"{step:>4} {i+1:>4} {clip_len:7.1f} {speech:7.1f} {held:6.1f} {seg_len:7.1f}")

        for kind, items_ in (("v", segs), ("a", auds)):
            lst = vo / f"{kind}{step}.txt"
            lst.write_text("".join(f"file '{p.resolve()}'\n" for p in items_))
            ext = "mov" if kind == "v" else "wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                            "-i", str(lst), "-c", "copy", str(vo / f"{kind}{step}.{ext}")],
                           check=True)

        slug = titles.get(str(step)) or re.sub(
            r"^step\d+_action\d+_|\.mov$", "", plan[step][0][0].name)
        out = rec / f"step-{step:02d}-{slug}-{args.theme}-narrated.mov"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(vo / f"v{step}.mov"),
                        "-i", str(vo / f"a{step}.wav"), "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                        str(out)], check=True)
        narrated.append(out)

    full = rec / f"full-{args.theme}-narrated.mov"
    (vo / "full.txt").write_text("".join(f"file '{p.resolve()}'\n" for p in narrated))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(vo / "full.txt"), "-c", "copy", str(full)], check=True)

    progress.unit(units, units, "Narrated video ready")
    print(f"\n{len(narrated)} narrated step(s)")
    print(f"wrote {full}  ({dur(full):.1f}s)")
    print("next: tools/make_youtube_video.py --dir "
          f"{args.dir} --title \"...\" --art graph --label \"...\"")
    tts_clone.shutdown()


if __name__ == "__main__":
    main()
