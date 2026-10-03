#!/usr/bin/env python3
"""Render FlowCast Studio's app icon: a docs page becoming a video.

    uv run python mac/make_icon.py out/AppIcon.icns
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024


def _gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    g = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        g.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return g.resize((size, size))


def render() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # macOS icon grid: 824px rounded square centred in 1024
    pad, r = 100, 185
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((pad, pad, S - pad, S - pad), r, fill=255)
    shadow = mask.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.35))
    img.paste(Image.new("RGBA", (S, S), (0, 0, 0, 255)), (0, 14), shadow)
    img.paste(_gradient(S, (41, 37, 160), (13, 148, 136)).convert("RGBA"), (0, 0), mask)

    d = ImageDraw.Draw(img)
    # document card
    doc = (300, 250, 640, 700)
    d.rounded_rectangle(doc, 36, fill=(255, 255, 255, 245))
    for i, w in enumerate((250, 210, 240, 160, 200)):
        y = 330 + i * 64
        d.rounded_rectangle((350, y, 350 + w, y + 22), 11, fill=(41, 37, 160, 70))
    d.ellipse((350, 330 - 4, 380, 356), fill=(22, 163, 74, 255))
    # play badge overlapping the page
    cx, cy, rad = 640, 660, 150
    d.ellipse((cx - rad - 10, cy - rad - 10, cx + rad + 10, cy + rad + 10), fill=(255, 255, 255, 255))
    d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=(239, 68, 68, 255))
    tri = [(cx - 45, cy - 70), (cx - 45, cy + 70), (cx + 75, cy)]
    d.polygon(tri, fill=(255, 255, 255, 255))
    return img


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "AppIcon.icns")
    out.parent.mkdir(parents=True, exist_ok=True)
    base = render()
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            base.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            base.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
    base.save(out.with_suffix(".png"))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
