# FlowCast Studio (macOS)

A native Mac app over the FlowCast pipeline: browse every page of the
[WSO2 Integrator docs](https://wso2.com/integration-platform/docs/) as cards,
see which ones FlowCast can follow on its own, and turn any of them into a
narrated screen recording in your cloned voice.

```bash
mac/build.sh --install   # → ~/Applications/FlowCast Studio.app, the only copy
mac/build.sh             # build only, into mac/build/
```

`--install` moves the app rather than copying it, so there is one FlowCast
Studio on the Mac. The app is single-instance: a new launch closes older copies
(one that is mid-recording asks first).

Needs Xcode's command line tools (Swift 5.10+), `uv`, `ffmpeg`, and the
`.venv-voice` environment from `tools/README-voice-clone.md`.

## Which docs can FlowCast follow?

`tools/docs_audit.py` reads the docs' Markdown source
([wso2/docs-integrator](https://github.com/wso2/docs-integrator)) and runs every
instruction through FlowCast's real parser. Each page gets one verdict:

| Verdict | Meaning |
|---|---|
| **100% followable** | every line becomes an action, nothing outside WSO2 Integrator is needed — records hands-free |
| **Auto setup** | every line parses once FlowCast starts the page's broker or database itself and sends its test event — hands-free, needs Docker |
| **Needs your keys** | every line parses; the page's configurables need values only you have (API key, tenant URL) |
| **After setup** | every line parses, but the page needs something nobody can hand FlowCast (an account to sign up for) |
| **Needs a person** | some lines have no action (e.g. binding a field to a configurable); FlowCast stops there for you, then replays what you did next time |
| **Not a walkthrough** | concepts, reference, overviews |

## Prerequisites, keys and checkpoints

* **Prerequisites** — `kb/prereq_recipes.json` lists what FlowCast can start as a
  local container (RabbitMQ, Kafka, MQTT, MySQL, PostgreSQL, SQL Server, Redis,
  MongoDB, ActiveMQ, Solace, SFTP, SMTP). The **Prerequisites** stage starts
  Docker (colima) if needed, starts the containers, and waits until they answer.
  Event pages get their test event too: "publish a message in the management UI"
  becomes a command FlowCast runs. Settings › Services lists and stops them.
* **Keys and values** — a page's configurables appear in its detail panel.
  Secrets go to your login Keychain. During the run, `tools/write_config.py`
  writes them into the project's `Config.toml` — never typed on screen, never in
  the video, workflow files or logs. Values a started container provides (host,
  port, user, password) fill themselves in.
* **Checkpoints** — a line FlowCast has no action for is kept in the workflow as
  `<!-- manual: … -->`. The run stops there with the doc's own words; you tell
  FlowCast what to do one command at a time (each is recorded), then Continue.
  What you did is saved in `kb/checkpoint_answers.json` and replayed on the next
  run of that page, so you teach each gap once.

The app's **Refresh docs** button re-pulls the docs and re-audits them. From a
terminal: `uv run python tools/docs_audit.py`, then `--list ready` or
`--show <slug>` for a line-by-line parse.

## Making a video

**Make video** on a card runs five stages, each a command you can also run by hand:

| Stage | Command |
|---|---|
| Prepare | `tools/studio.py prepare <slug> [--fresh-projects]` — copies the generated workflow to `workflows/` (refreshing a generated copy; delete its first line to keep your edits), archives any old recording |
| Prerequisites | `tools/studio.py setup <slug>` — starts the page's containers |
| Record | `tools/autopilot.py workflows/<slug>.md` — guide mode, tapping every action itself; one clip per action |
| Script | `tools/studio.py narration <slug>` — one spoken line per clip |
| Voice clone | `tools/studio.py voice <slug>` — `narrate_sync.py` with Chatterbox and your reference |
| Master | `tools/studio.py master <slug>` — `make_youtube_video.py`, intro in the same voice |

When an action fails, the run pauses and the app shows the screen at that
moment with **Retry**, **Skip this action**, **Finish step**, or a box for a
command (`click Create`, `at 712,561`). What you answer is executed, recorded
and learned. Finished videos land in `output/youtube/<slug>/` and in **Library**.

**Settings › Voice** records a new 15-second reference sample from the mic and
can speak a test line in the cloned voice.

Each finished video gets a folder in `~/Movies/FlowCast Studio`:

```
2026-10-03 Build a File-Driven Integration in WSO2 Integrator/
    YouTube/   the video, its thumbnail, the title + description to paste
    Medium/    "… – Medium article.txt" (paste into a new story) and ".html"
               (open, copy, paste: keeps headings, lists, code), plus
               "01 Create the integration.gif" … one GIF per step
```

The article marks where each step's GIF goes — Medium takes images only by
upload. GIFs are 960 px, 10 fps, under Medium's 25 MB limit (src/medium.py).
`tools/studio.py package [slug]` rebuilds folders in this layout.

Two lanes: one video uses the screen at a time (Prepare, Prerequisites,
Record); recorded videos are scripted, voiced and mastered alongside, one at a
time, at background priority (`taskpolicy -b`) while something is recording.
Queue several videos and record them back to back — the voicing happens
behind you.

What keeps a recording responsive: the screen capture for the next action
starts while you decide (src/recorder.py `prewarm`), so a tap moves the mouse
at once; clips are lossless x264 `ultrafast`, tidied by stream copy instead of
a re-encode; screenshots go through Quartz (src/fastcap.py, 0.05 s instead of
0.45 s); learning from a successful action happens on a background thread; and
in app runs (`FLOWCAST_DOC_ARTIFACTS=0`) the docs GIFs and joined tutorial are
skipped and each step's clips are joined in the background.

## Accounts, keys and the binding lesson

FlowCast never signs in or creates accounts. You sign in to a service yourself
once (sessions persist), enter its keys in the page's form (Keychain), and
FlowCast writes them to `Config.toml` off camera. Cards say which account a
page needs ("Your SAP account").

Every connector example also binds its connection fields to configurable
variables. Each page's plan (field → variable) is extracted from the docs. The
first time, the run asks you to bind one field with typed commands (`click
Hostname`, `click Configurables`, `click New Configurable`, `type sfHostname
into Variable Name`, `click Save`); FlowCast turns that into a template
(`kb/macros.json`) and binds every field on every later page itself. Fields
inside a record (`Config.username`) are a second, one-time lesson.

At docs commit cbe6b2d: 4 pages run hands-free today; one binding lesson plus
your keys adds 10; the nested-field lesson adds 21 more (mostly SAP); 40 more
need one extra line shown once each.

## When a recording gets stuck

FlowCast works down a ladder before it bothers you:

1. wait and retry (a panel still sliding in)
2. replay the fix that worked here last time (`kb/fixes.json`)
3. scroll down (a target below the fold)
4. ask a local Ollama model — **ornith:9b** by default — to choose which of the
   on-screen items the walkthrough named should be opened. It can only pick
   labels that are really there; on the real stuck File-Driven screen it chose
   `onModify`, the fix a person used. Settings › Help picks the model.
5. ask you — on the Mac and on your phone

After any fix, the action that led astray (a "+" that opened the wrong view) is
redone and the stuck action retried. Clips of attempts that did not work are
removed, so the video shows the fix, not the fumble. What worked is saved and
tried first next time, so every problem costs you (or the model) once.
`kb/run_history.json` records each run; a card says **Proven hands-free** only
after a real run finished without you.

## Phone

The phone link starts with every recording (Settings › Help) and its QR code is
on the "needs you" card; the toolbar's phone button shows it any time. The page
lists the same cards, starts videos and follows progress. With **Turn on
alerts** tapped once it chimes (and vibrates on Android) when a run needs you;
**tap the screenshot where FlowCast should click**, confirm, and it clicks
there, retries the step, and learns the fix. Keep the page open — a plain-HTTP
LAN page cannot receive push notifications when closed. Every request needs the per-launch token
in the link, and that link drives the Mac, so don't share it.

Going back in a step-by-step run (phone and the Mac's Runs view):

| Control | What it does | The video |
|---|---|---|
| Tap a ✓ action | does it again — for one marked done that did not take | its earlier try is removed |
| ↶ Undo last | takes back the last action and offers it again; presses ⌘Z only if it typed | that clip is removed |
| ⟲ Step N again | starts the current step from its first action | the step's clips are removed |
| ◀ Back to step N | goes back a step; both steps are recorded again | both steps' clips are removed |
| ⏮ Start over | stops, moves the project aside (~/WSO2Integrator-archive), records from step 1 | new recording |
| ■ Stop · pick another | stops this video; pick another from the list | — |

Undo, step again and back fix the video and the saved path, not WSO2
Integrator's screen (only typing is ⌘Z'd): put the screen back with a command
or a tap on the screenshot, or use Start over for a clean slate.

## Permissions

Recording happens in a Python child process, but macOS grants the permissions to
this app. Grant **Screen Recording** and **Accessibility** to FlowCast Studio
(Settings › Permissions has shortcuts), then quit and reopen it. The first run
also asks to control WSO2 Integrator and System Events.

`build.sh` signs with your Apple Development identity when one exists, so these
grants survive rebuilds.

## Launch arguments

`-FCSection ready|setup|partial|all|runs|library`, `-FCInspect <slug>` and
`-FCPhone YES` open the window on a given view, with a page's details, or with
the phone link running.
