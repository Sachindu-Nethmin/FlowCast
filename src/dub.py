"""Offline AI voice dubbing for FlowCast — narrates workflow steps onto the
recorded .mov files using macOS's built-in Speech Synthesis (`say`).

Fully offline: `say` is a system command bundled with every Mac, no API
key, no network call, no model download — same "on-device" approach as
src/voice.py's speech-to-text. Only touches .mov files (writes new
"-dubbed" copies, never overwrites the originals); GIFs, full_script.py,
and index.md are untouched — GIFs have no audio track at all, and the
others aren't video.

Usage (post-process — run AFTER recording a workflow, any mode):
    uv run python main.py workflow.md --dub

What it does:
    For each step-NN-<slug>-<theme>.mov already on disk, synthesizes
    narration from that step's title + instructions (the same clean text
    parser.instruction_lines() derives from workflow.md) and muxes it onto
    the video, writing step-NN-<slug>-<theme>-dubbed.mov. If the narration
    runs longer than the recorded clip, the video is extended by freezing
    its last frame (never truncates narration); if the clip runs longer,
    it simply continues silently after narration ends. A dubbed
    full-<theme>-dubbed.mov is then rebuilt by concatenating the dubbed
    step clips, so it stays in perfect sync without re-probing timestamps
    inside an already-combined file.

Customize the voice via environment variables (see `say -v ?` for the
full list of installed voices):
    FLOWCAST_DUB_VOICE=Samantha
    FLOWCAST_DUB_RATE=185     # words per minute, `say`'s default is ~175-200
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from src.parser import Step, instruction_lines, parse_markdown


# ── Narration synthesis (macOS 'say', fully offline) ─────────────────────────

def synthesize(text: str, out_wav: Path, voice: str | None = None,
                rate: int | None = None) -> Path:
    """Render `text` to a WAV file via macOS's built-in `say` command."""
    text = text.strip()
    if not text:
        raise ValueError("Cannot synthesize empty narration text")

    voice = voice or os.environ.get("FLOWCAST_DUB_VOICE")
    rate = rate or os.environ.get("FLOWCAST_DUB_RATE")

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    tmp_aiff = out_wav.with_suffix(".aiff")

    cmd = ["say", "-o", str(tmp_aiff)]
    if voice:
        cmd += ["-v", str(voice)]
    if rate:
        cmd += ["-r", str(rate)]
    cmd.append(text)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0 or not tmp_aiff.exists():
        raise RuntimeError(
            f"macOS 'say' failed (exit {result.returncode}): {result.stderr.strip()}\n"
            f"Run `say -v ?` to list valid voice names if FLOWCAST_DUB_VOICE is set."
        )

    # Normalize to a consistent WAV format ffmpeg can mux predictably.
    conv = subprocess.run(
        ["ffmpeg", "-y", "-i", str(tmp_aiff), "-ar", "44100", "-ac", "2", str(out_wav)],
        capture_output=True, text=True,
    )
    tmp_aiff.unlink(missing_ok=True)
    if conv.returncode != 0 or not out_wav.exists():
        raise RuntimeError(f"Failed to convert narration to WAV: {conv.stderr.strip()}")
    return out_wav


# ── Duration probing + video padding ─────────────────────────────────────────

def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise RuntimeError(f"Could not read duration of {path}: {result.stderr.strip()}")


def _pad_amount(video_seconds: float, audio_seconds: float, epsilon: float = 0.05) -> float:
    """How many extra seconds the video needs (freeze last frame) so it isn't
    shorter than the narration. 0 if the video is already long enough —
    narration is never truncated, but a video is never artificially shortened
    to match shorter narration either (it just plays out silently)."""
    extra = audio_seconds - video_seconds
    return max(0.0, extra) if extra > epsilon else 0.0


def _pad_video(mov_path: Path, extra_seconds: float, out_path: Path) -> Path:
    subprocess.run([
        "ffmpeg", "-y", "-i", str(mov_path),
        "-vf", f"tpad=stop_mode=clone:stop_duration={extra_seconds:.3f}",
        "-c:v", "libx264", "-preset", "slow", "-crf", "0",
        str(out_path),
    ], capture_output=True, check=True)
    return out_path


# ── Per-clip dubbing ──────────────────────────────────────────────────────────

def dub_mov(mov_path: Path, narration_text: str, out_path: Path | None = None,
            voice: str | None = None, rate: int | None = None) -> Path:
    """Mux AI-narrated audio onto one .mov. Writes a new "-dubbed" file;
    the original silent recording is left untouched."""
    if out_path is None:
        out_path = mov_path.with_name(f"{mov_path.stem}-dubbed{mov_path.suffix}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="dub_"))
    try:
        narration_wav = tmp_dir / "narration.wav"
        synthesize(narration_text, narration_wav, voice=voice, rate=rate)

        video_dur = _probe_duration(mov_path)
        audio_dur = _probe_duration(narration_wav)
        extra = _pad_amount(video_dur, audio_dur)

        video_for_mux = mov_path
        if extra > 0:
            video_for_mux = _pad_video(mov_path, extra, tmp_dir / "padded.mov")
            print(f"[dub] {mov_path.name}: narration ({audio_dur:.1f}s) runs "
                  f"{extra:.1f}s longer than the clip ({video_dur:.1f}s) — "
                  f"holding the last frame to cover it")

        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", str(video_for_mux), "-i", str(narration_wav),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "slow", "-crf", "0",
            "-c:a", "aac", "-b:a", "192k",
            str(out_path),
        ], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg mux failed for {mov_path.name}: {result.stderr.strip()}")

        print(f"[dub] {mov_path.name} → {out_path.name} "
              f"(video {video_dur:.1f}s, narration {audio_dur:.1f}s)")
        return out_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Whole-workflow orchestration ─────────────────────────────────────────────

def _narration_for_step(idx: int, step: Step) -> str:
    lines = instruction_lines(step.raw_instructions)
    body = ". ".join(l.rstrip(".") for l in lines if l.strip())
    return f"Step {idx}: {step.title}." + (f" {body}." if body else "")


def detect_theme_from_output(out_dir: Path) -> str:
    """Auto-detect which theme's recordings are on disk, so --dub doesn't
    need to open the app / take a screenshot at all."""
    if (out_dir / "full-dark.mov").exists() or list(out_dir.glob("step-*-dark.mov")):
        return "dark"
    if (out_dir / "full-light.mov").exists() or list(out_dir.glob("step-*-light.mov")):
        return "light"
    raise RuntimeError(
        f"No recorded step-*.mov files found in {out_dir} — run the workflow "
        f"first (with or without --guide) before using --dub."
    )


def dub_workflow(md_path: Path, out_dir: Path, theme: str,
                  voice: str | None = None, rate: int | None = None,
                  include_full: bool = True) -> dict:
    """Dub every already-recorded step clip for this workflow, then rebuild
    a dubbed full-<theme>-dubbed.mov from those dubbed clips (concatenation,
    not re-probing inside the pre-combined file, so sync stays exact)."""
    from src import recorder
    from src.artifacts import slug as _slug

    steps = parse_markdown(md_path)
    results: dict = {"steps": [], "full": None, "skipped": []}
    dubbed_movs: list[Path] = []

    for idx, step in enumerate(steps, 1):
        title_slug = _slug(step.title)
        mov = out_dir / f"step-{idx:02d}-{title_slug}-{theme}.mov"
        if not mov.exists():
            print(f"[dub] skip step {idx} ('{step.title}') — {mov.name} not recorded yet")
            results["skipped"].append(step.title)
            continue

        narration = _narration_for_step(idx, step)
        dubbed = dub_mov(mov, narration, voice=voice, rate=rate)
        dubbed_movs.append(dubbed)
        results["steps"].append({"step": idx, "title": step.title, "mov": str(dubbed)})

    if include_full and dubbed_movs:
        full_dubbed = out_dir / f"full-{theme}-dubbed.mov"
        recorder.combine(dubbed_movs, full_dubbed, keep_inputs=True)
        results["full"] = str(full_dubbed)
        print(f"[dub] Full dubbed video → {full_dubbed}")

    return results
