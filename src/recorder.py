from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

FPS = 10
WIDTH = 1280

_proc: subprocess.Popen | None = None
_mov_path: Path | None = None
_screen_idx: str | None = None
_stderr_tmp = None


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
    _screen_idx = "2"
    return _screen_idx



def start(name: str, output_dir: Path) -> None:
    global _proc, _mov_path, _stderr_tmp

    if _proc is not None:
        raise RuntimeError("Recorder already running")

    output_dir.mkdir(parents=True, exist_ok=True)
    _mov_path = output_dir / f"{name}.mov"

    idx = _get_screen_index()
    # avfoundation captures at logical resolution — just resample fps and scale
    vf = f"fps={FPS},scale={WIDTH}:-2:flags=lanczos"

    cmd = [
        "ffmpeg", "-y",
        "-f", "avfoundation",
        "-capture_cursor", "1",          # macOS composites the real hardware cursor
        "-framerate", str(FPS),
        "-pixel_format", "uyvy422",      # avfoundation native format — avoids fallback warning
        "-i", f"{idx}:none",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0",
        str(_mov_path),
    ]
    _stderr_tmp = tempfile.TemporaryFile()
    _proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=_stderr_tmp,
    )
    time.sleep(0.8)
    if _proc.poll() is not None:
        _stderr_tmp.seek(0)
        err = _stderr_tmp.read().decode(errors="replace")
        raise RuntimeError(f"Recorder exited early:\n{err}")
    print(f"[recorder] Recording → {_mov_path.name}")


def stop() -> Path:
    global _proc, _mov_path, _stderr_tmp

    if _proc is None:
        raise RuntimeError("Recorder not running")

    try:
        _proc.stdin.write(b"q")
        _proc.stdin.flush()
    except (BrokenPipeError, OSError):
        pass

    try:
        _proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
            _proc.wait()

    rc = _proc.returncode
    if _stderr_tmp is not None:
        _stderr_tmp.seek(0)
        err_bytes = _stderr_tmp.read()
        _stderr_tmp.close()
    else:
        err_bytes = b""

    path = _mov_path
    _proc = None
    _mov_path = None
    _stderr_tmp = None

    if rc != 0:
        raise RuntimeError(
            f"Recording failed (exit {rc}):\n" + err_bytes.decode(errors="replace")
        )
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Recording produced no output: {path}")

    print(f"[recorder] Saved → {path.name}")
    return path


def combine(clips: list[Path], output: Path, keep_inputs: bool = False) -> Path:
    """Concatenate .mov clips into a single .mov file."""
    if not clips:
        raise ValueError("No clips to combine")
    if len(clips) == 1:
        if keep_inputs:
            shutil.copy2(clips[0], output)
        else:
            clips[0].rename(output)
        return output

    list_file = output.parent / f"{output.stem}_concat.txt"
    with list_file.open("w") as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")

    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        # Re-encode to fix discontinuous PTS across avfoundation clips
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0",
        str(output),
    ], capture_output=True)
    if result.returncode != 0:
        list_file.unlink(missing_ok=True)
        raise RuntimeError(
            f"ffmpeg concat failed (exit {result.returncode}):\n"
            + result.stderr.decode(errors="replace")
        )

    list_file.unlink(missing_ok=True)
    if not keep_inputs:
        for clip in clips:
            clip.unlink(missing_ok=True)
    print(f"[recorder] Combined {len(clips)} clip(s) → {output.name}")
    return output


def to_gif(mov: Path, gif: Path) -> Path:
    # frames already cropped/scaled during recording — just resample fps and palette
    vf = f"fps={FPS},scale={WIDTH}:-2:flags=lanczos"
    palette = gif.parent / f"{gif.stem}_palette.png"

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
