---
name: doc-to-youtube
description: Turn a pasted WSO2 Integrator documentation page (numbered "Step 1 / Step 2 …" instructions) into a full FlowCast production — workflow markdown, recorded per-step GIFs and clips, narration in the user's cloned voice, a branded intro card, and a YouTube-ready master with thumbnail, chapters and description. Use whenever the user pastes doc steps or a guide, or says "make a video from this", "record this doc", "turn this guide into a tutorial", or invokes /doc-to-youtube.
---

# Documentation page → YouTube tutorial

The user pastes a documentation page. You turn it into a finished, uploadable
video. Everything below runs locally on this Mac; nothing is published anywhere.

## What gets produced

| Artifact | Path |
|---|---|
| Workflow markdown (the recording script) | `workflows/<slug>.md` |
| Per-step GIFs + clips, `full-<theme>.mov`, docs `index.md` | `output/recordings/<slug>/` |
| Narration script | `output/recordings/<slug>/narration.txt` |
| Narrated video | `output/recordings/<slug>/full-<theme>-narrated.mov` |
| YouTube master + thumbnail + description + chapters | `output/youtube/<slug>/` |

## Step 1 — Write the workflow markdown

Read `reference/workflow-grammar.md` in this skill folder **before writing the
file**. The recorder matches fixed regexes, not intent: `Select the **Create**
card.` parses to nothing, `Select **Create**.` parses to a click. That reference
is the contract.

Pick a kebab-case slug from the page's subject (`integration-as-api-hello-world`)
and write `workflows/<slug>.md`. Keep the doc's own step titles and values;
strip tab markers, NOTE blocks and cloud-editor asides; add the desktop-only
project-location lines the grammar reference describes.

## Step 2 — Verify before touching the screen

```bash
uv run python tools/check_workflow.py workflows/<slug>.md
```

Every line must be `✓` or `·`. A `✗` means the recorder would skip that line —
reword it and re-run. Do not proceed with any `✗`.

## Step 3 — Get consent, then record

Recording takes over the mouse and keyboard for several minutes and needs the
app visible and unattended. **Ask the user before starting it**, and tell them
roughly how long it will be (~40s per step). Never start a recording run
unprompted or while they are mid-task.

```bash
uv run python main.py workflows/<slug>.md --no-narrate
```

`--no-narrate` is deliberate: record silent first, write a good narration
script, then speak it. Letting the default auto-narration run produces a
click-by-click read of the raw instructions.

Recovery, without re-shooting everything:

* One step went wrong → `--step N`
* Everything from a step onward → `--from-step N`
* A control could not be found → FlowCast's healer prompts; the run continues.

### Driving the run yourself

The healer only asks when `sys.stdin.isatty()` is true, so a run you start
directly has no terminal and **aborts the step** instead of asking. To answer
its prompts yourself, go through the supervisor — it runs FlowCast inside a pty
and screenshots the screen at each prompt:

```bash
python tools/supervise_record.py --workflow workflows/<slug>.md   # backgrounded
python tools/supervise_record.py --status                          # when blocked
python tools/supervise_record.py --answer "skip for now"
```

`--status` prints the prompt, the last 40 lines, and the path to a screenshot —
read that image and answer from what is on screen, not from what the workflow
says should be there. `--auto-safe` handles the one prompt with a defensible
default. `--stop` aborts at the next prompt.

**This needs macOS Screen Recording permission for the process that launches
it**, or FlowCast cannot capture at all; the supervisor checks up front and
exits with instructions rather than failing mid-run. Accessibility applies
immediately when granted, Screen Recording only at app launch — so quit and
reopen after granting.

Answering the `Remember 'X' → click 'Y' … and fix the workflow file? [y/N]`
prompt:

* **`y`** only when the workflow genuinely names the wrong control and `Y` is
  what that instruction always meant.
* **`N`** when the control was right but something had to happen first — a
  sign-in screen to dismiss, a panel to open, a scroll. That is a *missing
  line*, not a wrong one: answer `N`, then add the precursor line to
  `workflows/<slug>.md` yourself. A wrong `y` rewrites the workflow and teaches
  the KB a mapping that will misfire on every later run.

## Step 4 — Write the narration script

Write `output/recordings/<slug>/narration.txt` yourself — do not accept the
auto-generated template. Read `reference/narration-and-copy.md` for the block
format and the one-line-per-action rule that keeps the voice synced to the
screen.

## Step 5 — Narrate in the user's cloned voice

```bash
FLOWCAST_TTS=chatterbox \
FLOWCAST_VOICE_REF=$PWD/assets/voice/reference.wav \
uv run python tools/dub_natural.py --dir output/recordings/<slug>
```

Produces `full-<theme>-narrated.mov`. Lines are cached by text, so a re-run only
re-synthesizes what changed. If the clone talks too fast, add
`FLOWCAST_VOICE_CFG=0.3`. Without the two env vars it falls back to the macOS
`say` voice — only do that if the user asks.

## Step 6 — Intro card + YouTube master

```bash
FLOWCAST_TTS=chatterbox \
FLOWCAST_VOICE_REF=$PWD/assets/voice/reference.wav \
uv run python tools/make_youtube_video.py \
  --dir output/recordings/<slug> \
  --title "Build a Hello World REST API" \
  --subtitle "Expose and call an API in minutes" \
  --art graph --label "GET /greeting"
```

This renders the branded title card, speaks its hook in the same cloned voice,
concatenates card + tutorial in a single encode, normalises loudness to −14 LUFS
(video stream-copied, so no second generation of picture loss), and writes the
master, a 1280×720 thumbnail, a description with timed chapters, and a
chapters-only file.

**The card and the thumbnail are one design** — `src/brand.py`, the same
navy/cyan system as the workflow thumbnails on the design canvas: logo lockup
top-left, then `--eyebrow` → `--title` headline → `--subtitle` in cyan, with a
line-art illustration bleeding off the right edge. Change the look there, not in
either tool, so the video and its thumbnail cannot drift apart.

Pick the illustration to match the workflow, and put something real from the
guide in its speech bubble:

| `--art` | For | Default label |
|---|---|---|
| `chat` | AI chat agents | `Hello` |
| `robot` | automations / Hello World | `Hello, World!` |
| `files` | file listeners, local files | `File modified` |
| `graph` | HTTP / GraphQL services, APIs | `/news` |
| `sync` | FTP, scheduled data sync | `sales.json` |
| `sap` | connector-to-connector integrations | `POST /salesorder` |

`--label` overrides that text — use the guide's own path, method or output
(`GET /greeting`, `Hello World`), never invented copy. `--art none` drops the
illustration for a text-only card.

The card animates element by element (logo pops, wordmark settles, eyebrow →
headline lines → subhead rise on a stagger, illustration pops, label bubble
lands last) over a slow push-in. Nothing to configure; `--no-zoom` in
`make_intro.py` stops the push if a card ever needs to sit still.

Defaults worth knowing: `--quality 1440p` (YouTube gives ≥1440p uploads a
higher bitrate, which matters for small UI text), `--theme auto`, x264
`--preset medium --crf 16`. Add `--endcard` for a spoken outro card,
`--preset slow` for a smaller file, `--quality native` to keep the recorded
1920×1202 frame untouched.

Check the card before the long encode — this is instant, the master is not:

```bash
uv run python tools/make_intro.py --title "Build a Hello World REST API" \
  --subtitle "Expose and call an API in minutes" --art graph \
  --label "GET /greeting" --thumbnail-only /tmp/card.png
```

Title and hook copy: see `reference/narration-and-copy.md`.

## Step 7 — Hand it over

Report the master, thumbnail and description paths, the runtime, and the
chapter list. Send the master with SendUserFile so the user can watch it without
digging through `output/`. Mention `output/recordings/<slug>/index.md` too — it
is the themed docs markdown with the GIFs, ready to paste back into the
documentation site.

Uploading to YouTube is the user's call — this skill stops at the finished file.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `check_workflow.py` reports `✗` | Reword per `reference/workflow-grammar.md` |
| Recorder clicks the wrong control | Re-run that step with `--step N`; if it repeats, the label in the markdown does not match the UI |
| `no narrated recordings in …` | Step 5 has not run for that theme |
| Voice runs ahead of the screen | A `[step N]` block has more lines than that step has actions |
| Voice sounds rushed | `FLOWCAST_VOICE_CFG=0.3` |
| `no voice-clone interpreter` | `uv venv --python 3.11 .venv-voice && VIRTUAL_ENV=$PWD/.venv-voice uv pip install -e ".[clone]"` |
| Chapters missing from the description | Fewer than 3 steps ≥10s — expected, YouTube would ignore them |
| Card colours, type or spacing look off-brand | Edit the tokens at the top of `src/brand.py` — both the intro and the thumbnail read them |
| Headline overflows into the illustration | It auto-shrinks 142→78px; shorter beats smaller — cut the title to ~4 words |
| Bubble text is wrong for the guide | Pass `--label`, don't edit the art painter |
