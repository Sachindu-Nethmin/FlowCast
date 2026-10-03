"""Voice-cloned narration backend — drop-in replacement for macOS `say`.

FlowCast normally narrates with `say`. Point these two environment variables at
a voice sample and every narration line is instead synthesized by Chatterbox in
that voice, with the rest of the pipeline (sentence placement, per-action clip
padding, concat) unchanged:

    FLOWCAST_TTS=chatterbox
    FLOWCAST_VOICE_REF=/path/to/reference.wav

The model lives in a separate `.venv-voice` environment (torch is heavy and the
project venv stays light), driven as a long-lived subprocess so the weights load
once per run instead of once per sentence — see tools/voice_clone_server.py.
Synthesized lines are cached on disk, so re-running a narration only pays for
lines whose text actually changed.

Tunables (all optional):
    FLOWCAST_VOICE_PYTHON        python that has chatterbox-tts   [.venv-voice/bin/python]
    FLOWCAST_VOICE_DEVICE        mps | cuda | cpu                 [auto]
    FLOWCAST_VOICE_EXAGGERATION  0.0-1.0, emotional intensity     [0.4]
    FLOWCAST_VOICE_CFG           0.0-1.0, lower = slower pacing   [0.5]
    FLOWCAST_VOICE_CACHE         cache dir                        [output/.voice_cache]
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# One server per process — loading the model costs ~20s, so it is worth keeping.
_proc: subprocess.Popen | None = None
_ref_used: str | None = None


# ── configuration ────────────────────────────────────────────────────────────

def is_enabled() -> bool:
    """True when narration should use the cloned voice instead of `say`."""
    return os.environ.get("FLOWCAST_TTS", "say").strip().lower() == "chatterbox"


def reference_wav() -> Path:
    """The voice sample to clone. Raises if unset or missing."""
    ref = os.environ.get("FLOWCAST_VOICE_REF", "").strip()
    if not ref:
        raise RuntimeError(
            "FLOWCAST_TTS=chatterbox needs FLOWCAST_VOICE_REF=<reference.wav> "
            "(7-20s of clean single-speaker speech)")
    path = Path(ref).expanduser()
    if not path.exists():
        raise RuntimeError(f"voice reference not found: {path}")
    return path


def _python() -> Path:
    """Interpreter that has chatterbox-tts installed."""
    override = os.environ.get("FLOWCAST_VOICE_PYTHON", "").strip()
    py = Path(override).expanduser() if override else _ROOT / ".venv-voice" / "bin" / "python"
    if not py.exists():
        raise RuntimeError(
            f"no voice-clone interpreter at {py}\n"
            f"Create it with:  uv venv --python 3.11 .venv-voice && "
            f"VIRTUAL_ENV=$PWD/.venv-voice uv pip install chatterbox-tts")
    return py


def _cache_dir() -> Path:
    d = Path(os.environ.get("FLOWCAST_VOICE_CACHE", str(_ROOT / "output" / ".voice_cache")))
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── server lifecycle ─────────────────────────────────────────────────────────

def _read_reply(proc: subprocess.Popen, phase: str) -> dict:
    """Next protocol line from the server, skipping any stray output."""
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError(f"voice-clone server died during {phase} (see log above)")
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            print(f"[narrate] {line}", file=sys.stderr)   # library chatter


def _start() -> subprocess.Popen:
    """Spawn the model server and block until it reports ready."""
    global _proc, _ref_used
    ref = str(reference_wav())
    if _proc is not None and _proc.poll() is None and _ref_used == ref:
        return _proc
    shutdown()

    server = _ROOT / "tools" / "voice_clone_server.py"
    proc = subprocess.Popen(
        [str(_python()), str(server), ref],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
        text=True, bufsize=1, cwd=str(_ROOT))

    msg = _read_reply(proc, "start-up")
    if not msg.get("ok"):
        raise RuntimeError(f"voice-clone server failed to start: {msg.get('error')}")

    print(f"[narrate] cloned voice ready on {msg.get('device')} "
          f"({Path(ref).name}, {msg.get('sr')}Hz)", file=sys.stderr)
    _proc, _ref_used = proc, ref
    atexit.register(shutdown)
    return proc


def shutdown() -> None:
    """Stop the model server if one is running."""
    global _proc, _ref_used
    if _proc is None:
        return
    try:
        if _proc.poll() is None:
            _proc.stdin.write(json.dumps({"quit": True}) + "\n")
            _proc.stdin.flush()
            _proc.wait(timeout=10)
    except Exception:
        _proc.kill()
    finally:
        _proc, _ref_used = None, None


# ── synthesis ────────────────────────────────────────────────────────────────

def median_f0(path: Path, fmin: float = 60, fmax: float = 400) -> tuple[float, int]:
    """Median fundamental frequency over voiced frames, by autocorrelation.

    Used to hold every line at one pitch: Chatterbox reproduces a reference
    voice well on short lines and drifts upward on longer ones, and within a
    single video that wobble is what makes a voice stop sounding like one
    person.
    """
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path),
                          "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    sr, win, hop = 16000, 1024, 256
    lo, hi = int(sr / fmax), int(sr / fmin)
    picks = []
    for i in range(0, max(len(x) - win, 0), hop):
        f = x[i:i + win]
        if np.sqrt((f ** 2).mean()) < 0.02:
            continue
        f = f - f.mean()
        ac = np.correlate(f, f, "full")[win - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        if not len(seg):
            continue
        peak = int(np.argmax(seg)) + lo
        if ac[peak] / ac[0] < 0.3:
            continue
        picks.append(sr / peak)
    return (float(np.median(picks)), len(picks)) if picks else (float("nan"), 0)


def _ltas(path: Path, sr: int = 16000, n: int = 512):
    """Long-term average spectrum, normalised — a coarse fingerprint of vocal
    timbre. Two takes of the same speaker score alike; a take that has drifted
    toward a different voice scores lower against the reference."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1",
                          "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if len(x) < n:
        return None
    w = np.hanning(n)
    acc = np.zeros(n // 2 + 1)
    cnt = 0
    for i in range(0, len(x) - n, n // 2):
        f = x[i:i + n]
        if np.sqrt((f ** 2).mean()) < 0.02:
            continue
        acc += np.abs(np.fft.rfft(f * w))
        cnt += 1
    if not cnt:
        return None
    spec = np.log(acc / cnt + 1e-8)
    return (spec - spec.mean()) / (spec.std() + 1e-8)


def timbre_similarity(path: Path, ref_spec=None) -> float:
    """How much `path` sounds like the reference speaker. 1.0 is identical."""
    import numpy as np
    ref = ref_spec if ref_spec is not None else _ltas(reference_wav())
    got = _ltas(path)
    if ref is None or got is None:
        return float("nan")
    return float(np.dot(ref, got) / len(ref))


def pitch_shift(src: Path, dst: Path, ratio: float) -> None:
    """Move pitch without touching tempo, so narration timing is unaffected."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                    "-af", f"rubberband=pitch={ratio:.5f}", str(dst)], check=True)


def pitch_target() -> float | None:
    """FLOWCAST_VOICE_PITCH_HZ: a number, or 'reference' to use the sample's
    own pitch. Unset means leave every line exactly as the model produced it."""
    want = os.environ.get("FLOWCAST_VOICE_PITCH_HZ", "").strip().lower()
    if not want:
        return None
    if want in ("ref", "reference"):
        hz, frames = median_f0(reference_wav())
        return hz if frames >= 8 else None
    try:
        return float(want)
    except ValueError:
        print(f"[voice-clone] ignoring FLOWCAST_VOICE_PITCH_HZ={want!r}", file=sys.stderr)
        return None


MAX_PITCH_SHIFT = 0.25   # beyond this rubberband sounds artificial


def _match_pitch(path: Path, target: float) -> None:
    """Shift `path` onto `target` Hz in place, when the move is modest enough
    to stay natural. A clip needing more than MAX_PITCH_SHIFT is left alone —
    that usually means the measurement failed, not that the voice moved."""
    f0, frames = median_f0(path)
    if frames < 8 or not (f0 == f0):        # NaN guard
        return
    ratio = target / f0
    if abs(ratio - 1) > MAX_PITCH_SHIFT:
        print(f"[voice-clone] pitch {f0:.0f}Hz → {target:.0f}Hz skipped (too far)",
              file=sys.stderr)
        return
    tmp = path.with_suffix(".pitch.wav")
    pitch_shift(path, tmp, ratio)
    tmp.replace(path)


def _to_narration_wav(src: Path, dst: Path) -> None:
    """Convert the model's mono output to the 44.1k stereo the dubber expects,
    trimming the leading/trailing silence Chatterbox tends to add."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src),
         "-af", "silenceremove=start_periods=1:start_silence=0.05:start_threshold=-50dB:"
                "detection=peak,areverse,"
                "silenceremove=start_periods=1:start_silence=0.10:start_threshold=-50dB:"
                "detection=peak,areverse,"
                "loudnorm=I=-18:TP=-1.5:LRA=11",
         "-ar", "44100", "-ac", "2", str(dst)],
        capture_output=True, check=True)


def _key(text: str) -> str:
    """Cache key covering everything that changes the audio.

    The pitch target belongs here: it changes the rendering, so leaving it out
    would silently replay a clip made at the old target after you change it.
    """
    parts = [
        text.strip(),
        str(reference_wav()),
        str(reference_wav().stat().st_mtime_ns),
        os.environ.get("FLOWCAST_VOICE_EXAGGERATION", "0.4"),
        os.environ.get("FLOWCAST_VOICE_CFG", "0.5"),
        os.environ.get("FLOWCAST_VOICE_PITCH_HZ", ""),
        os.environ.get("FLOWCAST_VOICE_TAKES", "1"),
    ]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:20]


def synthesize(text: str, out_wav: Path) -> float:
    """Speak `text` in the cloned voice into `out_wav` (44.1k stereo).

    Returns the clip's duration in seconds, matching narrate._say_to_wav so the
    two backends are interchangeable."""
    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    cached = _cache_dir() / f"{_key(text)}.wav"
    if cached.exists():
        shutil.copyfile(cached, out_wav)
        return _duration(out_wav)

    proc = _start()
    raw = out_wav.with_name(out_wav.stem + ".raw.wav")
    req = {
        "text": text,
        "out": str(raw),
        "exaggeration": float(os.environ.get("FLOWCAST_VOICE_EXAGGERATION", "0.4")),
        "cfg_weight": float(os.environ.get("FLOWCAST_VOICE_CFG", "0.5")),
    }

    # The model is stochastic, and a short line gives it little context to hold
    # a speaker's identity — which is exactly where takes wander off and start
    # sounding like someone else. Sampling a few and keeping the one closest to
    # the reference costs time, not quality.
    takes = max(1, int(os.environ.get("FLOWCAST_VOICE_TAKES", "1")))
    target = pitch_target()
    ref_spec = _ltas(reference_wav()) if takes > 1 else None
    best: Path | None = None
    best_score = -1e9

    try:
        for n in range(takes):
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            msg = _read_reply(proc, "synthesis")
            if not msg.get("ok"):
                raise RuntimeError(f"voice-clone synthesis failed: {msg.get('error')}")

            candidate = out_wav if takes == 1 else out_wav.with_name(
                f"{out_wav.stem}.take{n}.wav")
            _to_narration_wav(raw, candidate)
            if target:
                _match_pitch(candidate, target)
            if takes == 1:
                best = candidate
                break
            score = timbre_similarity(candidate, ref_spec)
            if score > best_score:
                if best is not None and best != out_wav:
                    best.unlink(missing_ok=True)
                best, best_score = candidate, score
            else:
                candidate.unlink(missing_ok=True)

        if best is not None and best != out_wav:
            best.replace(out_wav)
            print(f"[voice-clone] best of {takes}: similarity {best_score:.2f}",
                  file=sys.stderr)
        shutil.copyfile(out_wav, cached)
    finally:
        raw.unlink(missing_ok=True)
    return _duration(out_wav)


def _duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True, text=True)
    return float(r.stdout.strip() or 0.0)
