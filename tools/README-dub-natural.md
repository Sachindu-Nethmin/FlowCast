# Natural AI voiceover for FlowCast recordings

`tools/dub_natural.py` adds a natural, YouTube-tutorial-style voiceover to the
silent screen recordings FlowCast produces. It uses macOS's built-in `say`
command with an **Enhanced / Premium neural voice**, so it is:

- **Free & offline** — no API key, no network, no per-minute cost.
- **Commercial-safe** — Apple places no usage restriction on the audio `say`
  generates, so you can publish the narrated videos.
- **Natural** — reads a hand-written conversational script, not the raw click
  instructions, with an Enhanced neural voice.

## 1. Install an Enhanced voice (one time, ~1 min)

The default macOS voices sound robotic. Install a natural one:

1. Open **System Settings → Accessibility → Spoken Content**.
2. Click the **ⓘ / Manage Voices** next to *System Voice*.
3. Under **English**, expand a voice and pick a **(Premium)** or **(Enhanced)**
   variant — good picks: **Ava (Premium)**, **Zoe (Premium)**, **Evan (Enhanced)**.
4. Download it (they're ~100–300 MB each).

Check what's installed:

```bash
python tools/dub_natural.py --list-voices
```

You also need `ffmpeg`:

```bash
brew install ffmpeg
```

Are these paid? **No.** The Enhanced/Premium voices are free official Apple
downloads — the only cost is disk space (~100–300 MB each).

The default voice is a **young male Enhanced voice (Evan)**. If Evan isn't
installed it falls back through other young male voices (Aaron, Nathan, Tom…),
then a compact male voice. Override any time with `--voice` or the
`FLOWCAST_DUB_VOICE` env var.

## 2. Run it

### One command (record from the .md, then narrate)

```bash
uv run python main.py workflows/quick-start-automation.md --narrate
```

This records the workflow following the markdown **and** adds the natural
voiceover in a single step, producing `full-<theme>-narrated.mov`. Combine with
`--guide` (or `--voice`) to narrate a session you record/author interactively:

```bash
uv run python main.py workflows/quick-start-automation.md --guide --narrate
```

### Post-process only (recordings already exist)

From the repo root:

```bash
python tools/dub_natural.py
```

That dubs `output/recordings/quick-start-automation` and writes
**`full-dark-narrated.mov`** (plus per-step `-narrated.mov` files) right next to
the originals. Your source recordings are never touched.

Common options:

```bash
python tools/dub_natural.py --dir output/recordings/<workflow>   # a different workflow
python tools/dub_natural.py --voice "Ava (Premium)"              # force a voice
python tools/dub_natural.py --rate 165                           # slower = clearer (default 172 wpm)
python tools/dub_natural.py --lead-in 0.6 --tail 0.4             # padding around each step's voice
```

If you don't pass `--voice`, it auto-picks the best Enhanced voice you have
installed (falling back to a standard voice with a warning if none).

## 3. Edit the words

The spoken script lives in `narration.txt` inside each recording folder, e.g.
`output/recordings/quick-start-automation/narration.txt`. One block per step:

```
[step 1]
Let's build our very first automation in WSO2 Integrator. ...

[step 2]
Now that our project is ready ...
```

Edit it freely and re-run — keep the `[step N]` headers. If a folder has no
`narration.txt`, the tool falls back to a bare-bones script from `index.md`.

### Intro & outro (paused first/last frame)

Add optional `[intro]` and `[outro]` blocks. The `[intro]` plays over a
**frozen first frame** — the video is paused until the intro finishes, then it
starts playing (so the opening line never talks over the first action). The
`[outro]` plays over a frozen last frame at the end.

```
[intro]
Let's build our first automation. In just a few minutes we'll go from an
empty project to a running task.

[step 1]
First, skip the sign-in for now. Then click Create...

...

[outro]
And that's your first automation up and running. Thanks for watching.
```

## Perfect sync (recommended)

There are three ways lines get timed, best first — the tool uses whichever is
available:

1. **Exact recorded action times (best).** When you record with `main.py`,
   FlowCast now saves the precise timestamp of every click to `timings.json`
   next to the recordings. Narration lines snap onto those exact moments — no
   guessing. This is automatic for anything recorded from now on. To get it for
   an older video, just re-record it once:

   ```bash
   uv run python main.py workflows/quick-start-automation.md
   ```

2. **Manual @time pins.** For an existing video you don't want to re-record,
   pin any line to an exact second in its step clip by starting the line with
   `@<seconds>`. Watch the clip, note when each action happens, and write:

   ```
   [step 1]
   @0.0 First, skip the sign-in for now.
   @3.2 Then click Create and name it HelloWorld.
   @6.8 Finally, hit Create Integration.
   ```

   Pinned lines are placed exactly there; unpinned lines are auto-placed.

3. **Scene detection (fallback).** If there are no recorded times and no pins,
   the tool detects on-screen changes and places lines there (a good guess, but
   not perfect).

## Per-action mode (each action = its own clip + its own voice)

Every action gets its **own video clip and its own voice line**, joined in
order. Each action clip **waits** for its narration to finish — if the line is
longer than the on-screen action, that clip's last frame is held until the
voice catches up — then it cuts to the next action. Voice and screen stay
locked together, action by action, with zero overlap or drift.

How it gets the per-action clips (best first):

1. **Saved action clips (most robust).** When you record with `main.py`,
   FlowCast now keeps a separate clip for every action in `action_clips/` (plus
   `action_clips.json`). Narration dubs each of those clips individually — no
   splitting, no guessing. Just re-record once:

   ```bash
   uv run python main.py workflows/quick-start-automation.md
   ```

2. **Split by recorded offsets.** If only `timings.json` exists, the combined
   step clip is split at the recorded action times.

3. **Overlay fallback.** If neither exists, the voice is placed on the
   continuous clip via scene detection.

Your `narration.txt` lines (one per action) are used as the wording; if the
line count doesn't match the action count, the recorded action labels are used
so it's always 1:1. To disable per-action and overlay instead:

```bash
python tools/dub_natural.py --no-wait
```

## How timing works (and how to fix drift)

A step usually contains several on-screen actions spread across many seconds.
Instead of reading the whole step's narration at the very start of the clip
(which makes the voice run ahead of, or behind, the screen), the tool splits
each step's narration into **sentences** and places each sentence at the moment
its action actually happens on screen — detected via scene changes in the clip.
Each line starts a hair before its action (`--lead-in`), and lines are never
allowed to overlap. If narration outruns a clip the last frame is held; if the
clip is longer it plays out. Dubbed step clips are then concatenated, so the
full video stays in sync.

**One sentence = one on-screen action.** For the tightest sync, write
`narration.txt` so each step has roughly one sentence per action, in the order
they happen. Fewer sentences than actions = looser sync; that's fine, they just
spread across the step.

### Sync knobs

```bash
python tools/dub_natural.py --sync scene      # align to on-screen changes (default)
python tools/dub_natural.py --sync even       # ignore scenes, spread lines evenly
python tools/dub_natural.py --sync start      # old behaviour: all at the clip start
python tools/dub_natural.py --scene-threshold 0.2   # lower = more anchor points
python tools/dub_natural.py --lead-in 0.5     # start each line 0.5s before its action
python tools/dub_natural.py --rate 165        # slower voice = each line is shorter to place
```

If a step's voice still drifts: it usually means the sentence count doesn't
match the action count. Edit that step's block in `narration.txt` (split or
merge sentences so each maps to one action) and re-run. If scene detection is
noisy (cursor movement, animations), try `--sync even`, or raise
`--scene-threshold` toward 0.4–0.5 to anchor only on big changes.

## vs. the built-in `--dub`

The repo already has `python main.py <workflow>.md --dub`, but it reads the raw
click steps aloud ("Select Create. Set Integration Name to HelloWorld…"), which
sounds mechanical. `dub_natural.py` reads the conversational `narration.txt`
with an Enhanced voice and adds lead-in/tail pacing instead.
