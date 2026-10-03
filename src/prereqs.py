"""Start a page's prerequisites before FlowCast records it.

A docs page that says "A running RabbitMQ instance (or use Docker: docker run …)"
cannot be followed hands-free until something starts RabbitMQ. The recipes in
kb/prereq_recipes.json say how: an image, its ports, how to tell it is ready,
the connection values it answers to, and — for event-driven pages — a command
that sends the test event the docs send by hand.

Every container is named `flowcast-<recipe id>` and left running between videos
(starting MySQL twice for two pages is wasted minutes). `stop()` removes them.

Docker comes from whatever is installed: a running daemon is used as is, and
colima is started when there is no daemon but colima is on the PATH.
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECIPES = ROOT / "kb" / "prereq_recipes.json"


def recipes() -> list[dict]:
    return json.loads(RECIPES.read_text())["recipes"]


def by_id(rid: str) -> dict:
    return next(r for r in recipes() if r["id"] == rid)


def match(text: str) -> list[str]:
    """Recipe ids whose subject the text asks for."""
    return [r["id"] for r in recipes() if re.search(r["match"], text, re.I)]


# ── docker engine ────────────────────────────────────────────────────────────

class SetupError(RuntimeError):
    pass


def _docker(*args: str, check: bool = True, timeout: float = 600) -> subprocess.CompletedProcess:
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise SetupError(f"docker {' '.join(args[:2])} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def engine_running() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return _docker("info", "--format", "{{.ServerVersion}}", check=False, timeout=20).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def ensure_engine(log=print, rosetta: bool = False) -> None:
    """A docker daemon, starting colima if that is what is installed."""
    if engine_running():
        return
    if not shutil.which("docker"):
        raise SetupError("Docker is not installed. Install colima (brew install colima docker) "
                         "or Docker Desktop, then try again.")
    if shutil.which("colima"):
        args = ["colima", "start"]
        if rosetta:
            args += ["--vm-type", "vz", "--vz-rosetta"]
        log("starting colima (the Docker VM) — about a minute the first time…")
        r = subprocess.run(args, capture_output=True, text=True, timeout=600)
        if r.returncode != 0 and not engine_running():
            raise SetupError(f"colima did not start: {(r.stderr or r.stdout).strip()[-400:]}")
    if not engine_running():
        raise SetupError("No Docker daemon is running. Open Docker Desktop (or run `colima start`).")


# ── containers ───────────────────────────────────────────────────────────────

def _name(rid: str) -> str:
    return f"flowcast-{rid}"


def _state(rid: str) -> str | None:
    r = _docker("inspect", "-f", "{{.State.Status}}", _name(rid), check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def _wait_ready(rec: dict, log, timeout: float = 180) -> None:
    deadline = time.time() + timeout
    port = rec.get("ready_port")
    while time.time() < deadline:
        ok = not port or _port_open(int(port))
        if ok and rec.get("ready_log"):
            logs = _docker("logs", "--tail", "200", _name(rec["id"]), check=False)
            ok = rec["ready_log"] in (logs.stdout + logs.stderr)
        if ok and rec.get("ready_http"):
            try:
                urllib.request.urlopen(rec["ready_http"], timeout=2)
            except Exception as e:      # 401 from a management UI still means "up"
                ok = "401" in str(e)
        if ok:
            # A port that accepts connections is not always a broker that
            # accepts messages; give slow starters their documented grace.
            time.sleep(float(rec.get("ready_seconds", 2)))
            return
        time.sleep(2)
    raise SetupError(f"{rec['label']} did not become ready within {int(timeout)}s "
                     f"(docker logs {_name(rec['id'])})")


def start(rid: str, log=print) -> dict:
    rec = by_id(rid)
    state = _state(rid)
    if state == "running":
        log(f"{rec['label']}: already running ({_name(rid)})")
    elif state:
        log(f"{rec['label']}: starting existing container")
        _docker("start", _name(rid))
    else:
        log(f"{rec['label']}: pulling and starting {rec['image']}")
        args = ["run", "-d", "--name", _name(rid)]
        if rec.get("platform"):
            args += ["--platform", rec["platform"]]
        for p in rec.get("ports", []):
            args += ["-p", p]
        for k, v in rec.get("env", {}).items():
            args += ["-e", f"{k}={v}"]
        args += rec.get("extra", [])
        args += [rec["image"], *rec.get("command", [])]
        _docker(*args, timeout=1200)
    _wait_ready(rec, log)
    log(f"{rec['label']}: ready")
    return rec


def stop(rids: list[str] | None = None, log=print) -> list[str]:
    """Remove FlowCast's containers (all of them when rids is None)."""
    if not engine_running():
        return []
    r = _docker("ps", "-a", "--filter", "name=^flowcast-", "--format", "{{.Names}}", check=False)
    names = [n for n in r.stdout.split() if rids is None or n.removeprefix("flowcast-") in rids]
    for n in names:
        _docker("rm", "-f", n, check=False)
        log(f"removed {n}")
    return names


def running() -> list[str]:
    if not engine_running():
        return []
    r = _docker("ps", "--filter", "name=^flowcast-", "--format", "{{.Names}}", check=False)
    return [n.removeprefix("flowcast-") for n in r.stdout.split()]


# ── connection values ────────────────────────────────────────────────────────

# Which recipe value a configurable's name stands for. Order matters: the
# first pattern that matches wins, so "dbPassword" is a password, not a db.
_MEANING = [
    ("password", r"pass(?:word)?|pwd"),
    ("user", r"user(?:name)?|login"),
    ("url", r"url|uri|jdbc|endpoint|connection ?string"),
    ("port", r"port"),
    ("host", r"host|server|address"),
    ("database", r"database|db(?:name)?$|schema"),
    ("bootstrap", r"bootstrap|brokers?"),
    ("vpn", r"vpn"),
    ("path", r"path|dir(?:ectory)?"),
]


def value_for(name: str, recipe_ids: list[str]) -> str | None:
    """The value a running prerequisite gives a configurable called `name`."""
    for rid in recipe_ids:
        vals = by_id(rid).get("values", {})
        for meaning, rx in _MEANING:
            if re.search(rx, name, re.I) and meaning in vals:
                return vals[meaning]
    return None
