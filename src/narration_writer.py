"""Write the voice-over: one spoken line per recorded action.

tools/narrate_sync.py speaks one line over each clip in guid/, so the script
has to match the recording action for action. tools/autopilot.py records the
label of every clip (actions.json); this turns those labels into lines a
voice clone reads well.

The rules are the ones in .claude/skills/doc/SKILL.md, learned the hard way:

  * spoken forms, not UI spellings — `GET` is "get", `API` is "A P I",
    `HelloWorldAPI` is "Hello World A P I"
  * name the button, do not describe the outcome — the cursor is visibly
    moving toward something named
  * one job per line

It is a first draft by design. FlowCast Studio shows it for editing before
any voice is synthesized.
"""
from __future__ import annotations

import re

# Read letter by letter; anything else in capitals is left to the voice.
SPELL = {"API", "APIs", "HTTP", "HTTPS", "URL", "URI", "AI", "CSV", "SQL", "XML",
         "EDI", "FTP", "SFTP", "MCP", "LLM", "TCP", "UDP", "CDC", "IDE", "UI",
         "ID", "JWT", "SAP", "AWS", "MQTT", "RAG", "PDF", "SMTP", "IMAP", "OAS"}
WORDS = {"GET": "get", "POST": "post", "PUT": "put", "DELETE": "delete",
         "PATCH": "patch", "HEAD": "head", "OPTIONS": "options", "JSON": "jason",
         "YAML": "yamel", "gRPC": "G R P C", "GraphQL": "Graph Q L",
         "WebSocket": "web socket", "RabbitMQ": "Rabbit M Q", "printInfo": "print info",
         "println": "print line", "Println": "print line", "io": "I O",
         "WSO2": "WSO2", "toml": "tom-ul", "TOML": "tom-ul", "Msg": "message"}


def _split_identifier(word: str) -> str:
    """HelloWorldAPI → Hello World API; external_api → external api."""
    if word in WORDS:
        return WORDS[word]
    if re.fullmatch(r"[A-Z]{2,5}s", word):
        return word                                            # plural acronym, keep whole
    w = re.sub(r"[_\-]+", " ", word)
    w = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", w)
    w = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", w)
    return w


_SPELL_UPPER = {w.upper() for w in SPELL}
_ENGLISH = {"rag", "sap", "id"}          # lowercase, these are words
_WORDS_CI = {k.lower(): v for k, v in WORDS.items()}


def _say(part: str) -> str:
    if part in WORDS:
        return WORDS[part]
    if re.fullmatch(r"[A-Z]{2,5}s", part) and part[:-1] in _SPELL_UPPER:
        return " ".join(part[:-1]) + "s"                       # APIs → A P Is
    if part.upper() in _SPELL_UPPER and not (part.islower() and part in _ENGLISH):
        return " ".join(part.upper())
    return _WORDS_CI.get(part.lower(), part) if part.lower() in ("json", "yaml", "toml", "msg") \
        else part


def spoken(text: str) -> str:
    """UI spelling → what the voice should say."""
    t = re.sub(r"[*`\"]", "", text)
    t = re.sub(r"https?://([\w.-]+)\S*", lambda m: "the " + m.group(1).split(".")[-2]
               + " endpoint", t)
    # paths: "/hello/greeting" → "slash hello slash greeting"
    t = re.sub(r"(?<![\w.])/(?=\w|$|\s)", " slash ", t)
    t = re.sub(r"(?<=\w)/(?=\w)", " slash ", t)
    words = []
    for tok in re.split(r"(\s+)", t):
        core = tok.strip(".,:;()")
        if not core or tok.isspace():
            words.append(tok)
            continue
        if core in WORDS:
            out = WORDS[core]
        else:
            out = " ".join(_say(p) for p in _split_identifier(core).split())
        words.append(tok.replace(core, out))
    t = "".join(words)
    t = re.sub(r"\s+", " ", t).strip()
    return t


SELECT_TEMPLATES = ["Select {x}.", "Then choose {x}.", "Click {x}.", "Now pick {x}."]


def line_for(label: str, i: int, step_title: str = "", last: bool = True) -> str:
    """One recorded action label (parser markdown or a guide command) → a line.

    `last` says whether this is the step's final clip: a wait in the middle of
    a step is the app starting up, a wait at the end is the result arriving."""
    raw = label.strip().rstrip(".")
    low = raw.lower()

    if re.match(r"open wso2 integrator", low):
        return "Let's start in WSO2 Integrator."
    if "skip for now" in low:
        return "Skip the sign in for now."
    m = re.match(r"wait (?:for )?([\d.]+)", low)
    if m:
        if not last:
            return "Give it a few seconds to start."
        if re.search(r"run|test|execute|result", step_title, re.I):
            return "Give it a moment, and there's the result."
        return "Give it a moment."
    m = re.match(r"run the shell command (.+?)(?: to (.+))?$", raw, re.I)
    if m:
        why = m.group(2)
        return f"From a terminal, we {spoken(why)}." if why else \
            "From a terminal, we trigger it with one command."
    if re.match(r"scroll (?:down|up)", low):
        return "Scroll down a little." if "down" in low else "Scroll back up."
    m = re.match(r"type (.+?) into (?:the )?(.+)$", raw, re.I)
    if m:
        return f"Enter {spoken(m.group(1))} as the {spoken(m.group(2)).lower()}."
    if re.match(r"(?:click )?at \d+[, ]+\d+", low):
        return "Click here."
    m = re.match(r"set (?:the )?(.+?) to (.+)$", raw, re.I)
    if m:
        field, value = m.group(1).strip(), m.group(2).strip().strip("`\"")
        f = spoken(field)
        if field.lower() == "integration name":
            return f"Name the integration {spoken(value)}."
        if field.lower() == "project name":
            return f"And the project, {spoken(value)}."
        if len(value) > 60:
            return f"Fill in the {f.lower()}."
        if re.match(r"https?://", value):
            return f"Point the {f} at the sample endpoint."
        return f"Set the {f} to {spoken(value)}."
    m = re.match(r"search (?:for )?(.+?)(?: in .+)?$", raw, re.I)
    if m and low.startswith("search"):
        return f"Search for {spoken(m.group(1))}."
    m = re.match(r"(?:press|hotkey) (.+)$", raw, re.I)
    if m:
        keys = m.group(1).replace("command", "command").replace("+", " ")
        return "Save it." if re.search(r"(cmd|command).*\bs\b", keys, re.I) else f"Press {spoken(keys)}."
    m = re.match(r"(?:select|click|choose) (.+?)(?: (under|in|inside|next to) (.+))?$", raw, re.I)
    if m:
        x, where, scope = m.group(1), m.group(2), m.group(3)
        x_s = spoken(x)
        if x.strip() == "+":
            return "Open the node panel." if not scope else \
                f"Open the node panel {where} {spoken(scope)}."
        if x.lower() == "run" or "toolbar" in low:
            return "Now run it."
        if x.lower() in ("save", "save connection"):
            return "Save it." if x.lower() == "save" else "Save the connection."
        if x.lower() == "create":
            return "Then select Create."
        tail = f", under {spoken(scope)}" if where == "under" and scope else ""
        return SELECT_TEMPLATES[i % len(SELECT_TEMPLATES)].format(x=x_s + tail)
    return spoken(raw) + "."


def write_script(clips: list[dict], step_titles: dict[int, str]) -> str:
    """actions.json clips → narrate_sync script (# step N, one line per clip)."""
    out: list[str] = ["# FlowCast Studio narration — one line per recorded action.",
                      "# Edit freely; keep the number of lines per step unchanged.", ""]
    by_step: dict[int, list[dict]] = {}
    for c in clips:
        by_step.setdefault(int(c["step"]), []).append(c)
    for n in sorted(by_step):
        title = step_titles.get(n, "")
        out.append(f"# step {n}")
        for i, c in enumerate(by_step[n]):
            line = line_for(c["label"], i, title, last=i == len(by_step[n]) - 1)
            if i == 0 and n > 1 and title:
                line = f"{spoken(title).rstrip('.')}. {line}"
            out.append(line)
        out.append("")
    return "\n".join(out)


def hook(meta: dict) -> str:
    build = (meta.get("build") or "").strip().rstrip(".")
    if build:
        b = build[0].lower() + build[1:]
        return spoken(f"In under ten minutes, let's build {b}.")
    return spoken(f"Let's {meta.get('title', 'build this').lower()} in WSO2 Integrator.")
