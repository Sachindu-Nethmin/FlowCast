"""The words around a recording, written by a local model (Ollama).

Everything a video needs besides the footage — its title, the thumbnail
headline, the spoken hook on the title card, the narration, the YouTube
description — used to come from templates. This asks a local model instead
(ornith:9b by default, the same one src/ai_helper.py uses), on this Mac, with
no network.

Every answer is checked before it is used, and anything that fails a check
falls back to the template it replaces:

  * narration keeps EXACTLY one line per recorded action — a missing line would
    shift every later line onto the wrong clip — and each line stays short
    enough to fit its clip; spoken forms ("A P I", "slash hello") are applied
    after the model, so it cannot undo them
  * titles and headlines have length limits; the art must be one the title card
    can draw
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from src import narration_writer as nw

OLLAMA = os.environ.get("FLOWCAST_OLLAMA", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.environ.get("FLOWCAST_WRITER_MODEL") or os.environ.get("FLOWCAST_AI_MODEL", "ornith:9b")
ARTS = ["chat", "robot", "files", "graph", "sync", "sap", "none"]


def available() -> bool:
    if os.environ.get("FLOWCAST_AI", "on").lower() in ("off", "0", "false", "no"):
        return False
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=2) as r:
            names = [m["name"] for m in json.load(r).get("models", [])]
        return MODEL in names or f"{MODEL}:latest" in names
    except Exception:
        return False


def _ask(prompt: str, schema: dict, timeout: float = 240) -> dict | None:
    body = {"model": MODEL, "stream": False, "think": False, "format": schema, "keep_alive": "2m",
            "options": {"temperature": 0.4}, "messages": [{"role": "user", "content": prompt}]}
    try:
        req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(json.load(r)["message"]["content"])
    except Exception:
        return None


def unload() -> None:
    """Free the model's memory now. On a 16 GB Mac, ornith:9b (5 GB) kept loaded
    pushed the voice model into swap and made the voice stage crawl."""
    try:
        req = urllib.request.Request(f"{OLLAMA}/api/generate",
                                     data=json.dumps({"model": MODEL, "keep_alive": 0}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception:
        pass


# ── narration ────────────────────────────────────────────────────────────────

_STEP = re.compile(r"^#\s*step\s+(\d+)\s*$", re.I)


def _parse(script: str) -> tuple[list[str], dict[int, list[str]]]:
    head, steps, cur = [], {}, None
    for ln in script.splitlines():
        m = _STEP.match(ln.strip())
        if m:
            cur = int(m.group(1))
            steps[cur] = []
        elif cur is None:
            head.append(ln)
        elif ln.strip() and not ln.strip().startswith("#"):
            steps[cur].append(ln.strip())
    return head, steps


def polish_narration(script: str, title: str, step_titles: dict[int, str],
                     actions: dict[int, list[str]]) -> tuple[str, int]:
    """(new script, number of steps the model rewrote). Line counts never change."""
    head, steps = _parse(script)
    rewritten = 0
    for n, lines in steps.items():
        acts = actions.get(n, [])
        schema = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "string"},
                                                             "minItems": len(lines), "maxItems": len(lines)}},
                  "required": ["lines"]}
        listing = "\n".join(f"{i + 1}. action: {a}\n   draft: {l}"
                            for i, (a, l) in enumerate(zip(acts + [""] * len(lines), lines)))
        prompt = (
            f"You write the voice-over for a screen-recorded tutorial: \"{title}\" in WSO2 "
            f"Integrator. This is step {n}: {step_titles.get(n, '')}.\n"
            f"Each line below is spoken over ONE recorded action, so keep exactly {len(lines)} lines, "
            "in order. Rewrite the drafts so they sound like one friendly developer explaining "
            "while they click — vary the wording, connect the lines, no filler.\n"
            "Rules: name the button or field the cursor goes to (do not describe outcomes "
            "that happen later); at most 18 words per line; keep the first line's step "
            "introduction if it has one; never add facts that are not in the action.\n\n"
            f"{listing}\n\nAnswer as JSON {{\"lines\": [...]}} with exactly {len(lines)} strings.")
        answer = _ask(prompt, schema)
        new = (answer or {}).get("lines") or []
        if len(new) == len(lines) and all(isinstance(x, str) and 2 <= len(x.split()) <= 22 for x in new):
            steps[n] = [nw.spoken(x.strip()).rstrip(".") + "." for x in new]
            rewritten += 1
    out = head[:]
    for n in sorted(steps):
        out += [f"# step {n}", *steps[n], ""]
    return "\n".join(out), rewritten


# ── title card, thumbnail, description ───────────────────────────────────────

def video_copy(meta: dict, step_titles: dict[int, str], doc_url: str | None,
               step_actions: dict[int, list[str]] | None = None) -> dict:
    """Title, thumbnail headline, subtitle, spoken hook, art, description parts.
    Missing or invalid fields are absent from the result (callers keep theirs)."""
    schema = {"type": "object", "properties": {
        "title": {"type": "string"}, "headline": {"type": "string"}, "subtitle": {"type": "string"},
        "hook": {"type": "string"}, "intro": {"type": "string"},
        "step_notes": {"type": "array", "items": {"type": "string"}},
        "hashtags": {"type": "array", "items": {"type": "string"}}},
        "required": ["title", "headline", "subtitle", "hook", "intro", "step_notes", "hashtags"]}
    step_actions = step_actions or {}
    steps = "\n".join(f"{n}. {t}" + (f"  (does: {'; '.join(step_actions.get(n, [])[:7])})"
                                      if step_actions.get(n) else "")
                      for n, t in sorted(step_titles.items()))
    prompt = (
        "Write the YouTube packaging for a screen-recorded WSO2 Integrator tutorial.\n"
        f"Docs page: {meta.get('title', '')}\nWhat it builds: {meta.get('build', '')}\n"
        f"Steps:\n{steps}\n\n"
        "- title: YouTube title, under 70 characters, says what you build and ends with "
        "\"in WSO2 Integrator\"\n"
        "- headline: thumbnail text, 2 to 5 words, no punctuation at the end\n"
        "- subtitle: under 45 characters, the concrete outcome (e.g. \"HTTP service, external API, "
        "JSON reply\"); never the words tutorial, video or recording\n"
        "- hook: one spoken sentence for the title card, 12 to 24 words, starts with what "
        "the viewer will have at the end\n"
        "- intro: 2 sentences for the description, plain and specific\n"
        f"- step_notes: exactly {len(step_titles)} short phrases (under 12 words), one per "
        "step in order, with the concrete detail that step sets (names, paths, values from "
        "'does') — not a repeat of the step title\n"
        "- hashtags: 4 to 6 hashtags without spaces\n"
        "Use only facts given above. Answer as JSON.")
    a = _ask(prompt, schema) or {}
    out: dict = {}
    if 10 <= len(a.get("title", "")) <= 80:
        out["title"] = a["title"].strip()
    if 1 <= len(a.get("headline", "").split()) <= 6:
        out["headline"] = a["headline"].strip().rstrip(".!")
    if 3 <= len(a.get("subtitle", "")) <= 60 and not re.search(r"tutorial|video|record", a["subtitle"], re.I):
        out["subtitle"] = a["subtitle"].strip()
    if 8 <= len(a.get("hook", "").split()) <= 30:
        out["hook"] = nw.spoken(a["hook"].strip())
    if a.get("intro"):
        out["intro"] = a["intro"].strip()
    notes = [str(x).strip() for x in a.get("step_notes") or []]
    titles = [t for _, t in sorted(step_titles.items())]
    echoes = sum(1 for nt, t in zip(notes, titles) if re.sub(r"\W", "", nt.lower()) == re.sub(r"\W", "", t.lower()))
    if len(notes) == len(step_titles) and echoes <= len(notes) // 3:
        out["step_notes"] = notes
    tags = [t if t.startswith("#") else f"#{t}" for t in a.get("hashtags") or [] if " " not in t]
    if 3 <= len(tags) <= 8:
        out["hashtags"] = tags
    return out


def description(title: str, copy: dict, chapters_txt: str, step_titles: dict[int, str],
                doc_url: str | None) -> str:
    """A description in the shape of the hand-edited ones (output/youtube/
    build-integration-api): intro, chapters, what each step adds, the guide."""
    lines = [copy.get("intro") or title, ""]
    if chapters_txt.strip():
        lines += ["Chapters", chapters_txt.strip(), ""]
    notes = copy.get("step_notes")
    lines.append("What we build")
    for i, (n, t) in enumerate(sorted(step_titles.items())):
        lines.append(f"{n}. {t}" + (f" — {notes[i]}" if notes else ""))
    lines += ["", "You need WSO2 Integrator installed locally (or the browser-based cloud editor)."]
    if doc_url:
        lines += ["", f"Written guide: {doc_url}"]
    lines += ["", " ".join(copy.get("hashtags") or ["#WSO2", "#WSO2Integrator", "#Integration", "#LowCode"])]
    return "\n".join(lines) + "\n"
