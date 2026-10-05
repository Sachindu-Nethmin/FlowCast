"""The LinkedIn part of a finished video's folder: three texts to paste.

    <date> <title>/LinkedIn/
        1 Post (no links).txt             post this
        2 First comment (links).txt       comment it on your post straight away
        3 Post with links (edit later).txt  after ~30 minutes, edit the post to this

LinkedIn shows posts with outside links to fewer people, so the post itself
carries none: the links go in the first comment, and into the post only once
it has had its first reach. The YouTube and Medium links exist only after you
upload, so they are marked spots; the docs link is filled in.

Written from what the video already has — the local model's intro and step
notes from the Master stage (no extra model call), or the YouTube description
when packaging an older video — and the recorded workflow's step titles.
"""
from __future__ import annotations

import re
from pathlib import Path

CTA = "🎥 The full walkthrough video and a written step-by-step guide are linked in the first comment 👇"


def _intro(article: dict, description: str) -> str:
    if article.get("intro"):
        return article["intro"].strip()
    for para in description.split("\n\n"):           # the description's opening paragraph
        p = para.strip()
        if p and not p.startswith(("#", "Chapters", "0:00")) and len(p.split()) >= 8:
            return p
    return ""


def _tags(article: dict, description: str) -> list[str]:
    tags = [t if t.startswith("#") else f"#{t}" for t in article.get("hashtags") or []]
    if not tags:
        tags = re.findall(r"#\w+", description)
    tags = list(dict.fromkeys(t for t in tags if t.lower() != "#shorts"))
    if "#WSO2" not in tags:
        tags.insert(0, "#WSO2")
    return tags[:5]                                   # a few: more reads as spam on LinkedIn


def build(folder: Path, title: str, steps: list[str], doc_url: str | None,
          article: dict | None = None, description: str = "") -> dict:
    """Write the three texts. `steps` are the video's step titles, in order."""
    article = article or {}
    folder.mkdir(parents=True, exist_ok=True)
    notes = article.get("step_notes") or []
    intro = _intro(article, description)

    body = [f"{title} — in {len(steps)} steps." if steps else title, ""]
    if intro:
        body += [intro, ""]
    if steps:
        body.append("What it builds, step by step:")
        for n, st in enumerate(steps, 1):
            note = notes[n - 1].strip() if n - 1 < len(notes) and notes[n - 1] else ""
            body.append(f"{n}. {st}" + (f" — {note}" if note else ""))
        body.append("")
    tags = " ".join(_tags(article, description))

    links = ["🎥 Video: [paste the YouTube link]",
             "📝 Step-by-step guide with GIFs: [paste the Medium link]"]
    if doc_url:
        links.append(f"📚 WSO2 Integrator docs: {doc_url}")

    post = "\n".join(body + [CTA, "", tags]) + "\n"
    comment = "\n".join(links) + "\n"
    edited = "\n".join(body + links + ["", tags]) + "\n"

    files = {"1 Post (no links).txt": post,
             "2 First comment (links).txt": comment,
             "3 Post with links (edit later).txt": edited}
    for name, text in files.items():
        (folder / name).write_text(text)
    return {"linkedin": [f"LinkedIn/{n}" for n in files]}
