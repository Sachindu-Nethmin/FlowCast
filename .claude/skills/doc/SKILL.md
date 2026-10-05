---
name: doc
description: Turn a FlowCast workflow into a finished, narrated YouTube video plus its Medium post and LinkedIn draft. Use when asked to record a workflow, make a video of a quick start, produce a tutorial video, or publish a walkthrough. Covers the whole run from pre-flight to upload kit.
---

# Workflow to published video

One recorded run becomes: a 1440p narrated YouTube master with chapters and a
thumbnail, a Medium post with a GIF per step, and a LinkedIn draft.

Work through the phases in order. Each one ends with something checkable, and a
mistake caught in phase 3 costs minutes where the same mistake caught in phase 7
costs a re-record.

---

## 1. Pre-flight

A stale run is the most common failure, and it fails late and confusingly.

```bash
pkill -f "main.py workflows"; pkill -f "uv run.*main.py"
lsof -nP -iTCP:8765 -sTCP:LISTEN          # must be empty, or the server cannot bind
rm -rf ~/WSO2Integrator/*                 # so step 1 creates the project fresh
```

Archive any existing recording for this slug rather than deleting it:

```bash
mv output/recordings/<slug> output/recordings/<slug>-archived-$(date +%Y%m%d-%H%M)
```

This matters more than it sounds. The `guid/` folder accumulates clips across
every attempt, and a leftover clip from a failed run silently shifts every
narration line onto the wrong action.

Quit and reopen WSO2 Integrator if it is running, especially if you just deleted
the project it had open.

## 2. Record

```bash
uv run python main.py workflows/<slug>.md --phone
```

Scan the QR code and tap each line in order. The step ends by itself when you
tap its last action. Type in the box only to correct a line that does not parse.

A step whose result appears after the last click — a build finishing, a response
arriving — needs a dwell, or recording stops before the result exists:

```markdown
4. Wait 8 seconds.
```

## 3. Verify the recording before going further

```bash
ls output/recordings/<slug>/step-0*-dark.mov          # one per step
ls output/recordings/<slug>/step-0*/after.png         # one per step
ls output/recordings/<slug>/guid | wc -l              # one clean run only
```

A missing `after.png` means that step was skipped rather than completed, so it
produced no assembled video. Re-record it.

To redo a single step, make a one-step workflow file containing just that step,
run it, then copy its clips into the main recording renamed `stepNN_actionNNN_*`.

## 4. Write the narration, one line per action

List the actions and write a line against each:

```bash
ls output/recordings/<slug>/guid/step*_action*.mov
```

Write to a plain text file, `# step N` headers, one line per action, in order.

**Spoken forms, not UI spellings.** The model reads what you type:

| On screen | Write | Because |
|---|---|---|
| `GET` | `get` | otherwise spelled G-E-T |
| `API` | `A P I` | otherwise said as a word |
| `externalApi` | `external A P I` | run-together names are mangled |
| `HelloWorldAPI` | `Hello World A P I` | same |

**Name the button, do not describe the outcome.** The cursor is visibly moving
toward something named. "Then select Create" is right; "Create the service" is
wrong, and reads as a mismatch.

Give every line one job. A line that explains *why* belongs on the action that
earns it, usually a longer typing action with room to speak.

## 5. Narrate and assemble

```bash
FLOWCAST_TTS=chatterbox \
FLOWCAST_VOICE_REF=$PWD/assets/voice/reference.wav \
FLOWCAST_VOICE_PITCH_HZ=reference \
FLOWCAST_VOICE_TAKES=3 \
uv run python tools/narrate_sync.py --dir output/recordings/<slug> --script <script>.txt
```

Run with `--dry-run` first: it checks the line count against the clip count per
step and refuses on a mismatch, which is the error that silently ruins a video.

Both voice variables earn their place:

* `FLOWCAST_VOICE_PITCH_HZ=reference` holds every line at one pitch. Without it
  longer lines drift upward and the voice wanders mid-video.
* `FLOWCAST_VOICE_TAKES=3` keeps the take closest to the reference. Short lines
  are where a clone loses a speaker's identity, and sampling fixes it.

## 6. Build the master

```bash
FLOWCAST_TTS=chatterbox FLOWCAST_VOICE_REF=$PWD/assets/voice/reference.wav \
FLOWCAST_VOICE_PITCH_HZ=reference FLOWCAST_VOICE_TAKES=8 \
uv run python tools/make_youtube_video.py \
  --dir output/recordings/<slug> --title "<title>" --hook "<one spoken line>" \
  --theme dark --art graph --label "<endpoint or key value>" --rebuild-intro
```

**Set the voice variables here too.** The intro is synthesized separately, and
without them it falls back to a macOS system voice — a different person for the
first eight seconds.

Art kinds: `chat`, `robot`, `files`, `graph`, `sync`, `sap`, `none`. Pick one
that matches the subject and set `--label` to something real from the video.

## 7. Verify before publishing

```bash
uv run python - <<'PY'
from pathlib import Path
from src.tts_clone import _ltas, median_f0, timbre_similarity
ref = _ltas(Path("assets/voice/reference.wav"))
for seg in ("intro.wav", "body.wav"):        # cut these from the master first
    p = Path(seg)
    print(seg, f"{median_f0(p)[0]:.1f} Hz", f"{timbre_similarity(p, ref):.2f}")
PY
```

Intro and body should agree within a few Hz, and similarity should sit around
0.95. Check the chapter timestamps against the file rather than trusting the
ones written earlier — they shift whenever a line is re-rendered.

Watch the last frame: it should hold on the result, not on dead air.

## 8. Publishing artifacts

Thumbnails are framed by default. The video's own title card is not, and should
not be.

For Medium, copy the per-step GIFs into a folder with ordered names, and write
the post as plain text with `[ IMAGE: <file> ]` markers. Medium does not import
markdown, so plain text pastes more cleanly than markdown syntax.

Keep the Medium post purely a guide. The tooling story belongs on LinkedIn, if
anywhere.

---

## Failures worth recognising

| Symptom | Cause |
|---|---|
| `Address already in use` | a previous run still holds 8765 |
| Narration one action out of step | stray clips from an earlier attempt in `guid/` |
| Voice changes at the 8 second mark | voice variables not set for the intro build |
| Voice wanders between lines | no pitch target, or takes left at 1 |
| Step video missing entirely | that step was skipped, not completed |
| Result never appears | no dwell after the final click |
| Video ends in silence | recorded dwell far outlasts the closing line |
