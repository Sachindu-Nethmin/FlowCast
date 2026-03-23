"""
doc_parser.py — Parse WSO2 documentation markdown into recordable steps.

Supports three doc styles:
  1. GIF-referenced:  Each step ends with <img src="...gif">
  2. useBaseUrl:       Each step ends with useBaseUrl('/img/...gif')
  3. Plain steps:      ## Step N sections with numbered instructions (no GIF refs)
     GIF filenames are auto-generated from step titles.
"""
from __future__ import annotations

import re
from pathlib import Path

# Match both plain <img src="...gif"> and useBaseUrl('...gif') patterns
GIF_IMG_RE = re.compile(
    r'<img\s[^>]*src=["\']([^"\']+\.gif)["\']'     # <img src="...gif">
    r"|useBaseUrl\(['\"]([^'\"]+\.gif)['\"]\)",      # useBaseUrl('...gif')
    re.IGNORECASE,
)

# Match ## Step N or ### Step N headings
STEP_HEADING_RE = re.compile(
    r'^(#{2,3})\s+Step\s+(\d+)\s*[:\-–—]?\s*(.*)',
    re.MULTILINE | re.IGNORECASE,
)

HEADING_RE = re.compile(r'^#{1,6}\s+.+$', re.MULTILINE)

# Lines to skip when extracting plain-text instructions
_SKIP_LINE_PREFIXES = (
    '<', 'import ', 'useBaseUrl', '---', 'sidebar_position',
    'title:', 'description:', '```', '/>', 'sources={{',
    'light:', 'dark:', '}}',
)


def _title_to_slug(title: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower())
    return slug.strip('-')


def _clean_instructions(text: str) -> str:
    """Remove HTML/JSX/MDX lines, keep markdown/plain text instructions."""
    lines = []
    in_code_block = False
    for line in text.splitlines():
        s = line.strip()

        # Track code fences
        if s.startswith('```'):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        if not s:
            continue
        if any(s.startswith(p) for p in _SKIP_LINE_PREFIXES):
            continue
        # Skip JSX/Docusaurus component tags
        if s.startswith('</') or s.startswith('<Tabs') or s.startswith('<TabItem') or s.startswith('<ThemedImage'):
            continue
        # Skip GIF img lines (already captured by regex)
        if '.gif' in s.lower() and ('<img' in s.lower() or 'useBaseUrl' in s):
            continue
        lines.append(line)
    return '\n'.join(lines).strip()


def _nearest_heading_start(content: str, pos: int) -> int:
    """Return the start position of the last heading before `pos`."""
    preceding = content[:pos]
    matches = list(HEADING_RE.finditer(preceding))
    if matches:
        return matches[-1].start()
    return 0


def _extract_gif_path(match: re.Match) -> str:
    """Extract the GIF path from whichever capture group matched."""
    return match.group(1) or match.group(2)


def _strip_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """
    Strip YAML frontmatter (---...---) from the top of the file.
    Returns (frontmatter_dict, remaining_content).
    """
    fm = {}
    if not content.startswith('---'):
        return fm, content

    end = content.find('---', 3)
    if end == -1:
        return fm, content

    fm_block = content[3:end].strip()
    remaining = content[end + 3:].strip()

    for line in fm_block.splitlines():
        line = line.strip()
        if ':' in line:
            key, _, val = line.partition(':')
            key = key.strip().lower().replace(' ', '_')
            val = val.strip().strip('"').strip("'")
            if key and val:
                fm[key] = val

    return fm, remaining


def _extract_meta(frontmatter: dict, content_body: str) -> dict[str, str]:
    """Extract app/workspace metadata from frontmatter and body."""
    meta_keys = ('app', 'app_path', 'workspace_git', 'workspace_branch', 'workspace_test_branch')
    meta = {}

    # From frontmatter
    for key in meta_keys:
        if key in frontmatter:
            meta[key] = frontmatter[key]

    # From body (overrides frontmatter)
    for line in content_body.splitlines():
        s = line.strip()
        if s.startswith('<') or s.startswith('import '):
            continue
        m = re.match(r'^([a-z_]+)\s*:\s*(.+)$', s, re.IGNORECASE)
        if m:
            key = m.group(1).lower()
            if key in meta_keys:
                meta[key] = m.group(2).strip().strip('"').strip("'")

    return meta


def _extract_title(frontmatter: dict, content_body: str, filepath: Path, first_gif_m=None) -> str:
    """Extract the document title from frontmatter, H1 heading, or filename."""
    if first_gif_m:
        preceding_text = content_body[:first_gif_m.start()]
        h1_matches = list(re.finditer(r'^#\s+(.+)$', preceding_text, re.MULTILINE))
        if h1_matches:
            return h1_matches[-1].group(1).strip()

    h1_m = re.search(r'^#\s+(.+)$', content_body, re.MULTILINE)
    if h1_m:
        return h1_m.group(1).strip()

    return frontmatter.get('title', filepath.stem)


def _parse_gif_referenced(content_body: str) -> list[tuple[str, str]]:
    """Parse steps using GIF <img> / useBaseUrl references as delimiters."""
    steps = []
    prev_end = 0
    for m in GIF_IMG_RE.finditer(content_body):
        gif_path = _extract_gif_path(m)
        gif_filename = Path(gif_path).name
        chunk_start = max(prev_end, _nearest_heading_start(content_body, m.start()))
        chunk = content_body[chunk_start:m.start()]
        instructions = _clean_instructions(chunk)
        if instructions:
            steps.append((instructions, gif_filename))
        prev_end = m.end()
    return steps


def _parse_step_sections(content_body: str, folder_slug: str) -> list[tuple[str, str]]:
    """
    Parse steps from ## Step N / ### Step N sections when no GIF refs exist.
    Auto-generates GIF filenames from step titles.
    """
    step_matches = list(STEP_HEADING_RE.finditer(content_body))
    if not step_matches:
        return []

    steps = []
    for i, sm in enumerate(step_matches):
        step_title = sm.group(3).strip()
        step_num = sm.group(2)
        step_level = len(sm.group(1))  # number of # chars

        # Find the end of this step section (next heading at same or higher level, or EOF)
        section_start = sm.end()
        section_end = len(content_body)

        for j in range(i + 1, len(step_matches)):
            next_level = len(step_matches[j].group(1))
            if next_level <= step_level:
                section_end = step_matches[j].start()
                break

        # Also check for any ## heading (not just Step headings) that ends the section
        remaining = content_body[section_start:section_end]
        heading_end = re.search(r'^#{1,' + str(step_level) + r'}\s+', remaining, re.MULTILINE)
        if heading_end:
            section_end = section_start + heading_end.start()

        section_text = content_body[section_start:section_end]
        instructions = _clean_instructions(section_text)

        if not instructions:
            continue

        # Prepend the step heading to instructions for context
        heading_line = f"## Step {step_num}: {step_title}" if step_title else f"## Step {step_num}"
        instructions = f"{heading_line}\n\n{instructions}"

        # Auto-generate GIF filename from step title
        if step_title:
            gif_slug = _title_to_slug(step_title)
        else:
            gif_slug = f"step-{step_num}"
        gif_filename = f"{gif_slug}.gif"

        steps.append((instructions, gif_filename))

    return steps


def parse_doc(filepath: str | Path) -> tuple[str, str, list[tuple[str, str]], dict[str, str]]:
    """
    Parse a documentation markdown file into recordable steps.

    Handles three formats:
      1. Steps delimited by <img src="...gif"> tags
      2. Steps delimited by useBaseUrl('...gif') references
      3. ## Step N sections with numbered lists (no GIF refs)

    Returns: (title, folder_slug, steps, meta)
      steps = list of (instructions_text, gif_filename)
      meta = dict with optional 'app', 'app_path' keys
    """
    filepath = Path(filepath)
    content = filepath.read_text()

    # Strip Docusaurus frontmatter
    frontmatter, content_body = _strip_frontmatter(content)

    # Check for GIF references
    first_gif_m = GIF_IMG_RE.search(content_body)

    # Extract title and metadata
    title = _extract_title(frontmatter, content_body, filepath, first_gif_m)
    folder_slug = _title_to_slug(title)
    meta = _extract_meta(frontmatter, content_body)

    # Strategy 1: GIF-referenced steps (original format)
    if first_gif_m:
        steps = _parse_gif_referenced(content_body)
        if steps:
            return title, folder_slug, steps, meta

    # Strategy 2: Step-headed sections (no GIF refs — auto-generate filenames)
    steps = _parse_step_sections(content_body, folder_slug)

    return title, folder_slug, steps, meta
