"""DOM-based element detection via Chrome DevTools Protocol (CDP).

WSO2 Integrator is a VS Code-based Electron app. When launched with
`--remote-debugging-port=<PORT>`, its webviews are inspectable over CDP and
element positions can be read *exactly* from the DOM — no OCR guesswork.

Opt-in: set FLOWCAST_CDP_PORT=9222 (and launch the app with the same port).
When the port is unset or unreachable, every function returns None and the
caller falls back to OCR/template detection.

    open -a "WSO2 Integrator" --args --remote-debugging-port=9222

Coordinate model:
  DOM rects are in CSS px relative to each frame's viewport. We accumulate
  offsets up the iframe chain (matching webview targets to their <iframe>
  elements by the vscode-webview UUID in the URL), then add the window's
  screen origin + chrome height. On macOS, CSS px == logical px, which is
  exactly what pyautogui uses.

Requires the optional 'dom' extra:  uv sync --extra dom
  (requests + websocket-client)
"""
from __future__ import annotations

import itertools
import json
import os
import re

_PORT_ENV = "FLOWCAST_CDP_PORT"
_msg_id = itertools.count(1)


def enabled() -> bool:
    return bool(os.environ.get(_PORT_ENV, "").strip())


def _port() -> int:
    return int(os.environ.get(_PORT_ENV, "0"))


# ── Low-level CDP helpers ─────────────────────────────────────────────────────

def _list_targets() -> list[dict]:
    import requests
    r = requests.get(f"http://127.0.0.1:{_port()}/json/list", timeout=2)
    r.raise_for_status()
    return r.json()


def _cdp_eval(ws_url: str, expression: str, timeout: float = 4.0):
    """Evaluate a JS expression in a target; return the JSON-decoded value."""
    import websocket
    ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
    try:
        mid = next(_msg_id)
        ws.send(json.dumps({
            "id": mid,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True},
        }))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid:
                result = msg.get("result", {}).get("result", {})
                return result.get("value")
    finally:
        ws.close()


# ── JS snippets ───────────────────────────────────────────────────────────────
# Both snippets recurse into same-origin child iframes, accumulating offsets,
# and return {x, y, w, h, score, text} in this target's top viewport CSS px.

_JS_HELPERS = r"""
function fcVisible(el) {
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return null;
  const st = getComputedStyle(el);
  if (st.visibility === 'hidden' || st.display === 'none' || parseFloat(st.opacity) === 0) return null;
  return r;
}
function fcOwnText(el) {
  let t = '';
  for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent;
  t = t.trim();
  if (!t) t = (el.getAttribute && (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder'))) || '';
  if (!t && el.textContent && el.textContent.trim().length < 80) t = el.textContent.trim();
  return t.replace(/\s+/g, ' ');
}
function fcScoreText(text, target) {
  const t = text.toLowerCase().trim(), q = target.toLowerCase().trim();
  if (!t || !q) return 0;
  if (t === q) return 100;
  const tc = t.replace(/[^a-z0-9 ]/g, ''), qc = q.replace(/[^a-z0-9 ]/g, '');
  if (tc === qc) return 90;
  if (tc.replace(/ /g, '') === qc.replace(/ /g, '')) return 85;
  if (t.startsWith(q) && t.length < q.length * 2) return 70;
  if (t.includes(q) && t.length < q.length * 3) return 50;
  return 0;
}
function fcSearchDoc(doc, target, matcher, ox, oy) {
  let best = null;
  const all = doc.querySelectorAll('*');
  for (const el of all) {
    if (el.tagName === 'IFRAME' || el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
    const cand = matcher(el, target);
    if (!cand) continue;
    if (!best || cand.score > best.score ||
        (cand.score === best.score && cand.area < best.area)) {
      best = cand;
    }
  }
  // Recurse into same-origin iframes
  for (const fr of doc.querySelectorAll('iframe')) {
    let cdoc = null;
    try { cdoc = fr.contentDocument; } catch (e) {}
    if (!cdoc) continue;
    const fro = fr.getBoundingClientRect();
    const sub = fcSearchDoc(cdoc, target, matcher, ox + fro.x, oy + fro.y);
    if (sub && (!best || sub.score > best.score)) best = sub;
  }
  if (best) { best.x += ox; best.y += oy; }
  return best;
}
"""

# Matcher: clickable element (or any element) whose text matches the target.
_JS_FIND_TEXT = _JS_HELPERS + r"""
(function() {
  const target = %s;
  const CLICKABLE = new Set(['BUTTON','A','VSCODE-BUTTON','INPUT','SUMMARY','OPTION']);
  const matcher = (el, q) => {
    const text = fcOwnText(el);
    let score = fcScoreText(text, q);
    if (!score) return null;
    const r = fcVisible(el);
    if (!r) return null;
    if (CLICKABLE.has(el.tagName) || el.getAttribute('role') === 'button' ||
        el.onclick || getComputedStyle(el).cursor === 'pointer') score += 20;
    return {x: r.x + r.width/2, y: r.y + r.height/2, score, area: r.width*r.height, text};
  };
  return JSON.stringify(fcSearchDoc(document, target, matcher, 0, 0));
})()
"""

# Matcher: input/textarea/dropdown associated with a label text.
_JS_FIND_FIELD = _JS_HELPERS + r"""
(function() {
  const target = %s;
  const INPUTS = 'input, textarea, select, vscode-textfield, vscode-textarea, vscode-dropdown, [contenteditable="true"], [role="textbox"], [role="combobox"]';
  const matcher = (el, q) => {
    // Direct hit: input whose placeholder/aria-label/name matches
    if (el.matches && el.matches(INPUTS)) {
      const meta = [el.getAttribute('placeholder'), el.getAttribute('aria-label'),
                    el.getAttribute('name'), el.id].filter(Boolean).join(' ');
      const score = fcScoreText(meta, q);
      if (score >= 50) {
        const r = fcVisible(el);
        if (r) return {x: r.x + r.width/2, y: r.y + r.height/2, score: score + 30, area: r.width*r.height, text: meta};
      }
      return null;
    }
    // Label hit: element whose own text matches → find the input it controls
    const text = fcOwnText(el);
    const score = fcScoreText(text, q);
    if (score < 50 || text.length > q.length * 3) return null;
    const lr = fcVisible(el);
    if (!lr) return null;
    // 1. <label for=...>
    if (el.tagName === 'LABEL' && el.htmlFor) {
      const inp = el.ownerDocument.getElementById(el.htmlFor);
      if (inp) { const r = fcVisible(inp); if (r) return {x: r.x + r.width/2, y: r.y + r.height/2, score: score + 25, area: r.width*r.height, text}; }
    }
    // 2. Nearest input BELOW or RIGHT of the label (same container preferred)
    let scope = el.parentElement;
    for (let d = 0; d < 4 && scope; d++, scope = scope.parentElement) {
      const inputs = scope.querySelectorAll(INPUTS);
      let bestInp = null;
      for (const inp of inputs) {
        const r = fcVisible(inp);
        if (!r) continue;
        const below = r.top >= lr.top - 4 && r.top < lr.bottom + 120;
        const right = Math.abs((r.top + r.height/2) - (lr.top + lr.height/2)) < lr.height && r.left >= lr.right - 4;
        if (!below && !right) continue;
        const dist = Math.hypot(r.left - lr.left, r.top - lr.bottom);
        if (!bestInp || dist < bestInp.dist) bestInp = {r, dist};
      }
      if (bestInp) {
        const r = bestInp.r;
        return {x: r.x + r.width/2, y: r.y + r.height/2, score: score + Math.max(0, 20 - bestInp.dist/10), area: r.width*r.height, text};
      }
    }
    return null;
  };
  return JSON.stringify(fcSearchDoc(document, target, matcher, 0, 0));
})()
"""

# Window geometry + iframe map from the main VS Code window target.
_JS_WINDOW_INFO = r"""
(function() {
  const frames = [];
  for (const fr of document.querySelectorAll('iframe')) {
    const r = fr.getBoundingClientRect();
    frames.push({src: fr.src || '', name: fr.name || '', x: r.x, y: r.y, w: r.width, h: r.height});
  }
  return JSON.stringify({
    screenX: window.screenX, screenY: window.screenY,
    chromeY: window.outerHeight - window.innerHeight,
    chromeX: (window.outerWidth - window.innerWidth) / 2,
    frames
  });
})()
"""


def _webview_uuid(url: str) -> str | None:
    m = re.search(r"vscode-webview://([0-9a-f-]+)", url or "")
    return m.group(1) if m else None


def _get_window_info(targets: list[dict]) -> dict | None:
    """Find the main VS Code window target and read its geometry + iframes."""
    for t in targets:
        url = t.get("url", "")
        if t.get("type") == "page" and (url.startswith("vscode-file://") or "workbench" in url):
            try:
                raw = _cdp_eval(t["webSocketDebuggerUrl"], _JS_WINDOW_INFO)
                if raw:
                    return json.loads(raw)
            except Exception as e:
                print(f"[dom] window info failed: {e}")
    return None


def _find(js_template: str, query: str) -> tuple[int, int] | None:
    try:
        targets = _list_targets()
    except Exception as e:
        print(f"[dom] CDP unreachable on port {_port()}: {e}")
        return None

    win = _get_window_info(targets)
    expression = js_template % json.dumps(query)

    best = None          # (score, sx, sy, text)
    for t in targets:
        ws_url = t.get("webSocketDebuggerUrl")
        if not ws_url or t.get("type") not in ("page", "iframe", "webview"):
            continue
        try:
            raw = _cdp_eval(ws_url, expression)
        except Exception:
            continue
        if not raw:
            continue
        hit = json.loads(raw)
        if not hit:
            continue

        ox = oy = 0.0
        url = t.get("url", "")
        is_main = url.startswith("vscode-file://") or "workbench" in url
        if not is_main:
            # Webview target: add its <iframe> offset in the main window
            if not win:
                continue
            uuid = _webview_uuid(url)
            frame = None
            for f in win.get("frames", []):
                if uuid and uuid == _webview_uuid(f.get("src", "")):
                    frame = f
                    break
            if frame is None and len(win.get("frames", [])) == 1:
                frame = win["frames"][0]
            if frame is None:
                continue
            ox, oy = frame["x"], frame["y"]

        if win:
            sx = win["screenX"] + win.get("chromeX", 0) + ox + hit["x"]
            sy = win["screenY"] + win.get("chromeY", 0) + oy + hit["y"]
        else:
            sx, sy = ox + hit["x"], oy + hit["y"]

        if best is None or hit["score"] > best[0]:
            best = (hit["score"], sx, sy, hit.get("text", ""))

    if best and best[0] >= 50:
        score, sx, sy, text = best
        pos = (int(round(sx)), int(round(sy)))
        print(f"[dom] '{query}' → {pos} (score={score}, text='{text}')")
        return pos
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def find_element_dom(target: str) -> tuple[int, int] | None:
    """Exact DOM lookup of a clickable element by visible text. None on any failure."""
    if not enabled():
        return None
    return _find(_JS_FIND_TEXT, target)


def find_field_dom(field_label: str) -> tuple[int, int] | None:
    """Exact DOM lookup of an input field by label/placeholder. None on any failure."""
    if not enabled():
        return None
    label = field_label.replace("*", "").strip()
    return _find(_JS_FIND_FIELD, label)
