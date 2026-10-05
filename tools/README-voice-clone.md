# Voice-cloned narration for FlowCast recordings

By default FlowCast narrates with macOS `say` (see `README-dub-natural.md`).
This backend swaps that synthetic voice for a **clone of a real voice**, built
from a short sample of someone speaking — so the tutorial videos sound like you
rather than like a system voice.

It uses [Chatterbox](https://github.com/resemble-ai/chatterbox) (Resemble AI's
open-source zero-shot TTS), which is:

- **Free & local** — no API key, no per-minute cost; runs on the Mac's GPU (MPS).
- **Zero-shot** — no training run; a 7–20s reference sample is the whole setup.
- **Watermarked** — every clip carries Resemble's inaudible Perth watermark, so
  the audio stays traceable as synthetic.

Only clone a voice you have permission to use — your own, or one whose owner
has agreed.

## 1. Install (one time, ~5 min)

Chatterbox pulls in torch (~2.5GB), so it lives in its **own** virtualenv and
never weighs down the main project environment:

```bash
uv venv --python 3.11 .venv-voice
VIRTUAL_ENV=$PWD/.venv-voice uv pip install -e ".[clone]"
```

The `setuptools<81` pin in that extra is load-bearing: the `perth` watermarker
still imports `pkg_resources`, and without it `perth` silently degrades to a
`None` watermarker class and Chatterbox fails to construct.

Model weights (~1GB) download automatically on first run and are then cached by
Hugging Face.

## 2. Record a reference sample

7–20 seconds of clean, continuous speech from a single speaker — a normal
speaking tone, no music or background chatter. A Voice Memo is fine.

Clean it up and convert it to the expected 24kHz mono WAV:

```bash
ffmpeg -i memo.m4a \
  -af "highpass=f=70,afftdn=nr=12:nf=-45,deesser,loudnorm=I=-20:TP=-2:LRA=9" \
  -ac 1 -ar 24000 assets/voice/reference.wav
```

Trim to just the speech with `-ss`/`-to` if the recording has dead air at either
end — leading silence and room tone degrade the clone noticeably.

## 3. Narrate

Set two environment variables and run the normal narration path; everything else
(sentence placement, per-action clip timing, concat) is unchanged:

```bash
FLOWCAST_TTS=chatterbox \
FLOWCAST_VOICE_REF=$PWD/assets/voice/reference.wav \
python -c "from pathlib import Path; from src import narrate; \
  narrate.narrate_workflow(Path('output/recordings/quick-start-automation'), theme='dark')"
```

This rewrites `*-narrated.mov` in that directory. Unset `FLOWCAST_TTS` to go
back to `say`.

Because the clip pipeline pads each action clip to fit its line, re-synthesized
audio of a different length than the `say` original re-times itself — no manual
re-sync needed.

## Tuning

| Variable | Default | Effect |
|---|---|---|
| `FLOWCAST_VOICE_REF` | — | Reference WAV (required) |
| `FLOWCAST_VOICE_EXAGGERATION` | `0.4` | Emotional intensity. Raise for livelier delivery; lower for a flat, instructional read |
| `FLOWCAST_VOICE_CFG` | `0.5` | Adherence to the reference. **Lower it to ~0.3 if the clone talks too fast** |
| `FLOWCAST_VOICE_DEVICE` | auto | `mps` / `cuda` / `cpu` |
| `FLOWCAST_VOICE_PYTHON` | `.venv-voice/bin/python` | Interpreter holding chatterbox-tts |
| `FLOWCAST_VOICE_CACHE` | `output/.voice_cache` | Cache dir |

Synthesized lines are cached by text + reference + settings, so re-running a
narration only pays for lines whose wording actually changed. Delete the cache
directory to force a full re-render.

## How it fits together

`src/narrate.py` funnels every spoken line through one function, `_say_to_wav`,
which dispatches to this backend when `FLOWCAST_TTS=chatterbox`:

```
narrate.py  _say_to_wav()
   └─ src/tts_clone.py          in the project venv — cache, ffmpeg post, protocol
        └─ tools/voice_clone_server.py   in .venv-voice — holds the loaded model
```

The server is a long-lived subprocess speaking JSON lines over stdin/stdout, so
the model loads once per run rather than once per sentence (~20s each). It hands
the protocol a private duplicate of fd 1 and redirects real stdout to stderr,
because torch/perth/chatterbox print loading chatter — some of it from C — that
would otherwise corrupt the wire.

`src/dub.py`, the older raw-instruction dubber, still uses `say` only.

## Limits

- **English only.** Chatterbox v1 is English; a non-English reference still
  transfers timbre, but the read will carry an accent from the model's own
  phonetics.
- Long sentences drift. The narration script's one-line-per-action shape suits
  it well; avoid paragraph-length lines.
- Generation is roughly 2× realtime on an M-series GPU — a 100s narration takes
  a few minutes on a cold cache.
