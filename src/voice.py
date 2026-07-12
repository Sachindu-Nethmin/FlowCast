"""Voice input for FlowCast guide mode — push-to-talk (right arrow) commands.

Hold the RIGHT ARROW key to record a spoken command, release it to send.
The clip is transcribed via the Groq Whisper API and the resulting text is
handed to the exact same pipeline as typed "what next>" input
(src/nl_commands.parse_command), so --voice produces the identical
workflow.md / GIFs / full_script.py as typed guide mode — only how the
command text is captured changes.

Setup (only needed for --voice):
    uv sync --extra voice          # installs groq + pynput
    Add GROQ_API_KEY to .env       # free key: https://console.groq.com/keys

macOS permissions (grant once, to your terminal app — System Settings →
Privacy & Security):
    Microphone        — to record the spoken command
    Input Monitoring  — for pynput to see the right-arrow key globally
    (Accessibility is already required for the rest of FlowCast via pyautogui)

Voice is great for click / select / navigate commands ("click Create",
"search for Println", "select FTP"). It's a poor fit for exact typed values
(hostnames, ports, JSON, slugs like "sales-data-sync") since dictation
rarely comes back verbatim — press Esc at the prompt to type those instead.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path

AUDIO_RATE = 16000
_RECORD_STARTUP_DELAY = 0.35  # let ffmpeg actually open the mic before we talk

_audio_proc: subprocess.Popen | None = None
_audio_path: Path | None = None
_audio_stderr_tmp = None
_audio_idx: str | None = None


# ── Microphone device discovery (mirrors src/recorder._get_screen_index) ────

def _get_audio_index() -> str:
    global _audio_idx
    if _audio_idx is not None:
        return _audio_idx
    try:
        result = subprocess.run(
            ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=5,
        )
        in_audio_section = False
        for line in result.stderr.splitlines():
            if "audio devices" in line.lower():
                in_audio_section = True
                continue
            if in_audio_section:
                m = re.search(r'\[(\d+)\]', line)
                if m:
                    _audio_idx = m.group(1)
                    return _audio_idx
    except Exception:
        pass
    _audio_idx = "0"  # fall back to the default input device
    return _audio_idx


# ── Audio-only recording (separate from src/recorder.py's screen recorder —
#    they never run at the same time: a voice command is captured BEFORE the
#    resolved action starts screen recording, so there's no device conflict) ──

def _start_recording() -> Path:
    global _audio_proc, _audio_path, _audio_stderr_tmp
    if _audio_proc is not None:
        raise RuntimeError("Audio recorder already running")

    idx = _get_audio_index()
    tmp_dir = Path(tempfile.mkdtemp(prefix="voice_"))
    _audio_path = tmp_dir / "command.wav"

    cmd = [
        "ffmpeg", "-y",
        "-f", "avfoundation",
        "-i", f":{idx}",
        "-ar", str(AUDIO_RATE), "-ac", "1",
        str(_audio_path),
    ]
    _audio_stderr_tmp = tempfile.TemporaryFile()
    _audio_proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=_audio_stderr_tmp,
    )
    time.sleep(_RECORD_STARTUP_DELAY)
    if _audio_proc.poll() is not None:
        _audio_stderr_tmp.seek(0)
        err = _audio_stderr_tmp.read().decode(errors="replace")
        _audio_proc = None
        _audio_path = None
        raise RuntimeError(
            f"Could not open microphone (device index {idx}):\n{err}\n"
            f"Check System Settings → Privacy & Security → Microphone for your terminal app."
        )
    return _audio_path


def _stop_recording() -> Path | None:
    global _audio_proc, _audio_path, _audio_stderr_tmp
    if _audio_proc is None:
        return None
    try:
        _audio_proc.stdin.write(b"q")
        _audio_proc.stdin.flush()
    except (BrokenPipeError, OSError):
        pass
    try:
        _audio_proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _audio_proc.terminate()
        try:
            _audio_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _audio_proc.kill()
            _audio_proc.wait()

    if _audio_stderr_tmp is not None:
        _audio_stderr_tmp.close()
    path, _audio_proc, _audio_path, _audio_stderr_tmp = _audio_path, None, None, None

    if path and path.exists() and path.stat().st_size > 44:  # > bare WAV header
        return path
    return None


# ── Transcription (Groq Whisper API) ─────────────────────────────────────────

_groq_client = None


def _client():
    global _groq_client
    if _groq_client is None:
        try:
            from groq import Groq
        except ImportError as e:
            raise RuntimeError(
                "The 'groq' package is required for --voice. "
                "Install with: uv sync --extra voice  (or: pip install groq)"
            ) from e
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key or api_key == "your_groq_api_key_here":
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to .env to use --voice "
                "(free key: https://console.groq.com/keys)"
            )
        _groq_client = Groq(api_key=api_key)
    return _groq_client


def transcribe(path: Path) -> str:
    with path.open("rb") as f:
        result = _client().audio.transcriptions.create(
            file=(path.name, f.read()),
            model="whisper-large-v3-turbo",
            language="en",
            temperature=0.0,
        )
    return (result.text or "").strip()


def _clean_transcript(text: str) -> str:
    """Strip the trailing sentence punctuation Whisper likes to add
    ("Click Create." -> "Click Create") since it would otherwise get parsed
    as part of the click target / field value."""
    return re.sub(r'[.!?]+$', '', text.strip()).strip()


def _flush_stdin() -> None:
    """Best-effort: discard anything sitting in the tty's input buffer right
    before a fallback input() call, so a just-pressed Esc can't bleed into it."""
    try:
        import sys
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass


# ── Push-to-talk ──────────────────────────────────────────────────────────────

class _PTTResult:
    def __init__(self) -> None:
        self.text: str = ""
        self.mode: str = ""  # "voice" | "typed" | "cancelled"


def push_to_talk(prompt: str) -> str:
    """Block until the user holds+releases the right arrow (records + transcribes
    a command) or presses Esc (falls back to a typed line). Always returns a
    string — possibly empty if nothing was understood."""
    try:
        from pynput import keyboard
    except ImportError as e:
        raise RuntimeError(
            "The 'pynput' package is required for --voice. "
            "Install with: uv sync --extra voice  (or: pip install pynput)"
        ) from e

    result = _PTTResult()
    done = threading.Event()
    recording = threading.Event()

    print(f"\n{prompt}  🎙  hold → to talk (release to send) · Esc to type instead")

    def on_press(key):
        if key == keyboard.Key.right and not recording.is_set():
            recording.set()
            print("   ● recording… (release → to send)")
            try:
                _start_recording()
            except Exception as e:
                print(f"   ✗ {e}")
                result.mode = "typed"
                done.set()
                return False
        elif key == keyboard.Key.esc and not recording.is_set():
            result.mode = "typed"
            done.set()
            return False

    def on_release(key):
        if key == keyboard.Key.right and recording.is_set():
            print("   ⏳ transcribing…")
            clip = _stop_recording()
            text = ""
            if clip:
                try:
                    text = transcribe(clip)
                except Exception as e:
                    print(f"   ✗ transcription failed: {e}")
                finally:
                    clip.unlink(missing_ok=True)
                    try:
                        clip.parent.rmdir()
                    except OSError:
                        pass
            result.text = text
            result.mode = "voice"
            done.set()
            return False

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    done.wait()
    listener.stop()
    listener.join()

    if result.mode == "typed":
        _flush_stdin()
        return input("   (typed) what next> ").strip()

    heard = _clean_transcript(result.text)
    print(f'   📝 heard: "{heard}"' if heard else
          "   (heard nothing — hold → a little longer, or Esc to type)")
    return heard
