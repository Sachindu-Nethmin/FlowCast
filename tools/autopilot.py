#!/usr/bin/env python3
"""
autopilot.py — record a workflow hands-free, asking a person only when stuck.

`--phone` guide mode records one clip per action (the clips voice-clone
narration is synced to), but a person taps every line. This runs the same
guide loop in-process and taps for you: each step's parsed actions are fed in
order as `#action:N`, exactly what the phone page sends.

A line FlowCast has no action for is written into generated workflows as
`<!-- manual: … -->`. The run stops there and hands you the doc's words; what
you do is recorded, and saved to kb/checkpoint_answers.json so the next run of
the same page replays it instead of asking (until a replayed command fails).
Answer `next` when that line is done.

When an action fails, it is retried after a pause, then with the fix you gave
last time (kb/fixes.json), then once more after scrolling down (a target below
the fold), and only then does the run pause and ask you — on stdin, as one
JSON event, which FlowCast Studio puts on your phone. Step by step (--guided)
you are asked at once. No local model is used while recording:

    retry           run the same action again
    skip            leave this action out and go on
    ok              finish this step now
    abort           stop the recording
    <anything>      a guide command, e.g. "click Create" or "at 512,300";
                    it is executed and recorded in place of the failed action

Machine-readable progress goes to stdout as lines starting `@@studio ` + JSON
(start / step / action / help / done); everything else is FlowCast's own log.

    uv run python tools/autopilot.py workflows/<slug>.md

Writes output/recordings/<slug>/actions.json: the label of every clip in
guid/, in order — what tools/studio.py writes narration against.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import subprocess
import threading
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("FLOWCAST_NO_PROMPT", "1")      # healer must never block on input()
os.environ.setdefault("FLOWCAST_STEP_INPUT", "0")
# Recording for a video: no docs GIFs / joined tutorial (src/guide._video_only).
os.environ.setdefault("FLOWCAST_DOC_ARTIFACTS", "0")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src import guide, kb_learn, recorder, runner  # noqa: E402
from src.artifacts import slug as _slug  # noqa: E402
from src.interactive import action_to_markdown  # noqa: E402
from src.parser import _parse_instructions, parse_markdown  # noqa: E402

OUTPUT = ROOT / "output" / "recordings"

# Lines the current UI may simply not show: the sign-in card is absent when
# already signed in. Failing on one of these is not worth a person's time.
OPTIONAL = ("skip for now",)
# Actions that put text in a field: ⌘Z takes those back. Undoing a click only
# takes it out of the video — ⌘Z there could undo an earlier edit instead.
TYPING = ("type", "search", "select")


class _Tee:
    """Keep the tail of FlowCast's own log, to explain a failure."""

    def __init__(self, stream) -> None:
        self.stream = stream
        self.tail: collections.deque[str] = collections.deque(maxlen=40)
        self._buf = ""

    def write(self, s: str) -> int:
        self.stream.write(s)
        self._buf += s
        *lines, self._buf = self._buf.split("\n")
        self.tail.extend(ln for ln in lines if ln.strip())
        return len(s)

    def flush(self) -> None:
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


_tee = _Tee(sys.stdout)
sys.stdout = _tee


def emit(event: str, **data) -> None:
    _tee.stream.write("@@studio " + json.dumps({"event": event, **data}) + "\n")
    _tee.stream.flush()


def _plain(label: str) -> str:
    return guide._plain(label).rstrip(".")


CHECKPOINT = re.compile(r"<!--\s*manual:\s*(.*?)\s*-->")
STEP_HEAD = re.compile(r"^#{2,3}\s+Step\s+\d+", re.I)
LEARNED = ROOT / "kb" / "checkpoint_answers.json"
FIXES = ROOT / "kb" / "fixes.json"              # what unstuck a failed action, per page
HISTORY = ROOT / "kb" / "run_history.json"      # evidence of hands-free runs
MACROS = ROOT / "kb" / "macros.json"            # how to bind a field, learned once
PROVEN = ROOT / "kb" / "proven.json"            # the path a guided run took, replayed after
BINDING_LINE = re.compile(r"\b(bind|bound|binding)\b.*configurable|configurable.*\b(bind|bound)\b", re.I)
# Clicks that open whatever is under the cursor's context. When one of these
# "succeeds" in the wrong view (the + of a configuration form instead of the
# flow diagram), the action after it fails — so after a fix it is redone.
OPENER = re.compile(r"^\+|^add\b|^\+ add\b", re.I)
GENERIC = {"+", "save", "create", "run", "test", "execute", "skip for now", "create integration",
           "create new integration", "save connection", "+ add artifact", "+ add handler",
           "add artifact", "add handler", "add connection", "call function", "automation"}
CONTINUE = ("next", "done", "continue", "ok", "")


_ORIG_RESOLVE = runner.resolve
_PILOT: "Pilot | None" = None


def _resolve(action: dict) -> dict:
    """runner.resolve, but answered from the pre-located next action when it is
    the one being run — the screen has not changed while you looked at the phone."""
    p = _PILOT
    if p is not None and p.pre is not None and p.pre[0] == _plain(action_to_markdown(action)):
        found = dict(p.pre[1])
        p.pre = None
        return found
    return _ORIG_RESOLVE(action)


def _window_open() -> bool:
    r = subprocess.run(["osascript", "-e", 'tell application "System Events" to '
                        'if exists process "WSO2 Integrator" then return count of windows of '
                        'process "WSO2 Integrator"'], capture_output=True, text=True, timeout=10)
    return (r.stdout.strip() or "0") not in ("0", "")


def _full_screen_when_ready(timeout: float = 45) -> None:
    """WSO2 Integrator in native full screen — once its window exists.

    ensure_fullscreen(force=True) at the start of a step does nothing while the
    app is still launching (no window yet), and the per-action checks after it
    only maximise. So: wait for the window, then ask for full screen."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if _window_open():
                time.sleep(2.0)                 # let the first window settle
                runner.ensure_fullscreen(force=True)
                return
        except Exception:
            pass
        time.sleep(1.0)
    print("  [autopilot] WSO2 Integrator window did not appear — full screen not set")


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except json.JSONDecodeError:
        return {}


def _save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))


def checkpoints(md: Path) -> dict[int, list[tuple[int, str]]]:
    """{step: [(index of the action it comes before, the doc's words)]}.

    doc_catalog writes a line FlowCast cannot do as `<!-- manual: … -->`. The
    parser strips HTML, so to guide mode it does not exist; counting the
    actions each line before it makes tells us where to stop and ask."""
    out: dict[int, list[tuple[int, str]]] = {}
    step, count = 0, 0
    for line in md.read_text().splitlines():
        if STEP_HEAD.match(line):
            step, count = step + 1, 0
            continue
        m = CHECKPOINT.search(line)
        if m and step:
            out.setdefault(step, []).append((count, m.group(1)))
        elif step and re.match(r"^\s*\d+\.\s", line):
            count += len(_parse_instructions(line))
    return out


class Pilot:
    def __init__(self, steps, out_dir: Path, slug: str = "",
                 manual: dict[int, list[tuple[int, str]]] | None = None,
                 guided: bool = False) -> None:
        self.steps = steps
        self.out_dir = out_dir
        self.slug = slug
        self.manual_points = manual or {}
        self.step = None
        self.step_idx = 0
        self.next = 0            # next action index to tap
        self.current: int | None = None
        self.last_ok: bool | None = None
        self.correcting = False
        self.recovery: dict[tuple[int, int], int] = {}   # 1 = waited, 2 = scrolled
        self.after_scroll = False
        self.help_seq = 0
        self.clips: list[dict] = []
        # manual checkpoint state
        self.checkpoint: tuple[int, str] | None = None
        self.done_points: set[tuple[int, int, str]] = set()
        self.replay: list[str] | None = None
        self.taught: list[str] = []
        self.pending: str | None = None
        self.learned = _load(LEARNED)
        self.fixes = _load(FIXES)
        self.macros = _load(MACROS)
        self.replay_source: str | None = None
        # Guided: you take every action from the phone; what you did becomes the
        # path. Otherwise a path proven by an earlier guided run is replayed.
        self.guided = guided
        self.proven = _load(PROVEN).get(slug) if not guided else None
        self.path: dict[int, list[str]] = {}     # ops this run, per step
        self.ops: list[str] | None = None         # proven ops left in this step
        self.guided_cmd: str | None = None
        self.done_idx: set[int] = set()
        # The next action, already located while you look at the phone, so a
        # tap acts at once (runner.resolve is patched to use it).
        self.pre: tuple[str, dict] | None = None
        self._pre_thread: threading.Thread | None = None
        try:
            from src import doc_catalog
            page = next((p for p in doc_catalog.load().get("pages", []) if p["slug"] == slug), {})
            self.bindings: list[dict] = page.get("bindings") or []
        except Exception:
            self.bindings = []
        self.episode: dict | None = None     # recovering from one failed action
        self.episodes = 0
        self.attempts = 0
        self.stats = {"asked_person": 0, "manual_lines": 0, "ai_fixes": 0, "learned_replays": 0,
                      "auto_retries": 0}

    # guide._guide_step wrapper: know which step we are in
    def guide_step(self, orig):
        def wrapped(step, step_idx, *a, **kw):
            self.step, self.step_idx = step, step_idx
            self.next, self.current, self.last_ok = 0, None, None
            self.done_idx = set()
            self.path[step_idx] = []
            ops = (self.proven or {}).get("steps", {}).get(str(step_idx))
            self.ops = list(ops) if ops else None
            emit("step", n=step_idx, title=step.title,
                 actions=[_plain(action_to_markdown(x)) for x in step.actions],
                 manual=[t for _, t in self.manual_points.get(step_idx, [])])
            given = step
            if any(pos >= len(step.actions) for pos, _ in self.manual_points.get(step_idx, [])):
                # Guide mode ends a step the moment its last listed action
                # succeeds, which would skip a checkpoint that comes after it.
                # One unlisted, never-tapped action keeps the step open until
                # prompt_next says "ok".
                given = dataclasses.replace(step, actions=[*step.actions,
                                                           {"action": "wait", "seconds": 0}])
            mov, meta = orig(given, step_idx, *a, **kw)
            if self.episode is not None:
                # The retried action was the step's last, so guide mode closed
                # the step without asking what next: settle the fix here.
                if self.last_ok and self.episode["phase"] == "retry":
                    self._succeeded()
                self.episode = None
            emit("step_done", n=step_idx, status=meta.get("status", "recorded"),
                 video=str(mov) if mov else None)
            return mov, meta
        return wrapped

    # guide._execute_command wrapper: know whether the action worked
    def execute(self, orig):
        def wrapped(command, tmp_dir, clip_idx, step_idx):
            if command.get("_direct") and command.get("action") == "click":
                # A tap on the phone's screenshot ("at x,y"). Guide mode fires
                # those without filming them; route it through the normal path
                # (located already) so the click is in the video.
                command = {k: v for k, v in command.items() if k != "_direct"}
                self.pre = (_plain(action_to_markdown(command)), dict(command))
            ok, clip = orig(command, tmp_dir, clip_idx, step_idx)
            if ok and command.get("action") == "open_app":
                _full_screen_when_ready()
            label = _plain(action_to_markdown(command))
            self.last_ok = ok
            if ok and not self.correcting and self.current is not None:
                self.done_idx.add(self.current)
            if ok and clip:
                # The name guide mode gives the copy it is about to put in guid/
                # (src/guide.py): typed commands keep their own wording.
                raw = (self.episode or {}).get("pending") if self.correcting else None
                raw = raw or (self.pending if self.correcting and self.pending else None) \
                    or action_to_markdown(command)
                self.clips.append({"step": step_idx, "label": label,
                                   "index": self.current, "correction": self.correcting,
                                   "kind": command.get("action"),
                                   "attempt": (self.episode or {}).get("attempt"),
                                   "episode": (self.episode or {}).get("n"),
                                   "file": f"step{step_idx:02d}_action{clip_idx:03d}_{_slug(raw[:40])}.mov"})
            emit("action", step=step_idx, index=self.current, label=label, ok=ok,
                 clip=bool(clip), correction=self.correcting)
            return ok, clip
        return wrapped

    def ask(self, reason: str, kind: str = "failed", text: str = "", tried: list | None = None,
            step_info: dict | None = None) -> str:
        """Block until whoever launched us answers on stdin."""
        self.help_seq += 1
        shot = self.out_dir / f"help-{self.help_seq:03d}.png"
        if kind == "step":
            # A full-size PNG per step cost ~1 s before every prompt; the phone
            # asks the app for the current screen only when you open it.
            shot = None
        else:
            try:
                runner._screenshot().save(str(shot))
            except Exception:
                shot = None
        if kind in ("manual", "step"):
            label, failure = text, reason
        else:
            label = _plain(action_to_markdown(self.step.actions[self.current])) \
                if self.current is not None and self.current < len(self.step.actions) else ""
            failure = next((ln.strip() for ln in reversed(_tee.tail) if "✗" in ln), reason)
        size = runner.screen_size()
        emit("help", seq=self.help_seq, step=self.step_idx, index=self.current, kind=kind,
             label=label, reason=failure, screenshot=str(shot) if shot else None,
             screen=[size[0], size[1]], tried=tried or [], **({"step_info": step_info} if step_info else {}),
             context=list(_tee.tail)[-12:])
        if kind == "step" and step_info and step_info.get("next") is not None:
            self._start_preresolve(step_info["next"])
        # The screen capture for whatever you send starts now, while you
        # decide; your tap then moves the mouse at once (src/recorder.py).
        recorder.prewarm()
        line = sys.stdin.readline()
        if self._pre_thread is not None:
            self._pre_thread.join(timeout=15)    # never resolve twice at once
            self._pre_thread = None
        if not line:                      # launcher went away
            return "abort"
        return line.strip()

    def _start_preresolve(self, i: int) -> None:
        act = self.step.actions[i]
        self.pre = None
        if act.get("action") not in ("click", "type", "select", "search"):
            return

        def work() -> None:
            try:
                r = _ORIG_RESOLVE(dict(act))
                if r and r.get("x") is not None and not r.get("_skip"):
                    self.pre = (_plain(action_to_markdown(act)), r)
            except Exception:
                pass                       # the tap resolves it again, with recovery
        self._pre_thread = threading.Thread(target=work, daemon=True)
        self._pre_thread.start()

    # ── manual checkpoints ──────────────────────────────────────────────────

    def _key(self) -> str:
        return f"{self.step_idx}|{self.checkpoint[1]}"

    def _point_at(self, index: int) -> tuple[int, str] | None:
        for pos, text in self.manual_points.get(self.step_idx, []):
            if pos == index and (self.step_idx, pos, text) not in self.done_points:
                return pos, text
        return None

    def _macro_commands(self) -> list[str] | None:
        """The binding template filled in for every field this page binds."""
        simple = self.macros.get("bind", {}).get("commands")
        nested = self.macros.get("bind_nested", {}).get("commands")
        if not self.bindings:
            return None
        out: list[str] = []
        for b in self.bindings:
            tpl = nested if b.get("nested") else simple
            if not tpl:
                return None           # a kind of field nobody has shown FlowCast yet
            for c in tpl:
                out.append(c.replace("{field}", b["field"]).replace("{sub}", b.get("sub") or "")
                            .replace("{var}", b["variable"]).replace("{type}", b.get("type") or "string"))
        return out

    def _learn_macro(self, cmds: list[str]) -> None:
        """Turn the commands you used to bind ONE field into a template.

        Finds the first field whose name and variable both appear in what you
        typed, takes the commands from its first mention up to the next field's,
        and replaces the names with {field} / {var} / {type}. Clicks by
        coordinates do not generalise across fields, so they are not learned."""
        for kind, group in (("bind", [b for b in self.bindings if not b.get("nested")]),
                            ("bind_nested", [b for b in self.bindings if b.get("nested")])):
            for n, b in enumerate(group):
                names = [b["field"], b["variable"]] + ([b["sub"]] if b.get("sub") else [])
                hits = [i for i, c in enumerate(cmds) if any(re.search(rf"\b{re.escape(x)}\b", c, re.I) for x in names)]
                if not hits or not any(re.search(rf"\b{re.escape(b['variable'])}\b", c) for c in cmds):
                    continue
                nxt = group[n + 1] if n + 1 < len(group) else None
                end = len(cmds)
                if nxt:
                    later = [i for i, c in enumerate(cmds) if i > hits[0] and re.search(
                        rf"\b{re.escape(nxt['field'] if not nxt.get('nested') else nxt['sub'])}\b", c, re.I)]
                    end = later[0] if later else end
                seg = cmds[hits[0]:end]
                if any(re.match(r"^(?:click\s+)?at\s+\d", c, re.I) for c in seg):
                    print("  [autopilot] binding used screen positions — not generalisable; "
                          "type commands like 'click Configurables' to teach it")
                    break
                tpl = []
                for c in seg:
                    c = re.sub(rf"\b{re.escape(b['variable'])}\b", "{var}", c)
                    if b.get("sub"):
                        c = re.sub(rf"\b{re.escape(b['sub'])}\b", "{sub}", c)
                    c = re.sub(rf"\b{re.escape(b['field'])}\b", "{field}", c)
                    tpl.append(c)
                if any("{var}" in c for c in tpl):
                    self.macros[kind] = {"commands": tpl, "learned_from": self.slug,
                                         "learned_at": time.strftime("%Y-%m-%d")}
                    _save(MACROS, self.macros)
                    print(f"  [autopilot] learned how to bind a {'nested ' if kind == 'bind_nested' else ''}"
                          f"field: {' → '.join(tpl)} — used on every page from now on")
                break

    def _leave_checkpoint(self, learn: bool) -> None:
        pos, text = self.checkpoint
        if learn and self.taught and self.bindings and BINDING_LINE.search(text) \
                and self.replay_source != "macro":
            self._learn_macro(self.taught)
        self.replay_source = None
        self.done_points.add((self.step_idx, pos, text))
        if learn and self.taught:
            self.learned.setdefault(self.slug, {})[self._key()] = self.taught
            LEARNED.write_text(json.dumps(self.learned, indent=2))
            print(f"  [autopilot] learned {len(self.taught)} command(s) for this step — "
                  f"replayed automatically next time")
        self.checkpoint, self.replay, self.taught, self.pending = None, None, [], None
        self.last_ok, self.correcting = None, False

    def _manual(self) -> str:
        """In a checkpoint: replay what was taught, else ask the person."""
        if self.replay is not None:
            if self.pending and self.last_ok:
                self.taught.append(self.pending)      # kept if a later one breaks
            self.pending = None
            if self.last_ok is False:
                print("  [autopilot] a taught command did not work this time — asking you")
                self.replay = None
            elif self.replay:
                self.pending = self.replay.pop(0)
                self.correcting, self.last_ok = True, None
                return self.pending
            else:
                self._leave_checkpoint(learn=False)
                return self.prompt_next()
        if self.pending and self.last_ok:
            self.taught.append(self.pending)
        self.pending = None
        self.stats["manual_lines"] += 1
        answer = self.ask("this line needs you", kind="manual", text=self.checkpoint[1])
        low = answer.lower()
        if low in ("abort", "quit", "stop"):
            return "abort"
        if low in CONTINUE or low == "skip":
            self._leave_checkpoint(learn=low != "skip")
            return self.prompt_next()
        self.pending, self.correcting, self.last_ok = answer, True, None
        return answer

    # ── recovering from a failed action ─────────────────────────────────────
    #
    # The ladder, cheapest first: wait and retry → replay what fixed this spot
    # before → scroll → ask the local model to choose → ask you. Each fix is a
    # list of commands, then the failed action is tried again (after redoing a
    # "+"-style opener before it, which had opened the wrong thing). What
    # works is saved to kb/fixes.json and becomes the first thing tried next
    # time, so a fix costs you (or the model) once.

    def _label(self, i: int) -> str:
        return _plain(action_to_markdown(self.step.actions[i]))

    def _fix_key(self) -> str:
        step, i = self.episode["key"]
        return f"{step}|{self._label(i)}"

    def _opener_before(self) -> int | None:
        i = self.episode["key"][1] - 1
        if i >= 0:
            act = self.step.actions[i]
            if act.get("action") == "click" and OPENER.match((act.get("target") or "").strip()):
                return i
        return None

    def _begin(self, source: str, queue: list[str], redo: bool) -> str | None:
        self.attempts += 1
        ep = self.episode
        ep.update(source=source, queue=list(queue), cmds=[], pending=None, redo=redo,
                  attempt=self.attempts, phase="fixing")
        return self._recover()

    def _retry(self) -> str:
        ep = self.episode
        self.correcting, self.last_ok = False, None
        if ep["redo"] and self._opener_before() is not None:
            ep["phase"] = "redo"
            prev = self._opener_before()
            # The earlier tap of that opener went to the wrong view; its clip is
            # dropped once the fix is known to work (see _succeeded).
            ep["drop_opener"] = prev
            return f"#action:{prev}"
        ep["phase"] = "retry"
        return f"#action:{ep['key'][1]}"

    def _succeeded(self) -> None:
        ep = self.episode
        step, i = ep["key"]
        # Keep the clips of the attempt that worked; earlier tries (a wrong
        # guess, the first opener that went astray) leave the video.
        drop = [c for c in self.clips if c["step"] == step and c.get("attempt")
                and c.get("attempt") != ep["attempt"] and c.get("episode") == ep["n"]]
        if ep.get("drop_opener") is not None:
            prev = [c for c in self.clips if c["step"] == step and c["index"] == ep["drop_opener"]
                    and not c.get("attempt")]
            drop += prev[:1]
        for c in drop:
            (self.out_dir / "guid" / c["file"]).unlink(missing_ok=True)
            self.clips.remove(c)
        if ep["source"] in ("ai", "you") and ep["cmds"]:
            entry = {"commands": ep["cmds"], "then": "retry", "redo": ep["redo"],
                     "by": ep["source"], "learned_at": time.strftime("%Y-%m-%d")}
            self.fixes.setdefault(self.slug, {})[self._fix_key()] = entry
            _save(FIXES, self.fixes)
            print(f"  [autopilot] learned: {' → '.join(ep['cmds'])} fixes "
                  f"'{self._label(i)}' — used automatically next run")
        if ep["source"] == "ai":
            self.stats["ai_fixes"] += 1
        if ep["source"] == "learned":
            self.stats["learned_replays"] += 1
        emit("recovered", step=step, index=i, by=ep["source"], commands=ep["cmds"])
        self.episode = None

    def _next_stage(self) -> str | None:
        ep = self.episode
        step, i = ep["key"]
        act = self.step.actions[i]
        if self.guided:
            # Step by step you are at the phone already: you are asked at once
            # (no pause-and-retry, scroll or local-model guesses first). What
            # you do is still learned for the automatic runs.
            return self._ask_person()
        while True:
            ep["stage"] += 1
            stage = ep["stage"]
            if stage == 1:                                  # a panel still sliding in
                print("  [autopilot] retrying once after a short pause…")
                self.stats["auto_retries"] += 1
                time.sleep(2.0)
                self.attempts += 1
                ep.update(source="wait", attempt=self.attempts, redo=False, cmds=[])
                return self._retry()
            if stage == 2:                                  # what fixed it last time
                fix = self.fixes.get(self.slug, {}).get(self._fix_key())
                if fix:
                    print(f"  [autopilot] replaying the fix learned {fix.get('learned_at', '')}: "
                          f"{' → '.join(fix['commands'])}")
                    emit("recovering", step=step, index=i, by="learned", commands=fix["commands"])
                    out = self._begin("learned", fix["commands"], fix.get("redo", False))
                    ep["then"] = fix.get("then", "retry")
                    return out
                continue
            if stage == 3:                                  # below the fold
                if act.get("action") in ("click", "type"):
                    print("  [autopilot] not visible — scrolling down and trying again")
                    return self._begin("scroll", ["scroll down 5"], False)
                continue
            # Then you, on the phone. (A local model used to guess here; it
            # cost memory the voice stage needed and minutes per guess.)
            return self._ask_person()

    def _recover(self) -> str | None:
        ep = self.episode
        if ep["phase"] == "start":
            return self._next_stage()
        if ep["phase"] == "fixing":
            if ep["pending"] is not None:
                ok, done = self.last_ok, ep["pending"]
                ep["pending"] = None
                if ok is None:          # guide mode could not parse it — ask again
                    return self._ask_person() if ep["source"] == "you" else self._next_stage()
                if not ok:
                    ep["queue"] = []
                    return self._ask_person() if ep["source"] == "you" else self._next_stage()
                ep["cmds"].append(done)
                if ep["source"] == "you":
                    ep["you"].append(done)
            if ep["queue"]:
                cmd = ep["queue"].pop(0)
                ep["pending"] = cmd
                self.correcting, self.last_ok = True, None
                return cmd
            if ep.get("then") == "continue":
                self._succeeded()
                return None
            return self._retry()
        if ep["phase"] == "redo":
            ep["phase"] = "retry"
            self.correcting, self.last_ok = False, None
            return f"#action:{ep['key'][1]}"
        if ep["phase"] == "retry":
            if self.last_ok:
                self._succeeded()
                return None
            if ep["source"] == "you":
                return self._ask_person()
            return self._next_stage()
        return None

    def _ask_person(self) -> str | None:
        ep = self.episode
        self.stats["asked_person"] += 1
        ep["stage"] = 99
        tried = [c for c in ep["ai_tried"]]
        answer = self.ask("action failed", tried=tried)
        low = answer.lower().strip()
        if low in ("abort", "quit", "stop"):
            return "abort"
        if low in ("continue", "done", "ok", "next"):
            # Done by hand (with the commands sent so far): learn it as a
            # replacement for the action.
            if ep["you"]:
                self.fixes.setdefault(self.slug, {})[self._fix_key()] = {
                    "commands": ep["you"], "then": "continue", "redo": False, "by": "you",
                    "learned_at": time.strftime("%Y-%m-%d")}
                _save(FIXES, self.fixes)
            ep["source"] = "you"
            self.episode = None
            self.correcting, self.last_ok = False, None
            return self.prompt_next()
        if low == "skip":
            self.episode = None
            self.correcting, self.last_ok = False, None
            return self.prompt_next()
        if low in ("retry", "again", ""):
            ep["source"] = "you"
            return self._retry()
        # Your command runs, then the failed action is tried again.
        if ep["source"] != "you":
            self.attempts += 1
            ep.update(source="you", attempt=self.attempts, cmds=[], redo=False)
        ep["phase"], ep["queue"], ep["pending"] = "fixing", [], answer
        self.correcting, self.last_ok = True, None
        return answer

    # ── the decision ────────────────────────────────────────────────────────

    def prompt_next(self, voice: bool = False, label: str = "what next") -> str:
        """Stands in for the phone: decide what guide mode does next."""
        actions = self.step.actions
        if self.checkpoint is not None:
            return self._manual()
        if self.episode is not None:
            step_cmd = self._recover()
            if step_cmd is not None:
                return step_cmd
        elif self.last_ok is False and self.current is not None and not self.correcting:
            act = actions[self.current] if self.current < len(actions) else {}
            if (act.get("target") or "").lower() in OPTIONAL:
                print(f"  [autopilot] '{act.get('target')}' not on screen — optional, moving on")
            else:
                self.episodes += 1
                self.episode = {"n": self.episodes, "key": (self.step_idx, self.current),
                                "stage": 0, "phase": "start",
                                "queue": [], "pending": None, "cmds": [], "source": None,
                                "attempt": None, "redo": False, "ai_tried": [], "you": []}
                step_cmd = self._recover()
                if step_cmd is not None:
                    return step_cmd
        if self.guided_cmd is not None:
            # A command you sent from the phone becomes part of the path only if it worked.
            if self.last_ok:
                self.path[self.step_idx].append(f"cmd:{self.guided_cmd}")
            self.guided_cmd = None
        self.correcting = False
        self.last_ok = None

        point = self._point_at(self.next)
        if point:
            self.checkpoint, self.last_ok = point, None
            taught = self.learned.get(self.slug, {}).get(self._key())
            macro = self._macro_commands() if BINDING_LINE.search(point[1]) else None
            if taught:
                print(f"  [autopilot] replaying {len(taught)} taught command(s) for: {point[1][:70]}")
                self.replay, self.replay_source = list(taught), "taught"
            elif macro:
                print(f"  [autopilot] binding {len(self.bindings)} field(s) with the learned template")
                emit("recovering", step=self.step_idx, index=self.next, by="macro",
                     commands=[f"bind {b['field']}{'.' + b['sub'] if b['sub'] else ''} → {b['variable']}"
                               for b in self.bindings])
                self.replay, self.replay_source = macro, "macro"
            return self._manual()
        if self.guided:
            return self._ask_step()
        if self.ops is not None:
            return self._replay_path()
        if self.next >= len(actions):
            return "ok"
        self.current = self.next
        self.next += 1
        return f"#action:{self.current}"

    # ── guided: one action at a time, from the phone ────────────────────────

    def _tap(self, i: int) -> str:
        if self.pre and self.pre[0] != _plain(action_to_markdown(self.step.actions[i])):
            self.pre = None
        # Next comes the first action after this one not done yet — after a
        # redo, the actions that follow it are usually done already.
        self.current = i
        self.next = next((j for j in range(i + 1, len(self.step.actions)) if j not in self.done_idx),
                         len(self.step.actions))
        self.path[self.step_idx].append(f"#{i}")
        return f"#action:{i}"

    def _ask_step(self) -> str:
        """Show the step on the phone and do what is tapped there."""
        actions = self.step.actions
        while True:
            labels = [_plain(action_to_markdown(a)) for a in actions]
            nxt = self.next if self.next < len(actions) else None
            answer = self.ask("your move", kind="step",
                              text=labels[nxt] if nxt is not None else "Step done — continue",
                              step_info={"title": self.step.title, "actions": labels,
                                         "done": sorted(self.done_idx), "next": nxt,
                                         "can_undo": bool(self.path.get(self.step_idx)),
                                         "steps": len(self.steps)})
            low = answer.strip().lower()
            if low in ("abort", "quit", "stop"):
                return "abort"
            if low in ("", "next", "do", "do it", "go"):
                if nxt is None:
                    return "ok"
                return self._tap(nxt)
            if low.startswith("#action:"):
                try:
                    i = int(low.split(":", 1)[1])
                except ValueError:
                    continue
                if 0 <= i < len(actions):
                    if i in self.done_idx:
                        # Marked done but it did not take: do it again, and the
                        # earlier try leaves the video.
                        self._forget(i)
                    return self._tap(i)
                continue
            if low == "undo":
                if self._undo():
                    return "undo"         # guide mode presses ⌘Z
                continue
            if low in ("step over", "restart step"):
                gone = self._drop_clips([c for c in self.clips if c["step"] == self.step_idx])
                self.path[self.step_idx] = []
                self.done_idx, self.next, self.current, self.pre = set(), 0, None, None
                print(f"  [autopilot] step {self.step_idx} starts over ({gone} clip(s) out of the video)")
                continue
            if low in ("back", "previous"):
                # Guide mode goes back a step (from step 1: does step 1 again).
                # Both steps are recorded afresh, so their clips leave the video.
                target = max(1, self.step_idx - 1)
                gone = self._drop_clips([c for c in self.clips if c["step"] >= target])
                for n in [n for n in self.path if n >= target]:
                    del self.path[n]
                self.pre = None
                print(f"  [autopilot] back to step {target} ({gone} clip(s) out of the video)")
                return "back"
            if low == "skip":
                if nxt is not None:
                    self.path[self.step_idx].append(f"skip:{nxt}")
                    self.next = nxt + 1
                continue
            if low in ("ok", "done", "finish", "continue"):
                return "ok"
            # Your own command, before (or instead of) the next listed action.
            self.pre = None
            self.guided_cmd, self.correcting, self.last_ok = answer.strip(), True, None
            return answer.strip()

    def _drop_clips(self, clips: list[dict]) -> int:
        """Take clips out of the video: the file in guid/ and its log entry."""
        for c in clips:
            (self.out_dir / "guid" / c["file"]).unlink(missing_ok=True)
            if c in self.clips:
                self.clips.remove(c)
        return len(clips)

    def _forget(self, i: int) -> None:
        """Action i of this step is done again: its earlier tries go."""
        ops = self.path.get(self.step_idx, [])
        if f"#{i}" in ops:
            ops.remove(f"#{i}")
        self._drop_clips([c for c in self.clips if c["step"] == self.step_idx
                          and c["index"] == i and not c["correction"]])
        self.done_idx.discard(i)

    def _undo(self) -> bool:
        """Take back the last thing done in this step. True if it typed text."""
        ops = self.path.get(self.step_idx) or []
        if not ops:
            print("  [autopilot] nothing to undo in this step")
            return False
        op = ops.pop()
        if op.startswith("skip:"):
            self.next = int(op[5:])
            return False
        mine = [c for c in self.clips if c["step"] == self.step_idx]
        if op.startswith("#"):
            i = int(op[1:])
            tail = []
            for c in reversed(mine):     # the action and any retries of it
                if c["index"] != i or c["correction"]:
                    break
                tail.append(c)
            self.done_idx.discard(i)
            self.next = i
        else:
            tail = mine[-1:]             # a command you sent
        self.pre = None
        self._drop_clips(tail)
        print(f"  [autopilot] undid {op} ({len(tail)} clip(s) out of the video)")
        return any(c["kind"] in TYPING for c in tail)

    def _replay_path(self) -> str:
        """Follow the path the guided run took for this step."""
        while self.ops:
            op = self.ops.pop(0)
            if op.startswith("#"):
                return self._tap_replay(int(op[1:]))
            if op.startswith("skip:"):
                self.next = int(op[5:]) + 1
                continue
            if op.startswith("cmd:"):
                self.correcting, self.last_ok = True, None
                print(f"  [autopilot] proven path: {op[4:]}")
                return op[4:]
        self.ops = None
        return "ok"

    def _tap_replay(self, i: int) -> str:
        self.current, self.next = i, i + 1
        return f"#action:{i}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workflow", type=Path)
    ap.add_argument("--guided", action="store_true",
                    help="take every action from the phone; a complete run becomes the proven path")
    args = ap.parse_args()

    md = args.workflow if args.workflow.is_absolute() else ROOT / args.workflow
    steps = parse_markdown(md)
    slug = _slug(md.stem)
    out_dir = OUTPUT / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    emit("start", slug=slug, workflow=str(md), out_dir=str(out_dir),
         steps=[{"n": i, "title": s.title,
                 "actions": [_plain(action_to_markdown(a)) for a in s.actions]}
                for i, s in enumerate(steps, 1)])

    pilot = Pilot(steps, out_dir, slug, checkpoints(md), guided=args.guided)
    global _PILOT
    _PILOT = pilot
    runner.resolve = _resolve
    if pilot.proven:
        print(f"  [autopilot] following the path proven on {pilot.proven.get('proven_at', '?')}")
    guide._guide_step = pilot.guide_step(guide._guide_step)
    guide._execute_command = pilot.execute(guide._execute_command)
    guide._prompt_next = pilot.prompt_next

    started = time.time()
    try:
        # Open WSO2 Integrator first and wait for its window, so the whole run —
        # step 1 included — is filmed in native full screen.
        subprocess.run(["open", "-a", "WSO2 Integrator"], capture_output=True)
        _full_screen_when_ready()
        theme = runner.detect_theme()
        print(f"  Theme identified: {theme.upper()}")
        emit("theme", theme=theme)
        guide.run_guide(steps, out_dir, slug, theme)
    except Exception as e:
        emit("error", message=f"{type(e).__name__}: {e}")
        raise
    finally:
        recorder.discard_prewarm()
        kb_learn.flush()
        (out_dir / "actions.json").write_text(json.dumps(
            {"recorded_at": started, "clips": pilot.clips}, indent=2))
    guid = out_dir / "guid"
    fresh = [p for p in guid.glob("step*_action*.mov") if p.stat().st_mtime >= started - 1] \
        if guid.is_dir() else []
    recorded = _load(out_dir / "guide_metadata.json").get("recorded_steps")
    if args.guided and recorded == len(steps):
        proven = _load(PROVEN)
        proven[slug] = {"proven_at": time.strftime("%Y-%m-%d %H:%M"),
                        "steps": {str(n): ops for n, ops in pilot.path.items()}}
        _save(PROVEN, proven)
        print(f"  [autopilot] every step recorded — this path is saved; the next run is automatic")
        emit("proven", slug=slug)
    run = {"slug": slug, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - started),
           "mode": "guided" if args.guided else ("proven" if pilot.proven else "auto"),
           "steps": len(steps), "recorded": recorded, **pilot.stats,
           "hands_free": not args.guided and recorded == len(steps) and pilot.stats["asked_person"] == 0
                         and pilot.stats["manual_lines"] == 0}
    hist = _load(HISTORY)
    hist.setdefault(slug, []).append(run)
    _save(HISTORY, hist)
    emit("history", **run)
    emit("done", slug=slug, clips=len(fresh), labelled=len(pilot.clips),
         seconds=round(time.time() - started))


if __name__ == "__main__":
    main()
