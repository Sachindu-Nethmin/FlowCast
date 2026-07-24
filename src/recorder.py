from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

FPS = 30
WIDTH = 1920
MENU_BAR_H = 70  # logical pixels — macOS menu bar + border

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
    # crop removes the menu bar, then resample fps and scale
    vf = f"crop=in_w:in_h-{MENU_BAR_H}:0:{MENU_BAR_H},fps={FPS},scale={WIDTH}:-2:flags=lanczos"

    cmd = [
        "ffmpeg", "-y",
        "-f", "avfoundation",
        "-capture_cursor", "1",          # macOS composites the real hardware cursor
        "-framerate", str(FPS),
        "-pixel_format", "uyvy422",      # avfoundation native format — avoids fallback warning
        "-i", f"{idx}:none",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "slow", "-crf", "0",
        str(_mov_path),
    ]
    for attempt in range(2):
        _stderr_tmp = tempfile.TemporaryFile()
        _proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=_stderr_tmp,
        )
        time.sleep(1.0)
        if _proc.poll() is None:
            break  # ffmpeg is running — recording started successfully
        _stderr_tmp.seek(0)
        err = _stderr_tmp.read().decode(errors="replace")
        _stderr_tmp.close()
        _proc = None
        if attempt == 0 and "Invalid device index" in err:
            print("[recorder] AVFoundation device unavailable, retrying in 2s...")
            time.sleep(2.0)
            continue
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
    finally:
        try:
            _proc.stdin.close()
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

    # Give macOS AVFoundation time to release the screen capture device before
    # the next recording can start — without this pause the next ffmpeg launch
    # gets "Invalid device index" because the device is still held.
    time.sleep(0.5)

    if rc != 0:
        raise RuntimeError(
            f"Recording failed (exit {rc}):\n" + err_bytes.decode(errors="replace")
        )
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Recording produced no output: {path}")

    # Optimize: Remove idle time (static frames) from the clip
    path = trim(path)

    print(f"[recorder] Saved → {path.name}")
    return path


def trim(mov_path: Path) -> Path:
    """Re-encode at full quality without removing frames (keeps real-time speed)."""
    if not mov_path.exists() or mov_path.stat().st_size == 0:
        return mov_path

    trimmed_path = mov_path.parent / f"{mov_path.stem}_trimmed{mov_path.suffix}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(mov_path),
        "-c:v", "libx264", "-preset", "slow", "-crf", "0",
        str(trimmed_path),
    ]

    try:
        subprocess.run(cmd, capture_output=True, check=True)
        mov_path.unlink()
        trimmed_path.rename(mov_path)
    except Exception as e:
        print(f"[recorder] Re-encode failed for {mov_path.name}: {e}")
        if trimmed_path.exists():
            trimmed_path.unlink()

    return mov_path


def combine(clips: list[Path], output: Path, keep_inputs: bool = False) -> Path:
    """Concatenate .mov clips into a single .mov file."""
    # Filter out missing clips (files that were deleted or never created)
    valid = [c for c in clips if c.exists() and c.stat().st_size > 0]
    if len(valid) < len(clips):
        missing = [c for c in clips if not c.exists()]
        if missing:
            print(f"[recorder] WARNING: {len(missing)} clip(s) missing, skipping: {[m.name for m in missing]}")
    clips = valid

    if not clips:
        raise ValueError("No clips to combine (all missing)")
    if len(clips) == 1:
        if keep_inputs:
            shutil.copy2(clips[0], output)
        else:
            clips[0].rename(output)
        return output

    # Copy clips to a stable directory next to the output to avoid temp-dir cleanup issues
    stable_dir = output.parent / "_clips"
    stable_dir.mkdir(exist_ok=True)
    stable_clips = []
    for i, clip in enumerate(clips):
        stable = stable_dir / f"clip_{i:03d}{clip.suffix}"
        shutil.copy2(clip, stable)
        stable_clips.append(stable)

    list_file = output.parent / f"{output.stem}_concat.txt"
    with list_file.open("w") as f:
        for clip in stable_clips:
            f.write(f"file '{clip.resolve()}'\n")

    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c:v", "libx264", "-preset", "slow", "-crf", "0",
        str(output),
    ], capture_output=True)

    # Clean up
    list_file.unlink(missing_ok=True)
    shutil.rmtree(stable_dir, ignore_errors=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg concat failed (exit {result.returncode}):\n"
            + result.stderr.decode(errors="replace")
        )

    if not keep_inputs:
        for clip in clips:
            clip.unlink(missing_ok=True)
    print(f"[recorder] Combined {len(clips)} clip(s) → {output.name}")
    return output


def to_gif(mov: Path, gif: Path) -> Path:
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
