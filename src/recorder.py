"""
recorder.py — Per-step GIF recorder using FFmpeg avfoundation (macOS).
Each step gets its own GIF via start(step_name) / stop().
"""
from __future__ import annotations

import signal
import subprocess
import time
from pathlib import Path

RECORDINGS_DIR = Path(__file__).parent.parent / "output" / "recordings"
FPS = 10

_output_dir: Path = RECORDINGS_DIR


def set_output_dir(path: str | Path) -> None:
    global _output_dir
    _output_dir = Path(path)


WIDTH = 1280  # GIF output width; height auto-scales


def _get_screen_device_index() -> str:
    """
    Probe avfoundation to find the screen capture device index.
    Returns the index as a string (e.g. "1" or "2").
    Defaults to "1" if probing fails.
    """
    try:
        probe = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Device list is in stderr
        output = probe.stderr
        for line in output.splitlines():
            line_lower = line.lower()
            if "capture screen" in line_lower or "screen" in line_lower:
                # Lines look like: [AVFoundation input device @ ...] [1] Capture screen 0
                import re
                m = re.search(r"\[(\d+)\]", line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return "1"


_SCREEN_INDEX: str | None = None


def _screen_index() -> str:
    global _SCREEN_INDEX
    if _SCREEN_INDEX is None:
        _SCREEN_INDEX = _get_screen_device_index()
        print(f"[recorder] Using avfoundation screen device index: {_SCREEN_INDEX}")
    return _SCREEN_INDEX


class StepRecorder:
    """
    Context-manager style recorder. Call start() then stop() around each action.
    Or use as a context manager:
        with StepRecorder("step_01_click_foo"):
            runner.execute_single_action(action)
    """

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._gif_path: Path | None = None

    def start(self, step_name: str, output_dir: Path | None = None, raw: bool = False) -> None:
        """Begin recording screen.

        raw=False: encode directly to GIF (single-step use).
        raw=True:  capture to .mov clip for later combining.
        """
        if self._proc is not None:
            raise RuntimeError("Recorder already running — call stop() first")

        out = Path(output_dir) if output_dir is not None else _output_dir
        out.mkdir(parents=True, exist_ok=True)

        if raw:
            self._gif_path = out / f"{step_name}.mov"
            cmd = [
                "ffmpeg", "-y",
                "-f", "avfoundation",
                "-capture_cursor", "1",
                "-framerate", str(FPS),
                "-i", f"{_screen_index()}:none",
                "-vf", f"fps={FPS},scale={WIDTH}:-1:flags=lanczos",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0",
                str(self._gif_path),
            ]
        else:
            self._gif_path = out / f"{step_name}.gif"
            vf = (
                f"fps={FPS},"
                f"scale={WIDTH}:-1:flags=lanczos,"
                "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
            )
            cmd = [
                "ffmpeg", "-y",
                "-f", "avfoundation",
                "-capture_cursor", "1",
                "-i", f"{_screen_index()}:none",
                "-vf", vf,
                "-loop", "0",
                str(self._gif_path),
            ]

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Brief pause so FFmpeg initialises before the action fires
        time.sleep(0.5)
        print(f"[recorder] Recording started → {self._gif_path.name}")

    def stop(self) -> Path:
        """
        Gracefully terminate FFmpeg and wait for the GIF to be written.
        Returns the Path to the finished GIF.
        """
        if self._proc is None:
            raise RuntimeError("Recorder is not running")

        # Send 'q' to FFmpeg stdin — the clean shutdown signal
        try:
            self._proc.stdin.write(b"q")
            self._proc.stdin.flush()
        except BrokenPipeError:
            pass

        try:
            self._proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            self._proc.send_signal(signal.SIGTERM)
            self._proc.wait(timeout=15)

        path = self._gif_path
        self._proc = None
        self._gif_path = None
        print(f"[recorder] GIF saved → {path}")
        return path

    # Context-manager support
    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self._proc is not None:
            self.stop()


# Module-level singleton for convenience
_recorder = StepRecorder()


def start(step_name: str, output_dir: Path | None = None, raw: bool = False) -> None:
    _recorder.start(step_name, output_dir=output_dir, raw=raw)


def stop() -> Path:
    return _recorder.stop()


def combine(clips: list[Path], output: Path) -> Path:
    """Concatenate .mov clip files and convert to a single GIF."""
    if not clips:
        raise ValueError("No clips to combine")

    list_file = output.parent / f"{output.stem}_concat.txt"
    with list_file.open("w") as f:
        for clip in clips:
            f.write(f"file '{clip.resolve()}'\n")

    vf = (
        f"fps={FPS},"
        f"scale={WIDTH}:-1:flags=lanczos,"
        "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
    )

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-vf", vf,
        "-loop", "0",
        str(output),
    ], check=True, capture_output=True)

    list_file.unlink(missing_ok=True)
    print(f"[recorder] Combined {len(clips)} clip(s) → {output}")
    return output
