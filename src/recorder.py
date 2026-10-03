from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

FPS = 30
WIDTH = 1920
DEFAULT_MENU_BAR_H = 70  # logical pixels — macOS menu bar + border
# Set to 0 by runner._set_menu_crop() when the app is in native full screen,
# where there is no menu bar to crop away.
MENU_BAR_H = DEFAULT_MENU_BAR_H

_proc: subprocess.Popen | None = None
_mov_path: Path | None = None
_screen_idx: str | None = None
_stderr_tmp = None

# A capture started before the action is known (prewarm), so the action's clip
# begins the moment it is asked for: ffmpeg + AVFoundation take about a second
# to start, which used to sit between a tap on the phone and the mouse moving.
# start() adopts it and stop() cuts the waiting off the head.
DEVICE_GAP = 0.5    # AVFoundation lets go of the screen this long after a stop
WARMUP = 0.9        # start-up before a new capture's frames can be relied on
LEAD = 1.2          # seconds before the first move kept (from spawn: ~0.4-1 s on screen)
WARM_LIMIT = 900    # an unused pre-started capture ends itself after 15 minutes
_capture_path: Path | None = None   # where ffmpeg writes (differs when adopted)
_head = 0.0                         # seconds to cut off the front at stop
_last_stop = 0.0
_warm: dict | None = None
_warm_thread: threading.Thread | None = None


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


def _cmd(path: Path, limit: float | None = None) -> list[str]:
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
        # Lossless (crf 0) at any preset; ultrafast keeps up with the screen
        # with nothing to flush on stop ("slow" held ~2 s of lookahead). A
        # keyframe every half second lets a pre-started capture be cut by copy.
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0", "-g", str(FPS // 2),
    ]
    if limit:
        cmd += ["-t", str(limit)]
    return cmd + [str(path)]


def _wait_device() -> None:
    gap = DEVICE_GAP - (time.time() - _last_stop)
    if gap > 0:
        time.sleep(gap)


def prewarm(output_dir: Path | None = None) -> None:
    """Start capturing now, in the background, for the next action.

    Call while waiting (for a tap on the phone, for detection to find the
    target). A no-op while recording or already warm."""
    global _warm_thread, _warm
    if _proc is not None or _warm_thread is not None:
        return
    if _warm is not None:
        if (_warm["proc"].poll() is None and time.time() - _warm["spawned"] < WARM_LIMIT - 120
                and _warm["crop"] == MENU_BAR_H):
            return
        _end(_warm)                      # ended by itself, or about to
        _warm = None
    folder = output_dir or Path(tempfile.gettempdir()) / "flowcast-prewarm"

    def spawn() -> None:
        global _warm
        _wait_device()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"warm-{os.getpid()}-{time.time_ns()}.mov"
        err = tempfile.TemporaryFile()
        try:
            proc = subprocess.Popen(_cmd(path, WARM_LIMIT), stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=err)
        except Exception:
            err.close()
            return
        _warm = {"proc": proc, "path": path, "stderr": err, "spawned": time.time(),
                 "crop": MENU_BAR_H}

    _warm_thread = threading.Thread(target=spawn, daemon=True)
    _warm_thread.start()


def _take_warm() -> dict | None:
    global _warm, _warm_thread
    if _warm_thread is not None:
        _warm_thread.join()
        _warm_thread = None
    w, _warm = _warm, None
    return w


def _end(w: dict) -> None:
    """Stop a pre-started capture nobody used, and delete it."""
    global _last_stop
    proc = w["proc"]
    if proc.poll() is None:
        try:
            proc.stdin.write(b"q")
            proc.stdin.flush()
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        _last_stop = time.time()
    w["stderr"].close()
    w["path"].unlink(missing_ok=True)


def discard_prewarm() -> None:
    w = _take_warm()
    if w is not None:
        _end(w)


atexit.register(discard_prewarm)


def start(name: str, output_dir: Path) -> None:
    global _proc, _mov_path, _stderr_tmp, _capture_path, _head

    if _proc is not None:
        raise RuntimeError("Recorder already running")

    output_dir.mkdir(parents=True, exist_ok=True)
    _mov_path = output_dir / f"{name}.mov"

    w = _take_warm()
    if w is not None:
        age = time.time() - w["spawned"]
        # Same crop as now, or its frames would be a different size from the
        # other clips (a full-screen change since it started).
        if w["proc"].poll() is None and age < WARM_LIMIT - 120 and w["crop"] == MENU_BAR_H:
            if age < WARMUP:             # asked for the moment it was started
                time.sleep(WARMUP - age)
                age = WARMUP
            _proc, _stderr_tmp, _capture_path = w["proc"], w["stderr"], w["path"]
            _head = max(0.0, age - LEAD)
            print(f"[recorder] Recording → {_mov_path.name} (already capturing)")
            return
        _end(w)

    _capture_path, _head = _mov_path, 0.0
    cmd = _cmd(_mov_path)
    for attempt in range(2):
        _wait_device()
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
    global _proc, _mov_path, _stderr_tmp, _capture_path, _head, _last_stop

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

    path, capture, head = _mov_path, _capture_path, _head
    _proc = None
    _mov_path = None
    _stderr_tmp = None
    _capture_path, _head = None, 0.0
    # AVFoundation needs a moment to release the screen before the next
    # capture starts — waited for by that start (_wait_device), not here.
    _last_stop = time.time()

    if rc != 0:
        raise RuntimeError(
            f"Recording failed (exit {rc}):\n" + err_bytes.decode(errors="replace")
        )
    if capture is None or not capture.exists() or capture.stat().st_size == 0:
        raise RuntimeError(f"Recording produced no output: {capture}")

    path = _finish(capture, path, head)

    print(f"[recorder] Saved → {path.name}")
    return path


def _finish(capture: Path, path: Path, head: float = 0.0) -> Path:
    """Write the clip to `path` with its timestamps starting at zero, cutting
    `head` seconds of waiting off a pre-started capture. A stream copy (0.1 s);
    this used to re-encode every clip with the slow preset (~1.5 s an action)
    without changing a frame."""
    out = path.with_name(f"{path.stem}.part{path.suffix}")
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if head > 0.3:
        cmd += ["-ss", f"{head:.2f}"]     # lands on the keyframe at or before it
    cmd += ["-i", str(capture), "-c", "copy", "-avoid_negative_ts", "make_zero", str(out)]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        out.replace(path)
        if capture != path:
            capture.unlink(missing_ok=True)
    except Exception as e:
        print(f"[recorder] could not tidy {path.name} ({e}); kept as captured")
        out.unlink(missing_ok=True)
        if capture != path:
            shutil.move(str(capture), str(path))
    return path


def trim(mov_path: Path) -> Path:
    """Timestamps from zero, no re-encode (kept for callers of the old name)."""
    if not mov_path.exists() or mov_path.stat().st_size == 0:
        return mov_path
    return _finish(mov_path, mov_path)


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
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0",   # lossless; slow was 3x the wait
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
