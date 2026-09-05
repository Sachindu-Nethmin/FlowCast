# Narration script and YouTube copy

## narration.txt

Lives next to the recordings: `output/recordings/<slug>/narration.txt`.
`src/narrate.py` reads blocks keyed by tag; `#` lines are comments.

```
[card]      → spoken over the branded title card (this skill's intro)
[intro]     → spoken over a FROZEN first frame of step 1 (video paused)
[step N]    → one line per on-screen action, in order
[outro]     → spoken over a frozen last frame
[endcard]   → optional, spoken over the "Thanks for watching" card
```

`[card]` and `[endcard]` are read by `tools/make_youtube_video.py`;
`[intro]`, `[step N]` and `[outro]` are read by `src/narrate.py`.

### Rules that keep the voice in sync

* **One line per action.** Each step's lines are matched to the recorded
  per-action clips in order — the clip waits for its line, so a missing line
  makes the voice run ahead of the screen and an extra line makes it lag.
* **Short sentences.** The cloned voice drifts on paragraph-length lines; keep
  each under about 15 words.
* Prefix a line with `@12.5` to pin it to an exact second in that step's clip
  when automatic placement is off.
* Speak the *intent*, not the click: "Give the agent its instructions" beats
  "Set the Instructions field to the following value".
* Say values out loud only when they matter (a URL, a base path). Skip GUIDs.
* Never read the literal UI casing of code values — say "slash hello", not
  "forward slash h-e-l-l-o".

### Shape of a good script

```
[card]
Let's expose a REST API in WSO2 Integrator — no code required.

[intro]
We'll create an integration, add an HTTP service, call an external API, and
return its response. It takes about five minutes.

[step 1]
Start by opening WSO2 Integrator.
Create a new integration.
Name it Hello World API.
...

[outro]
That's a working REST API, built and tested end to end. Thanks for watching.
```

## Video title

* Under 60 characters so it is not truncated in search results.
* Front-load the outcome, then the product: **"Build a Hello World REST API in
  WSO2 Integrator"**, not "WSO2 Integrator tutorial part 1".
* No clickbait, no ALL CAPS — these are product docs videos.

## Filename

`tools/make_youtube_video.py` derives it from the title:
`Build-a-Hello-World-REST-API-in-WSO2-Integrator.mp4`. Keep the title clean and
the filename follows.

## Description

Generated into `<Title>.description.txt` with chapters already timed. Before
handing it over, check that:

* the first chapter is `0:00`,
* there are at least three chapters (YouTube ignores fewer),
* each chapter is at least 10 seconds long (the tool folds shorter steps in).

## Thumbnail

1280x720, same card design as the intro, written next to the master. It is
deliberately typographic: the recording itself is dense UI, so a busy thumbnail
reads as noise at feed size.
