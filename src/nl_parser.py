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

# ---------------------------------------------------------------------------
# WSO2 UI Knowledge Base — field label → search hints mapping
# ---------------------------------------------------------------------------
_KB_PATH = Path(__file__).parent.parent / "kb" / "wso2_ui_kb.json"
_kb_cache: dict | None = None


def _get_kb() -> dict:
    """Load the WSO2 UI knowledge base (cached)."""
    global _kb_cache
    if _kb_cache is None:
        if _KB_PATH.exists():
            _kb_cache = json.loads(_KB_PATH.read_text())
        else:
            _kb_cache = {}
    return _kb_cache


def _resolve_field_target(raw_field: str) -> tuple[str, list[str], str | None, str | None, str | None]:
    """
    Resolve a field name from markdown instructions to the best OCR search target.

    Returns (resolved_target, search_hints, component_type, placeholder, default_value):
      - resolved_target: the exact text to search for on screen
      - search_hints: alternative strings to try if the first doesn't match
      - component_type: e.g. "TextField", "DirectorySelector", "Dropdown" (from KB)
      - placeholder: placeholder text shown in the empty input field (from KB)
      - default_value: pre-filled value in the field (e.g. "/" for Service base path)

    Uses the KB field_lookup table to map common names to exact UI labels,
    then returns the field's search_hints for OCR matching.
    """
    kb = _get_kb()
    field_lookup = kb.get("field_lookup", {})
    fields = kb.get("fields", {})

    # Normalize: lowercase, strip surrounding punctuation
    normalized = raw_field.lower().strip().rstrip('.,;:')

    # Direct lookup
    canonical = field_lookup.get(normalized)
    if canonical and canonical in fields:
        entry = fields[canonical]
        hints = entry.get("search_hints", [canonical])
        placeholder = entry.get("placeholder")
        default_value = entry.get("default_value")
        comp_type = entry.get("component")
        target = placeholder if placeholder else canonical
        return target, hints + ([placeholder] if placeholder else []), comp_type, placeholder, default_value

    # Partial match: only if the lookup key is at least 60% of the input length
    # to avoid "path" matching "resource path" → "Select Path"
    best_match = None
    best_overlap = 0
    for key, canonical_name in field_lookup.items():
        # Require the key to appear as a full word boundary in the input, or vice versa
        if key == normalized:
            continue  # already checked in direct lookup
        # Check if key matches as whole words within normalized
        if re.search(r'\b' + re.escape(key) + r'\b', normalized):
            overlap = len(key) / max(len(normalized), 1)
            if overlap > best_overlap and overlap >= 0.6:
                best_overlap = overlap
                best_match = canonical_name

    if best_match and best_match in fields:
        entry = fields[best_match]
        hints = entry.get("search_hints", [best_match])
        placeholder = entry.get("placeholder")
        default_value = entry.get("default_value")
        comp_type = entry.get("component")
        target = placeholder if placeholder else best_match
        return target, hints + ([placeholder] if placeholder else []), comp_type, placeholder, default_value

    # No KB match — return as-is
    return raw_field, [raw_field], None, None, None


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


def _parse_structured_md(instructions: str) -> list[dict] | None:
    """
    Fast-path parser for well-formatted markdown instructions.

    Key convention:
      "Select/Click" + **bold**  → CLICK on the bold UI element
      "Set/Enter/Keep" + **field** + `value` → SEARCH for field, TYPE the value
      `backtick` alone  → value to type

    Examples:
      1. Select **Create New Integration**.        → click "Create New Integration"
      2. Enter the integration name (`HelloWorld`). → type "HelloWorld" in "integration name"
      3. Set **Service base path** to `/hello`.     → type "/hello" in "Service base path"
      4. Keep **Service contract** as **Design from scratch**. → type/select "Design from scratch" in "Service contract"
      5. Click **+** after the **Start** node.      → click "+" with hint "near Start"
      6. Select **Browse** and select **Open**.     → click "Browse", click "Open"
    """
    # Extract numbered/bulleted list items
    lines = []
    for line in instructions.splitlines():
        s = line.strip()
        m = re.match(r'^\d+\.\s+(.+)$', s) or re.match(r'^[-*]\s+(.+)$', s)
        if m:
            lines.append(m.group(1).strip())

    if not lines:
        return None

    # Need at least some lines with **bold** markers
    bold_count = sum(1 for l in lines if '**' in l)
    if bold_count == 0:
        return None

    # Keyword sets for intent detection
    CLICK_VERBS = r'\bselect\b|\bclick\b|\btap\b|\bpress\b|\badd\b'
    TYPE_VERBS = r'\bset\b|\benter\b|\btype\b|\bname\b|\bstore\b|\bfill\b'

    actions = []
    for line in lines:
        low = line.lower()
        bolds = re.findall(r'\*\*(.+?)\*\*', line)
        ticks = re.findall(r'`([^`]+)`', line)

        # ── 1. Offset click: Click **Fx** offset 200px right ──
        offset_m = re.search(
            r'\*\*(.+?)\*\*\s+offset\s+(\d+)\s*px\s+(right|left|up|down)',
            line, re.IGNORECASE,
        )
        if offset_m:
            target = offset_m.group(1)
            amount = int(offset_m.group(2))
            direction = offset_m.group(3).lower()
            off_x = amount if direction == "right" else -amount if direction == "left" else 0
            off_y = amount if direction == "down" else -amount if direction == "up" else 0
            act = {"action": "click", "target": target, "timeout": 10}
            if off_x:
                act["offset_x"] = off_x
            if off_y:
                act["offset_y"] = off_y
            actions.append(act)
            continue

        # ── 2. Open app: "Open WSO2 Integrator" ──
        if re.search(r'\bopen\b.*\bintegrator\b|\blaunch\b|\bstart\b.*\bapp\b', low):
            app_name = ""
            if bolds:
                app_name = bolds[0]
            else:
                am = re.search(r'open\s+(.+?)\.?\s*$', line, re.IGNORECASE)
                if am:
                    app_name = am.group(1)
            actions.append({"action": "open_app", "app_name": app_name,
                            "app_path": f"$HOME/Applications/{app_name}.app"})
            continue

        # ── 3a. "Add the `action` from the `connection`" → click connection, click action ──
        add_action_m = re.match(
            r'add\s+the\s+`([^`]+)`\s+action\s+from\s+(?:the\s+)?`([^`]+)`',
            line, re.IGNORECASE,
        )
        if add_action_m:
            action_name = add_action_m.group(1)
            connection_name = add_action_m.group(2)
            actions.append({"action": "click", "target": connection_name, "timeout": 10,
                            "hint": "connection in node panel"})
            actions.append({"action": "click", "target": action_name, "timeout": 10,
                            "hint": f"action from {connection_name}"})
            print(f"[nl_parser] ADD ACTION: click '{connection_name}' → click '{action_name}'")
            continue

        # ── 3b. KEEP → skip (leave default, don't change) ──
        # "Keep **Service contract** as **Design from scratch**."
        if re.search(r'\bkeep\b', low):
            print(f"[nl_parser] Skipping 'Keep' (leave default): {line[:60]}")
            continue

        # ── 4. SET/ENTER → TYPE action (search field, enter value) ──
        # "Set **Service base path** to `/hello`."
        # "Enter the integration name (for example, `HelloWorld`)."
        # "Name the connection `externalApi` and save."
        # "Store the action result in a variable named `response` with type `json`."
        # "Set the resource path to `/greeting` and select **Save**."  (compound)
        if re.search(TYPE_VERBS, low):
            # ── Compound: strip trailing "and select/click **X**" into a separate click ──
            trailing_clicks = []
            working_line = line
            trailing_pat = re.compile(
                r'\s+and\s+(?:select|click|press|tap)\s+\*\*(.+?)\*\*\.?\s*$',
                re.IGNORECASE,
            )
            tm = trailing_pat.search(working_line)
            while tm:
                trailing_clicks.append(tm.group(1))
                working_line = working_line[:tm.start()].rstrip()
                tm = trailing_pat.search(working_line)

            # Re-extract bolds/ticks from the cleaned line (without trailing click parts)
            line_bolds = re.findall(r'\*\*(.+?)\*\*', working_line)
            line_ticks = re.findall(r'`([^`]+)`', working_line)

            # Determine value: from `backtick` or second **bold**
            value = None
            raw_field = None

            if line_ticks:
                # Value is the first backtick
                value = line_ticks[0]
                # Field is the first **bold**, or extracted from text
                if line_bolds:
                    raw_field = line_bolds[0]
                else:
                    fm = (
                        re.search(r'(?:variable|field|param)\s+named\b', working_line, re.IGNORECASE)
                        or re.search(
                            r'(?:enter|set|type|fill|name)\s+(?:the\s+)?(.+?)(?:\s+to\b|\s+as\b|\s+named\b|\s*\(|\s*`)',
                            working_line, re.IGNORECASE,
                        )
                    )
                    if fm and fm.lastindex:
                        raw_field = fm.group(1).strip().rstrip(',. ')
                        raw_field = re.sub(r'\s+(?:in|into|a|an|the)\s*$', '', raw_field, flags=re.IGNORECASE).strip()
                    elif re.search(r'variable\s+named', working_line.lower()):
                        raw_field = "variable name"
                    else:
                        raw_field = "field"
            elif len(line_bolds) >= 2:
                # "Set **field** to **value**" — no backticks
                raw_field = line_bolds[0]
                value = line_bolds[1]

            if value and raw_field:
                resolved, hints, comp_type, placeholder, default_val = _resolve_field_target(raw_field)
                action_dict = {"action": "type", "field_target": resolved,
                               "value": value, "timeout": 10}
                if hints and hints != [resolved]:
                    action_dict["_search_hints"] = hints
                if comp_type:
                    action_dict["_component_type"] = comp_type
                if placeholder:
                    action_dict["_placeholder"] = placeholder
                if default_val:
                    action_dict["_default_value"] = default_val
                actions.append(action_dict)
                print(f"[nl_parser] SET/ENTER: field '{raw_field}' → '{resolved}', value '{value}'")

                # Append any trailing click actions
                for click_target in trailing_clicks:
                    actions.append({"action": "click", "target": click_target, "timeout": 10})
                    print(f"[nl_parser] COMPOUND CLICK: '{click_target}'")
                continue

        # ── 4. Enter quoted value into focused field: Enter '"Hello World"' ──
        enter_quoted = re.search(r"""[Ee]nter\s+'([^']+)'""", line)
        if enter_quoted:
            actions.append({"action": "type", "field_target": "field",
                            "value": enter_quoted.group(1), "timeout": 10,
                            "skip_click": True})
            continue

        # ── 5. SELECT/CLICK → CLICK action ──
        if bolds and re.search(CLICK_VERBS, low):

            # Multi-action: "Select **Browse** and select **Open**."
            multi_action = re.split(
                r'\s+(?:and\s+)?(?:select|click|press|tap)\s+',
                line, flags=re.IGNORECASE,
            )
            if len(multi_action) > 1 and len(bolds) > 1:
                for bold_target in bolds:
                    hint = None
                    pat = re.compile(
                        r'\*\*' + re.escape(bold_target) + r'\*\*'
                        r'\s+(?:after|before|inside|next to|near)\s+(?:the\s+)?(.+?)(?:\s+and\b|\.|$)',
                        re.IGNORECASE,
                    )
                    hm = pat.search(line)
                    if hm:
                        hint = hm.group(1).strip()
                    act: dict = {"action": "click", "target": bold_target, "timeout": 10}
                    if hint:
                        act["hint"] = hint
                    actions.append(act)
                continue

            # Single click with optional hint
            target = bolds[0]
            hint = None
            if len(bolds) > 1:
                # "Click **+** after the **Start** node" → hint from second bold
                hint = " ".join(f"near {b}" for b in bolds[1:])
            elif re.search(r'(?:after|before|inside|next to|near|from|under)\s+', low):
                hint_m = re.search(
                    r'(?:after|before|inside|next to|near|from|under)\s+(?:the\s+)?(.+?)(?:\.|$)',
                    line, re.IGNORECASE,
                )
                if hint_m:
                    hint = hint_m.group(1).strip()
            action: dict = {"action": "click", "target": target, "timeout": 10}
            if hint:
                action["hint"] = hint
            actions.append(action)
            continue

        # ── 6. Informational lines — skip ──
        if not bolds and not re.search(CLICK_VERBS + r'|' + TYPE_VERBS, low):
            print(f"[nl_parser] Skipping informational: {line[:60]}")
            continue

        # ── 7. Fallback: bold without clear verb → click ──
        if bolds:
            actions.append({"action": "click", "target": bolds[0], "timeout": 10})
            continue

        print(f"[nl_parser] Skipping unrecognized: {line[:60]}")

    return actions if actions else None


def _parse_markdown_actions(raw: str) -> list[dict] | None:
    """
    Fallback: parse LLM markdown-formatted response into action dicts.
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

    # Fast path: try structured markdown parsing (**bold** = UI, `tick` = value)
    structured = _parse_structured_md(instructions)
    if structured:
        print(f"[nl_parser] Fast-parsed {len(structured)} actions from structured markdown")
        # Expand open_app into shell commands
        expanded = []
        for action in structured:
            if action.get("action") == "open_app":
                app_name = action.get("app_name", meta.get("app", ""))
                app_path = action.get("app_path", meta.get("app_path", ""))
                expanded.extend(_make_open_and_maximize(app_name, app_path))
            else:
                expanded.append(action)

        # Apply offsets from instruction text
        _apply_click_offsets(expanded, instructions)

        # Show parsed steps
        for i, a in enumerate(expanded, 1):
            if a["action"] == "click":
                hint = f" (hint: {a['hint']})" if a.get("hint") else ""
                off = ""
                if a.get("offset_x") or a.get("offset_y"):
                    off = f" [offset: ({a.get('offset_x', 0)}, {a.get('offset_y', 0)})]"
                print(f"  {i}. Click on \"{a.get('target')}\"{hint}{off}")
            elif a["action"] == "type":
                print(f"  {i}. Type \"{a.get('value')}\" in \"{a.get('field_target')}\"")
            elif a["action"] == "hotkey":
                print(f"  {i}. Press {'+'.join(a.get('keys', []))}")
            elif a["action"] == "shell":
                print(f"  {i}. Run: {a.get('command', '')[:60]}")

        return expanded, meta

    # Slow path: use LLM
    print("[nl_parser] No structured markdown found, falling back to LLM...")
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
