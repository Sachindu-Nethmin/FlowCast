"""
doc_parser.py — Parse WSO2 documentation markdown into recordable steps.
Each .gif reference in the doc becomes one step: the text preceding it
is the instruction for that GIF.
"""
import re
from pathlib import Path

GIF_IMG_RE = re.compile(r'<img\s[^>]*src=["\']([^"\']+\.gif)["\']', re.IGNORECASE)
HEADING_RE = re.compile(r'^#{1,6}\s+.+$', re.MULTILINE)


def _title_to_slug(title: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower())
    return slug.strip('-')


def _clean_html(text: str) -> str:
    """Remove lines that are HTML tags, keep markdown/plain text."""
    lines = [l for l in text.splitlines() if l.strip() and not l.strip().startswith('<')]
    return '\n'.join(lines).strip()


def _nearest_heading_start(content: str, pos: int) -> int:
    """Return the start position of the last heading before `pos`."""
    preceding = content[:pos]
    matches = list(HEADING_RE.finditer(preceding))
    if matches:
        return matches[-1].start()
    return 0


def parse_doc(filepath: str | Path) -> tuple[str, str, list[tuple[str, str]], dict[str, str]]:
    """
    Returns: (title, folder_slug, steps, meta)
    steps = list of (instructions_text, gif_filename)
    meta = dict with optional 'app', 'app_path' keys
    """
    content = Path(filepath).read_text()

    # Find the H1 heading that precedes the first GIF reference (the section title)
    first_gif_m = GIF_IMG_RE.search(content)
    if first_gif_m:
        preceding_text = content[:first_gif_m.start()]
        h1_matches = list(re.finditer(r'^#\s+(.+)$', preceding_text, re.MULTILINE))
        if h1_matches:
            title = h1_matches[-1].group(1).strip()
        else:
            title = Path(filepath).stem
    else:
        title_m = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_m.group(1).strip() if title_m else Path(filepath).stem
    folder_slug = _title_to_slug(title)

    # Extract optional metadata: scan the whole file for key: value lines
    # that appear between any heading and the next heading/div
    meta = {}
    for line in content.splitlines():
        s = line.strip()
        if s.startswith('<'):
            continue
        m = re.match(r'^([a-z_]+)\s*:\s*(.+)$', s, re.IGNORECASE)
        if m:
            key = m.group(1).lower()
            if key in ('app', 'app_path', 'workspace_git', 'workspace_branch', 'workspace_test_branch'):
                meta[key] = m.group(2).strip()

    # Extract (instructions, gif_filename) pairs.
    # For each GIF, scope instructions to the nearest heading before it
    # so that preamble text from earlier sections is excluded.
    steps = []
    prev_end = 0
    for m in GIF_IMG_RE.finditer(content):
        gif_filename = Path(m.group(1)).name
        chunk_start = max(prev_end, _nearest_heading_start(content, m.start()))
        chunk = content[chunk_start:m.start()]
        instructions = _clean_html(chunk)
        if instructions:
            steps.append((instructions, gif_filename))
        prev_end = m.end()

    return title, folder_slug, steps, meta
