#!/usr/bin/env python3
"""
doc_to_workflow.py — turn a pasted WSO2 Integrator docs page into a workflow
markdown file the recorder can actually follow.

A docs page is written for a human reading it; `src/parser.py` matches fixed
regexes. `Select the Create New Integration card.` reads fine and parses to
NOTHING. This does the mechanical part of that translation — structure, the
known rewrites, the desktop-only lines the cloud editor does not need — and
then runs every line back through the real parser so anything it could not
translate is reported instead of silently dropped.

It does not replace judgement. Lines it cannot confidently rewrite are left
alone and flagged; fix those by hand against
`.claude/skills/doc-to-youtube/reference/workflow-grammar.md`.

Usage:
    python tools/doc_to_workflow.py page.txt --slug integration-as-api
    pbpaste | python tools/doc_to_workflow.py - --slug integration-as-api
    ... --cloud            # skip the desktop-only sign-in / Browse lines
    ... --narration        # also write a narration.txt skeleton, correctly sized
    ... --dry-run          # print the workflow, write nothing

Writes `workflows/<slug>.md`, plus `<slug>.meta.json` carrying the page title,
"what you'll build" and prerequisite links for the video description.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.parser import _parse_instructions  # noqa: E402

STEP_RE = re.compile(r"^\s*#*\s*Step\s+(\d+)\s*:\s*(.+?)\s*$", re.I)
NUMBERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*\S)\s*$")
TAB_MARKER_RE = re.compile(r"^\s*\*\s*(Visual Designer|Ballerina Code|.*Code)\s*$", re.I)
ADMONITION_RE = re.compile(r"^\s*(NOTE|TIP|INFO|WARNING|IMPORTANT|CAUTION)\s*:?\s*$", re.I)
PREREQ_RE = re.compile(r"^\s*PREREQUISITES?\s*$", re.I)
META_RE = re.compile(r"^\s*Time:\s*(?P<time>[^|]+?)\s*\|\s*What you'?ll build:\s*(?P<build>.+?)\s*$", re.I)
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")

# Trailing clauses that are context, not part of the clickable label.
TRAILING = [
    (re.compile(r"\s+in the confirmation dialog\.?$", re.I), ""),
    (re.compile(r"\s+from the project overview canvas\.?$", re.I), ""),
    (re.compile(r"\s+in the design canvas\.?$", re.I), ""),
    (re.compile(r"\s+in the (?:HTTP service )?design view\.?$", re.I), ""),
]
# Clauses the parser DOES understand and that must survive verbatim.
KEEP_CLAUSE = re.compile(
    r"\s+(under\s+.+|next to\s+.+|inside the resource flow.*|in the toolbar)\.?$", re.I)

INFORMATIONAL = re.compile(r"^\s*(keep|confirm|verify|check that|ensure)\b", re.I)


def _bold(text: str) -> str:
    text = text.strip().rstrip(".")
    return text if text.startswith("**") else f"**{text}**"


def _rewrite_select(body: str) -> str:
    """`Select the X card` / `Select X under Y` -> parser-legal forms."""
    keep = ""
    m = KEEP_CLAUSE.search(body)
    if m:
        keep = " " + m.group(1).strip().rstrip(".")
        body = body[:m.start()]
    for pat, repl in TRAILING:
        body = pat.sub(repl, body)
    body = body.strip().rstrip(".")
    # "the X card" / "the X button" / "the X option" -> X
    body = re.sub(r"^the\s+(.+?)\s+(card|button|option|tab|icon)$", r"\1", body, flags=re.I)
    body = re.sub(r"^the\s+", "", body, flags=re.I)
    # "under Y" inside the kept clause gets bolded too — it is a scope hint.
    keep = re.sub(r"\bunder\s+(.+)$", lambda m: "under " + _bold(m.group(1)), keep, flags=re.I)
    keep = re.sub(r"\bnext to\s+(.+?)( section)?$",
                  lambda m: "next to " + _bold(m.group(1)) + (m.group(2) or ""), keep, flags=re.I)
    return f"Select {_bold(body)}{keep}."


def _rewrite_set(field: str, value: str) -> str:
    field = field.strip().strip("*").rstrip(".")
    value = value.strip().rstrip(".")
    if value.startswith("`") and value.endswith("`"):
        val = value
    elif value.startswith("**") and value.endswith("**"):
        val = value                                    # bold value is legal
    else:
        val = f"`{value.strip('`')}`"
    return f"Set {_bold(field)} to {val}."


def rewrite(line: str, integration_name: str | None) -> tuple[str, str]:
    """Return (rewritten line, note). An empty note means a clean rewrite."""
    raw = line.strip()
    if INFORMATIONAL.match(raw):
        return raw, ""                                  # intentionally actionless

    if re.match(r"^open\s+WSO2\s+Integrator", raw, re.I):
        return "Open WSO2 Integrator.", ""

    m = re.match(r"^Set\s+(.+?)\s+to\s+(.+?)\.?$", raw, re.I)
    if m:
        return _rewrite_set(m.group(1), m.group(2)), ""

    m = re.match(r"^Select\s+(.+?)\.?$", raw, re.I)
    if m:
        body = m.group(1)
        if re.search(r"your integration", body, re.I):
            if not integration_name:
                return raw, "names the integration indirectly — set it by hand"
            return f"Select {_bold(integration_name)}.", ""
        return _rewrite_select(body), ""

    # "In the HTTP service design view, select + Add Resource." — the parser is
    # happy with a leading clause as long as `select` sits right before the
    # bold target, so keep the doc's phrasing and bold what follows.
    m = re.match(r"^(?P<pre>.+?\bselect)\s+(?P<target>.+?)\.?$", raw, re.I)
    if m:
        return f"{m.group('pre')} {_rewrite_select(m.group('target'))[len('Select '):]}", ""

    return raw, "no rule matched — check against the grammar reference"


def parse_page(text: str) -> dict:
    lines = text.splitlines()
    doc: dict = {"title": "", "time": "", "build": "", "links": [], "steps": []}
    step, in_prereq, skip_admonition = None, False, False

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        m = STEP_RE.match(line)
        if m:
            in_prereq = skip_admonition = False
            step = {"n": int(m.group(1)), "title": m.group(2), "items": []}
            doc["steps"].append(step)
            continue

        if PREREQ_RE.match(line):
            in_prereq = True
            continue
        if ADMONITION_RE.match(line):
            skip_admonition = True
            continue
        if not stripped:
            skip_admonition = False
            continue
        if TAB_MARKER_RE.match(line) and step is None:
            continue

        if in_prereq:
            doc["links"] += [(t, u) for t, u in LINK_RE.findall(line)]
            continue
        if skip_admonition:
            continue                                    # NOTE body — cloud-editor aside

        m = META_RE.match(stripped)
        if m:
            doc["time"], doc["build"] = m.group("time").strip(), m.group("build").strip()
            continue

        m = NUMBERED_RE.match(line)
        if m and step is not None:
            step["items"].append(m.group(2))
            continue

        if step is None and not doc["title"] and not stripped.startswith(("*", "[", "#")):
            doc["title"] = stripped
    return doc


def build_workflow(doc: dict, cloud: bool) -> tuple[str, list[tuple[str, str]]]:
    integration = None
    for s in doc["steps"]:
        for it in s["items"]:
            m = re.search(r"Set\s+Integration Name\s+to\s+`?([\w.-]+)`?", it, re.I)
            if m:
                integration = m.group(1)
    out, notes = [], []
    for s in doc["steps"]:
        out.append(f"## Step {s['n']}: {s['title']}\n")
        n = 0
        for item in s["items"]:
            line, note = rewrite(item, integration)
            if note:
                notes.append((item, note))
            # Desktop-only reality the cloud editor never shows.
            if not cloud and re.match(r"^Open WSO2 Integrator", line, re.I):
                n += 1
                out.append(f"{n}. {line}")
                n += 1
                out.append(f"{n}. Select **Skip for now**.")
                continue
            n += 1
            out.append(f"{n}. {line}")
            if not cloud and re.match(r"^Set \*\*Project Name\*\*", line):
                n += 1
                out.append(f"{n}. Select **Browse**.")
                n += 1
                out.append(f"{n}. Select the project location and select **Open**.")
        # Give the server time to boot so the GIF shows it actually starting.
        out = [re.sub(r"^(\d+\. Select \*\*Run\*\*)\.$", r"\1 in the toolbar.", ln)
               for ln in out]
        out.append("")
    return "\n".join(out).rstrip() + "\n", notes


def validate(md: str) -> list[tuple[str, int]]:
    """Every actionable line, with how many actions the real parser makes of it."""
    results = []
    for line in md.splitlines():
        m = NUMBERED_RE.match(line)
        if not m:
            continue
        body = m.group(2)
        n = len(_parse_instructions(f"1. {body}"))
        results.append((body, n))
    return results


def narration_skeleton(doc: dict, md: str) -> str:
    per_step, current = {}, None
    for line in md.splitlines():
        m = STEP_RE.match(line)
        if m:
            current = int(m.group(1))
            per_step[current] = []
            continue
        m = NUMBERED_RE.match(line)
        if m and current:
            body = m.group(2)
            if _parse_instructions(f"1. {body}"):
                per_step[current].append(body)
    out = [f"# FlowCast natural narration — {doc['title'] or 'workflow'}",
           "#",
           "# One line per SUB-STEP, in order, matching the recorded actions 1:1.",
           "# REWRITE these — they are the raw click steps, not a script.",
           "",
           "[card]", doc["title"] or "Let's build this in WSO2 Integrator.", "",
           "[intro]", doc["build"] or "Here's what we'll build.", ""]
    for n, items in sorted(per_step.items()):
        out.append(f"[step {n}]")
        out += [re.sub(r"\*\*|`", "", i).rstrip(".") + "." for i in items]
        out.append("")
    out += ["[outro]", "That's it, built and tested end to end. Thanks for watching.", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Docs page -> FlowCast workflow markdown.")
    ap.add_argument("page", help="file with the pasted docs page, or - for stdin")
    ap.add_argument("--slug", required=True, help="workflows/<slug>.md")
    ap.add_argument("--cloud", action="store_true",
                    help="cloud editor: skip the sign-in / Browse / location lines")
    ap.add_argument("--narration", action="store_true", help="also write a narration skeleton")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    text = sys.stdin.read() if args.page == "-" else Path(args.page).read_text()
    doc = parse_page(text)
    md, notes = build_workflow(doc, args.cloud)

    print(f"Title      : {doc['title'] or '(none found)'}")
    print(f"Time       : {doc['time'] or '-'}")
    print(f"Builds     : {doc['build'] or '-'}")
    print(f"Steps      : {len(doc['steps'])}")
    print()

    results = validate(md)
    bad = [b for b, n in results if n == 0 and not INFORMATIONAL.match(b)]
    for body, n in results:
        mark = "·" if INFORMATIONAL.match(body) else ("✓" if n else "✗")
        print(f"  {mark} {body}")
    print(f"\n  {len(results)} line(s), {sum(n for _, n in results)} action(s)")
    for item, note in notes:
        print(f"  ! {item!r}: {note}")
    if bad:
        print(f"\n  {len(bad)} line(s) parse to NOTHING — fix before recording:")
        for b in bad:
            print(f"      {b}")

    if args.dry_run:
        print("\n" + "─" * 60 + "\n" + md)
        return

    wf = ROOT / "workflows" / f"{args.slug}.md"
    wf.write_text(md)
    print(f"\nwrote {wf}")
    meta = {"title": doc["title"], "time": doc["time"], "build": doc["build"],
            "links": doc["links"], "slug": args.slug}
    (wf.with_suffix(".meta.json")).write_text(json.dumps(meta, indent=2))
    print(f"wrote {wf.with_suffix('.meta.json')}")

    if args.narration:
        rec = ROOT / "output" / "recordings" / args.slug
        rec.mkdir(parents=True, exist_ok=True)
        (rec / "narration.txt").write_text(narration_skeleton(doc, md))
        print(f"wrote {rec / 'narration.txt'}  (skeleton — rewrite it)")

    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
