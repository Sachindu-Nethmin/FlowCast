"""Natural-language command parser for FlowCast teach mode.

Turns terminal input like
    click create button
    enter myfile in the file name field
    type * * * * * into cron expression
    select GET from method
    search for salesforce in the connector search
    press cmd+s
    scroll down
into FlowCast action dicts (same schema as src/parser.py produces).

Control words return ("control", name):  quit / done / skip / help / where / undo
"""
from __future__ import annotations

import re
from typing import Any

_FIELD_SUFFIX = r'(?:\s+(?:field|box|input|textbox|text box|area))?'
_BTN_SUFFIX = r'(?:\s+(?:button|btn|card|tab|link|icon|option|item|menu))?'

CONTROLS = {"quit", "exit", "q", "done", "finish", "skip", "help", "?",
            "where", "look", "undo", "retry", "ok", "continue", "abort"}

_CONTROL_ALIASES = {
    "exit": "quit", "q": "quit", "finish": "done", "?": "help", "look": "where",
    "continue": "ok", "abort": "abort",
}


def parse_command(text: str) -> tuple[str, Any]:
    """Parse one line of user input.

    Returns ("control", name) | ("action", action_dict) | ("error", message).
    """
    t = text.strip()
    if not t:
        return ("error", "empty command")
    low = t.lower().strip()

    if low in CONTROLS:
        return ("control", _CONTROL_ALIASES.get(low, low))

    # click at 512,300  /  at 512 300
    m = re.match(r'^(?:click\s+)?at\s+(\d+)[,\s]+(\d+)$', low)
    if m:
        return ("action", {"action": "click", "target": f"({m.group(1)},{m.group(2)})",
                           "x": int(m.group(1)), "y": int(m.group(2)), "_direct": True})

    # enter/type/fill VALUE in/into/to (the) FIELD (field)
    m = re.match(
        r'^(?:enter|type|fill|input|put|write)\s+(.+?)\s+(?:in|into|to|on)\s+(?:the\s+)?(.+?)'
        + _FIELD_SUFFIX + r'$', t, re.IGNORECASE)
    if m:
        value, field = m.group(1).strip(), m.group(2).strip()
        return ("action", {"action": "type", "field_target": field, "value": value})

    # search for VALUE (in/from the FIELD/PANEL) with optional hint
    # e.g. "search for Println in the right panel"
    #      "search Println from the connector search"
    m = re.match(r'^search(?:\s+for)?\s+(.+?)(?:\s+(?:in|from)\s+(?:the\s+)?(.+?))?$', t, re.IGNORECASE)
    if m:
        value = re.sub(r'^["\']|["\']$', '', m.group(1).strip())
        field = (m.group(2) or "Search").strip()
        hint = None
        if "right" in field.lower():
            hint = "right panel"
        elif "left" in field.lower():
            hint = "left panel"
        return ("action", {"action": "search", "field_target": "Search",
                           "value": value, "hint": hint})

    # select OPTION from/in (the) DROPDOWN
    m = re.match(r'^(?:select|choose|pick)\s+(.+?)\s+(?:from|in)\s+(?:the\s+)?(.+?)$',
                 t, re.IGNORECASE)
    if m:
        return ("action", {"action": "select", "field_target": m.group(2).strip(),
                           "value": m.group(1).strip()})

    # press/hotkey KEYS (cmd+s, enter, escape...)
    m = re.match(r'^(?:press|hotkey|keys?)\s+(.+)$', low)
    if m:
        keys = re.split(r'[+\s]+', m.group(1).strip())
        keymap = {"cmd": "command", "ctrl": "ctrl", "opt": "option", "alt": "option",
                  "esc": "escape", "return": "enter", "del": "delete"}
        keys = [keymap.get(k, k) for k in keys if k]
        return ("action", {"action": "hotkey", "keys": keys})

    # scroll up/down (N)
    m = re.match(r'^scroll\s+(up|down)(?:\s+(\d+))?$', low)
    if m:
        n = int(m.group(2) or 3)
        return ("action", {"action": "scroll", "clicks": n if m.group(1) == "up" else -n})

    # wait (N seconds)
    m = re.match(r'^wait(?:\s+(?:for\s+)?(\d+(?:\.\d+)?))?(?:\s*s(?:econds?)?)?$', low)
    if m:
        return ("action", {"action": "wait", "seconds": float(m.group(1) or 1.0)})

    # click TARGET below/after/under/next to/right of ANCHOR — spatial guidance.
    # e.g. "click + below Start", "click + after the Start node",
    #      "click + next to Query", "click Expression right of Path"
    m = re.match(
        r'^(?:click|press|tap|hit|push)(?:\s+on)?(?:\s+the)?\s+(.+?)\s+'
        r'(below|under|after|next to|beside|right of)\s+(?:the\s+)?(.+?)'
        r'(?:\s+node|\s+section|\s+label)?$', t, re.IGNORECASE)
    if m:
        target, rel, anchor = m.group(1).strip(), m.group(2).lower(), m.group(3).strip()
        hint = {"below": "below:", "under": "below:", "after": "below:",
                "next to": "next_to:", "beside": "next_to:",
                "right of": "right_of:"}[rel] + anchor
        return ("action", {"action": "click", "target": target, "hint": hint})

    # click (the) TARGET (button) — also the fallback for bare text
    m = re.match(r'^(?:click|press|tap|hit|push)(?:\s+on)?(?:\s+the)?\s+(.+?)'
                 + _BTN_SUFFIX + r'$', t, re.IGNORECASE)
    if m:
        return ("action", {"action": "click", "target": m.group(1).strip()})

    # Bare text → treat as a click target
    if len(t) <= 60:
        return ("action", {"action": "click", "target": t})

    return ("error", f"could not understand: '{t}' (type 'help' for examples)")


HELP_TEXT = """\
Guidance commands (natural language):
  click create button              click the 'Create' button
  click Add Artifact               bare text also works as a click target
  click + below Start              + connector under the Start node
  click + next to Query            + button beside a label
  at 512,300                       click exact coordinates
  enter myfile in the file name field
  type * * * * * into cron expression
  select GET from method
  search for salesforce in connector search
  press cmd+s   |  press enter
  scroll down   |  scroll up 5
  wait 3                           wait 3 seconds
  where                            re-describe what's on screen
  undo                             press cmd+z
  edit                             preview workflow markdown changes
  ok                               save workflow changes & continue run
  skip                             skip this workflow action
  abort                            stop the run
"""
