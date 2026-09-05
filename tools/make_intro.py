#!/usr/bin/env python3
"""
make_intro.py — branded title-card intro (and matching thumbnail) for FlowCast
tutorial videos.

The card IS the thumbnail design: same navy/cyan palette, same logo lockup,
same eyebrow → headline → subhead column, same line-art illustration. Both come
from `src/brand.py`, so a video and its thumbnail cannot drift apart.

It is animated element by element rather than as one zooming picture — the logo
tile pops, the wordmark settles beside it, the eyebrow, headline lines and
subhead rise and fade in on a stagger, the illustration pops, and its label
bubble lands last. A slow push-in runs underneath. The spoken hook uses the
SAME voice backend as the narration, so `FLOWCAST_TTS=chatterbox` gives the
intro your cloned voice too.

Usage:
    python tools/make_intro.py --title "Build a Hello World REST API" \
        --subtitle "Expose a REST API in minutes" --art graph \
        --text "In this tutorial we'll expose a REST API in WSO2 Integrator." \
        --out output/intro/hello-world-api.mp4

    # thumbnail only (1280x720, YouTube's recommended size)
    python tools/make_intro.py --title "..." --thumbnail-only out.png

Options worth knowing:
    --quality 1080p|1440p|4k   canvas size (default 1440p — YouTube gives
                               >=1440p uploads a noticeably higher bitrate)
    --eyebrow "GET STARTED"    small letterspaced kicker above the headline
    --art chat|robot|files|graph|sync|sap|none   right-hand illustration
    --no-zoom                  static framing instead of the slow push-in
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import brand, narrate  # noqa: E402

FPS = 30
QUALITY = {"1080p": (1920, 1080), "1440p": (2560, 1440), "4k": (3840, 2160)}

# The card is a dark, branded object whatever theme the screen recording used;
# `bg` is the letterbox pad colour make_youtube_video.py fills around the body,
# so the whole video stays on one background.
THEMES = {"dark": {"bg": brand.BASE}, "light": {"bg": brand.BASE}}

IN_DUR = 0.85          # seconds an element takes to arrive
ART_KINDS = list(brand.ARTS)


def make_thumbnail(title: str, subtitle: str, out_png: Path, theme: str = "dark",
                   eyebrow: str = "GET STARTED", art: str = "none",
                   label: str | None = None) -> Path:
    """1280x720 YouTube thumbnail — the same card, rendered as a still."""
    brand.render_thumbnail(title, out_png, eyebrow=eyebrow, subhead=subtitle,
                           art=art, label=label)
    print(f"[intro] thumbnail → {out_png}")
    return out_png


def _voice_over(text: str, wav: Path, voice: str | None, rate: int) -> float:
    """Speak `text` through FlowCast's normal voice backend (cloned when
    FLOWCAST_TTS=chatterbox). Sentences are synthesized separately — long
    single utterances drift on the clone backend — and joined with short gaps."""
    chosen = voice
    try:
        from src import tts_clone
        cloned = tts_clone.is_enabled()
    except Exception:
        cloned = False
    if not cloned:
        chosen = narrate.pick_voice(voice, narrate.list_installed_voices())

    sentences = narrate._split_sentences(text)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        parts: list[Path] = []
        for i, s in enumerate(sentences):
            p = tmp / f"s{i:02d}.wav"
            narrate._say_to_wav(s, p, chosen or "Alex", rate)
            parts.append(p)
            if i < len(sentences) - 1:                     # 0.28s breath between lines
                gap = tmp / f"g{i:02d}.wav"
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-t", "0.28",
                                "-i", "anullsrc=r=44100:cl=stereo", str(gap)],
                               capture_output=True, check=True)
                parts.append(gap)
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(wav)], capture_output=True, check=True)
    dur = narrate._probe_duration(wav)
    print(f"[intro] voice-over: {len(sentences)} line(s), {dur:.1f}s "
          f"({'cloned voice' if cloned else chosen})")
    return dur


def _compose(bg: Image.Image, layers: list[dict], t: float, unit: float) -> Image.Image:
    """One frame: the static background with each element at its own progress."""
    frame = bg.copy()
    for L in layers:
        p = (t - L["cue"]) / IN_DUR
        if p <= 0:
            continue
        img, pos = L["img"], L["pos"]
        if p < 1:
            fade = brand.ease_out_cubic(p)
            if L["pop"]:
                k = 0.90 + 0.10 * brand.ease_out_back(p)
                w, h = max(int(img.width * k), 1), max(int(img.height * k), 1)
                pos = (pos[0] + (img.width - w) // 2, pos[1] + (img.height - h) // 2)
                img = img.resize((w, h), Image.BILINEAR)
            else:
                pos = (pos[0], int(pos[1] + L["rise"] * unit * (1 - fade)))
            if fade < 1:
                img = img.copy()
                img.putalpha(img.getchannel("A").point(
                    lambda v, f=fade: int(v * f)))
        frame.alpha_composite(img, pos)
    return frame


def build_intro(title: str, subtitle: str, text: str, out: Path,
                quality: str = "1440p", theme: str = "dark",
                voice: str | None = None, rate: int = 172,
                lead_in: float = 0.7, tail: float = 1.0,
                zoom: bool = True, crf: int = 14, preset: str = "faster",
                eyebrow: str = "GET STARTED", art: str = "none",
                label: str | None = None) -> Path:
    """Render the animated title card with its voice-over → `out` (.mp4)."""
    size = QUALITY[quality]
    unit = size[1] / brand.DESIGN_H
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        wav = tmp / "vo.wav"
        speech = _voice_over(text, wav, voice, rate) if text.strip() else 0.0
        # Long enough for the choreography to land and breathe, whatever the VO.
        dur = max(round(lead_in + speech + tail, 2), 5.5)
        frames = int(dur * FPS)

        bg = brand.background(size).convert("RGBA")
        layers = brand.card_layers(title, eyebrow, subtitle, art, size, label)

        vf = []
        if zoom:
            vf.append(f"zoompan=z='min(1+0.045*on/{max(frames - 1, 1)},1.045)':"
                      f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                      f"d=1:s={size[0]}x{size[1]}:fps={FPS}")
        vf += [f"fade=t=in:st=0:d=0.45",
               f"fade=t=out:st={dur - 0.6:.2f}:d=0.6",
               "setsar=1", "format=yuv420p"]

        cmd = ["ffmpeg", "-y",
               "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{size[0]}x{size[1]}", "-r", str(FPS), "-i", "-"]
        if speech:
            cmd += ["-i", str(wav)]
        else:
            cmd += ["-f", "lavfi", "-t", str(dur), "-i", "anullsrc=r=44100:cl=stereo"]
        af = (f"adelay={int(lead_in * 1000)}|{int(lead_in * 1000)},apad,"
              f"atrim=0:{dur},afade=t=out:st={dur - 0.5:.2f}:d=0.5,"
              f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo")
        cmd += ["-vf", ",".join(vf), "-af", af,
                "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-shortest", "-movflags", "+faststart", str(out)]

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for n in range(frames):
                frame = _compose(bg, layers, n / FPS, unit)
                proc.stdin.write(frame.convert("RGB").tobytes())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed building the intro:\n{err[-2000:]}")

    print(f"[intro] {out}  ({dur:.1f}s, {size[0]}x{size[1]}@{FPS}, art={art})")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Branded intro card + voice-over.")
    ap.add_argument("--title", required=True, help="headline (wraps to two lines)")
    ap.add_argument("--subtitle", default="", help="cyan line under the headline")
    ap.add_argument("--text", default="", help="spoken hook (omit for a silent card)")
    ap.add_argument("--out", type=Path, default=Path("output/intro/intro.mp4"))
    ap.add_argument("--quality", choices=list(QUALITY), default="1440p")
    ap.add_argument("--theme", choices=list(THEMES), default="dark")
    ap.add_argument("--eyebrow", default="GET STARTED")
    ap.add_argument("--art", choices=ART_KINDS, default="none")
    ap.add_argument("--label", default=None,
                    help="text in the illustration's speech bubble")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--rate", type=int, default=172)
    ap.add_argument("--no-zoom", action="store_true")
    ap.add_argument("--thumbnail", type=Path, default=None, help="also write a 1280x720 thumbnail")
    ap.add_argument("--thumbnail-only", type=Path, default=None)
    args = ap.parse_args()

    if args.thumbnail_only:
        make_thumbnail(args.title, args.subtitle, args.thumbnail_only,
                       args.theme, args.eyebrow, args.art, args.label)
        return

    build_intro(args.title, args.subtitle, args.text, args.out,
                quality=args.quality, theme=args.theme,
                voice=args.voice, rate=args.rate, zoom=not args.no_zoom,
                eyebrow=args.eyebrow, art=args.art, label=args.label)
    if args.thumbnail:
        make_thumbnail(args.title, args.subtitle, args.thumbnail,
                       args.theme, args.eyebrow, args.art, args.label)


if __name__ == "__main__":
    main()
