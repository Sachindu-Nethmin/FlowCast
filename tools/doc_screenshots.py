#!/usr/bin/env python3
"""
doc_screenshots.py — turn a FlowCast recording into a documentation page with
still screenshots, in the shape the official WSO2 Integrator docs use.

FlowCast records a workflow and writes per-step GIFs plus `index.md`. GIFs are
right for a video or a blog post and wrong for a docs page: the published docs
(`en/docs/get-started/build-integration-api.md` and friends) use ONE still PNG
per step, referenced through `<ThemedImage>`.

This reads the recording that already exists — the per-step `.mov` and the
`timings.json` written beside it — picks the frame that best shows the result
of each step, and writes:

  * `step-NN-<slug>.png`   — one still per step, scaled to docs width
  * `<slug>.md`            — a Docusaurus page with frontmatter, imports and
                             <ThemedImage> blocks pointing at those stills

`timings.json` carries the timestamp of every action inside a step, so the
frame is chosen from real action boundaries, not guessed. Two moments are
useful and both are supported:

  settled    (default) dwell seconds AFTER the last action — the dialog has
             closed, the artifact is on the canvas, the step is done.
  pre-click  lead seconds BEFORE the last action — the form is filled in and
             the confirming button is still visible. This is what most of the
             published "create project" / "add connection" screenshots show.

Use `--candidates` when no single rule wins: it writes a frame per action into
`candidates/` so you can look through them and pick by hand.

Usage:
    python tools/doc_screenshots.py output/recordings/quick-start-automation
    ... --moment pre-click            # form-filled instead of result
    ... --candidates                  # one frame per action, to choose by hand
    ... --at 4=6.2                      # pin step 4 to an exact timestamp
    ... --title "Build an Automation" --sidebar-position 6
    ... --img-base /img/get-started/build-automation
    ... --install "<docs>/en"         # copy PNGs into the docs repo static dir
    ... --dry-run                     # print the page, write nothing

Defaults assume the docs conventions in wso2/docs-integrator: images under
`static/img/<section>/<slug>/`, page body under `docs/`.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STEP_MOV_RE = re.compile(r"^step-(\d+)-(.+?)-(light|dark)\.mov$")
STEP_HEADING_RE = re.compile(r"^##\s*Step\s+(\d+)\s*:\s*(.+?)\s*$", re.I)
THEMED_IMAGE_START_RE = re.compile(r"^\s*<ThemedImage\b")
THEMED_IMAGE_END_RE = re.compile(r"/>\s*$")

DOCS_WIDTH = 1600          # published screenshots sit around 1500-1700px wide
DEFAULT_DWELL = 1.2        # seconds after the last action before the frame
DEFAULT_LEAD = 0.35        # seconds before the last action for --moment pre-click
TAIL_GUARD = 0.2           # never seek into the last frames of a clip


def slug(text: str) -> str:
    """Match src/artifacts.slug so filenames line up with the recording."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


@dataclass
class Step:
    index: int
    title: str
    instructions: list[str] = field(default_factory=list)
    movs: dict[str, Path] = field(default_factory=dict)   # theme -> .mov
    actions: list[dict] = field(default_factory=list)     # from timings.json
    shots: dict[str, str] = field(default_factory=dict)   # theme -> png filename

    @property
    def stem(self) -> str:
        return f"step-{self.index:02d}-{slug(self.title)}"


# ── reading what the recording already knows ─────────────────────────────────

def parse_index(index_md: Path) -> list[Step]:
    """Pull step titles and their numbered instructions out of the recording's
    generated index.md. The <ThemedImage> blocks are dropped — this tool writes
    its own, pointing at stills instead of GIFs."""
    if not index_md.is_file():
        return []
    steps: list[Step] = []
    in_image = False
    for line in index_md.read_text().splitlines():
        if in_image:
            in_image = not THEMED_IMAGE_END_RE.search(line)
            continue
        if THEMED_IMAGE_START_RE.match(line):
            in_image = not THEMED_IMAGE_END_RE.search(line)
            continue
        heading = STEP_HEADING_RE.match(line)
        if heading:
            steps.append(Step(index=int(heading.group(1)), title=heading.group(2)))
            continue
        if steps and line.strip():
            steps[-1].instructions.append(line.rstrip())
    for step in steps:
        while step.instructions and not step.instructions[-1].strip():
            step.instructions.pop()
    return steps


def discover_movs(rec_dir: Path) -> dict[int, dict[str, Path]]:
    """step index -> {theme: mov}. Narrated cuts are skipped: they are the same
    frames with audio, and the un-narrated file is always present."""
    found: dict[int, dict[str, Path]] = {}
    for mov in sorted(rec_dir.glob("step-*.mov")):
        if "-narrated" in mov.name:
            continue
        m = STEP_MOV_RE.match(mov.name)
        if not m:
            continue
        found.setdefault(int(m.group(1)), {})[m.group(3)] = mov
    return found


def load_timings(rec_dir: Path) -> dict[str, list[dict]]:
    timings = rec_dir / "timings.json"
    if not timings.is_file():
        return {}
    try:
        return json.loads(timings.read_text())
    except json.JSONDecodeError as exc:
        print(f"  ! {timings.name} is not valid JSON ({exc}) — falling back to duration", file=sys.stderr)
        return {}


# ── frame selection ──────────────────────────────────────────────────────────

def duration(mov: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(mov)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def pick_time(actions: list[dict], length: float, moment: str,
              dwell: float, lead: float) -> float:
    """The frame worth publishing is tied to the LAST action of the step: the
    click that commits the form. 'settled' waits for the UI to catch up with
    it, 'pre-click' catches the form while it is still on screen.

    A step whose only timestamp is 0.0 carries no usable boundary — the whole
    clip is one action — so fall back to a point late in the clip, where the
    result is on screen."""
    ceiling = max(0.0, length - TAIL_GUARD)
    stamps = [float(a.get("t", 0.0)) for a in actions]
    if not stamps or (len(stamps) == 1 and stamps[0] == 0.0):
        return min(length * 0.75, ceiling)
    last = max(stamps)
    target = last - lead if moment == "pre-click" else last + dwell
    return max(0.0, min(target, ceiling))


def grab(mov: Path, seconds: float, dest: Path, width: int) -> bool:
    """Decode to `seconds` and write one PNG. Seeking after -i is exact, which
    matters here — a keyframe-snapped frame can land mid-dialog-animation."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(mov), "-ss", f"{seconds:.3f}",
           "-frames:v", "1"]
    if width:
        cmd += ["-vf", f"scale={width}:-2:flags=lanczos"]
    cmd.append(str(dest))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not dest.is_file():
        print(f"  ! ffmpeg failed on {mov.name} @ {seconds:.2f}s: "
              f"{result.stderr.strip()[:200]}", file=sys.stderr)
        return False
    return True


def rescale(src: Path, dest: Path, width: int) -> bool:
    """Copy a already-captured still to the output, scaled to docs width."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    if width:
        cmd += ["-vf", f"scale={width}:-2:flags=lanczos"]
    cmd.append(str(dest))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not dest.is_file():
        print(f"  ! ffmpeg failed on {src}: {result.stderr.strip()[:200]}", file=sys.stderr)
        return False
    return True


# ── page generation ──────────────────────────────────────────────────────────

def themed_image(alt: str, light: str, dark: str) -> str:
    return (
        "<ThemedImage\n"
        f"    alt=\"{alt}\"\n"
        "    sources={{\n"
        f"        light: useBaseUrl('{light}'),\n"
        f"        dark: useBaseUrl('{dark}'),\n"
        "    }}\n"
        "/>"
    )


def build_page(steps: list[Step], *, title: str, description: str, keywords: str,
               sidebar_position: int | None, img_base: str, tabs: bool) -> str:
    front = ["---"]
    if sidebar_position is not None:
        front.append(f"sidebar_position: {sidebar_position}")
    front += [
        f'title: "{title}"',
        f"description: {description}",
        f"keywords: [{keywords}]",
        "---",
        "",
        "import ThemedImage from '@theme/ThemedImage';",
        "import useBaseUrl from '@docusaurus/useBaseUrl';",
    ]
    if tabs:
        front += ["import Tabs from '@theme/Tabs';",
                  "import TabItem from '@theme/TabItem';"]
    front += ["", f"# {title}", "",
              "**Time:** Under 10 minutes | **What you'll build:** TODO — one sentence.",
              "", "TODO — one short paragraph on what this page covers.", "",
              ":::info Prerequisites", "",
              "A working WSO2 Integrator environment. Choose the path that fits how you want to work:",
              "",
              "- [Cloud setup](setup/cloud-setup.md) — launch WSO2 Integrator in a browser-based cloud editor.",
              "- [Local setup](setup/local-setup.md) — install and launch the WSO2 Integrator IDE on your machine.",
              ":::", ""]
    if tabs:
        front += ["<Tabs>", '<TabItem value="ui" label="Visual Designer" default>', ""]

    body: list[str] = []
    for step in steps:
        body.append(f"## Step {step.index}: {step.title}")
        body.append("")
        body.extend(step.instructions)
        body.append("")
        if step.shots:
            light = step.shots.get("light") or step.shots.get("dark")
            dark = step.shots.get("dark") or step.shots.get("light")
            body.append(themed_image(
                f"{step.title} — TODO describe what the screenshot shows",
                f"{img_base}/{light}", f"{img_base}/{dark}"))
            body.append("")

    tail = ["</TabItem>", "</Tabs>", ""] if tabs else []
    return "\n".join(front + body + tail).rstrip() + "\n"


# ── cli ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording", type=Path,
                    help="output/recordings/<workflow> — must contain step-*.mov")
    ap.add_argument("--moment", choices=["settled", "pre-click"], default="settled",
                    help="frame relative to the step's last action (default: settled)")
    ap.add_argument("--dwell", type=float, default=DEFAULT_DWELL,
                    help=f"seconds after the last action for --moment settled (default: {DEFAULT_DWELL})")
    ap.add_argument("--lead", type=float, default=DEFAULT_LEAD,
                    help=f"seconds before the last action for --moment pre-click (default: {DEFAULT_LEAD})")
    ap.add_argument("--width", type=int, default=DOCS_WIDTH,
                    help=f"scale PNGs to this width, 0 keeps native (default: {DOCS_WIDTH})")
    ap.add_argument("--candidates", action="store_true",
                    help="also write one frame per action into candidates/, to choose by hand")
    ap.add_argument("--at", action="append", metavar="STEP=SECONDS", default=[],
                    help="pin one step's frame to an exact timestamp, overriding the heuristic "
                         "(repeatable, e.g. --at 4=6.2)")
    ap.add_argument("--prefer", choices=["live", "video"], default="live",
                    help="'live' uses the guide-mode still at step-NN/after.png when one exists "
                         "(exact moment, app already full screen); 'video' always seeks the .mov")
    ap.add_argument("--theme", choices=["light", "dark", "both"], default="both",
                    help="which recorded theme(s) to capture (default: both, when recorded)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output directory (default: <recording>/docs)")
    ap.add_argument("--title", default=None, help="page title (default: derived from the slug)")
    ap.add_argument("--description", default="TODO — one sentence for search results.")
    ap.add_argument("--keywords", default="wso2 integrator")
    ap.add_argument("--sidebar-position", type=int, default=None)
    ap.add_argument("--img-base", default=None,
                    help="URL base for images (default: /img/get-started/<slug>)")
    ap.add_argument("--no-tabs", action="store_true",
                    help="omit the Visual Designer / Ballerina Code tab scaffold")
    ap.add_argument("--install", type=Path, default=None,
                    help="docs site root (…/en) — copy PNGs into its static/<img-base> dir")
    ap.add_argument("--dry-run", action="store_true", help="print the page, write nothing")
    args = ap.parse_args()

    overrides: dict[int, float] = {}
    for pin in args.at:
        step_no, _, seconds = pin.partition("=")
        try:
            overrides[int(step_no)] = float(seconds)
        except ValueError:
            sys.exit(f"--at expects STEP=SECONDS, got {pin!r}")

    rec = args.recording if args.recording.is_absolute() else ROOT / args.recording
    if not rec.is_dir():
        sys.exit(f"no such recording directory: {rec}")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found on PATH — install ffmpeg first")

    wf_slug = rec.name
    img_base = (args.img_base or f"/img/get-started/{wf_slug}").rstrip("/")
    out_dir = args.out or rec / "docs"
    title = args.title or wf_slug.replace("-", " ").title()

    steps = parse_index(rec / "index.md")
    movs = discover_movs(rec)
    if not movs:
        sys.exit(f"no step-*.mov files in {rec} — record the workflow first")
    if not steps:
        # No index.md to lean on: title the steps from the mov filenames.
        steps = [Step(index=i, title=STEP_MOV_RE.match(next(iter(t.values())).name).group(2).replace("-", " ").capitalize())
                 for i, t in sorted(movs.items())]
        print("  ! no index.md — step titles taken from filenames, instructions left empty")

    timings = load_timings(rec)
    themes = ["light", "dark"] if args.theme == "both" else [args.theme]

    print(f"recording : {rec}")
    print(f"moment    : {args.moment} "
          f"({'+%.2fs after' % args.dwell if args.moment == 'settled' else '-%.2fs before' % args.lead} last action)\n")

    captured = 0
    for step in steps:
        step.movs = movs.get(step.index, {})

        # A --guide run minimises the terminal, restores WSO2 Integrator full
        # screen, performs the step, then screenshots it. That still IS the
        # publishable frame — no seek, no cursor-mid-animation risk.
        live = rec / f"step-{step.index:02d}" / "after.png"
        if args.prefer == "live" and live.is_file() and step.index not in overrides:
            png = out_dir / f"{step.stem}.png"
            if args.dry_run:
                step.shots["light"] = png.name
                print(f"  · Step {step.index}: {step.title} — would use live still "
                      f"{live.parent.name}/after.png -> {png.name}")
                continue
            if rescale(live, png, args.width):
                step.shots["light"] = png.name
                captured += 1
                print(f"  ✓ Step {step.index}: {step.title} — live still "
                      f"{live.parent.name}/after.png -> {png.name}")
            continue

        if not step.movs:
            print(f"  ✗ Step {step.index}: {step.title} — no recording")
            continue
        for theme in themes:
            mov = step.movs.get(theme)
            if mov is None:
                continue
            actions = timings.get(mov.name, [])
            step.actions = actions or step.actions
            length = duration(mov)
            at = (min(overrides[step.index], max(0.0, length - TAIL_GUARD))
                  if step.index in overrides
                  else pick_time(actions, length, args.moment, args.dwell, args.lead))
            pinned = " (pinned)" if step.index in overrides else ""
            png = out_dir / f"{step.stem}-{theme}.png" if len(themes) > 1 else out_dir / f"{step.stem}.png"
            if args.dry_run:
                step.shots[theme] = png.name
                print(f"  · Step {step.index}: {step.title} — would grab {at:6.2f}s / {length:.2f}s"
                      f"{pinned} ({len(actions)} action(s)) -> {png.name}")
                continue
            if grab(mov, at, png, args.width):
                step.shots[theme] = png.name
                captured += 1
                print(f"  ✓ Step {step.index}: {step.title} — {at:6.2f}s / {length:.2f}s"
                      f"{pinned} ({len(actions)} action(s)) -> {png.name}")

            if args.candidates and actions:
                for n, action in enumerate(actions):
                    t = min(float(action.get("t", 0.0)) + args.dwell, max(0.0, length - TAIL_GUARD))
                    label = slug(action.get("label", f"action-{n}"))[:48]
                    grab(mov, t, out_dir / "candidates" / f"{step.stem}-{theme}-a{n:02d}-{label}.png",
                         args.width)
                print(f"      {len(actions)} candidate frame(s) -> {out_dir / 'candidates'}")

    page = build_page(steps, title=title, description=args.description,
                      keywords=args.keywords, sidebar_position=args.sidebar_position,
                      img_base=img_base, tabs=not args.no_tabs)

    if args.dry_run:
        print("\n" + "─" * 72 + "\n" + page)
        return

    md_path = out_dir / f"{wf_slug}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(page)
    print(f"\nwrote {captured} screenshot(s) to {out_dir}")
    print(f"wrote {md_path}")

    if args.install:
        static = args.install / "static" / img_base.lstrip("/")
        static.mkdir(parents=True, exist_ok=True)
        for png in sorted(out_dir.glob("*.png")):
            shutil.copy2(png, static / png.name)
        print(f"copied {len(list(out_dir.glob('*.png')))} PNG(s) to {static}")
        print(f"next: move {md_path.name} under {args.install / 'docs'} and add it to sidebars.ts")


if __name__ == "__main__":
    main()
