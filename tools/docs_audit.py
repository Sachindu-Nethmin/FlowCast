#!/usr/bin/env python3
"""
docs_audit.py — how many WSO2 Integrator docs pages can FlowCast follow?

Reads every page of https://wso2.com/integration-platform/docs/ from its
Markdown source (github.com/wso2/docs-integrator), runs each instruction
through the real parser, and writes:

    kb/docs_catalog.json          every page, its verdict, its parsed steps
    kb/docs_workflows/<slug>.md   a FlowCast workflow for every walkthrough

FlowCast Studio (the Mac app under mac/) reads the catalog to show its cards.

Usage:
    uv run python tools/docs_audit.py            # fetch/update source, audit
    uv run python tools/docs_audit.py --offline  # audit the existing checkout
    uv run python tools/docs_audit.py --show build-automation
    uv run python tools/docs_audit.py --list ready

See src/doc_catalog.py for what each verdict means.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import doc_catalog as dc  # noqa: E402

LABEL = {"ready": "100% followable", "auto": "FlowCast starts the prerequisites itself",
         "keys": "needs your API keys / values", "setup": "followable after manual setup",
         "partial": "needs a person", "none": "not a walkthrough"}


def _summary(cat: dict) -> None:
    s = cat["summary"]
    print(f"\nWSO2 Integrator docs @ {cat['commit']}  ({cat['site']})")
    print(f"  {s['total']} pages, {s['walkthroughs']} of them step-by-step walkthroughs\n")
    for v in dc.VERDICTS:
        print(f"  {s[v]:5d}  {v:8} {LABEL[v]}")
    print(f"  {s['verified']:5d}  verified by an actual recording\n")
    cols = dc.VERDICTS
    print("  " + f"{'area':22}" + "".join(f"{v:>8}" for v in cols))
    for area, c in sorted(s["by_area"].items()):
        print("  " + f"{area:22}" + "".join(f"{c[v]:8d}" for v in cols))
    if s["setup_blockers"]:
        print("\n  what 'setup' pages need first: " + ", ".join(
            f"{k} ({v})" for k, v in sorted(s["setup_blockers"].items(), key=lambda kv: -kv[1])))


def _show(cat: dict, slug: str) -> None:
    page = next((p for p in cat["pages"] if p["slug"] == slug or p["path"].endswith(slug)), None)
    if not page:
        sys.exit(f"no page matching {slug!r}")
    print(f"{page['title']}  [{page['verdict']}]  {page['url']}")
    print(f"  coverage {page['coverage']:.0%}, {page['action_count']} actions, "
          f"blockers: {', '.join(page['blockers']) or '-'}  notes: {', '.join(page['notes']) or '-'}")
    for s in page["steps"]:
        print(f"\n  Step {s['n']}: {s['title']}")
        for ln in s["lines"]:
            mark = {"action": "✓", "info": "·", "unparsed": "✗"}[ln["kind"]]
            print(f"    {mark} {ln['source'][:100]}")
            for w in ln["workflow"]:
                if w != ln["source"]:
                    print(f"        → {w[:100]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="do not git fetch/pull")
    ap.add_argument("--source", type=Path, default=None,
                    help="an existing docs-integrator checkout (its root)")
    ap.add_argument("--show", default=None, help="print one page's line-by-line parse")
    ap.add_argument("--list", choices=dc.VERDICTS, default=None)
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = ap.parse_args()

    if args.show or args.list:
        cat = dc.load()
        if not cat:
            sys.exit("no catalog yet — run without --show/--list first")
        if args.show:
            _show(cat, args.show)
        else:
            for p in cat["pages"]:
                if p["verdict"] == args.list:
                    print(f"{p['slug']:48} {p['action_count']:3d} actions  {p['title']}")
        return

    if args.source:
        docs = args.source / "en" / "docs"
    elif args.offline:
        docs = dc.SOURCE_DIR / "en" / "docs"
    else:
        print("syncing docs source …", flush=True)
        docs = dc.sync_source()
    if not docs.is_dir():
        sys.exit(f"no docs at {docs} — run without --offline to fetch them")

    cat = dc.build(docs)
    dc.CATALOG.parent.mkdir(parents=True, exist_ok=True)
    dc.CATALOG.write_text(json.dumps(cat, indent=1))
    if args.json:
        print(json.dumps(cat["summary"], indent=2))
    else:
        _summary(cat)
        print(f"\n  wrote {dc.CATALOG.relative_to(ROOT)} and "
              f"{dc.WORKFLOW_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
