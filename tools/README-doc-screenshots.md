# Docs-style step-by-step guides from a FlowCast recording

`tools/doc_screenshots.py` turns a recording FlowCast already made into a
documentation page that matches the published WSO2 Integrator docs: numbered
steps, and **one still PNG per step** inside a `<ThemedImage>` block.

The GIFs FlowCast writes are right for a video or a blog post. The docs pages
(`en/docs/get-started/build-integration-api.md` and its siblings) use stills.
This closes that gap without re-recording anything.

## Why the frames land in the right place

Each recording carries a `timings.json` next to the `.mov` files. It holds the
timestamp of every action inside a step:

```json
"step-01-create-the-project-dark.mov": [
  { "t": 0.0,  "label": "Click Skip for now." },
  { "t": 27.8, "label": "Click Browse." },
  { "t": 34.8, "label": "Click Create Integration." }
]
```

The frame worth publishing is tied to the **last** action of the step, the click
that commits the form. Two moments are useful:

| `--moment` | Frame | Shows |
|---|---|---|
| `settled` (default) | last action `+ --dwell` (1.2s) | the form filled in, cursor on the confirming button |
| `pre-click` | last action `- --lead` (0.35s) | the form filled in, just before the click |

A step whose only timestamp is `0.0` has no usable boundary, so the tool falls
back to 75% into the clip and says so in the output. Pin those by hand.

## Capturing live instead of from video

FlowCast's guide mode already drives the loop you probably want. `src/step_input.py`
minimises the WSO2 Integrator window and brings your terminal forward
(`_step_aside`), takes the next instruction typed or spoken, restores the window
full screen (`_come_back`), performs the action, records it, and screenshots the
result to `step-NN/after.png`.

```bash
uv run python main.py workflows/quick-start-automation.md --guide          # typed
uv run python main.py workflows/quick-start-automation.md --guide --voice  # spoken
```

Because the terminal is out of the way and the app is full screen when that
screenshot is taken, `after.png` IS the publishable frame. This tool uses it
when it exists and only falls back to seeking the `.mov` when it does not.
Force either source with `--prefer live` / `--prefer video`.

## Prerequisites

- `ffmpeg` and `ffprobe` on `PATH` (`brew install ffmpeg`)
- A recording under `output/recordings/<workflow>/` containing `step-*.mov`.
  `timings.json` and `index.md` are optional but make the result much better:
  `index.md` supplies the step titles and instruction lists.

## 1. Generate the page and the stills

```bash
python tools/doc_screenshots.py output/recordings/quick-start-automation
```

Writes into `output/recordings/quick-start-automation/docs/`:

- `step-01-create-the-project-dark.png` … one per step, scaled to 1600px wide
- `quick-start-automation.md` — frontmatter, the Docusaurus imports, the step
  headings and instructions carried over from `index.md`, and a `<ThemedImage>`
  block per step

Preview without writing anything:

```bash
python tools/doc_screenshots.py output/recordings/quick-start-automation --dry-run
```

## 2. Fix the steps the heuristic gets wrong

Read the console output. A step reported with `1 action(s)` is the usual
suspect: the whole step was one long action, so there was no boundary to aim at.

Write a frame for every action and look through them:

```bash
python tools/doc_screenshots.py output/recordings/quick-start-automation --candidates
```

Candidates land in `docs/candidates/`, named after the action label
(`step-03-add-logic-dark-a04-set-values-to-hello-world.png`). Pick the timestamp
you want, then pin it:

```bash
python tools/doc_screenshots.py output/recordings/quick-start-automation --at 4=6.2
```

`--at` is repeatable and overrides the heuristic for that step only.

> If no frame in the clip shows what the step is about — a run step whose
> terminal output arrives after the recording stops — the recording is too
> short. Add a dwell to the end of that step and record it again. No frame
> selection can recover something that was never captured.

## 3. Move it into the docs repo

```bash
python tools/doc_screenshots.py output/recordings/quick-start-automation \
    --title "Build an Automation" \
    --sidebar-position 6 \
    --description "Build an automation in WSO2 Integrator that prints to the terminal." \
    --keywords "wso2 integrator, automation, quick start, ballerina" \
    --img-base /img/get-started/build-automation \
    --install "/path/to/WSO2 Integrator Docs/en"
```

`--install` copies the PNGs to `en/static<img-base>/`. Move the `.md` under
`en/docs/` yourself and add it to `sidebars.ts` — placement is an editorial
decision, not a mechanical one.

## 4. Before opening a PR

The generated page is a draft with `TODO` markers in three places, all of which
a human has to fill in:

- the **Time / What you'll build** line
- the **one-paragraph** introduction
- every image **`alt`** — it ships as `<title> — TODO describe what the
  screenshot shows`. Alt text is read aloud by screen readers, so describe what
  is on screen, the way the published pages do: *"Create new integration form
  with Integration Name set to HelloWorldAPI"*.

Then run the docs repo's own checks:

```bash
npm run typecheck
npm run build
```

## Options

| Flag | Default | Effect |
|---|---|---|
| `--moment settled\|pre-click` | `settled` | frame relative to the step's last action |
| `--dwell SECONDS` | `1.2` | offset after the last action for `settled` |
| `--lead SECONDS` | `0.35` | offset before the last action for `pre-click` |
| `--at STEP=SECONDS` | — | pin one step to an exact timestamp (repeatable) |
| `--candidates` | off | one frame per action into `candidates/` |
| `--width PX` | `1600` | scale width, `0` keeps the native size |
| `--prefer live\|video` | `live` | use `step-NN/after.png` when present, else seek the `.mov` |
| `--theme light\|dark\|both` | `both` | which recorded themes to capture |
| `--out DIR` | `<recording>/docs` | where to write |
| `--img-base URL` | `/img/get-started/<slug>` | URL base written into the page |
| `--install DIR` | — | docs site root (`…/en`) to copy PNGs into |
| `--no-tabs` | off | omit the Visual Designer / Ballerina Code tab scaffold |
| `--dry-run` | off | print the page, write nothing |
