"""Ask a local Ollama model how to get unstuck — as a multiple-choice question.

Before a recording stops to ask a person, tools/autopilot.py asks this. The
usual cause of a stuck action is that the app is on a different view than the
docs assume: "Select + in the flow diagram" when no flow diagram is open (the
docs skip "open the onModify handler first"). The fix is nearly always to open
something the walkthrough already named.

Asked open-ended ("what should I click?"), 9B models wander — ornith:9b picked
"Types" on that screen. Asked to choose, they get it: FlowCast builds the
options itself from labels that are BOTH on screen (Apple Vision OCR) AND named
earlier in the walkthrough (FileTracker, Local Files, onModify, …), and the
model picks one or "none". Every option is real by construction, so a wrong
answer costs one harmless click, never an invented one.

On the stuck screen from a real run (Oct 3, File-Driven Integration step 4),
ornith:9b and gemma4:E4B both chose "onModify" — the fix a person used.

Local only (http://127.0.0.1:11434). Settings:

    FLOWCAST_AI=off|on              [on when the model is pulled]
    FLOWCAST_AI_MODEL=ornith:9b     gemma4:E4B also works; vision models get the screenshot
    FLOWCAST_OLLAMA=http://127.0.0.1:11434
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.request

from PIL import Image

OLLAMA = os.environ.get("FLOWCAST_OLLAMA", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.environ.get("FLOWCAST_AI_MODEL", "ornith:9b")
TIMEOUT = float(os.environ.get("FLOWCAST_AI_TIMEOUT", "150"))


def available(model: str | None = None) -> bool:
    if os.environ.get("FLOWCAST_AI", "on").lower() in ("off", "0", "false", "no"):
        return False
    model = model or MODEL
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=2) as r:
            names = [m["name"] for m in json.load(r).get("models", [])]
        return model in names or f"{model}:latest" in names
    except Exception:
        return False


def _post(path: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(f"{OLLAMA}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _is_vision(model: str) -> bool:
    try:
        return "vision" in _post("/api/show", {"model": model}, 5).get("capabilities", [])
    except Exception:
        return False


def warm(model: str | None = None) -> None:
    """Load the model now, so the first question is not also a 30 s load."""
    try:
        _post("/api/generate", {"model": model or MODEL, "prompt": "", "keep_alive": "10m"}, 120)
    except Exception:
        pass


# ── the screen ───────────────────────────────────────────────────────────────

def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+/]", "", s.lower())


def screen_labels(shot: Image.Image, logical_width: int) -> list[dict]:
    """Every OCR'd label with its centre in logical (click) coordinates."""
    from src.ocr_engine import read_text
    scale = shot.width / float(logical_width or shot.width)
    out = []
    for bbox, text, conf in read_text(shot):
        # Tree icons come back as glyph noise ahead of the label: "= onModify",
        # "v Local Files", "• fileListener".
        text = re.sub(r"^(?:[^\w\s+/]{1,3}\s+|[vV>»•oc]-?\s+|\(\S{1,3}\)\s+)+", "", str(text).strip())
        if not text or conf < 0.3:
            continue
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        out.append({"text": text, "x": int(sum(xs) / 4 / scale), "y": int(sum(ys) / 4 / scale)})
    out.sort(key=lambda l: (l["y"] // 12, l["x"]))
    return out


def _where(labels: list[dict]) -> str:
    """The view, as a person would name it: its breadcrumb, else its biggest title."""
    crumbs = [l["text"] for l in labels if l["text"].count(">") >= 1 and len(l["text"]) < 120]
    return crumbs[0] if crumbs else (labels[0]["text"] if labels else "unknown")


# ── the question ─────────────────────────────────────────────────────────────

_SCHEMA = {"type": "object",
           "properties": {"choice": {"type": "integer"}, "reason": {"type": "string"}},
           "required": ["choice", "reason"]}


def choose(instruction: str, problem: str, history: list[str], named: list[str],
           tried: list[str], shot: Image.Image, logical_width: int,
           model: str | None = None, latest: str | None = None) -> tuple[str | None, str]:
    """Pick the click most likely to reach the view `instruction` needs.

    history: what the walkthrough has done ("Step 3: selected + Add Handler,
             then onModify"); named: the things it named (targets and values of
             actions already done, plus the instruction's own). Returns
    (command or None, reason)."""
    model = model or MODEL
    labels = screen_labels(shot, logical_width)
    want = {norm(n) for n in named if len(norm(n)) >= 3}
    skip = {norm(t.removeprefix("click ")) for t in tried}
    options, seen = [], set()
    for l in labels:
        k = norm(l["text"])
        if k in want and k not in seen and k not in skip:
            seen.add(k)
            options.append(l)
    if not options:
        return None, "nothing on screen that the walkthrough named"
    menu = "\n".join(f"{i + 1}. open \"{o['text']}\"" for i, o in enumerate(options))
    menu += f"\n{len(options) + 1}. none of these"
    prompt = (
        "WSO2 Integrator is a VS Code based IDE. A documentation walkthrough is being "
        "followed step by step.\n\nDone so far:\n" + "\n".join(f"- {h}" for h in history[-8:])
        + (f"\n\nMost recently created item: {latest} — a step normally continues inside "
           "what the step before it created." if latest else "")
        + f"\n\nThe screen now shows: {_where(labels)}\n"
        f"Next instruction: \"{instruction}\"\nIt did not work: {problem}\n\n"
        "In WSO2 Integrator, clicking an item in the left project tree opens it: a handler "
        "or automation opens its flow diagram (where \"+\" and the node search live), an "
        "artifact opens its designer. Instructions assume the right view is already open.\n\n"
        f"Which ONE option gets to the view this instruction needs?\n{menu}\n"
        "Answer as JSON {\"choice\": <number>, \"reason\": \"<one sentence>\"}.")
    msg: dict = {"role": "user", "content": prompt}
    if _is_vision(model):
        img = shot.copy()
        img.thumbnail((1280, 1280))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=80)
        msg["images"] = [base64.b64encode(buf.getvalue()).decode()]
    try:
        reply = _post("/api/chat", {"model": model, "stream": False, "think": False,
                                    "format": _SCHEMA, "keep_alive": "10m",
                                    "options": {"temperature": 0}, "messages": [msg]}, TIMEOUT)
        answer = json.loads(reply["message"]["content"])
    except Exception as e:
        return None, f"local model unavailable ({type(e).__name__})"
    n = int(answer.get("choice", 0))
    reason = str(answer.get("reason", ""))[:200]
    if not 1 <= n <= len(options):
        return None, reason or "model chose none"
    return f"click {options[n - 1]['text']}", reason
