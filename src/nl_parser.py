"""
nl_parser.py — Convert a plain text instruction file into structured
action dicts using an LLM (Gemini, Groq, or local Ollama).

Configure via .env:
    LLM_PROVIDER=groq            # "gemini" (default), "groq", or "ollama"
    GROQ_API_KEY=your_key        # required for Groq
    GROQ_MODEL=llama-3.3-70b-versatile  # optional, defaults to llama-3.3-70b-versatile
    OLLAMA_MODEL=llama3.1        # any model you have pulled
    OLLAMA_HOST=http://localhost:11434  # optional, defaults to localhost

Example input file (workflows/my_task.txt):
    app: WSO2 Integrator
    app_path: $HOME/Applications/WSO2 Integrator.app

    Open the app and maximize it.
    Then click Create, type Project1 as the integration name,
    browse for a folder and hit Open to confirm.
    Finally click Create Integration.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY not set in .env")
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


_SYSTEM_PROMPT = """\
You are a macOS UI automation planner. Given natural language instructions, convert them into a JSON array of action steps.

Each action must be one of these types:

1. **open_app** — Open and maximize a macOS application
   {"action": "open_app", "app_name": "App Name", "app_path": "/path/to/App.app"}

2. **click** — Click on a UI element identified by its visible text label
   {"action": "click", "target": "Button Label", "timeout": 10}
   For icon/symbol targets (target has no letters, e.g. '+'), also add a "hint" field
   describing the element's location context from the instruction, e.g.:
   {"action": "click", "target": "+", "hint": "between Start and Error Handler nodes in the flowchart", "timeout": 10}
   If the instruction says to click offset N px right/left/up/down of a label, add offset_x/offset_y (pixels, right/down are positive):
   {"action": "click", "target": "Fx", "offset_x": 10, "offset_y": 0, "timeout": 10}

3. **type** — Type text into a field identified by its visible label/placeholder
   {"action": "type", "field_target": "Field Label", "value": "text to type", "timeout": 10}

4. **hotkey** — Press a keyboard shortcut
   {"action": "hotkey", "keys": ["command", "shift", "g"], "wait": 1}

5. **scroll** — Scroll at a UI element
   {"action": "scroll", "target": "Element Label", "clicks": -3}
   Use negative clicks for down, positive for up.

6. **shell** — Run a shell command
   {"action": "shell", "command": "the command", "wait": 2}

7. **wait** — Pause for a duration
   {"action": "shell", "command": "sleep N", "wait": N}

Rules:
- Return ONLY a valid JSON array. No markdown fences, no explanation, no extra text.
- ALWAYS use **open_app** (never shell) to launch or open an application, even if the user also says "maximize". The open_app action handles maximizing automatically.
- For "click" and "type" actions, the "target" / "field_target" must be the exact visible text label the user would see on screen (button text, placeholder text, menu label).
- For "type" actions, the "value" MUST be copied VERBATIM from the instructions. Never substitute, normalize, or infer a different value. If the user says 'enter foo', value must be "foo". If the user says 'enter bar', value must be "bar".
- Interpret casual language: "hit", "tap", "press" (on a button) → click. "enter", "put", "fill in", "name it" → type. "launch", "start", "fire up", "open" → open_app.
- If the user mentions an app name but no path, use the app_name and set app_path to "$HOME/Applications/{app_name}.app".
- Break compound sentences into individual steps. "Click Create then type hello" → two actions.
- Preserve the order of operations as the user described them.
- If the user says "wait" or "pause", convert to a sleep shell command.
"""


def _call_gemini(user_prompt: str) -> str:
    """Send prompt to Gemini and return the raw response text."""
    client = _get_gemini_client()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    print(f"[nl_parser] Sending instructions to Gemini ({model})...")

    response = client.models.generate_content(
        model=model,
        contents=[
            {"role": "user", "parts": [{"text": _SYSTEM_PROMPT + "\n\n" + user_prompt}]},
        ],
    )
    return response.text.strip()


def _call_groq(user_prompt: str) -> str:
    """Send prompt to Groq and return the raw response text."""
    from groq import Groq

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY not set in .env")

    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    print(f"[nl_parser] Sending instructions to Groq ({model})...")

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content.strip()


def _call_ollama(user_prompt: str) -> str:
    """Send prompt to a local Ollama model and return the raw response text."""
    import requests

    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.1")
    print(f"[nl_parser] Sending instructions to Ollama ({model})...")

    payload = {
        "model": model,
        "stream": True,
        "think": False,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }

    chunks = []
    with requests.post(
        f"{host}/api/chat",
        json=payload,
        stream=True,
        timeout=(30, None),   # (connect_timeout, read_timeout=no limit)
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            chunk = data.get("message", {}).get("content", "")
            if chunk:
                chunks.append(chunk)
            if data.get("done"):
                break

    return "".join(chunks).strip()


def _call_llm(user_prompt: str) -> str:
    """Route to the configured LLM provider."""
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    if provider == "groq":
        return _call_groq(user_prompt)
    elif provider == "ollama":
        return _call_ollama(user_prompt)
    else:
        return _call_gemini(user_prompt)


def _extract_metadata(text: str) -> tuple[dict[str, str], str]:
    """
    Pull key: value metadata lines from the top of the text.
    Returns (metadata_dict, remaining_text).
    """
    meta = {}
    remaining_lines = []
    past_meta = False

    for line in text.splitlines():
        stripped = line.strip()
        if not past_meta and not stripped:
            continue  # skip leading blank lines
        if not past_meta and re.match(r'^[a-z_]+\s*:', stripped, re.IGNORECASE):
            key, _, val = stripped.partition(":")
            key = key.strip().lower()
            val = val.strip()
            if key and val:
                meta[key] = val
                continue
        past_meta = True
        remaining_lines.append(line)

    return meta, "\n".join(remaining_lines).strip()


def _make_open_and_maximize(app_name: str, app_path: str) -> list[dict]:
    """Generate open + activate + maximize actions for a macOS app."""
    return [
        {
            "action": "shell",
            "command": f'open "{app_path}"',
            "wait": 8,
        },
        {
            "action": "shell",
            "command": (
                f"osascript"
                f" -e 'tell application \"{app_name}\" to activate'"
                f" -e 'delay 1'"
                f" -e 'tell application \"Finder\" to set _b to bounds of window of desktop'"
                f" -e 'tell application \"System Events\" to tell process \"{app_name}\"'"
                f" -e '  set position of window 1 to {{0, 25}}'"
                f" -e '  set size of window 1 to {{item 3 of _b, (item 4 of _b) - 25}}'"
                f" -e 'end tell'"
            ),
            "wait": 2,
        },
    ]


def _parse_markdown_actions(raw: str) -> list[dict] | None:
    """
    Fallback: parse qwen's markdown-formatted response into action dicts.
    Handles numbered lists where each item describes an action.
    Returns None if it can't extract anything useful.
    """
    actions = []

    # Split on numbered list items: "1. ...", "2. ...", etc.
    items = re.split(r'\n?\d+\.\s+', raw.strip())
    items = [i.strip() for i in items if i.strip()]

    for item in items:
        # Normalize the item: lowercase first word for matching
        low = item.lower()

        # Detect action type from keywords
        if re.search(r'\bopen[_\s]app\b|launch|open the app|start the app', low):
            # Try to extract app_name from item
            m = re.search(r'(?:open|launch|start)\s+(?:the\s+)?(.+?)(?:\s+app|\s+application)?(?:\s*[-–:]|$)', item, re.IGNORECASE)
            app_name = m.group(1).strip() if m else ""
            actions.append({"action": "open_app", "app_name": app_name, "app_path": f"$HOME/Applications/{app_name}.app"})

        elif re.search(r'\bclick\b|\btap\b|\bpress\b(?!\s+(?:command|ctrl|shift|alt|cmd))', low):
            # Extract quoted target or last meaningful noun phrase
            m = re.search(r'["\u201c](.+?)["\u201d]', item)
            if not m:
                m = re.search(r'(?:click|tap|press)\s+(?:the\s+|on\s+)?(.+?)(?:\s+button|\s+link|\s*$)', item, re.IGNORECASE)
            target = m.group(1).strip() if m else item[:40]
            actions.append({"action": "click", "target": target, "timeout": 10})

        elif re.search(r'\btype\b|\benter\b|\bfill\b|\binput\b', low):
            # Extract value (quoted preferred) and field
            val_m = re.search(r'["\u201c](.+?)["\u201d]', item)
            value = val_m.group(1) if val_m else ""
            field_m = re.search(r'(?:in|into|the)\s+(?:the\s+)?(.+?)(?:\s+field|\s+box|\s+input)?(?:\s*$)', item, re.IGNORECASE)
            field = field_m.group(1).strip() if field_m else "field"
            if value:
                actions.append({"action": "type", "field_target": field, "value": value, "timeout": 10})

        elif re.search(r'\bpress\b.+(?:command|ctrl|shift|alt|cmd)', low) or re.search(r'\bhotkey\b|\bshortcut\b', low):
            # Extract key names
            key_map = {"command": "command", "cmd": "command", "ctrl": "ctrl", "control": "ctrl",
                       "shift": "shift", "alt": "alt", "option": "alt",
                       "return": "return", "enter": "return", "tab": "tab",
                       "g": "g", "a": "a", "c": "c", "v": "v", "x": "x", "z": "z"}
            keys = [key_map[w] for w in re.findall(r'\b([a-zA-Z]+)\b', low) if w in key_map]
            if keys:
                actions.append({"action": "hotkey", "keys": keys, "wait": 1})

    return actions if actions else None


def _extract_type_values(instructions: str) -> list[str]:
    """
    Pull typed values directly from the instruction text, line by line.

    Matches patterns like:
        enter Test
        type hello world
        fill in my-project
        name it foo
        put bar
    """
    patterns = [
        # Literal double-quoted value wrapped in single quotes: Enter '"Hello World"'
        # → typed value includes the double quotes
        (r"""\b(?:enter|type|fill\s+in|name\s+it|put)\b\s+'(".+?")'""", True),
        # Normal quoted value: Enter "Hello World" → strips quotes
        (r'\b(?:enter|type|fill\s+in|name\s+it|put)\b\s+["\'](.+?)["\']', False),
        # Unquoted value
        (r'\b(?:enter|type|fill\s+in|name\s+it|put)\b\s+(\S+(?:\s+\S+)*?)(?:\s*[.,;]|\s*$)', False),
    ]
    values = []
    for line in instructions.splitlines():
        line = line.strip()
        if not line:
            continue
        for pat, keep_quotes in patterns:
            m = re.search(pat, line, re.IGNORECASE)
            if m:
                val = m.group(1).strip().rstrip('.,;')
                if val and val.lower() not in ('the', 'a', 'an', 'it', 'this', 'that'):
                    values.append(val)
                break  # one value per line
    return values


def _apply_click_offsets(actions: list[dict], instructions: str) -> None:
    """
    Parse offset directives from instruction lines and apply them to the
    matching click action, e.g.:
        Click Fx offset 40px right  →  action["offset_x"] = 40
        Click label offset 20px down →  action["offset_y"] = 20
    """
    offset_pat = re.compile(
        r'click\s+(.+?)\s+offset\s+(\d+)\s*px\s+(right|left|up|down)',
        re.IGNORECASE,
    )
    for line in instructions.splitlines():
        m = offset_pat.search(line.strip())
        if not m:
            continue
        target_hint = m.group(1).strip().lower()
        amount = int(m.group(2))
        direction = m.group(3).lower()

        # Find the click action whose target matches the hint
        for idx, action in enumerate(actions):
            if action.get("action") != "click":
                continue
            if target_hint in action.get("target", "").lower():
                if direction == "right":
                    action["offset_x"] = amount
                elif direction == "left":
                    action["offset_x"] = -amount
                elif direction == "down":
                    action["offset_y"] = amount
                elif direction == "up":
                    action["offset_y"] = -amount
                print(f"[nl_parser] Applied offset {direction} {amount}px to click '{action['target']}'")
                # Mark the immediately following type action to skip its own click
                # so it types into the field we just focused, not re-click Fx.
                for k in range(idx + 1, len(actions)):
                    if actions[k].get("action") == "type":
                        actions[k]["skip_click"] = True
                        print(f"[nl_parser] Marked next type action as skip_click (field pre-focused)")
                        break
                break


def _override_type_values(actions: list[dict], instructions: str) -> None:
    """
    Replace LLM-parsed 'value' fields in type actions with values
    extracted directly from the instruction text.
    """
    file_values = _extract_type_values(instructions)
    type_actions = [a for a in actions if a.get("action") == "type"]

    for i, action in enumerate(type_actions):
        if i < len(file_values):
            old = action.get("value", "")
            new = file_values[i]
            if old != new:
                print(f"[nl_parser] Override type value: '{old}' → '{new}' (from file)")
                action["value"] = new


def parse_file(filepath: str | Path) -> list[dict[str, Any]]:
    """
    Parse a plain text instruction file into action dicts.

    The file can optionally start with metadata lines (app:, app_path:),
    followed by free-form natural language instructions.
    """
    actions, _ = parse_file_with_meta(filepath)
    return actions


def parse_file_with_meta(filepath: str | Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """
    Parse a plain text instruction file into (actions, metadata).

    Returns (actions, metadata_dict) where metadata has 'app' and 'app_path' keys.
    """
    filepath = Path(filepath)
    content = filepath.read_text()
    return parse_text_with_meta(content)


def parse_text(content: str) -> list[dict[str, Any]]:
    """
    Parse a plain text string of instructions into action dicts.
    """
    actions, _ = parse_text_with_meta(content)
    return actions


def parse_text_with_meta(content: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """
    Parse a plain text string of instructions into (actions, metadata).
    """
    meta, instructions = _extract_metadata(content)

    if not instructions.strip():
        print("[nl_parser] No instructions found in input.")
        return [], meta

    # Build context from metadata
    context_parts = []
    if meta.get("app"):
        context_parts.append(f"The target application is: {meta['app']}")
    if meta.get("app_path"):
        context_parts.append(f"The app path is: {meta['app_path']}")

    context = "\n".join(context_parts)
    user_prompt = f"{context}\n\nInstructions:\n{instructions}" if context else instructions

    print(f"[nl_parser] Instructions from file:\n{instructions}\n")
    raw = _call_llm(user_prompt)

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        actions = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[nl_parser] Failed to parse LLM response as JSON: {e}")
        print(f"[nl_parser] Raw response:\n{raw[:500]}")
        # Try markdown fallback
        fallback = _parse_markdown_actions(raw)
        if fallback:
            print(f"[nl_parser] Markdown fallback parsed {len(fallback)} actions")
            actions = fallback
        else:
            return [], meta

    if not isinstance(actions, list):
        if isinstance(actions, dict):
            # Single action dict — wrap it
            if "action" in actions:
                actions = [actions]
            else:
                # Wrapped array — try common keys
                for key in ("actions", "steps", "result", "items", "workflow"):
                    if key in actions and isinstance(actions[key], list):
                        actions = actions[key]
                        break
                else:
                    # Last resort: grab the first list value in the dict
                    for v in actions.values():
                        if isinstance(v, list):
                            actions = v
                            break
                    else:
                        print(f"[nl_parser] Expected a JSON array, got dict with keys: {list(actions.keys())}")
                        return [], meta
        else:
            print(f"[nl_parser] Expected a JSON array, got {type(actions).__name__}")
            return [], meta

    # Post-process: strip surrounding quotes from targets (LLM sometimes outputs
    # target: "\"+"  instead of  target: "+")
    _QUOTE_CHARS = '"\'"\u201c\u201d'
    for action in actions:
        for field in ("target", "field_target"):
            val = action.get(field)
            if isinstance(val, str):
                stripped = val.strip(_QUOTE_CHARS)
                if stripped != val:
                    print(f"[nl_parser] Stripped quotes from {field}: '{val}' → '{stripped}'")
                    action[field] = stripped

    # Post-process: override LLM "type" values with values extracted
    # directly from the instructions, so txt file edits always take effect.
    _override_type_values(actions, instructions)

    # Post-process: extract click offsets from instruction text and apply them.
    # Handles patterns like "Click Fx offset 40px right" reliably even if the
    # LLM forgets to include offset_x/offset_y in its JSON.
    _apply_click_offsets(actions, instructions)

    # Post-process: expand open_app into shell commands
    expanded = []
    for action in actions:
        if action.get("action") == "open_app":
            app_name = action.get("app_name", meta.get("app", ""))
            app_path = action.get("app_path", meta.get("app_path", ""))
            expanded.extend(_make_open_and_maximize(app_name, app_path))
        else:
            expanded.append(action)

    print(f"[nl_parser] Parsed {len(expanded)} actions from natural language")

    # Show parsed steps for user confirmation
    for i, a in enumerate(expanded, 1):
        if a["action"] == "click":
            print(f"  {i}. Click on \"{a.get('target')}\"")
        elif a["action"] == "type":
            print(f"  {i}. Type \"{a.get('value')}\" in \"{a.get('field_target')}\"")
        elif a["action"] == "hotkey":
            print(f"  {i}. Press {'+'.join(a.get('keys', []))}")
        elif a["action"] == "scroll":
            print(f"  {i}. Scroll at \"{a.get('target')}\"")
        elif a["action"] == "shell":
            print(f"  {i}. Run: {a.get('command', '')[:60]}")

    return expanded, meta
