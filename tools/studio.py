#!/usr/bin/env python3
"""
studio.py — the FlowCast Studio backend: one command per stage of the
doc-page → narrated-video pipeline. The Mac app (mac/FlowCastStudio) runs
these; each is also usable by hand.

    uv run python tools/studio.py catalog [--refresh]
    uv run python tools/studio.py prepare <doc-slug> [--fresh-projects]
    uv run python tools/studio.py setup <doc-slug>         (start prerequisites)
    uv run python tools/autopilot.py workflows/<doc-slug>.md        (record)
    uv run python tools/studio.py narration <doc-slug> [--force]
    uv run python tools/studio.py voice <doc-slug> [--ref wav] [--takes 3]
    uv run python tools/studio.py master <doc-slug> [--quality 1440p]
    uv run python tools/studio.py library
    uv run python tools/studio.py voice-check [--ref wav] [--say "text"]

Progress the app needs is printed as lines starting `@@studio ` + JSON; the
rest is ordinary log output. The stages follow .claude/skills/doc/SKILL.md:
archive before recording, one narration line per clip, the same voice
variables for the body AND the intro.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src import doc_catalog as dc  # noqa: E402
from src import narration_writer as nw  # noqa: E402

RECORDINGS = ROOT / "output" / "recordings"
YOUTUBE = ROOT / "output" / "youtube"
WORKFLOWS = ROOT / "workflows"
DEFAULT_REF = ROOT / "assets" / "voice" / "reference.wav"
PROJECTS = Path.home() / "WSO2Integrator"


def emit(event: str, **data) -> None:
    print("@@studio " + json.dumps({"event": event, **data}), flush=True)


def fail(message: str) -> None:
    emit("error", message=message)
    sys.exit(1)


def _page(slug: str) -> dict:
    cat = dc.load()
    if not cat:
        fail("no catalog yet — run: tools/studio.py catalog --refresh")
    page = next((p for p in cat["pages"] if p["slug"] == slug), None)
    if not page:
        fail(f"no docs page with slug {slug!r}")
    return page


def _meta(slug: str) -> dict:
    for f in (WORKFLOWS / f"{slug}.meta.json", dc.WORKFLOW_DIR / f"{slug}.meta.json"):
        if f.exists():
            return json.loads(f.read_text())
    page = next((p for p in dc.load().get("pages", []) if p["slug"] == slug), None)
    if not page:
        return {"title": slug.replace("-", " ").title(), "build": "", "slug": slug, "links": []}
    return {"title": page["title"], "build": page.get("build", ""), "slug": slug,
            "links": [["Documentation", page["url"]]]}


def _voice_env(ref: Path, takes: int) -> dict:
    # The voice model is cached locally (~/.cache/huggingface); never let it
    # reach for the network, so the whole pipeline runs offline.
    return {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "FLOWCAST_TTS": "chatterbox", "FLOWCAST_VOICE_REF": str(ref),
            "FLOWCAST_VOICE_PITCH_HZ": "reference", "FLOWCAST_VOICE_TAKES": str(takes),
            "PYTHONUNBUFFERED": "1"}


def _theme(rec: Path) -> str:
    for theme in ("dark", "light"):
        if list(rec.glob(f"step-*-{theme}.mov")):
            return theme
    return "dark"


def _run(cmd: list[str], env: dict | None = None) -> int:
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, env=env or {**os.environ, "PYTHONUNBUFFERED": "1"}).returncode


# ── catalog ──────────────────────────────────────────────────────────────────

def cmd_catalog(args) -> None:
    if args.refresh or not dc.CATALOG.exists():
        code = _run([sys.executable, str(ROOT / "tools" / "docs_audit.py")]
                    + (["--offline"] if args.offline else []))
        if code:
            fail("docs audit failed — see the log above")
    cat = dc.load()
    emit("catalog", path=str(dc.CATALOG), summary=cat["summary"], commit=cat.get("commit"))


# ── prepare ──────────────────────────────────────────────────────────────────

def cmd_prepare(args) -> None:
    page = _page(args.slug)
    wf = WORKFLOWS / f"{args.slug}.md"
    gen = dc.WORKFLOW_DIR / f"{args.slug}.md"
    source = "existing"
    # A copy that still carries the generated marker is refreshed, so a docs
    # update or a generator fix reaches it. Remove that line to keep edits.
    stale = wf.exists() and gen.exists() and wf.read_text().startswith(dc.GENERATED_MARK) \
        and wf.read_text() != gen.read_text()
    if not wf.exists() or stale:
        if not gen.exists():
            fail(f"{page['title']} is not a walkthrough FlowCast can record")
        shutil.copy2(gen, wf)
        meta = gen.with_suffix(".meta.json")
        if meta.exists():
            shutil.copy2(meta, wf.with_suffix(".meta.json"))
        source = "refreshed" if stale else "generated"
    print(f"workflow: {wf.relative_to(ROOT)} ({source})")

    # A stale guid/ shifts every narration line onto the wrong action, so a
    # new recording always starts from an empty folder (old one archived).
    rec = RECORDINGS / args.slug
    if rec.exists() and any(rec.iterdir()):
        dest = rec.with_name(f"{args.slug}-archived-{datetime.now():%Y%m%d-%H%M}")
        rec.rename(dest)
        print(f"archived previous recording → {dest.relative_to(ROOT)}")

    if args.fresh_projects:
        _fresh_wso2()
    emit("prepared", slug=args.slug, workflow=str(wf), source=source,
         title=page["title"], url=page["url"])


WSO2_DATA = Path.home() / "Library" / "Application Support" / "WSO2 Integrator"


# The app's main process is Electron inside the bundle — not named after the app.
WSO2_PROCESS = "WSO2 Integrator.app/Contents/MacOS/"


def _wso2_running() -> bool:
    return subprocess.run(["pgrep", "-fq", WSO2_PROCESS]).returncode == 0


def _fresh_wso2() -> None:
    """Every recording starts from an empty WSO2 Integrator: the app is quit
    FIRST (an open project would write itself back), the projects in
    ~/WSO2Integrator are moved aside (never deleted), and the app is made to
    forget the last folder it had open — it is VS Code based and reopens it,
    and its unsaved-edit backups, on the next launch."""
    if _wso2_running():
        subprocess.run(["osascript", "-e", 'quit app "WSO2 Integrator"'], capture_output=True, timeout=30)
        for _ in range(30):                    # up to 15 s to close
            if not _wso2_running():
                break
            time.sleep(0.5)
        else:
            subprocess.run(["pkill", "-f", WSO2_PROCESS])        # a dialog held it open
            for _ in range(20):
                if not _wso2_running():
                    break
                time.sleep(0.5)
        print("quit WSO2 Integrator")
    if PROJECTS.is_dir() and any(PROJECTS.iterdir()):
        # Step 1 creates the project; one left over from a previous run makes
        # "Create Integration" fail on a name clash. Moved aside, never deleted.
        dest = PROJECTS.with_name("WSO2Integrator-archive") / f"{datetime.now():%Y%m%d-%H%M%S}"
        dest.mkdir(parents=True, exist_ok=True)
        for item in PROJECTS.iterdir():
            shutil.move(str(item), str(dest / item.name))
        print(f"moved existing projects → {dest}")
    storage = WSO2_DATA / "User" / "globalStorage" / "storage.json"
    try:
        data = json.loads(storage.read_text())
    except (OSError, json.JSONDecodeError):
        return
    windows = data.get("windowsState") or {}
    last = windows.get("lastActiveWindow") or {}
    changed = bool(last.get("folder") or last.get("workspace") or windows.get("openedWindows"))
    last.pop("folder", None)
    last.pop("workspace", None)
    windows["openedWindows"] = []
    backups = data.get("backupWorkspaces") or {}
    if backups.get("folders") or backups.get("workspaces"):
        backups["folders"], backups["workspaces"], changed = [], [], True
    if changed:
        storage.write_text(json.dumps(data, indent=2))
        print("WSO2 Integrator will open without the last project")


# ── prerequisites ────────────────────────────────────────────────────────────

def cmd_setup(args) -> None:
    """Start what the page needs (containers), before recording begins."""
    from src import prereqs
    page = _page(args.slug)
    rids = page.get("recipes") or []
    if not rids:
        emit("setup", recipes=[], message="nothing to start")
        return
    try:
        prereqs.ensure_engine(rosetta=any(prereqs.by_id(r).get("platform") for r in rids))
        for rid in rids:
            emit("setup_progress", recipe=rid, label=prereqs.by_id(rid)["label"])
            prereqs.start(rid)
    except prereqs.SetupError as e:
        fail(str(e))
    emit("setup", recipes=rids, labels=[prereqs.by_id(r)["label"] for r in rids])


def cmd_services(args) -> None:
    from src import prereqs
    if args.stop:
        removed = prereqs.stop()
        emit("services", running=[], removed=removed)
    else:
        emit("services", running=prereqs.running(), engine=prereqs.engine_running(),
             recipes=[{"id": r["id"], "label": r["label"]} for r in prereqs.recipes()])


# ── narration ────────────────────────────────────────────────────────────────

def _fresh_clips(rec: Path, since: float) -> list[Path]:
    guid = rec / "guid"
    return sorted((p for p in guid.glob("step*_action*.mov") if p.stat().st_mtime >= since - 1),
                  key=lambda p: p.stat().st_mtime) if guid.is_dir() else []


def cmd_narration(args) -> None:
    rec = RECORDINGS / args.slug
    log = rec / "actions.json"
    if not log.exists():
        fail(f"no actions.json in {rec} — record with tools/autopilot.py first")
    data = json.loads(log.read_text())
    clips = data["clips"]
    actual = _fresh_clips(rec, data["recorded_at"])
    per_step_log: dict[int, int] = {}
    for c in clips:
        per_step_log[c["step"]] = per_step_log.get(c["step"], 0) + 1
    per_step_disk: dict[int, int] = {}
    for p in actual:
        n = int(re.match(r"step(\d+)_", p.name).group(1))
        per_step_disk[n] = per_step_disk.get(n, 0) + 1
    if per_step_log != per_step_disk:
        fail(f"clip log and guid/ disagree: {per_step_log} vs {per_step_disk}")

    from src.parser import parse_markdown
    wf = WORKFLOWS / f"{args.slug}.md"
    parsed = parse_markdown(wf) if wf.exists() else []
    titles = {i: s.title for i, s in enumerate(parsed, 1)}
    from src.interactive import action_to_markdown
    step_actions = {i: [action_to_markdown(a) for a in s.actions] for i, s in enumerate(parsed, 1)}
    script = rec / "narration-script.txt"
    meta = _meta(args.slug)
    if script.exists() and not args.force:
        print(f"keeping existing {script.relative_to(ROOT)} (--force to rewrite)")
    else:
        text = nw.write_script(clips, titles, step_actions)
        (rec / "narration-script.rules.txt").write_text(text)
        from src import local_writer as lw
        if args.ai_polish and not args.no_ai and lw.available():
            print(f"polishing the narration with {lw.MODEL} (local)…", flush=True)
            acts: dict[int, list[str]] = {}
            for c in clips:
                acts.setdefault(int(c["step"]), []).append(c["label"])
            text, n = lw.polish_narration(text, meta.get("title", args.slug), titles, acts)
            lw.unload()          # the voice stage next needs the memory
            print(f"  {n} of {len(acts)} step(s) rewritten; the rest keep the template wording")
        script.write_text(text)
        print(f"wrote {script.relative_to(ROOT)}")
    emit("narration", path=str(script), lines=len(clips), hook=nw.hook(meta),
         title=meta.get("title"))


# ── voice + master ───────────────────────────────────────────────────────────

def cmd_voice(args) -> None:
    rec = RECORDINGS / args.slug
    script = rec / "narration-script.txt"
    if not script.exists():
        fail("no narration-script.txt — run the narration stage first")
    ref = Path(args.ref) if args.ref else DEFAULT_REF
    theme = _theme(rec)
    base = [sys.executable, str(ROOT / "tools" / "narrate_sync.py"), "--dir", str(rec),
            "--script", str(script), "--theme", theme]
    data = json.loads((rec / "actions.json").read_text()) if (rec / "actions.json").exists() else {}
    if data.get("recorded_at"):
        base += ["--since", str(data["recorded_at"] - 1)]
    env = _voice_env(ref, args.takes)
    if _run(base + ["--dry-run"], env):
        fail("the narration does not line up with the recording — fix the line count per step")
    if _run(base, env):
        fail("voice synthesis failed — see the log above")
    full = rec / f"full-{theme}-narrated.mov"
    emit("voiced", path=str(full), theme=theme)


def _art(text: str) -> str:
    t = text.lower()
    for words, art in ((("agent", " ai ", "chat", "llm", "rag", "mcp"), "robot"),
                       (("file", "csv", "ftp"), "files"),
                       (("sap",), "sap"),
                       (("event", "kafka", "rabbitmq", "queue", "mqtt", "automation", "sync"), "sync")):
        if any(w in f" {t} " for w in words):
            return art
    return "graph"


def _label(wf: Path) -> str | None:
    if not wf.exists():
        return None
    text = wf.read_text()
    base = re.search(r"Service Base Path\*\* to `([^`]+)`", text)
    res = re.search(r"Resource path\*\* to `([^`]+)`", text, re.I)
    method = re.search(r"Select \*\*(GET|POST|PUT|DELETE|PATCH)\*\*", text)
    if base and res:
        return f"{method.group(1) if method else 'GET'} {base.group(1).rstrip('/')}/{res.group(1).lstrip('/')}"
    name = re.search(r"Integration Name\*\* to `([^`]+)`", text)
    return name.group(1) if name else None


def cmd_master(args) -> None:
    rec = RECORDINGS / args.slug
    theme = _theme(rec)
    if not (rec / f"full-{theme}-narrated.mov").exists():
        fail("no narrated video yet — run the voice stage first")
    meta = _meta(args.slug)
    from src import local_writer as lw
    from src.parser import parse_markdown
    from src.interactive import action_to_markdown
    wf = WORKFLOWS / f"{args.slug}.md"
    steps = parse_markdown(wf) if wf.exists() else []
    titles = {i: s.title for i, s in enumerate(steps, 1)}
    acts = {i: [re.sub(r"[*`]", "", action_to_markdown(a)) for a in s.actions] for i, s in enumerate(steps, 1)}
    url = next((u for t, u in meta.get("links", []) if t == "Documentation"), None) \
        or next((p["url"] for p in dc.load().get("pages", []) if p["slug"] == args.slug), None)
    copy: dict = {}
    from src import progress
    progress.unit(0, 5, "Writing the YouTube title, description and thumbnail text")
    if lw.available() and not args.no_ai:
        print(f"writing the title, thumbnail text, hook and description with {lw.MODEL} (local)…", flush=True)
        copy = lw.video_copy(meta, titles, url, acts)
        lw.unload()
        print("  " + ", ".join(f"{k}: {v!r}" for k, v in copy.items() if k in ("title", "headline", "hook")))
    title = args.title or copy.get("title") or f"{meta['title']} in WSO2 Integrator"
    cmd = [sys.executable, str(ROOT / "tools" / "make_youtube_video.py"), "--dir", str(rec),
           "--title", title, "--hook", args.hook or copy.get("hook") or nw.hook(meta),
           "--theme", theme, "--quality", args.quality, "--art", _art(f"{meta['title']} {args.slug}"),
           "--rebuild-intro"]
    if copy.get("headline"):
        cmd += ["--headline", copy["headline"]]
    if copy.get("subtitle"):
        cmd += ["--subtitle", copy["subtitle"]]
    if args.out_dir:
        cmd += ["--out-dir", str(args.out_dir)]
    label = _label(WORKFLOWS / f"{args.slug}.md")
    if label:
        cmd += ["--label", label]
    ref = Path(args.ref) if args.ref else DEFAULT_REF
    # The intro is synthesized separately; without the same voice variables it
    # falls back to a system voice for the first eight seconds.
    if _run(cmd, _voice_env(ref, args.takes)):
        fail("building the master failed — see the log above")
    out = Path(args.out_dir) if args.out_dir else YOUTUBE / args.slug
    masters = [p for p in out.glob("*.mp4") if "-intro-" not in p.name and "-endcard-" not in p.name]
    master = max(masters, key=lambda p: p.stat().st_mtime) if masters else None
    if master:
        # The description in the shape of the hand-edited ones: what it is,
        # chapters at their real times, what each step adds, the guide.
        chapters = master.with_name(master.stem + ".chapters.txt")
        master.with_name(master.stem + ".description.txt").write_text(lw.description(
            title, copy, chapters.read_text() if chapters.exists() else "", titles, url))
        try:
            from src import packager
            print("writing the Medium guide and step GIFs…", flush=True)
            progress.unit(4, 5, "Writing the Medium guide and step GIFs")
            folder = packager.package(master, title, args.slug, url, rec=rec, workflow=wf,
                                      theme=theme, article=copy)
            print(f"packaged → {folder}")
            emit("packaged", folder=str(folder), title=title)
        except Exception as e:          # the master exists; packaging is a convenience
            print(f"packaging skipped: {e}")
    progress.unit(5, 5, "Video ready")
    emit("master", path=str(master) if master else None, folder=str(out))


# ── library + voice ──────────────────────────────────────────────────────────

def _doc_url(slug: str) -> str | None:
    pages = dc.load().get("pages", [])
    by_slug = next((p["url"] for p in pages if p["slug"] == slug), None)
    if by_slug:
        return by_slug
    doc = next((path for path, wf in dc.VERIFIED_WORKFLOWS.items() if wf == slug), None)
    return next((p["url"] for p in pages if p["path"] == doc), None) if doc else None


def cmd_package(args) -> None:
    """Package finished masters into named folders (all of them, or one slug)."""
    from src import packager
    done = []
    for d in sorted(YOUTUBE.iterdir()) if YOUTUBE.is_dir() else []:
        if not d.is_dir() or (args.slug and d.name != args.slug):
            continue
        masters = [p for p in d.glob("*.mp4") if "-intro-" not in p.name and "-endcard-" not in p.name]
        if not masters:
            continue
        master = max(masters, key=lambda p: p.stat().st_mtime)
        title = master.stem.replace("-", " ")
        rec = RECORDINGS / d.name
        folder = packager.package(master, title, d.name, _doc_url(d.name),
                                  when=datetime.fromtimestamp(master.stat().st_mtime),
                                  rec=rec, workflow=WORKFLOWS / f"{d.name}.md", theme=_theme(rec))
        print(f"{d.name} → {folder}")
        done.append(str(folder))
    emit("packaged_all", folders=done)


def cmd_library(_args) -> None:
    items = []
    if YOUTUBE.is_dir():
        for d in sorted(YOUTUBE.iterdir()):
            vids = [p for p in d.glob("*.mp4") if "-intro-" not in p.name and "-endcard-" not in p.name]
            if not vids:
                continue
            v = max(vids, key=lambda p: p.stat().st_mtime)
            thumb = v.with_name(v.stem + ".thumbnail.png")
            desc = v.with_name(v.stem + ".description.txt")
            items.append({"slug": d.name, "video": str(v), "title": v.stem.replace("-", " "),
                          "thumbnail": str(thumb) if thumb.exists() else None,
                          "description": str(desc) if desc.exists() else None,
                          "modified": v.stat().st_mtime, "bytes": v.stat().st_size})
    recs = []
    if RECORDINGS.is_dir():
        for d in sorted(RECORDINGS.iterdir()):
            if d.is_dir() and "-archived-" not in d.name and (d / "guid").is_dir():
                recs.append({"slug": d.name,
                             "narrated": any(d.glob("full-*-narrated.mov")),
                             "script": (d / "narration-script.txt").exists()})
    emit("library", videos=items, recordings=recs)


def cmd_voice_check(args) -> None:
    ref = Path(args.ref) if args.ref else DEFAULT_REF
    py = Path(os.environ.get("FLOWCAST_VOICE_PYTHON", "") or ROOT / ".venv-voice" / "bin" / "python")
    ok_py = py.exists() and subprocess.run([str(py), "-c", "import chatterbox"],
                                           capture_output=True).returncode == 0
    info = {"reference": str(ref), "reference_ok": ref.exists(), "python": str(py),
            "chatterbox_ok": ok_py, "ffmpeg_ok": shutil.which("ffmpeg") is not None}
    if args.say and ref.exists() and ok_py:
        os.environ.update(_voice_env(ref, 1))
        from src import tts_clone
        out = ROOT / "output" / "voice-preview.wav"
        dur = tts_clone.synthesize(args.say, out)
        tts_clone.shutdown()
        info.update(preview=str(out), seconds=round(dur, 2))
    emit("voice", **info)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("catalog")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--offline", action="store_true")
    p = sub.add_parser("prepare")
    p.add_argument("slug")
    p.add_argument("--fresh-projects", action="store_true",
                   help="move ~/WSO2Integrator/* aside so step 1 can create the project")
    p = sub.add_parser("narration")
    p.add_argument("slug")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-ai", action="store_true", help="template wording only")
    p.add_argument("--ai-polish", action="store_true",
                   help="reword the lines with the local model (off: it is only used for the "
                        "YouTube title, description and thumbnail text)")
    for name in ("voice", "master"):
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.add_argument("--ref", default=None, help="voice reference wav")
        p.add_argument("--takes", type=int, default=3 if name == "voice" else 8)
        if name == "master":
            p.add_argument("--quality", default="1440p")
            p.add_argument("--title", default=None)
            p.add_argument("--hook", default=None)
            p.add_argument("--out-dir", default=None)
            p.add_argument("--no-ai", action="store_true", help="templates only, no local model")
    p = sub.add_parser("setup", help="start the page's prerequisites")
    p.add_argument("slug")
    p = sub.add_parser("services", help="list (or --stop) FlowCast's containers")
    p.add_argument("--stop", action="store_true")
    p = sub.add_parser("package", help="put finished videos in named folders (~/Movies/FlowCast Studio)")
    p.add_argument("slug", nargs="?", default=None)
    sub.add_parser("library")
    p = sub.add_parser("voice-check")
    p.add_argument("--ref", default=None)
    p.add_argument("--say", default=None, help="speak this in the cloned voice")
    args = ap.parse_args()
    {"catalog": cmd_catalog, "prepare": cmd_prepare, "narration": cmd_narration,
     "setup": cmd_setup, "services": cmd_services, "package": cmd_package,
     "voice": cmd_voice, "master": cmd_master, "library": cmd_library,
     "voice-check": cmd_voice_check}[args.cmd](args)


if __name__ == "__main__":
    main()
