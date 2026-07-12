"""Voice input for FlowCast guide mode — push-to-talk (right arrow) commands.

Hold the RIGHT ARROW key to record a spoken command, release it to send.
The clip is transcribed fully ON-DEVICE via macOS's built-in Speech
framework (the same on-device engine behind Siri dictation) — no API key,
no network call, no model download. The resulting text is handed to the
exact same pipeline as typed "what next>" input (src/nl_commands.parse_command),
so --voice produces the identical workflow.md / GIFs / full_script.py as
typed guide mode — only how the command text is captured changes.

Setup (only needed for --voice):
    uv sync --extra voice          # installs pyobjc-framework-Speech + pynput

macOS permissions (grant once, to your terminal app — System Settings →
Privacy & Security):
    Speech Recognition — for on-device transcription (prompted automatically
                          on first use; must be granted to your terminal app)
    Microphone         — to record the spoken command
    Input Monitoring   — for pynput to see the right-arrow key globally
    (Accessibility is already required for the rest of FlowCast via pyautogui)

Recognition is forced on-device (requiresOnDeviceRecognition=True) so audio
never leaves the machine — if the current locale doesn't support on-device
recognition, transcribe() raises rather than silently falling back to
Apple's cloud dictation.

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
_SILENCE_DBFS_THRESHOLD = -50.0  # quieter than this = "nothing was actually recorded"

_audio_proc: subprocess.Popen | None = None
_audio_path: Path | None = None
_audio_stderr_tmp = None
_audio_idx: str | None = None
_audio_devices_cache: list[tuple[str, str]] | None = None


# ── Microphone device discovery (mirrors src/recorder._get_screen_index) ────

def list_audio_devices() -> list[tuple[str, str]]:
    """Return [(index, name), ...] for every AVFoundation audio input device.
    Run `python -c "from src.voice import list_audio_devices as l; print(l())"`
    (or just `ffmpeg -f avfoundation -list_devices true -i ""` yourself) if
    --voice keeps picking the wrong mic."""
    global _audio_devices_cache
    if _audio_devices_cache is not None:
        return _audio_devices_cache
    devices: list[tuple[str, str]] = []
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
            if "video devices" in line.lower():
                in_audio_section = False
                continue
            if in_audio_section:
                m = re.search(r'\[(\d+)\]\s*(.+)$', line)
                if m:
                    devices.append((m.group(1), m.group(2).strip()))
    except Exception:
        pass
    _audio_devices_cache = devices
    return devices


# Devices whose names suggest a real hardware mic vs. a virtual/conferencing
# passthrough device with no actual signal (Zoom, Teams, etc. install these
# and macOS often lists them BEFORE the real microphone).
_PREFERRED_NAME_HINTS = ("microphone", "built-in", "internal")
_DEPRIORITIZED_NAME_HINTS = (
    "zoom", "teams", "meet", "webex", "loopback", "blackhole",
    "soundflower", "ishowu", "obs", "virtual", "aggregate",
)


def _pick_best_device(devices: list[tuple[str, str]]) -> tuple[str, str] | None:
    if not devices:
        return None
    for idx, name in devices:
        if any(h in name.lower() for h in _PREFERRED_NAME_HINTS):
            return idx, name
    non_virtual = [(i, n) for i, n in devices
                   if not any(h in n.lower() for h in _DEPRIORITIZED_NAME_HINTS)]
    return non_virtual[0] if non_virtual else devices[0]


def _get_audio_index() -> tuple[str, str]:
    """Return (index, name). Honors FLOWCAST_AUDIO_DEVICE=<index> to override
    auto-detection — set this if the wrong mic keeps getting picked.

    Auto-detection prefers a device whose name looks like a real hardware
    microphone over conferencing-app virtual devices (Zoom, Teams, ...),
    which macOS often lists first even though they carry no real signal."""
    global _audio_idx
    override = os.environ.get("FLOWCAST_AUDIO_DEVICE")
    if override:
        name = next((n for i, n in list_audio_devices() if i == override), "(unknown)")
        return override, name
    if _audio_idx is not None:
        name = next((n for i, n in list_audio_devices() if i == _audio_idx), "(unknown)")
        return _audio_idx, name
    best = _pick_best_device(list_audio_devices())
    if best:
        _audio_idx = best[0]
        return best
    _audio_idx = "0"  # fall back to the default input device
    return "0", "(unknown — device list detection failed)"


# ── Audio-only recording (separate from src/recorder.py's screen recorder —
#    they never run at the same time: a voice command is captured BEFORE the
#    resolved action starts screen recording, so there's no device conflict) ──

def _start_recording() -> Path:
    global _audio_proc, _audio_path, _audio_stderr_tmp
    if _audio_proc is not None:
        raise RuntimeError("Audio recorder already running")

    idx, name = _get_audio_index()
    print(f"     using mic [{idx}] {name}"
          + ("" if not os.environ.get("FLOWCAST_AUDIO_DEVICE") else " (FLOWCAST_AUDIO_DEVICE override)"))
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


def _peak_dbfs(path: Path) -> float | None:
    """Peak volume of the clip in dBFS via ffmpeg's volumedetect filter.
    Returns None if it couldn't be measured. Used to catch the common
    'ffmpeg opened a device but captured silence' case (wrong device, or
    the OS didn't actually grant mic access) BEFORE handing it to the
    Speech framework, which otherwise just reports an opaque
    'No speech detected' for silent audio."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=10,
        )
        m = re.search(r'max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB', result.stderr)
        return float(m.group(1)) if m else None
    except Exception:
        return None


# ── Transcription (macOS Speech framework — fully on-device) ────────────────

_RECOGNITION_LOCALE = "en-US"
_AUTH_TIMEOUT = 15.0
_TRANSCRIBE_TIMEOUT = 30.0

_speech_authorized = False


def _import_speech():
    try:
        from Speech import SFSpeechRecognizer, SFSpeechURLRecognitionRequest
        from Foundation import NSURL, NSLocale, NSRunLoop, NSDate
    except ImportError as e:
        raise RuntimeError(
            "The 'pyobjc-framework-Speech' package is required for --voice. "
            "Install with: uv sync --extra voice  (or: pip install pyobjc-framework-Speech)"
        ) from e
    return SFSpeechRecognizer, SFSpeechURLRecognitionRequest, NSURL, NSLocale, NSRunLoop, NSDate


def _pump_run_loop_until(done: threading.Event, timeout: float) -> None:
    """Drive the current thread's run loop in short bursts while waiting for
    an async Speech-framework callback, with a hard timeout so a permission
    dialog the user ignores (or a locale quirk) can't hang the CLI forever."""
    _, _, _, _, NSRunLoop, NSDate = _import_speech()
    deadline = time.time() + timeout
    while not done.is_set() and time.time() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))


def _ensure_speech_authorized() -> None:
    global _speech_authorized
    if _speech_authorized:
        return
    SFSpeechRecognizer, *_ = _import_speech()

    done = threading.Event()
    status_holder = {"status": None}

    def handler(status):
        status_holder["status"] = status
        done.set()

    SFSpeechRecognizer.requestAuthorization_(handler)
    _pump_run_loop_until(done, _AUTH_TIMEOUT)

    # SFSpeechRecognizerAuthorizationStatus: 0 notDetermined, 1 denied, 2 restricted, 3 authorized
    if status_holder["status"] != 3:
        raise RuntimeError(
            "Speech Recognition permission was not granted (or the request timed out). "
            "Enable it for your terminal app in System Settings → Privacy & Security → "
            "Speech Recognition, then try again."
        )
    _speech_authorized = True


def transcribe(path: Path) -> str:
    """Transcribe a WAV file fully on-device via macOS's Speech framework."""
    (SFSpeechRecognizer, SFSpeechURLRecognitionRequest,
     NSURL, NSLocale, NSRunLoop, NSDate) = _import_speech()

    _ensure_speech_authorized()

    locale = NSLocale.localeWithLocaleIdentifier_(_RECOGNITION_LOCALE)
    recognizer = SFSpeechRecognizer.alloc().initWithLocale_(locale)
    if recognizer is None or not recognizer.isAvailable():
        raise RuntimeError(
            f"macOS speech recognizer unavailable for locale '{_RECOGNITION_LOCALE}'."
        )
    if not recognizer.supportsOnDeviceRecognition():
        raise RuntimeError(
            f"On-device speech recognition isn't available for locale "
            f"'{_RECOGNITION_LOCALE}' on this Mac. --voice requires on-device "
            f"recognition (audio never leaves the machine), so it's disabled here "
            f"rather than silently using Apple's cloud dictation."
        )

    url = NSURL.fileURLWithPath_(str(path))
    request = SFSpeechURLRecognitionRequest.alloc().initWithURL_(url)
    request.setRequiresOnDeviceRecognition_(True)
    request.setShouldReportPartialResults_(False)

    done = threading.Event()
    result_holder = {"text": "", "error": None}

    def handler(result, error):
        if error is not None:
            result_holder["error"] = str(error)
            done.set()
            return
        if result is not None and result.isFinal():
            result_holder["text"] = str(result.bestTranscription().formattedString())
            done.set()

    recognizer.recognitionTaskWithRequest_resultHandler_(request, handler)
    _pump_run_loop_until(done, _TRANSCRIBE_TIMEOUT)

    if not done.is_set():
        raise RuntimeError("Speech recognition timed out")
    if result_holder["error"]:
        raise RuntimeError(f"Speech recognition failed: {result_holder['error']}")
    return result_holder["text"].strip()


# Spoken words that stand in for symbol targets the UI actually uses — e.g.
# the on-canvas "+" connector button. You can't say a symbol, so map the
# word to it here before the command ever reaches parse_command(). Word
# boundaries only, case-insensitive, so this never touches a word that
# merely contains one of these as a substring.
_SYMBOL_WORDS = {
    "plus": "+",
}


def _substitute_symbol_words(text: str) -> str:
    for word, symbol in _SYMBOL_WORDS.items():
        text = re.sub(rf'\b{word}\b', symbol, text, flags=re.IGNORECASE)
    return text


def _clean_transcript(text: str) -> str:
    """Strip the trailing sentence punctuation Whisper likes to add
    ("Click Create." -> "Click Create") since it would otherwise get parsed
    as part of the click target / field value, and swap spoken symbol names
    ("plus" -> "+") so voice commands resolve the same as typed ones."""
    text = re.sub(r'[.!?]+$', '', text.strip()).strip()
    return _substitute_symbol_words(text)


def _flush_stdin() -> None:
    """Best-effort: discard anything sitting in the tty's input buffer right
    before a fallback input() call, so a just-pressed Esc can't bleed into it."""
    try:
        import sys
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass


def _suppress_tty_echo():
    """Turn off terminal echo for the duration of the push-to-talk listener.

    Holding the right arrow triggers OS key-repeat, and the terminal (not
    our Python process) echoes every one of those raw keystrokes to the
    screen as "^[[C^[[C^[[C..." — pure visual noise, and it also queues
    those bytes in the tty's input buffer where a later input() call could
    pick them up. Returns a zero-arg restore() callback; a no-op if stdin
    isn't a real tty (e.g. piped input) or on non-POSIX platforms.
    """
    try:
        import sys
        import termios
        if not sys.stdin.isatty():
            return lambda: None
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[3] = new[3] & ~termios.ECHO  # lflags: echo off, leave canonical mode alone
        termios.tcsetattr(fd, termios.TCSADRAIN, new)

        def restore():
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                pass

        return restore
    except Exception:
        return lambda: None


# ── Push-to-talk ──────────────────────────────────────────────────────────────

class _PTTResult:
    def __init__(self) -> None:
        self.clip: Path | None = None
        self.mode: str = ""  # "voice" | "typed"


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
            # Just stop the recording here — transcription (Speech framework
            # + its own run-loop pumping) happens on the MAIN thread below,
            # after the listener is fully torn down, rather than inside this
            # background listener-thread callback.
            result.clip = _stop_recording()
            result.mode = "voice"
            done.set()
            return False

    restore_echo = _suppress_tty_echo()
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    try:
        listener.start()
        done.wait()
        listener.stop()
        listener.join()
    finally:
        restore_echo()
        _flush_stdin()  # discard any key-repeat bytes that queued up while echo was off

    if result.mode == "typed":
        return input("   (typed) what next> ").strip()

    text = ""
    if result.clip:
        peak = _peak_dbfs(result.clip)
        if peak is not None and peak < _SILENCE_DBFS_THRESHOLD:
            print(f"   ⚠️  recorded clip is silent (peak {peak:.0f} dBFS) — not sending to "
                  f"the transcriber. This usually means either:")
            print(f"       • Microphone permission isn't granted to your terminal app "
                  f"(System Settings → Privacy & Security → Microphone), or")
            print(f"       • The wrong input device was picked — run "
                  f"`ffmpeg -f avfoundation -list_devices true -i \"\"` to see all mics, "
                  f"then set FLOWCAST_AUDIO_DEVICE=<index> and retry.")
        else:
            print("   ⏳ transcribing…")
            try:
                text = transcribe(result.clip)
            except Exception as e:
                print(f"   ✗ transcription failed: {e}")
        result.clip.unlink(missing_ok=True)
        try:
            result.clip.parent.rmdir()
        except OSError:
            pass

    heard = _clean_transcript(text)
    print(f'   📝 heard: "{heard}"' if heard else
          "   (heard nothing — hold → a little longer, or Esc to type)")
    return heard
