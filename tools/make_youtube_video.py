#!/usr/bin/env python3
"""
make_youtube_video.py — assemble a FlowCast recording into a YouTube-ready master.

Takes the narrated workflow video FlowCast already produced
(full-<theme>-narrated.mov), puts a branded, voiced title card in front of it,
normalises the whole thing to YouTube's recommended delivery specs, and writes
the upload kit next to it: master .mp4, 1280x720 thumbnail, description with
chapter timestamps, and a chapters-only file.

    python tools/make_youtube_video.py --dir output/recordings/<slug> \
        --title "Build a Hello World REST API in WSO2 Integrator"

Notable options:
    --quality 1440p|1080p|4k|native   canvas (default 1440p: YouTube allocates
                                      a higher bitrate to >=1440p uploads, so
                                      screen text survives its re-encode better)
    --theme dark|light|auto           which recorded theme to publish
    --hook "..."                      spoken line on the title card. Defaults to
                                      the [card] block of narration.txt, else
                                      a line generated from the title.
    --endcard                         append a spoken "thanks for watching" card
    --no-intro                        publish the narrated body on its own
    --preset slow                     x264 preset for the master (default medium)

Video is encoded once (single concat pass), then loudness-normalised to
-14 LUFS in an audio-only pass that stream-copies the video — so the master
never takes a second generation of picture loss.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import narrate                                     # noqa: E402
from make_intro import ART_KINDS, QUALITY, THEMES, build_intro, make_thumbnail  # noqa: E402

FPS = 30
LUFS = -14.0          # YouTube normalises playback to about this
TRUE_PEAK = -1.5


# ── inputs ───────────────────────────────────────────────────────────────────

def _detect_theme(rec_dir: Path) -> str:
    for theme in ("dark", "light"):
        if (rec_dir / f"full-{theme}-narrated.mov").exists():
            return theme
    for theme in ("dark", "light"):
        if list(rec_dir.glob(f"step-*-{theme}-narrated.mov")):
            return theme
    raise SystemExit(
        f"[youtube] no narrated recordings in {rec_dir}\n"
        f"          Record first, then narrate:\n"
        f"            FLOWCAST_TTS=chatterbox FLOWCAST_VOICE_REF=$PWD/assets/voice/reference.wav \\\n"
        f"              python tools/dub_natural.py --dir {rec_dir}")


def _body(rec_dir: Path, theme: str) -> Path:
    full = rec_dir / f"full-{theme}-narrated.mov"
    if full.exists():
        return full
    raise SystemExit(f"[youtube] missing {full.name} — run tools/dub_natural.py --dir {rec_dir}")


def _step_clips(rec_dir: Path, theme: str) -> list[tuple[int, Path]]:
    out = []
    for p in sorted(rec_dir.glob(f"step-*-{theme}-narrated.mov")):
        m = re.match(r"step-(\d+)-", p.name)
        if m:
            out.append((int(m.group(1)), p))
    return sorted(out)


def _step_titles(rec_dir: Path, clips: list[tuple[int, Path]], theme: str) -> dict[int, str]:
    """Human step titles: from the source workflow markdown when it is still
    around, otherwise recovered from the clip filenames."""
    titles: dict[int, str] = {}
    wf = ROOT / "workflows" / f"{rec_dir.name}.md"
    if wf.exists():
        try:
            from src.parser import parse_markdown
            for i, step in enumerate(parse_markdown(wf), 1):
                titles[i] = step.title
        except Exception:
            titles = {}
    for n, p in clips:
        if n not in titles:
            stem = re.sub(rf"^step-\d+-|-{theme}-narrated$", "", p.stem)
            titles[n] = stem.replace("-", " ").strip().capitalize()
    return titles


def _narration_block(rec_dir: Path, tag: str) -> str:
    """Read a free-form [tag] block out of narration.txt (e.g. [card])."""
    f = rec_dir / "narration.txt"
    if not f.exists():
        return ""
    want, buf, grabbing = tag.lower(), [], False
    for raw in f.read_text().splitlines():
        m = re.match(r"^\s*\[\s*([^\]]+?)\s*\]\s*$", raw)
        if m:
            grabbing = m.group(1).strip().lower() == want
            continue
        if grabbing and not raw.lstrip().startswith("#"):
            buf.append(raw.strip())
    return " ".join(x for x in buf if x).strip()


# ── assembly ─────────────────────────────────────────────────────────────────

def _probe_size(path: Path) -> tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)["streams"][0]
    return int(s["width"]), int(s["height"])


def _canvas(quality: str, body: Path) -> tuple[int, int]:
    if quality == "native":
        w, h = _probe_size(body)
        return w - w % 2, h - h % 2
    return QUALITY[quality]


def _concat(parts: list[Path], canvas: tuple[int, int], pad_hex: str,
            out: Path, preset: str, crf: int) -> Path:
    w, h = canvas
    chains, refs = [], []
    for i, _ in enumerate(parts):
        chains.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={pad_hex},setsar=1,fps={FPS},"
            f"format=yuv420p[v{i}]")
        chains.append(
            f"[{i}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[a{i}]")
        refs.append(f"[v{i}][a{i}]")
    chains.append("".join(refs) + f"concat=n={len(parts)}:v=1:a=1[v][a]")

    cmd = ["ffmpeg", "-y"]
    for p in parts:
        cmd += ["-i", str(p)]
    cmd += ["-filter_complex", ";".join(chains), "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
            "-x264-params", f"keyint={FPS*2}:min-keyint={FPS}:scenecut=40",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed:\n{r.stderr[-2500:]}")
    return out


def _loudnorm(src: Path, dst: Path) -> bool:
    """Two-pass EBU R128 normalisation to YouTube's target. Video is copied, so
    normalising costs nothing in picture quality. Returns False if measuring
    failed (the un-normalised file is then kept)."""
    measure = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(src), "-af",
         f"loudnorm=I={LUFS}:TP={TRUE_PEAK}:LRA=11:print_format=json",
         "-f", "null", "-"], capture_output=True, text=True)
    try:
        blob = measure.stderr[measure.stderr.rindex("{"):]
        stats = json.loads(blob[:blob.index("}") + 1] if "}" in blob else blob)
    except (ValueError, json.JSONDecodeError):
        return False

    af = (f"loudnorm=I={LUFS}:TP={TRUE_PEAK}:LRA=11:"
          f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
          f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
          f"offset={stats['target_offset']}:linear=true:print_format=summary")
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-c:v", "copy", "-af", af,
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", str(dst)], capture_output=True, text=True)
    if r.returncode != 0:
        return False
    print(f"[youtube] loudness {stats['input_i']} LUFS → {LUFS} LUFS (EBU R128, two-pass)")
    return True


# ── upload kit ───────────────────────────────────────────────────────────────

def _timestamp(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _chapters(intro_dur: float, clips: list[tuple[int, Path]],
              titles: dict[int, str], total: float) -> list[tuple[float, str]]:
    """YouTube chapter rules: the first mark is at 0:00, there are at least
    three marks, and every chapter — including the last — runs 10s or longer.
    A title card shorter than 10s gets no mark of its own; step 1's chapter
    simply starts at 0:00 and covers it."""
    marks: list[tuple[float, str]] = []
    if intro_dur >= 10.0:
        marks.append((0.0, "Intro"))

    t = intro_dur
    for n, clip in clips:
        title = titles.get(n, f"Step {n}")
        if not marks:
            marks.append((0.0, title))
        elif t - marks[-1][0] >= 10.0:
            marks.append((t, title))
        t += narrate._probe_duration(clip)

    while len(marks) > 1 and total - marks[-1][0] < 10.0:
        marks.pop()
    return marks if len(marks) >= 3 else []


def _filename(title: str) -> str:
    clean = re.sub(r"[^\w\s-]", "", title).strip()
    return re.sub(r"\s+", "-", clean)


def _description(title: str, subtitle: str, chapters: list[tuple[float, str]],
                 titles: dict[int, str], workflow: Path | None) -> str:
    lines = [title, ""]
    if subtitle:
        lines += [subtitle, ""]
    lines += [
        "A step-by-step walkthrough in WSO2 Integrator — every step is shown on "
        "screen exactly as you would do it yourself, at the pace you would do it.", ""]
    if chapters:
        lines.append("Chapters")
        lines += [f"{_timestamp(t)} {name}" for t, name in chapters]
        lines.append("")
    if titles:
        lines.append("What we build")
        lines += [f"{n}. {titles[n]}" for n in sorted(titles)]
        lines.append("")
    if workflow and workflow.exists():
        lines += ["Written guide: <paste the docs page URL here>", ""]
    lines += ["#WSO2 #WSO2Integrator #Integration #API #LowCode #Ballerina"]
    return "\n".join(lines)


# ── main ─────────────────────────────────────────────────────────────────────

def build(rec_dir: Path, title: str, subtitle: str = "", theme: str = "auto",
          quality: str = "1440p", hook: str | None = None, intro: bool = True,
          endcard: bool = False, preset: str = "medium", crf: int = 16,
          out_dir: Path | None = None, rebuild_intro: bool = False,
          eyebrow: str = "GET STARTED", art: str = "none",
          label: str | None = None) -> Path:
    rec_dir = Path(rec_dir)
    theme = _detect_theme(rec_dir) if theme == "auto" else theme
    body = _body(rec_dir, theme)
    canvas = _canvas(quality, body)
    pad_hex = "0x%02x%02x%02x" % THEMES[theme]["bg"]
    out_dir = out_dir or ROOT / "output" / "youtube" / rec_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[youtube] {rec_dir.name} · {theme} · {canvas[0]}x{canvas[1]} · "
          f"body {body.name} ({narrate._probe_duration(body):.0f}s)")

    parts: list[Path] = []
    intro_dur = 0.0
    if intro:
        text = hook or _narration_block(rec_dir, "card") or \
            f"{title}. Let's get started."
        intro_mp4 = out_dir / f"{rec_dir.name}-intro-{theme}.mp4"
        if rebuild_intro or not intro_mp4.exists():
            build_intro(title, subtitle, text, intro_mp4,
                        quality="1440p" if quality == "native" else quality, theme=theme,
                        eyebrow=eyebrow, art=art, label=label)
        else:
            print(f"[youtube] reusing existing intro {intro_mp4.name} (--rebuild-intro to redo)")
        intro_dur = narrate._probe_duration(intro_mp4)
        parts.append(intro_mp4)

    parts.append(body)

    if endcard:
        text = _narration_block(rec_dir, "endcard") or \
            "Thanks for watching. Subscribe for more WSO2 Integrator tutorials."
        end_mp4 = out_dir / f"{rec_dir.name}-endcard-{theme}.mp4"
        if rebuild_intro or not end_mp4.exists():
            build_intro("Thanks for watching", subtitle or title, text, end_mp4,
                        quality="1440p" if quality == "native" else quality,
                        theme=theme, zoom=False, eyebrow=eyebrow, art=art, label=label)
        parts.append(end_mp4)

    master = out_dir / f"{_filename(title)}.mp4"
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "raw.mp4"
        print(f"[youtube] encoding master ({len(parts)} segment(s), x264 preset {preset} crf {crf})…")
        _concat(parts, canvas, pad_hex, raw, preset, crf)
        if not _loudnorm(raw, master):
            print("[youtube] loudness pass unavailable — keeping raw levels")
            raw.replace(master)

    clips = _step_clips(rec_dir, theme)
    titles = _step_titles(rec_dir, clips, theme)
    chapters = _chapters(intro_dur, clips, titles, narrate._probe_duration(master))
    wf = ROOT / "workflows" / f"{rec_dir.name}.md"

    desc = out_dir / f"{_filename(title)}.description.txt"
    desc.write_text(_description(title, subtitle, chapters, titles, wf))
    if chapters:
        (out_dir / f"{_filename(title)}.chapters.txt").write_text(
            "\n".join(f"{_timestamp(t)} {n}" for t, n in chapters) + "\n")
    make_thumbnail(title, subtitle, out_dir / f"{_filename(title)}.thumbnail.png",
                   theme, eyebrow, art, label)

    dur = narrate._probe_duration(master)
    size_mb = master.stat().st_size / 1e6
    print(f"\n{'='*70}")
    print(f"  MASTER      {master}")
    print(f"              {canvas[0]}x{canvas[1]} @{FPS}fps · {_timestamp(dur)} · {size_mb:.0f} MB")
    print(f"  THUMBNAIL   {out_dir / f'{_filename(title)}.thumbnail.png'} (1280x720)")
    print(f"  DESCRIPTION {desc}")
    if chapters:
        print(f"  CHAPTERS    {len(chapters)} marks — paste into the description as-is")
    else:
        print("  CHAPTERS    skipped (YouTube needs 3+ marks, each 10s or longer)")
    print(f"{'='*70}")
    return master


def main() -> None:
    ap = argparse.ArgumentParser(description="Assemble a YouTube-ready master from a FlowCast recording.")
    ap.add_argument("--dir", type=Path, required=True, help="output/recordings/<slug>")
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="WSO2 Integrator")
    ap.add_argument("--theme", choices=["auto", "dark", "light"], default="auto")
    ap.add_argument("--quality", choices=list(QUALITY) + ["native"], default="1440p")
    ap.add_argument("--hook", default=None, help="spoken line for the title card")
    ap.add_argument("--no-intro", action="store_true")
    ap.add_argument("--endcard", action="store_true")
    ap.add_argument("--preset", default="medium", help="x264 preset (default medium; slow = smaller file)")
    ap.add_argument("--crf", type=int, default=16)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--rebuild-intro", action="store_true")
    ap.add_argument("--eyebrow", default="GET STARTED",
                    help="small letterspaced kicker on the card and thumbnail")
    ap.add_argument("--art", choices=ART_KINDS, default="none",
                    help="line-art illustration: chat, robot, files, graph, sync, sap")
    ap.add_argument("--label", default=None,
                    help="text in the illustration's speech bubble (e.g. 'GET /greeting')")
    args = ap.parse_args()

    build(args.dir, args.title, args.subtitle, theme=args.theme, quality=args.quality,
          hook=args.hook, intro=not args.no_intro, endcard=args.endcard,
          preset=args.preset, crf=args.crf, out_dir=args.out_dir,
          rebuild_intro=args.rebuild_intro, eyebrow=args.eyebrow, art=args.art,
          label=args.label)


if __name__ == "__main__":
    main()
