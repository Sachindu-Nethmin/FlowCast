#!/usr/bin/env python3
"""Benchmark FlowCast detection accuracy against saved failure screenshots.

Runs each OCR engine (EasyOCR vs Apple Vision) over the debug screenshots in
output/heal_debug (find_element failures) and output/debug_detection
(find_input_field failures), and reports found/miss + timing per engine.

Annotated result images (click point marked) are written to
output/benchmark/<engine>/ so hits can be verified visually.

Usage:
  uv run python tools/benchmark_detection.py                 # both engines
  uv run python tools/benchmark_detection.py --engine vision # one engine
  uv run python tools/benchmark_detection.py --limit 10
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PIL import Image, ImageDraw

ROOT = Path(__file__).parent.parent
HEAL_DIR = ROOT / "output" / "heal_debug"
FIELD_DIR = ROOT / "output" / "debug_detection"
OUT_DIR = ROOT / "output" / "benchmark"

_TS_RE = re.compile(r"_(\d{8})_(\d{6})$")


def _collect_cases() -> list[tuple[str, str, Path]]:
    """Return (kind, target, image_path). kind ∈ {element, field}."""
    cases = []
    if HEAL_DIR.exists():
        for p in sorted(HEAL_DIR.glob("*.png")):
            target = _TS_RE.sub("", p.stem).replace("_", " ").strip()
            if target:
                cases.append(("element", target, p))
    if FIELD_DIR.exists():
        for p in sorted(FIELD_DIR.glob("*.png")):
            stem = p.stem
            for prefix in ("fail_", "nolabel_"):
                if stem.startswith(prefix):
                    target = stem[len(prefix):].replace("_", " ").strip()
                    if target:
                        cases.append(("field", target, p))
                    break
    return cases


def _annotate(img: Image.Image, pos: tuple[int, int] | None, out: Path) -> None:
    dbg = img.copy()
    if pos:
        # detector returns logical coords; screenshots are physical (Retina).
        # Scale is unknown offline, so mark both 1x and 2x positions.
        d = ImageDraw.Draw(dbg)
        # Assume 2x Retina for annotation (most common); draw at both scales
        for s, color in ((2, "red"), (1, "orange")):
            x, y = pos[0] * s, pos[1] * s
            if x < dbg.width and y < dbg.height:
                d.ellipse([x - 14, y - 14, x + 14, y + 14], outline=color, width=4)
    out.parent.mkdir(parents=True, exist_ok=True)
    dbg.save(out)


def run_engine(engine: str, cases, save_images: bool) -> dict:
    os.environ["FLOWCAST_OCR"] = engine
    from src import detector, ocr_engine
    ocr_engine.clear_cache()

    stats = {"found": 0, "miss": 0, "time": 0.0, "rows": []}
    for kind, target, path in cases:
        img = Image.open(path).convert("RGB")
        t0 = time.time()
        pos = None
        try:
            if kind == "field":
                pos = detector.find_input_field(img, target)
            else:
                pos = detector.find_element(img, target)
        except Exception:
            pos = None
        dt = time.time() - t0
        stats["time"] += dt
        stats["found" if pos else "miss"] += 1
        stats["rows"].append((kind, target, pos, dt, path.name))
        mark = "✓" if pos else "✗"
        print(f"  [{engine}] {mark} {kind:7s} '{target}' → {pos}  ({dt:.1f}s)  [{path.name}]")
        if save_images and pos:
            _annotate(img, pos, OUT_DIR / engine / path.name)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["vision", "easyocr", "both"], default="both")
    ap.add_argument("--limit", type=int, default=0, help="max cases per kind")
    ap.add_argument("--no-images", action="store_true")
    args = ap.parse_args()

    cases = _collect_cases()
    if args.limit:
        by_kind: dict[str, list] = {}
        for c in cases:
            by_kind.setdefault(c[0], []).append(c)
        cases = [c for k in by_kind for c in by_kind[k][: args.limit]]

    if not cases:
        print("No debug screenshots found in output/heal_debug or output/debug_detection.")
        return
    print(f"Benchmarking {len(cases)} cases...\n")

    engines = ["easyocr", "vision"] if args.engine == "both" else [args.engine]
    results = {}
    for eng in engines:
        print(f"── Engine: {eng} " + "─" * 40)
        results[eng] = run_engine(eng, cases, save_images=not args.no_images)
        print()

    print("═" * 60)
    for eng, s in results.items():
        n = s["found"] + s["miss"]
        print(f"  {eng:8s}: {s['found']}/{n} found  "
              f"({100 * s['found'] / max(n, 1):.0f}%), total {s['time']:.0f}s")
    if not args.no_images:
        print(f"\nAnnotated hits saved to {OUT_DIR}/<engine>/ — verify click points visually.")
    print("Note: these are FAILURE screenshots from past runs — the old pipeline")
    print("scored 0% on most of them by definition. Any hit is an improvement,")
    print("but verify positions in the annotated images.")


if __name__ == "__main__":
    main()
