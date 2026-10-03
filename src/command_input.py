"""Learned command-input steps for FlowCast.

A \`command\` workflow action lets a recording flow pause so you can hand a
command to something that lives outside the WSO2 window. The first time a
\`command\` action is reached it:

  1. Prompts on the SAME terminal the recorder is running in (a Python
     input() prompt — no extra Terminal window is opened).
  2. Runs the command in the background.
  3. Saves it to kb/commands.json keyed by (workflow, step, action_index) —
     "trained".

On later runs the saved command is replayed automatically without prompting
(also in the background). No Terminal.app window is ever opened on screen, so
the recording only ever shows the WSO2 window.

File: kb/commands.json
{
  "version": 1,
  "entries": {
    "integration-as-api-hello-world.md::Create the integration::3": {
      "command": "curl ...",
      "use_count": 2,
      "last_used": "..."
    }
  }
}
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_COMMANDS_PATH = Path(__file__).parent.parent / "kb" / "commands.json"


# ── Persistence ───────────────────────────────────────────────────────────────

def _load() -> dict:
    if _COMMANDS_PATH.exists():
        try:
            return json.loads(_COMMANDS_PATH.read_text())
        except Exception:
            pass
    return {"version": 1, "entries": {}}


def _save(data: dict) -> None:
    _COMMANDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _COMMANDS_PATH.write_text(json.dumps(data, indent=2))


def _key(workflow: str, step_title: str, action_index: int) -> str:
    return f"{workflow}::{step_title}::{action_index}"


def has_learned(workflow: str, step_title: str, action_index: int) -> bool:
    return bool(_load().get("entries", {}).get(_key(workflow, step_title, action_index)))


def get_learned(workflow: str, step_title: str, action_index: int) -> str | None:
    entry = _load().get("entries", {}).get(_key(workflow, step_title, action_index))
    return entry.get("command") if entry else None


def save_learned(workflow: str, step_title: str, action_index: int, command: str) -> None:
    data = _load()
    entries = data.setdefault("entries", {})
    k = _key(workflow, step_title, action_index)
    prev = entries.get(k, {})
    entries[k] = {
        "command": command,
        "use_count": prev.get("use_count", 0) + 1,
        "last_used": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save(data)
    print(f"[command_input] Learned command for '{k}': '{command}'")


# ── Command helpers ─────────────────────────────────────────────────────────

def _run_command_background(command: str) -> None:
    """Run a command in the background, capturing output to stdout.

    This is the default: no Terminal window pops up. The command still runs for
    real, and its output appears in the FlowCast run log. When the workflow was
    given a command action (or a learned one exists), the run's caller (the
    supervisor or the user running main.py directly) is the one that prompted —
    nothing extra is shown on the screen.
    """
    print(f"[command_input] Running in background: {command}")
    try:
        subprocess.run(command, shell=True, check=False, timeout=180)
    except subprocess.TimeoutExpired:
        print(f"[command_input] timeout running: {command}")
    except Exception as e:
        print(f"[command_input] failed running '{command}': {e}")


# ── The user-facing prompt ("popup") ─────────────────────────────────────────

def _notify(title: str, message: str) -> None:
    """macOS notification so the user knows it's their turn, even when they are
    only watching the WSO2 window."""
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{message}" with title "{title}"',
        ], capture_output=True, timeout=5)
    except Exception:
        pass


def prompt_for_command(action: dict[str, Any], workflow_path: Path | None,
                       step_title: str, action_index: int,
                       ) -> tuple[str, str]:
    """Ask for a command on the terminal, with a popup cue.

    Returns (command, status): status is 'ran' (command entered), 'skip'
    (user skipped), or 'default' (used the workflow's default command).
    """
    default = action.get("command", "")
    # The "popup" is just the Python input() prompt below — no Terminal window
    # is opened, no AppleScript cue. The only thing shown is the notification
    # (silent if the app lacks notification permission).
    _notify("FlowCast", "Enter the next command (python input prompt).")

    if not _prompt_available():
        # No terminal to prompt on — fall back to the default (if any).
        if default:
            return default, "default"
        print("[command_input] No terminal available and no default command — skipping.")
        return "", "skip"

    print("\n" + "─" * 60)
    print("  COMMAND INPUT REQUIRED")
    if default:
        print(f"  Default (press Enter to use): {default}")
    print("  Type a shell command to run, or 'skip' to skip.")
    print("─" * 60)
    try:
        raw = input("command> ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "", "skip"
    if not raw and default:
        return default, "default"
    if not raw:
        return "", "skip"
    low = raw.lower()
    if low in ("skip", "s", "q", "quit", "abort"):
        return "", "skip"
    return raw, "ran"


def _prompt_available() -> bool:
    import sys
    import os
    if os.environ.get("FLOWCAST_NO_PROMPT", "").strip() == "1":
        return False
    return sys.stdin.isatty()