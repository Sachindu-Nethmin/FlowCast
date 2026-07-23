"""Natural AI voiceover core for FlowCast — shared by `main.py --narrate` and
`tools/dub_natural.py`.

Narrates the silent step recordings with macOS's built-in `say` using an
ENHANCED / PREMIUM neural voice (free, offline, commercial-safe). Unlike
src/dub.py — which reads the raw click instructions aloud — this reads a
conversational, YouTube-tutorial-style script:

  1. If a narration.txt (blocks keyed by [step N]) sits next to the
     recordings, that hand-written script is used verbatim.
  2. Otherwise a natural script is auto-generated from the workflow steps and
     written to narration.txt as an editable starting point.

Default voice is a young male Enhanced voice (Evan), overridable via the
FLOWCAST_DUB_VOICE env var or an explicit argument.
"""
from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Voice selection ──────────────────────────────────────────────────────────
# Young male English voices first (Enhanced/Premium sound natural; the plain
# names are always-installed compact fallbacks), then a couple of neutral ones.
DEFAULT_VOICE_PREFERENCE = [
    "Evan (Enhanced)", "Aaron (Enhanced)", "Nathan (Enhanced)",
    "Tom (Enhanced)", "Reed (Enhanced)", "Daniel (Enhanced)", "Oliver (Enhanced)",
    "Alex", "Tom", "Aaron", "Daniel", "Fred",          # compact male fallbacks
    "Ava (Premium)", "Samantha (Enhanced)", "Samantha",  # last-resort any-voice
]


def list_installed_voices() -> list[str]:
    """Full name of every voice `say` can use (may contain a parenthetical
    such as 'Evan (Enhanced)')."""
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True)
    voices: list[str] = []
    for line in out.stdout.splitlines():
        # "<name...>  <locale>  # sample" — name may contain spaces/parens, so
        # anchor on the locale token (xx_XX) and take everything before it.
        m = re.match(r"^(.*?)\s+([a-z]{2}[_-][A-Z]{2})(?:\s|$)", line)
        if m:
            voices.append(m.group(1).strip())
    return voices


def pick_voice(override: str | None = None,
               installed: list[str] | None = None) -> str:
    """Resolve the voice to use: explicit override → FLOWCAST_DUB_VOICE env →
    first installed voice from DEFAULT_VOICE_PREFERENCE → any installed voice."""
    override = override or os.environ.get("FLOWCAST_DUB_VOICE")
    if override:
        return override
    installed = installed if installed is not None else list_installed_voices()
    lookup = {v.lower(): v for v in installed}
    for pref in DEFAULT_VOICE_PREFERENCE:
        if pref.lower() in lookup:
            return lookup[pref.lower()]
    return installed[0] if installed else "Alex"


# ── Narration source ─────────────────────────────────────────────────────────

def _parse_cues(lines: list[str]) -> list[tuple]:
    """Turn a block's raw lines into (pinned_time | None, text) cues. A line may
    start with '@<seconds>' to PIN the following text to an exact time in the
    step clip (perfect manual sync); unpinned text is auto-placed."""
    cues: list[tuple] = []
    cur_time = None
    cur: list[str] = []

    def push():
        if cur:
            txt = " ".join(" ".join(cur).split())
            if txt:
                cues.append((cur_time, txt))

    for line in lines:
        m = re.match(r"^\s*@(\d+(?:\.\d+)?)\s*(.*)$", line)
        if m:
            push()
            cur = []
            cur_time = float(m.group(1))
            if m.group(2).strip():
                cur.append(m.group(2).strip())
        else:
            cur.append(line.strip())
    push()
    return cues


def load_narration_file(rec_dir: Path) -> dict:
    """Parse narration.txt → {step_index | 'intro' | 'outro': value}.

    A step value is a plain string when it has no @time pins, or a list of
    (time | None, text) cues when at least one line is pinned with '@<seconds>'.
    intro/outro are always plain strings."""
    path = rec_dir / "narration.txt"
    if not path.exists():
        return {}
    blocks: dict = {}
    current = None
    buf: list[str] = []

    def flush():
        if current is None:
            return
        if current in ("intro", "outro"):
            text = " ".join(" ".join(buf).split())
            if text:
                blocks[current] = text
            return
        cues = _parse_cues(buf)
        if not cues:
            return
        if any(t is not None for t, _ in cues):
            blocks[current] = cues                       # pinned → keep structure
        else:
            blocks[current] = " ".join(t for _, t in cues)  # plain string

    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith("#"):
            continue
        m = re.match(r"^\s*\[\s*(intro|outro|step\s+\d+)\s*\]", raw, re.IGNORECASE)
        if m:
            flush()
            tag = m.group(1).lower()
            current = tag if tag in ("intro", "outro") else int(tag.split()[1])
            buf = []
        else:
            buf.append(raw.rstrip())
    flush()
    return blocks


# ── Exact per-action timings (captured at record time) ───────────────────────

def _clean_label(s: str) -> str:
    """Strip markdown/quotes/backticks so spoken text reads cleanly."""
    return re.sub(r"[*`\"]+", "", str(s or "")).strip()


def _action_sentence(act: dict) -> str:
    """A short, accurate sentence describing ONE recorded sub-step's action, so
    the voiceover is one sentence per sub-step, in lockstep with the screen."""
    kind = act.get("action", "")
    target = _clean_label(act.get("target"))
    field = _clean_label(act.get("field_target"))
    value = _clean_label(act.get("value"))
    if target == "+":
        target = "the plus button"
    if kind == "open_app":
        return f"Open {_clean_label(act.get('app_name')) or 'the app'}."
    if kind == "type":
        if field and value:
            return f"Set {field} to {value}."
        return f"Type {value}." if value else ""
    if kind == "search":
        return f"Search for {value}." if value else "Search."
    if kind == "select":
        return f"Select {target}." if target else (f"Select {value}." if value else "")
    if kind == "click":
        return f"Click {target}." if target else "Click to continue."
    if kind in ("wait", "hotkey", "scroll"):
        return ""                                  # nothing meaningful to narrate
    if target:
        return f"{kind.capitalize()} {target}."
    return ""


def save_action_timings(rec_dir: Path, mov_name: str, clip_paths: list,
                        actions: list | None = None) -> Path:
    """Record, for each recorded action segment, its exact start time (s) plus a
    short label describing the action — so narration can be generated and placed
    one sentence per action, perfectly in sync. Called by the recorder after
    combining a step's per-action clips. Clips are named clip_<idx>, so the
    label is pulled from actions[idx] when available."""
    entries: list[dict] = []
    t = 0.0
    for c in clip_paths:
        c = Path(c)
        label = ""
        if actions is not None:
            m = re.search(r"clip_(\d+)", c.stem)
            if m:
                idx = int(m.group(1))
                if 0 <= idx < len(actions):
                    label = _action_sentence(actions[idx])
        entries.append({"t": round(t, 3), "label": label})
        try:
            t += _probe_duration(c)
        except Exception:
            pass
    path = Path(rec_dir) / "timings.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = {}
    data[mov_name] = entries
    path.write_text(json.dumps(data, indent=2))
    return path


def load_action_timings(rec_dir: Path) -> dict:
    """Return {mov_name: [{'t': float, 'label': str}, ...]}. Older files that
    stored a bare list of floats are normalised to this shape."""
    path = Path(rec_dir) / "timings.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return {}
    out = {}
    for name, entries in raw.items():
        norm = []
        for e in entries:
            if isinstance(e, dict):
                norm.append({"t": float(e.get("t", 0.0)), "label": e.get("label", "")})
            else:
                norm.append({"t": float(e), "label": ""})
        out[name] = norm
    return out


ACTION_CLIP_DIR = "action_clips"


def save_action_clips(rec_dir: Path, mov_name: str, clip_paths: list,
                      actions: list | None = None) -> Path:
    """Keep a real, separate video clip for EACH action of a step (copied out of
    the recorder's temp dir) plus a label describing it. This is the most robust
    input for per-action narration: narrate dubs each clip individually and
    concatenates them, so voice and screen line up action by action with no
    splitting or guessing. Writes action_clips/ + action_clips.json."""
    dest = Path(rec_dir) / ACTION_CLIP_DIR
    dest.mkdir(parents=True, exist_ok=True)
    stem = Path(mov_name).stem
    entries = []
    for j, c in enumerate(clip_paths):
        c = Path(c)
        dst = dest / f"{stem}-a{j:02d}{c.suffix or '.mov'}"
        try:
            shutil.copy(c, dst)
        except Exception:
            continue
        label = ""
        m = re.search(r"clip_(\d+)", c.stem)
        if actions and m:
            i = int(m.group(1))
            if 0 <= i < len(actions):
                label = _action_sentence(actions[i])
        entries.append({"clip": dst.name, "label": label})
    path = Path(rec_dir) / "action_clips.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = {}
    data[mov_name] = entries
    path.write_text(json.dumps(data, indent=2))
    return path


def load_action_clips(rec_dir: Path) -> dict:
    """Return {mov_name: [{'clip': abs_path, 'label': str}, ...]} or {}."""
    path = Path(rec_dir) / "action_clips.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return {}
    base = Path(rec_dir) / ACTION_CLIP_DIR
    out = {}
    for name, entries in raw.items():
        rows = []
        for e in entries:
            clip = base / e.get("clip", "")
            if clip.exists():
                rows.append({"clip": clip, "label": e.get("label", "")})
        if rows:
            out[name] = rows
    return out


_OPENERS = {"first": "To begin, ", "mid": "Next, ", "last": "Finally, "}
_CONNECTORS = ["First,", "Then", "Next,", "After that,", "Then", "Finally,"]


def _lower_first(s: str) -> str:
    return s[0].lower() + s[1:] if s else s


def _auto_step_text(idx: int, step, total: int) -> str:
    """Turn a parsed Step into flowing, conversational narration."""
    from src.parser import instruction_lines
    pos = "first" if idx == 1 else ("last" if idx == total else "mid")
    intro = _OPENERS[pos] + f"let's {_lower_first(step.title)}."

    lines = [l.strip().rstrip(".") for l in instruction_lines(step.raw_instructions)
             if l.strip()]
    parts = [f"{_CONNECTORS[i % len(_CONNECTORS)]} {_lower_first(line)}"
             for i, line in enumerate(lines)]
    body = ". ".join(parts)
    return f"{intro} {body}." if body else intro


def build_auto_narration(clips: list, steps: list | None, timings: dict,
                         action_clips: dict | None = None, name: str = "") -> dict:
    """Auto-generate a script. Best case (saved per-action clips or recorded
    timings): each step becomes ONE line per action — sentence-by-sentence,
    action-by-action. Otherwise falls back to a per-step paragraph. Always adds
    a paused [intro] and [outro]."""
    action_clips = action_clips or {}
    nice = name.replace("-", " ").replace("_", " ").strip() or "this workflow"
    blocks: dict = {"intro": f"In this quick tutorial, we'll walk through {nice}, "
                             f"step by step. Let's get started."}
    total = len(clips)
    for pos, (n, mov) in enumerate(clips):
        rows = action_clips.get(mov.name)
        entries = timings.get(mov.name) if timings else None
        if rows:                                   # one line per SAVED action clip
            blocks[n] = [(None, r.get("label", "")) for r in rows]
        elif entries:                              # one @pinned line per recorded action
            cues = [(e["t"], e["label"]) for e in entries if e.get("label")]
            if cues:
                blocks[n] = cues
        elif steps and n <= len(steps):            # fallback: per-step paragraph
            blocks[n] = _auto_step_text(n, steps[n - 1], total)
    blocks["outro"] = "And that's it — you've completed the walkthrough. Thanks for watching."
    return blocks


def _write_narration_template(rec_dir: Path, blocks: dict,
                              steps: list | None) -> Path:
    path = rec_dir / "narration.txt"
    lines = [
        "# FlowCast natural narration (auto-generated — edit me!)",
        "# Blocks headed by [intro], [step N], [outro]. '#' lines are ignored.",
        "# [intro]/[outro] play over a frozen first/last frame (video paused).",
        "# Lines beginning '@<seconds>' are PINNED to that exact time in the step",
        "# clip — one per action, so voice and screen stay in lockstep. Rewrite",
        "# the words freely; keep the @time to preserve sync (or delete it to",
        "# let the line auto-place).",
        "",
    ]
    if blocks.get("intro"):
        lines += ["[intro]", blocks["intro"], ""]
    for i in sorted(k for k in blocks if isinstance(k, int)):
        title = f"  — {steps[i-1].title}" if steps and i <= len(steps) else ""
        lines.append(f"[step {i}]{title}")
        val = blocks[i]
        if isinstance(val, list):                 # one line per action
            for t, text in val:
                lines.append(f"@{t:.1f} {text}" if t is not None else text)
        else:
            lines.append(val)
        lines.append("")
    if blocks.get("outro"):
        lines += ["[outro]", blocks["outro"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ── ffmpeg synth / mux / concat ──────────────────────────────────────────────

# Canonical output spec. macOS screen recordings are variable-frame-rate and
# can use pixel formats QuickTime won't play once re-encoded/concatenated (the
# classic "black video" bug). We normalise every clip to CFR 30fps + yuv420p at
# a single resolution so tpad, muxing and concat all stay uniform and playable.
FPS = 30


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise RuntimeError(f"could not read duration of {path.name}: {r.stderr.strip()}")


def _probe_size(path: Path) -> tuple[int, int]:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split("x")
        return int(w), int(h)
    except ValueError:
        raise RuntimeError(f"could not read size of {path.name}: {r.stderr.strip()}")


def _norm_vf(w: int, h: int, extra: list[str] | None = None) -> str:
    """Video-filter chain that forces uniform size (letterboxed), square pixels,
    constant fps and yuv420p — applied to every clip so playback never blacks
    out. `extra` filters (e.g. tpad freezes) run first."""
    chain = list(extra or [])
    chain += [
        f"scale={w}:{h}:force_original_aspect_ratio=decrease",
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
        "setsar=1", f"fps={FPS}", "format=yuv420p",
    ]
    return ",".join(chain)


def _say_to_wav(text: str, out_wav: Path, voice: str, rate: int) -> float:
    """Synthesize one utterance to a 44.1k stereo WAV. Returns its duration."""
    tmp_aiff = out_wav.with_suffix(".aiff")
    r = subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(tmp_aiff), text],
                       capture_output=True, text=True)
    if r.returncode != 0 or not tmp_aiff.exists():
        raise RuntimeError(
            f"`say` failed for voice '{voice}': {r.stderr.strip()}\n"
            f"List valid names with: python tools/dub_natural.py --list-voices")
    subprocess.run(["ffmpeg", "-y", "-i", str(tmp_aiff), "-ar", "44100", "-ac", "2",
                    str(out_wav)], capture_output=True, check=True)
    tmp_aiff.unlink(missing_ok=True)
    return _probe_duration(out_wav)


_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"\'])')


def _split_sentences(text: str) -> list[str]:
    """Split narration into sentence-sized chunks for placement."""
    parts = [s.strip() for s in _SENTENCE_RE.split(text.strip()) if s.strip()]
    return parts or [text.strip()]


def _detect_scene_times(mov: Path, threshold: float) -> list[float]:
    """Timestamps (s) where the screen changes significantly — i.e. where a
    UI action lands. Uses ffmpeg scene detection; empty if none/failure."""
    r = subprocess.run(
        ["ffmpeg", "-i", str(mov), "-filter:v",
         f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
        capture_output=True, text=True)
    times = sorted(float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr))
    return times


def _plan_starts(n: int, dur: float, scenes: list[float], mode: str,
                 lead: float, min_gap: float, sent_durs: list[float]) -> list[float]:
    """Decide when each of `n` sentences should START speaking.

    scene → anchor each sentence to an on-screen change (speak `lead`s before it);
    even → spread sentences evenly across the clip; start → all at the beginning.
    Overlaps are then removed by pushing later sentences after earlier ones."""
    if mode == "start":
        anchors = [0.0] * n
    elif mode == "even" or not scenes:
        anchors = [i * dur / n for i in range(n)]
    else:  # scene
        usable = [t for t in scenes if 0.2 < t < dur]
        if len(usable) < n:
            anchors = [i * dur / n for i in range(n)]
        else:
            # Map sentence i onto a scene change spread across the timeline.
            anchors = [usable[min(len(usable) - 1, round(i * (len(usable) - 1) / max(1, n - 1)))]
                       for i in range(n)]
    starts = [max(0.0, a - lead) for a in anchors]
    # Enforce order + no overlap: a sentence can't start before the previous ends.
    for i in range(1, n):
        earliest = starts[i - 1] + sent_durs[i - 1] + min_gap
        if starts[i] < earliest:
            starts[i] = earliest
    return starts


def _dub_clip(mov: Path, sentences: list[str], pins: list, out: Path, voice: str,
              rate: int, lead: float, tail: float, sync: str, scene_threshold: float,
              min_gap: float, size: tuple[int, int], action_offsets: list | None = None,
              intro_text: str | None = None, outro_text: str | None = None,
              hold_gap: float = 0.5) -> Path:
    """Narrate one clip. Lines are placed by, in priority order: explicit @time
    pins → exact per-action offsets captured at record time → scene detection →
    even spread. If intro_text is given, the clip's FIRST frame is held frozen
    while the intro is spoken, then the video plays; outro_text holds the LAST
    frame while a closing line is spoken."""
    tmp = Path(tempfile.mkdtemp(prefix="narrate_"))
    try:
        wavs, durs = [], []
        for i, s in enumerate(sentences):
            w = tmp / f"s{i:02d}.wav"
            durs.append(_say_to_wav(s, w, voice, rate))
            wavs.append(w)

        vdur = _probe_duration(mov)
        # Anchor timeline: prefer exact recorded action offsets, else scene
        # detection, else even/start per `sync`.
        if sync in ("even", "start"):
            anchors, mode = [], sync
        elif action_offsets:
            anchors, mode = list(action_offsets), "scene"
        else:
            anchors = _detect_scene_times(mov, scene_threshold) if sync != "start" else []
            mode = "scene" if anchors else "even"
        starts = _plan_starts(len(sentences), vdur, anchors, mode, lead, min_gap, durs)
        # Apply explicit @time pins verbatim (user knows best).
        for i, p in enumerate(pins or []):
            if p is not None:
                starts[i] = float(p)

        # Intro: freeze the first frame for its whole duration, shift the rest.
        seg_wavs: list[Path] = []
        seg_starts: list[float] = []
        hold_start = 0.0
        if intro_text:
            iw = tmp / "intro.wav"
            idur = _say_to_wav(intro_text, iw, voice, rate)
            hold_start = idur + hold_gap
            seg_wavs.append(iw)
            seg_starts.append(0.0)
        starts = [s + hold_start for s in starts]
        for w, st in zip(wavs, starts):
            seg_wavs.append(w)
            seg_starts.append(st)

        # Outro: after the video + last line finish, hold the last frame.
        content_end = max([hold_start + vdur] + [starts[i] + durs[i] for i in range(len(durs))])
        if outro_text:
            ow = tmp / "outro.wav"
            odur = _say_to_wav(outro_text, ow, voice, rate)
            seg_wavs.append(ow)
            seg_starts.append(content_end + min_gap)

        # Lay every segment on one timeline via adelay, then mix.
        inputs: list[str] = []
        for w in seg_wavs:
            inputs += ["-i", str(w)]
        filt = "".join(
            f"[{i}]adelay={int(seg_starts[i]*1000)}|{int(seg_starts[i]*1000)}[a{i}];"
            for i in range(len(seg_wavs)))
        filt += ("".join(f"[a{i}]" for i in range(len(seg_wavs)))
                 + f"amix=inputs={len(seg_wavs)}:normalize=0:dropout_transition=0,"
                 + f"apad=pad_dur={tail}[mix]")
        track = tmp / "track.wav"
        mix = subprocess.run(["ffmpeg", "-y", *inputs, "-filter_complex", filt,
                              "-map", "[mix]", str(track)], capture_output=True, text=True)
        if mix.returncode != 0:
            raise RuntimeError(f"failed to build narration track: {mix.stderr.strip()}")
        adur = _probe_duration(track)

        # Build the video: freeze first frame (hold_start) + freeze last frame to
        # cover any audio that runs past the played video (end hold / outro), and
        # ALWAYS normalise (CFR/yuv420p/uniform size) so nothing blacks out.
        base_len = vdur + hold_start
        end_pad = max(0.0, adur - base_len)
        holds = []
        if hold_start > 0.001:
            holds.append(f"tpad=start_mode=clone:start_duration={hold_start:.3f}")
        if end_pad > 0.05:
            holds.append(f"tpad=stop_mode=clone:stop_duration={end_pad:.3f}")
        vf = _norm_vf(size[0], size[1], holds)

        r = subprocess.run([
            "ffmpeg", "-y", "-i", str(mov), "-i", str(track),
            "-vf", vf, "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-vsync", "cfr",
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-movflags", "+faststart", "-shortest", str(out)],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"mux failed for {mov.name}: {r.stderr.strip()}")
        extra = (f", intro-hold {hold_start:.1f}s" if hold_start else "")
        placed = ", ".join(f"{s:.1f}s" for s in starts)
        print(f"[narrate] {mov.name} → {out.name}  (clip {vdur:.1f}s, "
              f"{len(sentences)} lines @ [{placed}]{extra}, sync={sync})")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _grab_frame(mov: Path, which: str, png: Path) -> None:
    if which == "first":
        cmd = ["ffmpeg", "-y", "-i", str(mov), "-frames:v", "1", str(png)]
    else:
        cmd = ["ffmpeg", "-y", "-sseof", "-0.2", "-i", str(mov), "-frames:v", "1", str(png)]
    subprocess.run(cmd, capture_output=True, check=True)


def _padded_audio(wav: Path, out: Path, delay: float, total: float) -> None:
    """Delay a voice wav by `delay`s and pad with silence to exactly `total`s."""
    subprocess.run([
        "ffmpeg", "-y", "-i", str(wav),
        "-af", f"adelay={int(delay*1000)}|{int(delay*1000)},apad",
        "-t", f"{total:.3f}", "-ar", "44100", "-ac", "2", str(out)],
        capture_output=True, check=True)


def _freeze_segment(png: Path, total: float, audio: Path, size: tuple[int, int],
                    out: Path) -> None:
    """A still-frame clip of `total`s (frozen frame + its narration) for intro/outro."""
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(png), "-i", str(audio),
        "-vf", _norm_vf(size[0], size[1]), "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-movflags", "+faststart", str(out)], capture_output=True, check=True)


def _dub_step_per_action(mov: Path, sentences: list[str], out: Path, voice: str,
                         rate: int, lead: float, tail: float, size: tuple[int, int],
                         offsets: list[float], intro_text: str | None,
                         outro_text: str | None, hold_gap: float, min_gap: float) -> Path:
    """Split a step clip into its individual ACTION clips (using recorded action
    offsets) and give each its OWN voice line. Each action clip WAITS for its
    narration to finish (last frame held if the voice runs long) before the
    video advances to the next action — so voice and screen stay locked, action
    by action. Requires len(sentences) == len(offsets)."""
    tmp = Path(tempfile.mkdtemp(prefix="peract_"))
    try:
        vdur = _probe_duration(mov)
        bounds = list(offsets) + [vdur]
        segs: list[Path] = []

        if intro_text:
            iw = tmp / "intro.wav"
            idur = _say_to_wav(intro_text, iw, voice, rate)
            total = idur + hold_gap
            png = tmp / "first.png"; _grab_frame(mov, "first", png)
            atrk = tmp / "intro_a.wav"; _padded_audio(iw, atrk, lead, total)
            seg = tmp / "seg_intro.mov"; _freeze_segment(png, total, atrk, size, seg)
            segs.append(seg)

        seg_lens = []
        for i, s in enumerate(sentences):
            st, en = offsets[i], bounds[i + 1]
            seg_dur = max(0.1, en - st)
            vw = tmp / f"v{i}.wav"
            vd = _say_to_wav(s, vw, voice, rate)
            total = max(seg_dur, lead + vd + tail)      # clip waits for the voice
            pad = total - seg_dur
            extra = [f"tpad=stop_mode=clone:stop_duration={pad:.3f}"] if pad > 0.03 else []
            raw = tmp / f"seg{i}.mov"
            subprocess.run([
                "ffmpeg", "-y", "-i", str(mov), "-ss", f"{st:.3f}", "-to", f"{en:.3f}",
                "-vf", _norm_vf(size[0], size[1], extra), "-an",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-r", str(FPS), str(raw)],
                capture_output=True, check=True)
            atrk = tmp / f"a{i}.wav"; _padded_audio(vw, atrk, lead, total)
            seg = tmp / f"m{i}.mov"
            subprocess.run([
                "ffmpeg", "-y", "-i", str(raw), "-i", str(atrk),
                "-map", "0:v", "-map", "1:a", "-t", f"{total:.3f}",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-r", str(FPS),
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                "-movflags", "+faststart", str(seg)], capture_output=True, check=True)
            segs.append(seg)
            seg_lens.append(round(total, 1))

        if outro_text:
            ow = tmp / "outro.wav"
            od = _say_to_wav(outro_text, ow, voice, rate)
            total = od + hold_gap
            png = tmp / "last.png"; _grab_frame(mov, "last", png)
            atrk = tmp / "outro_a.wav"; _padded_audio(ow, atrk, lead, total)
            seg = tmp / "seg_outro.mov"; _freeze_segment(png, total, atrk, size, seg)
            segs.append(seg)

        _concat(segs, out)
        print(f"[narrate] {mov.name} → {out.name}  (per-action: {len(sentences)} "
              f"clips, each waits for its voice; lens {seg_lens}s)")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _dub_one_action(clip: Path, sentence: str, out: Path, voice: str, rate: int,
                    lead: float, tail: float, size: tuple[int, int]) -> float:
    """Dub a SINGLE action clip with its own voice line. The clip waits for the
    voice (last frame held if the voice runs long). Returns the segment length."""
    tmp = Path(tempfile.mkdtemp(prefix="oneact_"))
    try:
        vdur = _probe_duration(clip)
        if not sentence:                            # no line → silent, normalised
            _silent_clip(clip, out, size)
            return vdur
        vw = tmp / "v.wav"
        vd = _say_to_wav(sentence, vw, voice, rate)
        total = max(vdur, lead + vd + tail)
        pad = total - vdur
        extra = [f"tpad=stop_mode=clone:stop_duration={pad:.3f}"] if pad > 0.03 else []
        raw = tmp / "raw.mov"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(clip), "-vf", _norm_vf(size[0], size[1], extra),
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(FPS), str(raw)],
            capture_output=True, check=True)
        atrk = tmp / "a.wav"; _padded_audio(vw, atrk, lead, total)
        subprocess.run([
            "ffmpeg", "-y", "-i", str(raw), "-i", str(atrk),
            "-map", "0:v", "-map", "1:a", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
            "-movflags", "+faststart", str(out)], capture_output=True, check=True)
        return total
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _dub_step_from_clips(rows: list, sentences: list[str], out: Path, voice: str,
                         rate: int, lead: float, tail: float, size: tuple[int, int],
                         intro_text: str | None, outro_text: str | None,
                         hold_gap: float) -> Path:
    """Build a step by dubbing each saved ACTION clip individually, then joining
    them. sentences (one per clip, from narration.txt) override the recorded
    labels when the counts match; otherwise labels are used so it's always 1:1."""
    tmp = Path(tempfile.mkdtemp(prefix="fromclips_"))
    try:
        if len(sentences) == len(rows):
            lines = sentences
        else:
            lines = [r["label"] for r in rows]      # fall back to recorded labels
        segs: list[Path] = []
        lens = []

        if intro_text:
            iw = tmp / "intro.wav"; idur = _say_to_wav(intro_text, iw, voice, rate)
            total = idur + hold_gap
            png = tmp / "first.png"; _grab_frame(rows[0]["clip"], "first", png)
            atrk = tmp / "intro_a.wav"; _padded_audio(iw, atrk, lead, total)
            seg = tmp / "seg_intro.mov"; _freeze_segment(png, total, atrk, size, seg)
            segs.append(seg)

        for i, r in enumerate(rows):
            seg = tmp / f"seg{i:02d}.mov"
            ln = _dub_one_action(r["clip"], lines[i], seg, voice, rate, lead, tail, size)
            segs.append(seg)
            lens.append(round(ln, 1))

        if outro_text:
            ow = tmp / "outro.wav"; od = _say_to_wav(outro_text, ow, voice, rate)
            total = od + hold_gap
            png = tmp / "last.png"; _grab_frame(rows[-1]["clip"], "last", png)
            atrk = tmp / "outro_a.wav"; _padded_audio(ow, atrk, lead, total)
            seg = tmp / "seg_outro.mov"; _freeze_segment(png, total, atrk, size, seg)
            segs.append(seg)

        _concat(segs, out)
        print(f"[narrate] {out.name}  (per-action from saved clips: {len(rows)} "
              f"action clips, each waits for its voice; lens {lens}s)")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _silent_clip(mov: Path, out: Path, size: tuple[int, int]) -> Path:
    """Normalise a step clip that has no narration, giving it a silent audio
    track so it matches the narrated clips for concatenation."""
    dur = _probe_duration(mov)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(mov),
        "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=44100:cl=stereo",
        "-vf", _norm_vf(size[0], size[1]), "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-vsync", "cfr",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-movflags", "+faststart", "-shortest", str(out)],
        capture_output=True, check=True)
    return out


def _concat(clips: list[Path], out: Path) -> None:
    # Inputs are already uniform (CFR/yuv420p/same size + AAC), so the concat
    # demuxer with a light re-encode joins them cleanly and stays playable.
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-vsync", "cfr",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-movflags", "+faststart", str(out)], capture_output=True, check=True)
    listing.unlink(missing_ok=True)


# ── Orchestration ────────────────────────────────────────────────────────────

def _detect_theme(rec_dir: Path) -> str:
    if list(rec_dir.glob("step-*-dark.mov")) or (rec_dir / "full-dark.mov").exists():
        return "dark"
    if list(rec_dir.glob("step-*-light.mov")) or (rec_dir / "full-light.mov").exists():
        return "light"
    return ""


def _step_clips(rec_dir: Path, theme: str) -> list[tuple[int, Path]]:
    suffix = f"-{theme}" if theme else ""
    found = []
    for mov in rec_dir.glob(f"step-*{suffix}.mov"):
        if mov.name.endswith("-narrated.mov"):
            continue
        m = re.match(r"step-(\d+)-", mov.name)
        if m:
            found.append((int(m.group(1)), mov))
    return sorted(found)


def _require_tools() -> None:
    if sys.platform != "darwin":
        raise RuntimeError("Narration uses macOS `say` — run on your Mac.")
    for exe in ("say", "ffmpeg", "ffprobe"):
        if not shutil.which(exe):
            raise RuntimeError(f"'{exe}' not on PATH. Install ffmpeg: brew install ffmpeg")


def narrate_workflow(rec_dir: Path, theme: str | None = None,
                     steps: list | None = None, voice: str | None = None,
                     rate: int = 172, lead_in: float = 0.35, tail: float = 0.35,
                     sync: str = "scene", scene_threshold: float = 0.3,
                     min_gap: float = 0.2, per_action: bool = True) -> Path:
    """Produce full-<theme>-narrated.mov for a recording directory. Uses
    narration.txt if present; otherwise auto-generates one from `steps`.

    Each step's narration is split into sentences and each sentence is placed at
    the moment its action happens on screen (sync='scene', via scene detection),
    so the voice tracks the screen instead of dumping all text at the start.
    sync='even' spreads sentences evenly; sync='start' is the old behaviour."""
    _require_tools()
    rec_dir = Path(rec_dir)
    if theme is None:
        theme = _detect_theme(rec_dir)

    clips = _step_clips(rec_dir, theme)
    if not clips:
        raise RuntimeError(f"no step-*.mov files found in {rec_dir}")

    timings = load_action_timings(rec_dir)   # exact per-action offsets + labels
    action_clips = load_action_clips(rec_dir)  # separate saved clip per action (best)
    narration = load_narration_file(rec_dir)
    if not narration and (action_clips or timings or steps):
        narration = build_auto_narration(clips, steps, timings, action_clips, name=rec_dir.name)
        tpl = _write_narration_template(rec_dir, narration, steps)
        print(f"[narrate] no narration.txt — auto-generated one at {tpl} (edit & re-run to refine)")
    if not narration:
        raise RuntimeError(
            f"no narration.txt in {rec_dir}, and no recorded timings or steps to "
            f"auto-generate from. Create narration.txt with [step N] blocks.")

    chosen = pick_voice(voice, list_installed_voices())
    note = "" if "(" in chosen else "  (compact voice — install an Enhanced one for a natural sound)"
    intro_text = narration.get("intro")
    outro_text = narration.get("outro")
    size = _probe_size(clips[0][1])   # canonical resolution — all clips match this
    src = ("saved per-action clips" if action_clips else
           ("recorded action offsets" if timings else "scene detection"))
    print(f"[narrate] voice: {chosen}{note}  |  rate {rate}wpm  |  {len(clips)} step clip(s)"
          f"  |  {size[0]}x{size[1]}@{FPS}fps  |  sync via {src}"
          + ("  |  intro-hold on step 1" if intro_text else ""))

    dubbed: list[Path] = []
    for pos, (n, mov) in enumerate(clips):
        value = narration.get(n)
        out = mov.with_name(f"{mov.stem}-narrated.mov")
        first = pos == 0
        last = pos == len(clips) - 1
        if not value:
            print(f"[narrate] step {n}: no narration block — clip stays silent")
            _silent_clip(mov, out, size)
            dubbed.append(out)
            continue
        # value is a plain string (auto sentence split) or a list of (time|None, text) cues.
        if isinstance(value, list):
            sentences = [t for _, t in value]
            pins = [t for t, _ in value]
        else:
            sentences = _split_sentences(value)
            pins = [None] * len(sentences)
        # Ignore degenerate pins (e.g. an old file where every line is @0.0).
        real_pins = [p for p in pins if p is not None]
        if len(set(real_pins)) <= 1 and len(real_pins) > 1:
            pins = [None] * len(sentences)
        offsets = [e["t"] for e in timings.get(mov.name, [])] or None
        # Only trust offsets that strictly increase (bad recordings gave all 0.0).
        if offsets and any(offsets[i] >= offsets[i + 1] for i in range(len(offsets) - 1)):
            offsets = None
        rows = action_clips.get(mov.name)

        # Best: dub each SAVED action clip on its own (true separate clip per
        # action, each waits for its voice). Next best: split the combined clip
        # at recorded offsets. Fallback: overlay on the continuous clip.
        if per_action and rows:
            _dub_step_from_clips(rows, sentences, out, chosen, rate, lead_in, tail,
                                 size, intro_text if first else None,
                                 outro_text if last else None, hold_gap=0.5)
        elif per_action and offsets and len(sentences) == len(offsets):
            _dub_step_per_action(mov, sentences, out, chosen, rate, lead_in, tail,
                                 size, offsets, intro_text if first else None,
                                 outro_text if last else None, hold_gap=0.5,
                                 min_gap=min_gap)
        else:
            _dub_clip(mov, sentences, pins, out, chosen, rate, lead_in, tail,
                      sync, scene_threshold, min_gap, size,
                      action_offsets=offsets,
                      intro_text=intro_text if first else None,
                      outro_text=outro_text if last else None)
        dubbed.append(out)

    full = rec_dir / (f"full-{theme}-narrated.mov" if theme else "full-narrated.mov")
    _concat(dubbed, full)
    print(f"[narrate] DONE → {full}")
    return full
