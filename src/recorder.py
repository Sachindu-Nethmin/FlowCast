from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

FPS = 10
WIDTH = 1280

_proc: subprocess.Popen | None = None
_mov_path: Path | None = None
_screen_idx: str | None = None


def _get_screen_index() -> str:
    global _screen_idx
    if _screen_idx is not None:
        return _screen_idx
    try:
        result = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stderr.splitlines():
            if "screen" in line.lower() or "capture screen" in line.lower():
                m = re.search(r'\[(\d+)\]', line)
                if m:
                    _screen_idx = m.group(1)
                    return _screen_idx
    except Exception:
        pass
    _screen_idx = "1"
    return _screen_idx


def start(name: str, output_dir: Path) -> None:
    global _proc, _mov_path
    if _proc is not None:
        raise RuntimeError("Recorder already running")

    output_dir.mkdir(parents=True, exist_ok=True)
    _mov_path = output_dir / f"{name}.mov"

    idx = _get_screen_index()
    cmd = [
        "ffmpeg", "-y",
        "-f", "avfoundation",
        "-capture_cursor", "1",
        "-framerate", str(FPS),
        "-i", f"{idx}:none",
        "-vf", f"fps={FPS},scale={WIDTH}:-1:flags=lanczos",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0",
        str(_mov_path),
    ]
    _proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8)
    print(f"[recorder] Recording → {_mov_path.name}")


def stop() -> Path:
    global _proc, _mov_path
    if _proc is None:
        raise RuntimeError("Recorder not running")
    try:
        _proc.stdin.write(b"q")
        _proc.stdin.flush()
    except BrokenPipeError:
        pass
    try:
        _proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        _proc.terminate()
        _proc.wait(timeout=10)
    path = _mov_path
    _proc = None
    _mov_path = None
    print(f"[recorder] Saved → {path.name}")
    return path


def combine(clips: list[Path], output: Path, keep_inputs: bool = False) -> Path:
    """Concatenate .mov clips into a single .mov file.

    keep_inputs=True leaves the source files untouched (used when combining
    permanent step MOVs into the full recording).
    """
    if not clips:
        raise ValueError("No clips to combine")
    if len(clips) == 1:
        if keep_inputs:
            import shutil
            shutil.copy2(clips[0], output)
        else:
            clips[0].rename(output)
        return output

    list_file = output.parent / f"{output.stem}_concat.txt"
    with list_file.open("w") as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output),
    ], check=True, capture_output=True)

    list_file.unlink(missing_ok=True)
    if not keep_inputs:
        for clip in clips:
            clip.unlink(missing_ok=True)
    print(f"[recorder] Combined {len(clips)} clip(s) → {output.name}")
    return output


def to_gif(mov: Path, gif: Path) -> Path:
    palette = gif.parent / f"{gif.stem}_palette.png"
    vf = f"fps={FPS},scale={WIDTH}:-1:flags=lanczos"

    subprocess.run([
        "ffmpeg", "-y", "-i", str(mov),
        "-vf", f"{vf},palettegen",
        str(palette),
    ], check=True, capture_output=True)

    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(mov), "-i", str(palette),
        "-lavfi", f"{vf} [x]; [x][1:v] paletteuse",
        "-loop", "0",
        str(gif),
    ], check=True, capture_output=True)

    palette.unlink(missing_ok=True)
    print(f"[recorder] GIF → {gif.name}")
    return gif
