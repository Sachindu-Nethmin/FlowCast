"""The Medium half of a finished video's folder: a written guide and its GIFs.

    <date> <title>/Medium/
        <title> – Medium article.txt     paste into a new Medium story
        <title> – Medium article.html    or open in a browser, copy, paste (keeps headings,
                                         bold, lists and code)
        01 Create the integration.gif    one per step, where the article says [GIF …]
        02 …

The steps come from the workflow that was recorded (workflows/<slug>.md),
rewritten for a reader: FlowCast's own lines ("Wait 10 seconds", "Open WSO2
Integrator", the first-run "Skip for now") are left out, prerequisite shell
commands move to "Before you start", "Scroll down and select" becomes
"Select". Medium cannot take images from a pasted file, so each step carries a
marked spot — upload that step's GIF there.

GIFs are cut from the step videos the recording left (step-NN-…-<theme>.mov)
at a size Medium accepts (it rejects images over 25 MB): 960 px at 10 fps,
smaller and slightly faster if a long step would be too big.
"""
from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path

GIF_LIMIT = 24 * 1024 * 1024
# (width, fps, speed): tried in order until a GIF fits under GIF_LIMIT.
GIF_LADDER = [(960, 10, 1.0), (800, 8, 1.25), (720, 6, 1.5), (640, 5, 2.0)]

_SKIP = [re.compile(p, re.I) for p in (
    r"^wait\b", r"^open wso2 integrator\.?$", r"^select \*\*skip for now\*\*\.?$",
    r"^<!--", r"^scroll (up|down)\.?$")]
_PREREQ = re.compile(r"^run the shell command `([^`]+)` to prepare the prerequisites\.?$", re.I)
_SHELL = re.compile(r"^run the shell command `([^`]+)`\.?$", re.I)


def _safe(name: str) -> str:
    name = re.sub(r"[/:\\]+", " – ", name)
    name = re.sub(r"[\x00-\x1f<>\"|?*]", "", name)
    return re.sub(r"\s+", " ", name).strip(" .")[:90]


def reader_steps(workflow: Path) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """(commands to run before starting, [(step title, reader lines in markdown)])."""
    before: list[str] = []
    steps: list[tuple[str, list[str]]] = []
    for line in workflow.read_text().splitlines():
        m = re.match(r"^##\s*Step\s*\d+\s*:\s*(.+)$", line)
        if m:
            steps.append((m.group(1).strip(), []))
            continue
        m = re.match(r"^\s*(?:\d+\.|[-*])\s+(.*)$", line)
        if not m or not steps:
            continue
        text = m.group(1).strip()
        if any(p.search(text) for p in _SKIP):
            continue
        if p := _PREREQ.match(text):
            before.append(p.group(1))
            continue
        if p := _SHELL.match(text):
            text = f"In a terminal, run `{p.group(1)}`."
        text = re.sub(r"^scroll (?:down|up) and select", "Select", text, flags=re.I)
        text = re.sub(r"^confirm (?:that )?", "Check that ", text, flags=re.I)
        steps[-1][1].append(text)
    return before, steps


def _plain(md: str) -> str:
    md = re.sub(r"\*\*([^*]+)\*\*", r"\1", md)
    return re.sub(r"`([^`]+)`", r"\1", md)


def _html(md: str) -> str:
    out = html.escape(md, quote=False)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", out)


def _strip(rec: Path, mov: Path) -> int:
    """The notch's black strip in this recording, measured on its clips."""
    from src.frames import black_top, strip_heights
    def size(p: Path) -> tuple[int, int]:
        o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
        w, h = (int(x) for x in o.stdout.strip().split(",")[:2])
        return w, h
    clips = sorted((rec / "guid").glob("step*_action*.mov"))
    by_size = strip_heights(clips, size) if clips else {}
    return by_size.get(size(mov), black_top(mov))


def make_gifs(rec: Path, theme: str, titles: list[str], out: Path) -> dict[int, Path]:
    """One GIF per step video in the recording, named '<NN> <step title>.gif'."""
    out.mkdir(parents=True, exist_ok=True)
    made: dict[int, Path] = {}
    for n, title in enumerate(titles, 1):
        movs = [p for p in rec.glob(f"step-{n:02d}-*-{theme}.mov") if "-narrated" not in p.name]
        if not movs:
            continue
        gif = out / f"{n:02d} {_safe(title)}.gif"
        band = _strip(rec, movs[0])
        trim = f"crop=iw:ih-{band}:0:{band}," if band else ""
        for width, fps, speed in GIF_LADDER:
            vf = (f"{trim}setpts=PTS/{speed},fps={fps},scale={width}:-2:flags=lanczos,split[a][b];"
                  "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(movs[0]), "-filter_complex", vf,
                                "-loop", "0", str(gif)], capture_output=True)
            if r.returncode == 0 and gif.exists() and gif.stat().st_size <= GIF_LIMIT:
                made[n] = gif
                break
        else:
            if gif.exists() and gif.stat().st_size > GIF_LIMIT:
                gif.unlink()            # too big for Medium even at the smallest size
    return made


def build(folder: Path, name: str, title: str, workflow: Path, rec: Path | None, theme: str,
          doc_url: str | None = None, article: dict | None = None) -> dict:
    """Write the Medium folder. Returns the manifest entries (paths relative to the video folder)."""
    article = article or {}
    folder.mkdir(parents=True, exist_ok=True)
    before, steps = reader_steps(workflow)
    gifs = make_gifs(rec, theme, [t for t, _ in steps], folder) if rec else {}
    notes = article.get("step_notes") or []
    intro = article.get("intro") or (f"A step-by-step guide to {title.removesuffix(' in WSO2 Integrator')} "
                                     "in WSO2 Integrator, with a short animation of every step.")
    subtitle = article.get("subtitle") or "Step by step, with a GIF for every step"
    tags = [t.lstrip("#") for t in (article.get("hashtags") or ["WSO2", "Integration", "LowCode"])][:5]

    def gif_spot(n: int) -> str:
        g = gifs.get(n)
        return f"[GIF — upload “{g.name}” here]" if g else "[no GIF for this step]"

    # ── plain text ──────────────────────────────────────────────────────────
    t = [f"TITLE: {title}", f"SUBTITLE: {subtitle}", "",
         "──── Paste everything below this line into the Medium story ────", "",
         intro, ""]
    t += ["Before you start", "• WSO2 Integrator installed on your machine."]
    t += [f"• In a terminal, run: {c}" for c in before]
    t.append("")
    for n, (st, lines) in enumerate(steps, 1):
        t.append(f"Step {n}: {st}")
        if n - 1 < len(notes) and notes[n - 1]:
            t.append(notes[n - 1])
        t.append(gif_spot(n))
        t += [f"{i}. {_plain(l)}" for i, l in enumerate(lines, 1)]
        t.append("")
    t += ["Watch it narrated", "[paste the YouTube link on its own line — Medium embeds the video]", ""]
    if doc_url:
        t += [f"Based on the WSO2 Integrator documentation: {doc_url}", ""]
    t += [f"Medium tags (add when publishing, up to 5): {', '.join(tags)}", ""]
    t += ["GIFs in this folder, in order:"] + [f"  {gifs[n].name}" for n in sorted(gifs)]
    txt = folder / f"{name} – Medium article.txt"
    txt.write_text("\n".join(t) + "\n")

    # ── html (open in a browser, select all, copy, paste into Medium) ───────
    h = [f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>",
         "<style>body{font:18px/1.6 Georgia,serif;max-width:720px;margin:40px auto;padding:0 16px}"
         ".gif{background:#fff7d6;border:1px dashed #c9a400;padding:8px 12px;font-family:sans-serif;font-size:15px}"
         "code{background:#f2f2f2;padding:1px 4px}</style>",
         "<p style='font-family:sans-serif;font-size:14px;color:#777'>Select all (⌘A), copy (⌘C), paste into a new "
         "Medium story. Then replace each yellow box with that step's GIF from this folder.</p>",
         f"<h1>{html.escape(title)}</h1>", f"<h2>{html.escape(subtitle)}</h2>",
         f"<p>{html.escape(intro)}</p>", "<h3>Before you start</h3><ul>",
         "<li>WSO2 Integrator installed on your machine.</li>"]
    h += [f"<li>In a terminal, run <code>{html.escape(c)}</code></li>" for c in before]
    h.append("</ul>")
    for n, (st, lines) in enumerate(steps, 1):
        h.append(f"<h3>Step {n}: {html.escape(st)}</h3>")
        if n - 1 < len(notes) and notes[n - 1]:
            h.append(f"<p><em>{html.escape(notes[n - 1])}</em></p>")
        h.append(f"<p class='gif'>{html.escape(gif_spot(n))}</p>")
        h.append("<ol>" + "".join(f"<li>{_html(l)}</li>" for l in lines) + "</ol>")
    h += ["<h3>Watch it narrated</h3>", "<p class='gif'>[paste the YouTube link on its own line]</p>"]
    if doc_url:
        h.append(f"<p>Based on the WSO2 Integrator documentation: "
                 f"<a href='{html.escape(doc_url)}'>{html.escape(doc_url)}</a></p>")
    page = folder / f"{name} – Medium article.html"
    page.write_text("\n".join(h) + "\n")

    rel = lambda p: f"Medium/{p.name}"
    return {"medium": rel(txt), "medium_html": rel(page), "gifs": [rel(gifs[n]) for n in sorted(gifs)]}
