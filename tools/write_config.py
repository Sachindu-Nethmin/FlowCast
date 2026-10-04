#!/usr/bin/env python3
"""
write_config.py — fill a WSO2 Integrator project's configurables, off camera.

Connector docs end their setup with "Set a value for each configurable listed
below" — an API key, a token, a database password. Typing those into the
Configurations panel would put them in the video. This writes them straight
into the integration's Config.toml instead, which is where the panel saves
them anyway.

    tools/write_config.py --project integration-as-api [--expect apiKey,serviceUrl]

Values come from the environment, never from the command line (a workflow line
is logged and saved; the environment is not):

    FLOWCAST_INPUTS    JSON object {configurable name: value} — FlowCast Studio
                       fills it from what you entered (secrets from Keychain)
    FLOWCAST_RECIPES   comma-separated prerequisite ids started for this page;
                       their connection values (host, port, user, …) fill any
                       configurable you did not set yourself
    FLOWCAST_PLACEHOLDERS=1
                       write placeholders ("<your-apiKey>") instead of your
                       values — what the video's Configurations panel shows.
                       Local-service values (localhost, a port) stay real.
                       tools/autopilot.py writes your real values just before
                       the run step, off camera.

Only configurables the project actually declares are written (Ballerina rejects
values for undeclared ones). `--expect` waits for those names to be declared,
since the UI saves config.bal a moment after the form closes. No value is ever
printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import prereqs  # noqa: E402

DECL = re.compile(r"^\s*configurable\s+([\w:\[\]?|.]+)\s+(\w+)\s*=\s*([^;]+);", re.M)
SECRET = re.compile(r"key|token|secret|pass(?:word)?|pwd|sid|credential|private", re.I)


def project_dir(name: str, base: Path) -> Path:
    exact = base / name
    if exact.is_dir():
        return exact
    want = re.sub(r"[^a-z0-9]", "", name.lower())
    for d in base.iterdir():
        if d.is_dir() and re.sub(r"[^a-z0-9]", "", d.name.lower()) == want:
            return d
    dirs = [d for d in base.iterdir() if d.is_dir()]
    if not dirs:
        sys.exit(f"no projects under {base}")
    return max(dirs, key=lambda d: d.stat().st_mtime)      # the one just created


def packages(proj: Path) -> list[Path]:
    out = []
    for toml in [proj / "Ballerina.toml", *proj.glob("*/Ballerina.toml")]:
        if toml.exists() and "[package]" in toml.read_text():
            out.append(toml.parent)
    return out


def declared(pkg: Path) -> dict[str, tuple[str, bool]]:
    """{name: (type, required)} from every .bal file in the package."""
    found = {}
    for bal in pkg.glob("*.bal"):
        for m in DECL.finditer(bal.read_text(errors="replace")):
            found[m.group(2)] = (m.group(1), m.group(3).strip() == "?")
    return found


def toml_value(typ: str, value: str) -> str:
    t = typ.rstrip("?")
    if t in ("int", "float", "decimal") and re.fullmatch(r"-?\d+(\.\d+)?", value.strip()):
        return value.strip()
    if t == "boolean":
        return "true" if value.strip().lower() in ("true", "1", "yes") else "false"
    if t.endswith("[]"):
        items = [v.strip() for v in value.split(",") if v.strip()]
        return "[" + ", ".join(json.dumps(i) for i in items) + "]"
    return json.dumps(value)                  # TOML basic string == JSON string


def placeholder(name: str, typ: str) -> str:
    """A value that shows what goes here without being anyone's."""
    t = typ.rstrip("?")
    if t in ("int", "float", "decimal"):
        return "0"
    if t == "boolean":
        return "false"
    if t.endswith("[]"):
        return "[]"
    if re.search(r"url|endpoint|host|uri", name, re.I):
        return json.dumps(f"https://your-{re.sub(r'(url|endpoint|uri)$', '', name, flags=re.I) or 'service'}.example.com")
    return json.dumps(f"<your-{name}>")


def merge(existing: str, entries: dict[str, str]) -> str:
    lines, seen = [], set()
    for ln in existing.splitlines():
        m = re.match(r"^\s*(\w+)\s*=", ln)
        if m and m.group(1) in entries:
            lines.append(f"{m.group(1)} = {entries[m.group(1)]}")
            seen.add(m.group(1))
        else:
            lines.append(ln)
    head = [f"{k} = {v}" for k, v in entries.items() if k not in seen]
    return "\n".join(head + lines).strip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True)
    ap.add_argument("--base", type=Path, default=Path.home() / "WSO2Integrator")
    ap.add_argument("--expect", default="", help="configurable names that must be declared")
    ap.add_argument("--wait", type=float, default=20)
    args = ap.parse_args()

    inputs = json.loads(os.environ.get("FLOWCAST_INPUTS") or "{}")
    placeholders = os.environ.get("FLOWCAST_PLACEHOLDERS") == "1"
    if placeholders:
        inputs = {}                          # yours go in just before the run, off camera
    recipes = [r for r in os.environ.get("FLOWCAST_RECIPES", "").split(",") if r]
    expect = [e for e in args.expect.split(",") if e]
    proj = project_dir(args.project, args.base)

    deadline = time.time() + args.wait
    while True:
        decl = {n: (t, req, pkg) for pkg in packages(proj) for n, (t, req) in declared(pkg).items()}
        if all(e in decl for e in expect) or time.time() > deadline:
            break
        time.sleep(1)
    if not decl:
        sys.exit(f"{proj.name}: no configurables declared yet — nothing to write")

    lower = {k.lower(): v for k, v in inputs.items()}
    by_pkg: dict[Path, dict[str, str]] = {}
    missing, report = [], []
    for name, (typ, required, pkg) in sorted(decl.items()):
        value = inputs.get(name) or lower.get(name.lower()) or prereqs.value_for(name, recipes)
        if value is None and placeholders and (required or name in expect):
            by_pkg.setdefault(pkg, {})[name] = placeholder(name, typ)
            report.append(f"{name} — placeholder")
            continue
        if value is None:
            if required:
                missing.append(name)
            continue
        by_pkg.setdefault(pkg, {})[name] = toml_value(typ, str(value))
        src = "yours" if name in inputs or name.lower() in lower else "from the local service"
        report.append(f"{name}{' (secret)' if SECRET.search(name) else ''} — {src}")

    for pkg, entries in by_pkg.items():
        cfg = pkg / "Config.toml"
        cfg.write_text(merge(cfg.read_text() if cfg.exists() else "", entries))
        os.chmod(cfg, 0o600)                  # it may hold secrets
        print(f"wrote {len(entries)} value(s) to {cfg}")
    for r in report:
        print(f"  {r}")
    if missing:
        sys.exit(f"no value for: {', '.join(missing)} — enter them in FlowCast Studio")


if __name__ == "__main__":
    main()
