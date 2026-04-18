from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_STEP_RE = re.compile(r'^#{2,3}\s+Step\s+\d+\s*[:\-–]?\s*(.*)', re.MULTILINE | re.IGNORECASE)
_GIF_RE  = re.compile(r'<img\s[^>]*src=["\']([^"\']+\.gif)["\']', re.IGNORECASE)

_APP_NAME = "WSO2 Integrator"
_APP_PATH = "/Users/sachindu/Applications/WSO2 Integrator.app"

# Maps natural-language field phrases (lowercase) to exact UI label strings.
# Used when the field name in the markdown is not bold and may differ from the
# visible label in the application.
_FIELD_ALIASES: dict[str, str] = {
    "integration name":  "Integration Name",
    "resource path":     "Resource Path",
    "base url":          "Base URL",
    "action path":       "Path",
    "return expression": "Return expression",
    "connection name":   "Connection Name",
    "response variable": "Response Variable",
    "response type":     "Response Type",
    "listener port":     "Listener port",
    "service base path": "Service Base Path",
    "service base path": "Service Base Path",
    # SAP connector fields
    "auth":              "Auth",
    "password":          "Password",
    "hostname":          "Hostname",
    "data format":       "Data Format",
    "salesordertype":    "SalesOrderType",
    "salesorganization": "SalesOrganization",
    "distributionchannel": "DistributionChannel",
    "organizationdivision": "OrganizationDivision",
}


def _normalise_field(raw: str) -> str:
    """Resolve a raw field phrase to the canonical UI label."""
    key = raw.strip().lower()
    return _FIELD_ALIASES.get(key, raw.strip().title())


def _parse_instructions(instructions: str) -> list[dict[str, Any]]:
    """Convert markdown instruction lines to UI action dicts — no LLM needed.

    Rules (applied per line, in priority order):
      • "Open WSO2 Integrator"               → open_app
      • line starts with "Keep"              → skip (value already set)
      • "[Ss]elect **X**"                    → click X
      • "[Aa]dd [a [new]] **X**"             → click X  (bold element)
      • "Add the `X` action"                 → click X  (backtick action name)
      • "[Ss]et **X** to `Y`"               → type field=X, value=Y
      • "[Ss]et [the] X to `Y`"             → type field=normalise(X), value=Y
      • "[Ee]nter … (for example, `Y`)"      → type field=normalise(…), value=Y
      • "Name the connection `X`"            → type Connection Name=X
      • "Store … variable named `X` … type `Y`" → type Response Variable=X
                                                   + select Response Type=Y
      • "[Ss]earch **X** for `Y`"           → search field_target=X, value=Y
      • "[Ss]earch for `Y`"                 → search field_target="Search", value=Y
      Suffix (added after the line's primary action):
      • "and save" anywhere in line          → hotkey command+s
    """
    actions: list[dict[str, Any]] = []

    for raw_line in instructions.splitlines():
        # Strip leading list markers ("1. ", "- ", etc.)
        line = re.sub(r'^\s*\d+\.\s*', '', raw_line).strip()
        line = re.sub(r'^\s*[-*]\s*', '', line).strip()
        if not line:
            continue

        # ── Open app ──────────────────────────────────────────────────────────
        if re.search(r'\bOpen\s+WSO2\s+Integrator\b', line, re.IGNORECASE):
            actions.append({
                "action":   "open_app",
                "app_name": _APP_NAME,
                "app_path": _APP_PATH,
            })
            continue

        # ── Skip "Keep …" lines ───────────────────────────────────────────────
        if re.match(r'Keep\b', line, re.IGNORECASE):
            continue

        line_actions: list[dict[str, Any]] = []

        # ── Click: "Select **+** next to [the] **X** [section]" ──────────────
        m = re.search(
            r'select\s+\*\*\+\*\*\s+next\s+to\s+(?:the\s+)?\*\*([^*]+)\*\*',
            line, re.IGNORECASE,
        )
        if m:
            line_actions.append({
                "action": "click",
                "target": "+",
                "hint": "next_to:" + m.group(1).strip(),
            })

        # ── Click: "Select **X** in **Y**" ───────────────────────────────────
        # e.g. "Select **Expression** in **Path**" → click Expression to the right of Path label
        if not line_actions:
            m = re.search(r'select\s+\*\*([^*]+)\*\*\s+in\s+\*\*([^*]+)\*\*', line, re.IGNORECASE)
            if m:
                line_actions.append({
                    "action": "click",
                    "target": m.group(1).strip(),
                    "hint": "right_of:" + m.group(2).strip(),
                })

        # ── Scroll + Click: "Scroll down and select **X**" ───────────────────
        # e.g. "Scroll down and select **Local Files** under **File Integration**"
        if not line_actions:
            m = re.search(r'scroll\s+down\s+and\s+select\s+\*\*([^*]+)\*\*', line, re.IGNORECASE)
            if m:
                line_actions.append({"action": "scroll", "clicks": -15})
                line_actions.append({"action": "click", "target": m.group(1).strip()})

        # ── Search + Click: "Search `X` and select **Y**" ────────────────────
        # e.g. "Search `printInfo` and select **printInfo**"
        # Must be checked before the generic "Select **X**" rule to avoid partial match.
        if not line_actions:
            m = re.search(r'search\s+`([^`]+)`\s+and\s+select\s+\*\*([^*]+)\*\*', line, re.IGNORECASE)
            if m:
                line_actions.append({
                    "action":       "search",
                    "field_target": "Search",
                    "value":        m.group(1).strip(),
                })
                line_actions.append({
                    "action": "click",
                    "target": m.group(2).strip(),
                })

        # ── Click: "Select **X**" ─────────────────────────────────────────────
        # Handles multiple selects in one sentence ("… and select **Open**")
        if not line_actions:
            for m in re.finditer(r'select\s+\*\*([^*]+)\*\*', line, re.IGNORECASE):
                line_actions.append({"action": "click", "target": m.group(1).strip()})

        # ── Click: "Add [a [new]] **X**" ──────────────────────────────────────
        if not line_actions:
            for m in re.finditer(r'\bAdd(?:\s+(?:a\s+)?(?:new\s+)?)?\s+\*\*([^*]+)\*\*', line, re.IGNORECASE):
                line_actions.append({"action": "click", "target": m.group(1).strip()})

        # ── Click: "Add the `X` action" ───────────────────────────────────────
        if not line_actions:
            m = re.search(r'\bAdd\s+the\s+`([^`]+)`\s+action\b', line, re.IGNORECASE)
            if m:
                line_actions.append({"action": "click", "target": m.group(1).strip()})

        # ── Type: "Set [the] [base] **X** to `Y`" or "Set **X** to **Y**"
        m = re.search(r'set\s+(?:the\s+)?(.*?)\*\*([^*]+)\*\*\s+to\s+`([^`]+)`', line, re.IGNORECASE)
        if m:
            field_name = (m.group(1).strip() + " " + m.group(2).strip()).strip()
            line_actions.insert(0, {
                "action":       "type",
                "field_target": _normalise_field(field_name),
                "value":        m.group(3),
            })

        # ── Type: "Set **X** to **Y**" (bold value, quotes preserved)
        if not line_actions:
            m = re.search(r'set\s+(?:the\s+)?(.*?)\*\*([^*]+)\*\*\s+to\s+\*\*([^*]+)\*\*', line, re.IGNORECASE)
            if m:
                field_name = (m.group(1).strip() + " " + m.group(2).strip()).strip()
                line_actions.insert(0, {
                    "action":       "type",
                    "field_target": _normalise_field(field_name),
                    "value":        m.group(3),
                })

        # ── Type: "Set [the] X to `Y`" (non-bold field name)
        if not line_actions:
            m = re.search(r'set\s+(?:the\s+)?([a-zA-Z ]+?)\s+to\s+`([^`]+)`', line, re.IGNORECASE)
            if m:
                line_actions.append({
                    "action":       "type",
                    "field_target": _normalise_field(m.group(1)),
                    "value":        m.group(2),
                })

        # ── Type: "Enter the X (for example, `Y`)" ───────────────────────────
        if not line_actions:
            m = re.search(
                r'[Ee]nter\s+(?:the\s+)?([^(`]+?)\s+\(for example,?\s+`([^`]+)`\)',
                line,
            )
            if m:
                line_actions.append({
                    "action":       "type",
                    "field_target": _normalise_field(m.group(1)),
                    "value":        m.group(2),
                })

        # ── Type: "Name the connection `X`" ──────────────────────────────────
        if not line_actions:
            m = re.search(r'[Nn]ame\s+the\s+connection\s+`([^`]+)`', line)
            if m:
                line_actions.append({
                    "action":       "type",
                    "field_target": "Connection Name",
                    "value":        m.group(1),
                })

        # ── Type + Select: "Store … variable named `X` … type `Y`" ──────────
        if not line_actions:
            m = re.search(
                r'[Ss]tore.*?variable.*?named\s+`([^`]+)`.*?type\s+`([^`]+)`',
                line, re.DOTALL,
            )
            if m:
                line_actions.append({
                    "action":       "type",
                    "field_target": "Response Variable",
                    "value":        m.group(1),
                })
                line_actions.append({
                    "action":       "select",
                    "field_target": "Response Type",
                    "value":        m.group(2),
                })

        # ── Search: "Search **X** [from the Y]" or "Search for `Y`" ───────────
        if not line_actions:
            # 1. New pattern: Search **Println** [from the right panel]
            # Here, the bolded text is the VALUE to search for.
            m = re.search(r'search\s+\*\*([^*]+)\*\*(?:\s+from\s+(?:the\s+)?([^*]+))?', line, re.IGNORECASE)
            if m:
                line_actions.append({
                    "action":       "search",
                    "field_target": "Search",
                    "value":        m.group(1).strip(),
                    "hint":         "panel:" + m.group(2).strip() if m.group(2) else None
                })
            else:
                # With explicit bold field name: Search **Connectors** for `api_sales_order_srv`
                m = re.search(r'search\s+\*\*([^*]+)\*\*\s+for\s+`([^`]+)`', line, re.IGNORECASE)
                if m:
                    line_actions.append({
                        "action":       "search",
                        "field_target": m.group(1).strip(),
                        "value":        m.group(2).strip(),
                    })
                else:
                    # Without field name: Search for `api_sales_order_srv`
                    m = re.search(r'search\s+for\s+`([^`]+)`', line, re.IGNORECASE)
                    if m:
                        line_actions.append({
                            "action":       "search",
                            "field_target": "Search",
                            "value":        m.group(1).strip(),
                        })

        actions.extend(line_actions)

        # ── Suffix: "and save" → hotkey ───────────────────────────────────────
        if re.search(r'\band\s+save\b', line, re.IGNORECASE):
            actions.append({"action": "hotkey", "keys": ["command", "s"]})

        # ── Suffix: "in the toolbar" → keep recording 3 extra seconds so the
        #    GIF shows the app starting up, then wait 5s for it to fully load ──
        if re.search(r'\bin\s+the\s+toolbar\b', line, re.IGNORECASE):
            if actions:
                actions[-1] = {**actions[-1], "post_delay": 5.0}
            actions.append({"action": "wait", "seconds": 5.0})

    return actions


@dataclass
class Step:
    title: str
    gif_filename: str
    actions: list[dict[str, Any]]
    raw_instructions: str = ""


def _title_to_slug(title: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower())
    return slug.strip('-')


def _parse_steps_from_md(content: str) -> list[tuple[str, str, str]]:
    matches = list(_STEP_RE.finditer(content))
    results = []
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()

        gif_m = _GIF_RE.search(body)
        gif_filename = Path(gif_m.group(1)).name if gif_m else f"{_title_to_slug(title)}.gif"

        instructions = re.sub(r'<[^>]+>', '', body).strip()
        results.append((title, gif_filename, instructions))
    return results


def instruction_lines(raw: str) -> list[str]:
    """Return display-ready instruction lines from a step's raw Markdown block.

    Strips list markers (``1. `` / ``- `` / ``* ``), HTML tags, and inline
    Markdown formatting (``**bold**``, `` `code` ``).  Used by TraceFlow and
    the FlowCast Studio preview to render human-readable checklist items.
    """
    lines = []
    for raw_line in raw.splitlines():
        line = re.sub(r'^\s*\d+\.\s+', '', raw_line).strip()
        line = re.sub(r'^\s*[-*+]\s+', '', line).strip()
        line = re.sub(r'<[^>]+>', '', line).strip()
        line = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
        line = re.sub(r'`([^`]+)`', r'\1', line)
        line = re.sub(r'\*([^*]+)\*',  r'\1', line)
        if line and not line.startswith('<'):
            lines.append(line)
    return lines


def parse_markdown(path: str | Path) -> list[Step]:
    content = Path(path).read_text()
    raw_steps = _parse_steps_from_md(content)
    steps = []
    for title, gif_filename, instructions in raw_steps:
        print(f"[parser] Parsing step: {title}")
        actions = _parse_instructions(instructions)
        steps.append(Step(
            title=title,
            gif_filename=gif_filename,
            actions=actions,
            raw_instructions=instructions
        ))
        print(f"[parser]   → {len(actions)} actions")
    return steps
