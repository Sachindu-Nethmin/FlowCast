"""Put each finished video in its own folder, ready to upload.

make_youtube_video.py leaves its output in output/youtube/<slug>/ under
machine names (Build-an-HTTP-API-in-WSO2-Integrator.mp4, an intro clip, a
chapters file). This makes a folder per video in ~/Movies/FlowCast Studio
(FLOWCAST_VIDEOS_DIR to change it), one subfolder per place it is published,
named for people:

    2026-10-03 Build an HTTP API in WSO2 Integrator/
        YouTube/
            Build an HTTP API in WSO2 Integrator.mp4
            Build an HTTP API in WSO2 Integrator – Thumbnail.png
            Build an HTTP API in WSO2 Integrator – YouTube description.txt
        Medium/                       (src/medium.py)
            Build an HTTP API in WSO2 Integrator – Medium article.txt / .html
            01 Create the integration.gif …
        video.json

YouTube takes the file name as the video's first title, so the video is named
after the title. Files are APFS clones of the originals: no extra disk space,
and editing one never changes the other.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

VIDEOS = Path(os.environ.get("FLOWCAST_VIDEOS_DIR") or Path.home() / "Movies" / "FlowCast Studio")
MANIFEST = "video.json"          # lets the app list the folder without guessing


def safe_name(title: str) -> str:
    """A title as a file name: no slashes or colons, no trailing dots."""
    name = re.sub(r"[/:\\\\]+", " – ", title)
    name = re.sub(r"[\x00-\x1f<>\"|?*]", "", name)
    return re.sub(r"\s+", " ", name).strip(" .")[:120] or "FlowCast video"


def _clone(src: Path, dst: Path) -> None:
    if dst.exists():
        dst.unlink()
    if subprocess.run(["cp", "-c", str(src), str(dst)], capture_output=True).returncode != 0:
        shutil.copy2(src, dst)


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True).stdout
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def _upload_text(title: str, description: str, video: Path, doc_url: str | None) -> str:
    """The one text file: title on top, the description to paste, then facts."""
    if doc_url:
        description = description.replace("<paste the docs page URL here>", doc_url)
    tags = re.findall(r"#\w+", description)
    secs = _duration(video)
    lines = ["TITLE", title, "", "DESCRIPTION", description.strip(), ""]
    if tags:
        lines += ["TAGS", ", ".join(t.lstrip("#") for t in tags), ""]
    lines += ["FILE", f"{video.name} — {int(secs // 60)}:{int(secs % 60):02d}, "
              f"{video.stat().st_size / 1e6:.0f} MB"]
    if doc_url:
        lines += ["", "SOURCE", doc_url]
    lines += ["", f"Made with FlowCast Studio on {datetime.fromtimestamp(video.stat().st_mtime):%d %B %Y}"]
    return "\n".join(lines) + "\n"


def package(master: Path, title: str, slug: str, doc_url: str | None = None,
            root: Path | None = None, when: datetime | None = None,
            rec: Path | None = None, workflow: Path | None = None, theme: str = "dark",
            article: dict | None = None) -> Path:
    """Copy `master` (+ thumbnail, description) into <folder>/YouTube, and write
    the Medium guide + step GIFs into <folder>/Medium when the workflow is given."""
    root = root or VIDEOS
    root.mkdir(parents=True, exist_ok=True)
    name = safe_name(title)
    when = when or datetime.now()
    folder = root / f"{when:%Y-%m-%d} {name}"
    # A re-run of the same page replaces its earlier folder (see _replace_older).
    yt = folder / "YouTube"
    yt.mkdir(parents=True, exist_ok=True)
    for old in (f"{name}.mp4", f"{name} – Thumbnail.png", f"{name} – YouTube description.txt"):
        (folder / old).unlink(missing_ok=True)       # the flat layout this replaces

    video = yt / f"{name}.mp4"
    _clone(master, video)
    thumb_src = master.with_name(master.stem + ".thumbnail.png")
    thumb = yt / f"{name} – Thumbnail.png"
    if thumb_src.exists():
        _clone(thumb_src, thumb)
    desc_src = master.with_name(master.stem + ".description.txt")
    description = desc_src.read_text() if desc_src.exists() else title
    text = yt / f"{name} – YouTube description.txt"
    text.write_text(_upload_text(title, description, video, doc_url))
    manifest = {
        "title": title, "slug": slug, "video": f"YouTube/{video.name}",
        "thumbnail": f"YouTube/{thumb.name}" if thumb.exists() else None, "text": f"YouTube/{text.name}",
        "made": when.isoformat(timespec="seconds"), "source": doc_url,
        "seconds": round(_duration(video), 1)}
    if workflow and workflow.exists():
        from src import medium
        try:
            manifest.update(medium.build(folder / "Medium", name, title, workflow, rec, theme,
                                         doc_url, article))
        except Exception as e:          # the YouTube half is done either way
            print(f"[package] Medium folder skipped: {e}")
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2))
    _replace_older(root, slug, folder)
    return folder


def _replace_older(root: Path, slug: str, keep: Path) -> None:
    """A re-run of the same page replaces its earlier video: other folders made
    for this slug go to the Trash (recoverable), so the Library shows one."""
    trash = Path.home() / ".Trash"
    for m in root.glob(f"*/{MANIFEST}"):
        folder = m.parent
        if folder == keep:
            continue
        try:
            if json.loads(m.read_text()).get("slug") != slug:
                continue
        except (OSError, json.JSONDecodeError):
            continue
        dest = trash / folder.name
        n = 2
        while dest.exists():
            dest = trash / f"{folder.name} {n}"
            n += 1
        shutil.move(str(folder), str(dest))
        print(f"[package] replaced the earlier video — moved to the Trash: {folder.name}")


def listing(root: Path | None = None) -> list[dict]:
    """Every packaged video, newest first (for the app and the phone)."""
    root = root or VIDEOS
    out = []
    if root.is_dir():
        for m in root.glob(f"*/{MANIFEST}"):
            try:
                d = json.loads(m.read_text())
            except json.JSONDecodeError:
                continue
            d["folder"] = str(m.parent)
            if (m.parent / d["video"]).exists():
                out.append(d)
    return sorted(out, key=lambda d: d.get("made", ""), reverse=True)
