"""Phone control for FlowCast guide mode — dictate on your phone, fix the text,
then send it to the Mac.

WHY THIS EXISTS

`--voice` listens on the Mac for a fixed five seconds, reads its guess back and
asks you to say "ok" or "edit". You never see the text, so a misheard word
costs a whole round trip. A phone gives you a text box: dictate with the
keyboard's own mic, read what it heard, fix the wrong word, send.

The bigger win is the screen. `src/step_input.py` minimises WSO2 Integrator
between steps (`_step_aside`) purely so the terminal prompt is reachable, then
restores it (`_come_back`). Move the prompt to the phone and the Mac screen is
never polluted — nothing needs hiding, and the recording is not interrupted.

HOW IT WORKS

A stdlib `http.server` on the Mac's LAN address serves one page. The phone
polls `/state` for the current prompt and posts to `/send`. `ask()` blocks the
guide loop on a queue until the phone sends something, so it is a drop-in
replacement for `input()` — same blocking call, same returned string.

SECURITY

The server binds to 0.0.0.0 so the phone can reach it, which means anything
else on the same Wi-Fi can too — and this page drives the mouse. Every request
therefore carries a per-run token; requests without it get 403. The token
changes on every run and is never written to disk.
"""
from __future__ import annotations

import json
import os
import queue
import secrets
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = int(os.environ.get("FLOWCAST_PHONE_PORT", "8765"))

# A tapped line sends its index, not its text. The label is doc prose ("Set
# Integration Name to HelloWorld"), and nl_commands.parse_command speaks the
# typed guide grammar ("click Create") — handed that sentence it returns a
# click on the whole thing. The index lets the caller run the already-parsed
# action instead of re-deriving it from English.
ACTION_TAP_PREFIX = "#action:"

_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>FlowCast</title>
<style>
:root{color-scheme:dark;--bg:#14161a;--card:#1d2026;--line:#2b3038;--fg:#e8eaed;--dim:#9aa3ad;--accent:#3d7eff;--ok:#3fb950;--busy:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,system-ui,sans-serif;
     padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}
header{display:flex;align-items:center;gap:.6rem;padding:.9rem 1rem;border-bottom:1px solid var(--line);
       position:sticky;top:0;background:var(--bg);z-index:2}
#dot{width:.6rem;height:.6rem;border-radius:50%;background:var(--busy);flex:none}
#dot.ready{background:var(--ok)}
#status{color:var(--dim);font-size:.85rem}
main{padding:1rem}
h1{font-size:1.15rem;margin:0 0 .75rem}
ol{margin:0;padding:0;list-style:none;counter-reset:i}
ol li{counter-increment:i;margin:.45rem 0}
ol button{display:flex;align-items:center;gap:.65rem;width:100%;text-align:left;margin:0;
          background:var(--card);color:var(--fg);border:1px solid var(--line);
          border-radius:.6rem;padding:.8rem;font-size:.95rem}
ol button::before{content:counter(i);color:var(--dim);flex:none;min-width:1.1rem}
ol button:disabled{opacity:.45}
ol li.done button{color:var(--dim);border-style:dashed}
ol li.done button::after{content:"✓";margin-left:auto;color:var(--ok)}
.hint{color:var(--dim);font-size:.8rem;margin:.5rem 0 0}
form{padding:0 1rem 1rem;position:sticky;bottom:0;background:var(--bg)}
textarea{width:100%;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:.7rem;
         padding:.8rem;font:inherit;resize:none}
textarea:focus{outline:2px solid var(--accent);border-color:transparent}
button{font:inherit;border:0;border-radius:.7rem;padding:.85rem;background:var(--accent);color:#fff;width:100%;margin-top:.6rem}
button:disabled{opacity:.45}
nav{display:flex;flex-wrap:wrap;gap:.5rem;padding:0 1rem 1.5rem}
nav button{background:var(--card);color:var(--fg);border:1px solid var(--line);
           font-size:.9rem;padding:.7rem .5rem;margin:0;flex:1 1 28%}
nav button[data-q="back"],nav button[data-q="next"]{flex:1 1 44%;font-weight:600}
</style></head><body>
<header><span id="dot"></span><span id="status">connecting…</span></header>
<main><h1 id="step">—</h1><ol id="steps"></ol>
<p class="hint">Tap a line to run it. The step ends by itself once every line is
done. Type below only to correct one or do something else.</p></main>
<form id="f">
  <textarea id="cmd" rows="2" autocapitalize="off" autocorrect="off"
    placeholder="Something different? Type it here."></textarea>
  <button id="send" type="submit" disabled>Send</button>
</form>
<nav id="quick">
  <button type="button" data-q="back">&#8592; Back</button>
  <button type="button" data-q="next">Next &#8594;</button>
  <button type="button" data-q="undo">undo</button>
  <button type="button" data-q="skip">skip</button>
  <button type="button" data-q="where">where</button>
</nav>
<script>
const t = new URLSearchParams(location.search).get('t') || '';
const $ = id => document.getElementById(id);
let waiting = false;

async function poll(){
  try{
    const r = await fetch('/state?t=' + t, {cache:'no-store'});
    if(!r.ok) throw new Error(r.status);
    const s = await r.json();
    waiting = !!s.prompt;
    $('dot').className = waiting ? 'ready' : '';
    $('status').textContent = waiting ? (s.prompt + ' — your turn') : s.status;
    $('step').textContent = s.step_title || '—';
    renderSteps(s.step_title || '', s.instructions || []);
    $('send').disabled = !waiting;
  }catch(e){ $('status').textContent = 'lost connection to the Mac'; $('dot').className=''; }
}

let signature = null;

// Rebuild only when the step actually changes — a rebuild on every poll would
// wipe the ✓ marks and steal the tap you were halfway through.
function renderSteps(title, list){
  const ol = $('steps');
  const sig = title + '|' + list.join('|');
  if(ol.dataset.sig !== sig){
    ol.dataset.sig = sig;
    ol.innerHTML = '';
    list.forEach((txt, n) => {
      const li = document.createElement('li');
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = txt;
      b.addEventListener('click', () => {
        if(!waiting) return;
        li.classList.add('done');
        send('#action:' + n);
      });
      li.appendChild(b);
      ol.appendChild(li);
    });
  }
  [...ol.children].forEach(li => { li.firstChild.disabled = !waiting; });
}

async function send(text){
  if(!text.trim()) return;
  $('send').disabled = true;
  await fetch('/send?t=' + t, {method:'POST', body:text});
  $('cmd').value = '';
  poll();
}

$('f').addEventListener('submit', e => { e.preventDefault(); send($('cmd').value); });
$('quick').addEventListener('click', e => {
  const q = e.target.dataset.q;
  if(q && waiting) send(q);
});
poll(); setInterval(poll, 1000);
</script></body></html>"""


class _Session:
    """Everything the page needs to render, plus the inbox `ask()` waits on."""

    def __init__(self) -> None:
        self.token = secrets.token_hex(3)      # short enough to type by hand
        self.lock = threading.Lock()
        self.prompt = ""                        # non-empty = FlowCast is waiting
        self.step_title = ""
        self.instructions: list[str] = []
        self.status = "FlowCast is working…"
        self.inbox: queue.Queue[str] = queue.Queue()

    def snapshot(self) -> dict:
        with self.lock:
            return {"prompt": self.prompt, "step_title": self.step_title,
                    "instructions": list(self.instructions), "status": self.status}


_session: _Session | None = None
_server: ThreadingHTTPServer | None = None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a) -> None:
        pass                                    # the terminal belongs to the guide loop

    def _authorised(self) -> bool:
        from urllib.parse import parse_qs, urlparse
        token = parse_qs(urlparse(self.path).query).get("t", [""])[0]
        return bool(_session) and secrets.compare_digest(token, _session.token)

    def _reply(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._authorised():
            return self._reply(403, b"forbidden", "text/plain; charset=utf-8")
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._reply(200, _PAGE.encode(), "text/html; charset=utf-8")
        if path == "/state":
            return self._reply(200, json.dumps(_session.snapshot()).encode(),
                               "application/json")
        self._reply(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        if not self._authorised() or self.path.split("?", 1)[0] != "/send":
            return self._reply(403, b"forbidden", "text/plain; charset=utf-8")
        length = int(self.headers.get("Content-Length", "0"))
        text = self.rfile.read(length).decode("utf-8", "replace").strip()
        if text:
            _session.inbox.put(text)
        self._reply(200, b"ok", "text/plain; charset=utf-8")


def _lan_ip() -> str:
    """The address the phone should dial. Opening a UDP socket to a public
    address picks the default route's interface without sending anything."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def start(port: int = DEFAULT_PORT) -> str:
    """Serve the page and return the URL to open on the phone."""
    global _session, _server
    if _server is not None:
        return url()
    _session = _Session()
    _server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    link = url()
    try:                                        # Universal Clipboard hands it to the phone
        subprocess.run(["pbcopy"], input=link.encode(), timeout=3)
    except Exception:
        pass
    return link


def url() -> str:
    port = _server.server_address[1] if _server else DEFAULT_PORT
    return f"http://{_lan_ip()}:{port}/?t={_session.token if _session else ''}"


def qr_ascii(link: str | None = None) -> str | None:
    """The URL as a scannable block for the terminal, so connecting the phone
    is one camera scan instead of typing an address and a token. Returns None
    if `qrcode` is missing — the caller still prints the URL either way."""
    try:
        import io
        import qrcode
    except ImportError:
        return None
    code = qrcode.QRCode(border=1)
    code.add_data(link or url())
    buf = io.StringIO()
    code.print_ascii(out=buf)
    return buf.getvalue().rstrip("\n")


def is_running() -> bool:
    return _server is not None


def set_step(title: str, instructions: list[str] | None = None) -> None:
    """Put the current step on the phone, so it can act as the script."""
    if not _session:
        return
    with _session.lock:
        _session.step_title = title
        _session.instructions = list(instructions or [])


def notify(text: str) -> None:
    """Status line shown while FlowCast is busy (result of the last action)."""
    if not _session:
        return
    with _session.lock:
        _session.status = text


def ask(label: str = "what next") -> str:
    """Block until the phone sends something. Drop-in for input()."""
    if not _session:
        raise RuntimeError("phone server not started — call start() first")
    with _session.lock:
        _session.prompt = label
    try:
        while True:
            try:
                return _session.inbox.get(timeout=0.5)
            except queue.Empty:
                continue
    finally:
        with _session.lock:
            _session.prompt = ""


def stop() -> None:
    global _server, _session
    if _server is not None:
        _server.shutdown()
        _server.server_close()
        _server = None
    _session = None
