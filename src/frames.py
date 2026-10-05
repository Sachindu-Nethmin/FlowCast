"""Looking at recorded frames."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def black_top(video: Path, at: float = 0.5) -> int:
    """Rows of (near) black across the top of a frame — the strip beside a
    MacBook's notch in a full-screen recording. A row counts when 97% of it is
    black: the recording indicator (a small dot) sits inside the strip."""
    import numpy as np
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        png = Path(td) / "f.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at}", "-i", str(video),
                        "-frames:v", "1", str(png)], capture_output=True)
        if not png.exists():
            return 0
        a = np.asarray(Image.open(png).convert("L"))
    dark = (a < 24).mean(axis=1)
    n = 0
    while n < len(dark) // 6 and dark[n] >= 0.97:       # never more than a sixth
        n += 1
    return n


def strip_heights(videos: list[Path], size_of) -> dict[tuple[int, int], int]:
    """The black strip per picture size, as most clips of that size show it.

    One frame can mislead — dark interface right under the strip, or a popup
    over it — but the strip itself is the same in every clip of a recording."""
    from collections import Counter
    seen: dict[tuple[int, int], Counter] = {}
    for v in videos:
        seen.setdefault(size_of(v), Counter())[black_top(v)] += 1
    # Most common; on a tie, the taller (cropping a little more is harmless).
    return {sz: max(c.items(), key=lambda kv: (kv[1], kv[0]))[0] for sz, c in seen.items()}
