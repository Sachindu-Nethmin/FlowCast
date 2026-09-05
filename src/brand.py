"""FlowCast brand system — the WSO2 Integrator thumbnail/title-card design.

One source of truth for the look used by `tools/make_intro.py` (animated title
card) and the YouTube thumbnail, so a video and its thumbnail cannot drift
apart. Every number here was measured off the approved reference thumbnail at
2560x1440; `unit` scales the whole design to any canvas height.

Layers, not one flat image: `card_layers()` returns each element cropped to its
own box with an origin and an animation cue, so the intro can choreograph them
(stagger, rise, fade, pop) instead of zooming a finished picture.

Shapes are drawn supersampled and downsampled — Pillow's draw primitives are
aliased, text is not — so type stays crisp while strokes come out clean.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ── Design tokens (measured from the reference thumbnail) ─────────────────────

BASE = (11, 18, 33)        # #0B1221 deepest navy
LIFT = (19, 41, 76)        # #13294C glow navy
SHAPE = (16, 28, 48)       # #101C30 illustration fill
ACCENT = (95, 212, 255)    # #5FD4FF WSO2 Integrator cyan
INK = (238, 244, 251)      # #EEF4FB headline white

DESIGN_W, DESIGN_H = 2560, 1440
MARGIN = 140
SS = 3                     # supersample factor for drawn shapes

_BOLD_FACES = [("/System/Library/Fonts/HelveticaNeue.ttc", 1),
               ("/System/Library/Fonts/Helvetica.ttc", 1),
               ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0)]

# Baselines, straight off the reference (design px at 2560x1440).
Y_WSO2, Y_INTEGRATOR = 189, 238
Y_EYEBROW = 502
Y_HEAD1, Y_HEAD2 = 679, 829
Y_SUB = 948
LINE_STEP = 150            # headline baseline-to-baseline

ART_BOX = (880, 560)       # illustration design box
ART_RENDER = (1000, 636)   # drawn size on the canvas (bleeds off the right edge)
ART_POS = (1560, 593)      # top-left of the illustration on the canvas


def font(size: int) -> ImageFont.FreeTypeFont:
    for path, index in _BOLD_FACES:
        try:
            return ImageFont.truetype(path, max(int(size), 1), index=index)
        except OSError:
            continue
    return ImageFont.load_default(max(int(size), 1))


def _rgba(color: tuple[int, int, int], alpha: float) -> tuple[int, int, int, int]:
    return (*color, max(0, min(255, int(round(alpha * 255)))))


# ── Text with letter-spacing (Pillow has none) ────────────────────────────────

def measure(text: str, f: ImageFont.FreeTypeFont, ls: float = 0.0) -> float:
    return sum(f.getlength(c) for c in text) + ls * max(len(text) - 1, 0)


def draw_text(d: ImageDraw.ImageDraw, x: float, baseline: float, text: str,
              f: ImageFont.FreeTypeFont, fill, ls: float = 0.0) -> float:
    """Draw at a BASELINE (anchor 'ls'), letter-spaced. Returns the end x."""
    if not ls:
        d.text((x, baseline), text, font=f, fill=fill, anchor="ls")
        return x + f.getlength(text)
    for ch in text:
        d.text((x, baseline), ch, font=f, fill=fill, anchor="ls")
        x += f.getlength(ch) + ls
    return x


# ── Background ────────────────────────────────────────────────────────────────

def background(size: tuple[int, int], dots: bool = True,
               dot_phase: float = 0.0) -> Image.Image:
    """Navy base + two radial glows + the 80px cyan dot grid.

    `dot_phase` (0..1) slides the grid by one cell for a slow parallax drift.
    """
    w, h = size
    unit = h / DESIGN_H
    img = Image.new("RGB", (w, h), BASE)

    # Radial lift at 33%/44% and the softer cyan glow behind the illustration,
    # both built small and scaled up — a full-size ellipse blur is 10x slower.
    small = (max(w // 8, 8), max(h // 8, 8))
    glow = Image.new("L", small, 0)
    gd = ImageDraw.Draw(glow)
    cx, cy = small[0] * 0.33, small[1] * 0.44
    rx, ry = small[0] * 0.52, small[1] * 0.52
    gd.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(small[0] * 0.16)).resize((w, h), Image.BILINEAR)
    img = Image.composite(Image.new("RGB", (w, h), LIFT), img, glow)

    warm = Image.new("L", small, 0)
    wd = ImageDraw.Draw(warm)
    cx, cy = small[0] * 0.92, small[1] * 0.44
    rx, ry = small[0] * 0.30, small[1] * 0.30
    wd.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=42)
    warm = warm.filter(ImageFilter.GaussianBlur(small[0] * 0.13)).resize((w, h), Image.BILINEAR)
    img = Image.composite(Image.new("RGB", (w, h), ACCENT), img, warm)

    if dots:
        step = 80 * unit
        r = 3 * unit
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        off = (37 * unit + dot_phase * step) % step
        y = off - step
        while y < h + step:
            x = off - step
            while x < w + step:
                ld.ellipse([x - r, y - r, x + r, y + r], fill=_rgba(ACCENT, 0.10))
                x += step
            y += step
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    return img


# ── Illustration primitives (drawn supersampled, then downsampled) ────────────

class _Pen:
    """Draws in design units onto a supersampled RGBA layer."""

    def __init__(self, box: tuple[int, int], scale: float, mode: str = "all",
                 label: str | None = None):
        self.s = scale
        self.mode = mode            # all | body (no bubble) | bubble (bubble only)
        self._on = mode in ("all", "body")
        self.label = label          # overrides the illustration's default bubble text
        self.img = Image.new("RGBA", (int(box[0] * scale), int(box[1] * scale)), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.stroke = int(round(7 * scale))

    def _p(self, *vals): return [v * self.s for v in vals]

    def rrect(self, x, y, w, h, r, fill=SHAPE, outline=ACCENT, width=None):
        if not self._on:
            return
        self.d.rounded_rectangle(self._p(x, y, x + w, y + h), radius=r * self.s,
                                 fill=fill, outline=outline,
                                 width=self.stroke if width is None
                                 else int(round(width * self.s)))

    def circle(self, cx, cy, r, fill=SHAPE, outline=ACCENT, width=None):
        if not self._on:
            return
        self.d.ellipse(self._p(cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline,
                       width=self.stroke if width is None else int(round(width * self.s)))

    def dot(self, cx, cy, r, fill=ACCENT):
        if not self._on:
            return
        self.d.ellipse(self._p(cx - r, cy - r, cx + r, cy + r), fill=fill)

    def line(self, pts, width=None, fill=ACCENT):
        if not self._on:
            return
        self.d.line([c * self.s for c in pts], fill=fill,
                    width=self.stroke if width is None else int(round(width * self.s)),
                    joint="curve")

    def poly(self, pts, fill=SHAPE, outline=ACCENT, width=None):
        if not self._on:
            return
        flat = [c * self.s for c in pts]
        if fill:
            self.d.polygon(flat, fill=fill)
        if outline:
            closed = flat + flat[:2]
            self.d.line(closed, fill=outline,
                        width=self.stroke if width is None else int(round(width * self.s)),
                        joint="curve")

    def arc(self, cx, cy, r, start, end, width=None):
        if not self._on:
            return
        self.d.arc(self._p(cx - r, cy - r, cx + r, cy + r), start, end, fill=ACCENT,
                   width=self.stroke if width is None else int(round(width * self.s)))

    def glyph(self, cx, cy, ch, size, fill=ACCENT):
        if not self._on:
            return
        f = font(int(size * self.s))
        self.d.text((cx * self.s, cy * self.s), ch, font=f, fill=fill, anchor="mm")

    def bubble(self, x, y, text, size=48, h=120, tail=34, max_right=872):
        """Speech bubble sized to its text, with a left-pointing tail."""
        if self.mode == "body":
            return x
        self._on = True
        if self.label:
            text = self.label
        f = font(int(size * self.s))
        tw = f.getlength(text) / self.s
        w = tw + 76
        if x + w > max_right:
            x = max_right - w
        r, ty = 28, y + h / 2
        self.rrect(x, y, w, h, r)
        # Tail: fill first (opens the body's left edge), then its two outer legs.
        self.d.polygon([c * self.s for c in
                        (x + 6, ty - 24, x - tail, ty, x + 6, ty + 24)], fill=SHAPE)
        self.line((x, ty - 24, x - tail, ty, x, ty + 24))
        self.d.text(((x + w / 2) * self.s, (y + h / 2) * self.s), text, font=f,
                    fill=INK, anchor="mm")
        if self.mode == "bubble":
            self._on = False
        return x


# ── The six illustrations (mirrors the artboards on the design canvas) ────────

def _art_robot(p: _Pen) -> None:
    p.line((215, 128, 215, 62))
    p.dot(215, 46, 15)
    p.rrect(85, 128, 262, 192, 46)
    p.dot(163, 212, 18)
    p.dot(269, 212, 18)
    p.line((178, 272, 254, 272), width=12)
    p.rrect(60, 352, 312, 192, 42)
    p.rrect(16, 398, 46, 62, 23)
    p.rrect(370, 398, 46, 62, 23)
    p.circle(216, 448, 34, fill=None)
    p.bubble(470, 190, "Hello, World!")


def _art_chat(p: _Pen) -> None:
    p.rrect(46, 150, 392, 368, 40)
    for cx in (104, 142, 180):
        p.dot(cx, 206, 11)
    p.rrect(92, 268, 216, 72, 30, fill=None)
    p.rrect(176, 368, 216, 72, 30, fill=None)
    p.poly((382, 92, 400, 140, 448, 158, 400, 176, 382, 224,
            364, 176, 316, 158, 364, 140))
    p.poly((492, 66, 500, 90, 524, 98, 500, 106, 492, 130,
            484, 106, 460, 98, 484, 90), width=5)
    p.bubble(560, 268, "Hello")


def _art_files(p: _Pen) -> None:
    p.rrect(150, 132, 196, 252, 20)
    p.line((192, 192, 304, 192), width=6)
    p.line((192, 240, 304, 240), width=6)
    p.line((192, 288, 262, 288), width=6)
    p.rrect(30, 278, 160, 62, 18)          # folder tab
    p.rrect(12, 316, 340, 208, 28)         # folder body (covers the tab's foot)
    p.dot(424, 204, 20)
    p.arc(410, 204, 52, -62, 62)
    p.arc(410, 204, 94, -62, 62)
    p.bubble(540, 322, "File modified", size=44)


def _art_graph(p: _Pen) -> None:
    for x, y in ((96, 152), (404, 146), (120, 470), (392, 452)):
        p.line((238, 292, x, y))
    p.poly((238, 194, 323, 243, 323, 341, 238, 390, 153, 341, 153, 243))
    p.dot(238, 292, 26)
    for x, y in ((96, 152), (404, 146), (120, 470), (392, 452)):
        p.circle(x, y, 42)
    p.bubble(576, 268, "/news")


def _art_sync(p: _Pen) -> None:
    p.rrect(40, 176, 196, 308, 28)
    p.line((40, 278, 236, 278), width=6)
    p.line((40, 380, 236, 380), width=6)
    for cy in (227, 329, 431):
        p.dot(86, cy, 12)
    p.line((272, 330, 384, 330))
    p.line((348, 296, 384, 330, 348, 364))
    p.rrect(420, 182, 212, 296, 26)
    p.glyph(495, 322, "{", 170)
    p.glyph(561, 322, "}", 170)
    p.bubble(672, 128, "sales.json", size=42)


def _art_sap(p: _Pen) -> None:
    p.rrect(36, 196, 248, 252, 34)
    p.poly((160, 244, 216, 276, 216, 340, 160, 372, 104, 340, 104, 276), fill=None)
    p.line((160, 244, 160, 308))
    p.line((160, 308, 104, 276))
    p.line((160, 308, 216, 276))
    p.line((160, 308, 160, 372))
    p.line((284, 322, 356, 322))
    p.line((444, 322, 516, 322))
    p.circle(400, 322, 44)
    p.dot(400, 322, 15)
    p.rrect(516, 196, 248, 252, 34)
    p.line((556, 322, 600, 322, 620, 268, 660, 376, 680, 322, 724, 322), width=9)
    p.bubble(452, 40, "POST /salesorder", size=40)


ARTS = {"chat": _art_chat, "robot": _art_robot, "files": _art_files,
        "graph": _art_graph, "sync": _art_sync, "sap": _art_sap, "none": None}


def art_layer(kind: str, unit: float, mode: str = "all",
              label: str | None = None) -> Image.Image | None:
    """Rasterise one illustration at canvas scale, antialiased.

    `mode` splits the drawing so the object and its label bubble can be
    animated on separate cues: "body", "bubble", or "all".
    """
    painter = ARTS.get(kind)
    if painter is None:
        return None
    p = _Pen(ART_BOX, SS, mode, label)
    painter(p)
    out = (int(ART_RENDER[0] * unit), int(ART_RENDER[1] * unit))
    return p.img.resize(out, Image.LANCZOS)


# ── Logo lockup ───────────────────────────────────────────────────────────────

def logo_layers(unit: float) -> list[dict]:
    """The tile+mark and the WSO2/Integrator wordmark, as two separate layers so
    they can be animated apart."""
    tile_px = int(132 * unit)
    p = _Pen((132, 132), SS)
    p.d.rounded_rectangle([2 * SS, 2 * SS, 130 * SS, 130 * SS], radius=34 * SS,
                          fill=_rgba(ACCENT, 0.05), outline=_rgba(ACCENT, 0.32),
                          width=int(2 * SS))
    p.d.line([c * SS * 1.32 for c in
              (24, 50, 40, 50, 44.5, 33, 53, 68, 59, 50, 74, 50)],
             fill=ACCENT, width=int(5 * SS), joint="curve")
    tile = p.img.resize((tile_px, tile_px), Image.LANCZOS)

    f_w, f_i = font(28 * unit), font(38 * unit)
    ww = measure("WSO2", f_w, 0.24 * 28 * unit)
    wi = f_i.getlength("Integrator")
    word_w, word_h = int(max(ww, wi) + 8 * unit), int(118 * unit)
    word = Image.new("RGBA", (word_w, word_h), (0, 0, 0, 0))
    wd = ImageDraw.Draw(word)
    draw_text(wd, 0, (Y_WSO2 - 140) * unit, "WSO2", f_w, ACCENT, ls=0.24 * 28 * unit)
    draw_text(wd, 0, (Y_INTEGRATOR - 140) * unit, "Integrator", f_i, INK)

    return [
        {"name": "tile", "img": tile, "pos": (int(MARGIN * unit), int(MARGIN * unit))},
        {"name": "wordmark", "img": word, "pos": (int(304 * unit), int(MARGIN * unit))},
    ]


# ── Copy block ────────────────────────────────────────────────────────────────

def fit_headline(headline: str | list[str], unit: float) -> tuple[list[str], int]:
    """Split into at most two lines and pick the size the reference uses."""
    lines = headline if isinstance(headline, list) else _wrap_two(headline)
    longest = max(len(l) for l in lines)
    size = 142 if longest <= 16 else (128 if longest <= 19 else 116)
    max_w = 1360 * unit
    while size > 78 and max(measure(l, font(size * unit)) for l in lines) > max_w:
        size -= 4
    return lines, size


def _wrap_two(text: str) -> list[str]:
    words = text.split()
    if len(words) < 2:
        return [text]
    best, best_delta = 1, None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        delta = abs(len(a) - len(b))
        if best_delta is None or delta < best_delta:
            best, best_delta = i, delta
    return [" ".join(words[:best]), " ".join(words[best:])]


def card_layers(headline: str | list[str], eyebrow: str = "GET STARTED",
                subhead: str = "", art: str = "none",
                size: tuple[int, int] = (DESIGN_W, DESIGN_H),
                label: str | None = None) -> list[dict]:
    """Every element of the card as its own cropped RGBA layer + origin.

    Each layer carries `cue` (seconds into the animation) and `rise` (design px
    it travels up as it fades in) so callers can choreograph without knowing the
    layout.
    """
    w, h = size
    unit = h / DESIGN_H
    layers: list[dict] = []

    for i, l in enumerate(logo_layers(unit)):
        l["cue"], l["rise"] = 0.15 + 0.10 * i, 0
        l["pop"] = (i == 0)
        layers.append(l)

    def text_layer(name, text, f, fill, baseline, ls, cue, rise=26):
        wpx = int(measure(text, f, ls) + 12 * unit)
        hpx = int(f.size * 1.5)
        top = int(baseline * unit - f.size * 1.12)
        img = Image.new("RGBA", (max(wpx, 1), max(hpx, 1)), (0, 0, 0, 0))
        draw_text(ImageDraw.Draw(img), 0, baseline * unit - top, text, f, fill, ls)
        layers.append({"name": name, "img": img, "pos": (int(MARGIN * unit), top),
                       "cue": cue, "rise": rise, "pop": False})

    if eyebrow:
        f = font(46 * unit)
        text_layer("eyebrow", eyebrow.upper(), f, ACCENT, Y_EYEBROW, 0.13 * 46 * unit, 0.55)

    lines, hsize = fit_headline(headline, unit)
    fh = font(hsize * unit)
    ls_h = -0.022 * hsize * unit
    for i, line in enumerate(lines[:2]):
        baseline = Y_HEAD1 + i * LINE_STEP if len(lines) > 1 else (Y_HEAD1 + Y_HEAD2) / 2
        text_layer(f"headline{i}", line, fh, INK, baseline, ls_h, 0.80 + 0.14 * i, 34)

    if subhead:
        f = font(52 * unit)
        text_layer("subhead", subhead, f, ACCENT, Y_SUB, -0.01 * 52 * unit, 1.16)

    pos = (int(ART_POS[0] * unit), int(ART_POS[1] * unit))
    for name, mode, cue in (("art", "body", 1.02), ("art_label", "bubble", 1.46)):
        a = art_layer(art, unit, mode, label)
        if a is None:
            continue
        # Crop to the drawn pixels so a "pop" scales about the element's own
        # centre — an uncropped 1000px layer would scale about the whole box.
        box = a.getbbox()
        if box:
            a = a.crop(box)
            here = (pos[0] + box[0], pos[1] + box[1])
        else:
            here = pos
        layers.append({"name": name, "img": a, "pos": here,
                       "cue": cue, "rise": 0, "pop": True})
    return layers


# ── Flattened still (thumbnail / static card) ─────────────────────────────────

def render_card(headline: str | list[str], eyebrow: str = "GET STARTED",
                subhead: str = "", art: str = "none",
                size: tuple[int, int] = (DESIGN_W, DESIGN_H),
                frame: bool = False, label: str | None = None) -> Image.Image:
    img = background(size).convert("RGBA")
    for layer in card_layers(headline, eyebrow, subhead, art, size, label):
        img.alpha_composite(layer["img"], layer["pos"])
    if frame:
        d = ImageDraw.Draw(img)
        b = int(28 * size[1] / DESIGN_H)
        d.rectangle([0, 0, size[0] - 1, size[1] - 1], outline=(*ACCENT, 255), width=b)
    return img


def render_thumbnail(headline: str | list[str], out_png: Path,
                     eyebrow: str = "GET STARTED", subhead: str = "",
                     art: str = "none", width: int = 1280,
                     label: str | None = None) -> Path:
    """YouTube thumbnail: rendered at 2560x1440, downsampled for crisp type."""
    card = render_card(headline, eyebrow, subhead, art, label=label)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    card.convert("RGB").resize((width, width * 9 // 16), Image.LANCZOS).save(
        out_png, quality=95, subsampling=0)
    return out_png


# ── Easing ────────────────────────────────────────────────────────────────────

def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_out_back(t: float) -> float:
    """Slight overshoot — used for the pop on the logo tile and illustration."""
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)
