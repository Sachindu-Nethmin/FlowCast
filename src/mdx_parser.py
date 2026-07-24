"""
FlowCast — src/mdx_parser.py
=============================
MDX documentation pre-processor.

Converts the rich MDX / Docusaurus format used by WSO2 docs into the
plain FlowCast-compatible Markdown that ``parse_markdown()`` expects.

Transformations applied
───────────────────────
1. Strip YAML frontmatter (``---…---`` at file start)
2. Remove non-step ``##`` sections:
     Prerequisites, Scheduling …, What's Next, Related …, etc.
3. Convert ``<ThemedImage … />`` JSX to ``<img src="filename.gif" />``
     (selects the light or dark GIF variant based on the ``theme`` arg)
4. Remove fenced code blocks (````` ``` … ``` `````)
5. Flatten inline Markdown links  ``[text](url)`` → ``text``
6. Drop everything before the first ``## Step`` heading
   (document title, intro paragraphs, etc.)

Input example (MDX)
───────────────────
    ---
    title: 'Quick Start: Build an Automation'
    ---

    # Quick Start: Build an Automation
    **Time:** Under 10 minutes …

    ## Prerequisites
    - [WSO2 Integrator extension installed](install.md)

    ## Step 1: Create the project
    1. Open WSO2 Integrator.
    2. Select **Create**.
    <ThemedImage
        alt="Create the project"
        sources={{
            light: useBaseUrl('/img/.../create-the-project-light.gif'),
            dark:  useBaseUrl('/img/.../create-the-project-dark.gif'),
        }}
    />

    ## Scheduling Automations
    For production use …

Output (FlowCast-compatible .md)
──────────────────────────────────
    ## Step 1: Create the project

    1. Open WSO2 Integrator.
    2. Select **Create**.
    <img src="create-the-project-light.gif" />
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path


# ── Compiled regexes ──────────────────────────────────────────────────────────

# YAML frontmatter at the very beginning of the file
_FRONTMATTER_RE = re.compile(r'^---\s*\n.*?\n---\s*\n?', re.DOTALL)

# Self-closing <ThemedImage … /> JSX component (non-greedy on the body)
_THEMED_IMG_RE  = re.compile(r'<ThemedImage\b.*?/>', re.DOTALL | re.IGNORECASE)

# Fenced code blocks  (``` … ```)
_CODE_BLOCK_RE  = re.compile(r'```[^`]*?```', re.DOTALL)

# Inline Markdown links  [text](url)
_MD_LINK_RE     = re.compile(r'\[([^\]]+)\]\([^)]+\)')

# Any HTML or JSX tag (broad — used for final cleanup)
_TAG_RE         = re.compile(r'<[^>]+>')

# H1 heading (document title)
_H1_RE          = re.compile(r'^#\s+.+$', re.MULTILINE)

# Any H2 heading
_H2_RE          = re.compile(r'^##\s+(.+)$', re.MULTILINE)

# Step heading (mirrors FlowCast's _STEP_RE)
_STEP_H2_RE     = re.compile(
    r'^#{2,3}\s+Step\s+\d+\s*[:\-–]?',
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _gif_from_themed_image(block: str, theme: str) -> str:
    """Extract the GIF filename for *theme* from a ``<ThemedImage>`` block.

    Falls back to the opposite theme if the requested one is absent.
    """
    # Try requested theme  (e.g. "light: useBaseUrl('/…/foo-light.gif')")
    pattern = re.compile(
        theme + r":\s*useBaseUrl\(['\"]([^'\"]+\.gif)['\"]\)",
        re.IGNORECASE,
    )
    m = pattern.search(block)
    if m:
        return Path(m.group(1)).name

    # Fallback — any useBaseUrl GIF found in the block
    fallback = re.search(r"useBaseUrl\(['\"]([^'\"]+\.gif)['\"]\)", block)
    if fallback:
        return Path(fallback.group(1)).name

    return ""


# ── Public API ────────────────────────────────────────────────────────────────

def preprocess_mdx(content: str, theme: str = "light") -> str:
    """Convert MDX documentation to FlowCast-compatible Markdown.

    Parameters
    ----------
    content:
        Raw MDX / Markdown documentation string.
    theme:
        ``"light"`` or ``"dark"`` — controls which GIF variant to reference.

    Returns
    -------
    str
        Clean Markdown containing only the ``## Step N`` sections and their
        numbered instruction lists, suitable for ``parse_markdown()``.
    """
    # ── 1. Strip frontmatter ───────────────────────────────────────────────
    content = _FRONTMATTER_RE.sub("", content)

    # ── 2. Convert <ThemedImage> → <img src="…"> ──────────────────────────
    def _replace_themed(m: re.Match) -> str:
        gif = _gif_from_themed_image(m.group(0), theme)
        return f'<img src="{gif}" />\n' if gif else ""

    content = _THEMED_IMG_RE.sub(_replace_themed, content)

    # ── 3. Remove fenced code blocks ──────────────────────────────────────
    content = _CODE_BLOCK_RE.sub("", content)

    # ── 4. Flatten inline links ───────────────────────────────────────────
    content = _MD_LINK_RE.sub(r"\1", content)

    # ── 5. Keep only ## Step sections ─────────────────────────────────────
    #  Walk line-by-line; emit lines only while inside a step block.
    out: list[str] = []
    in_step = False

    for line in content.splitlines(keepends=True):
        stripped = line.rstrip()

        # H1 title — always skip
        if re.match(r'^#\s+', stripped) and not stripped.startswith("##"):
            in_step = False
            continue

        # H2 (or H3) heading
        if stripped.startswith("##"):
            if _STEP_H2_RE.match(stripped):
                in_step = True          # entering a step section
                out.append(line)
            else:
                in_step = False         # e.g. ## Prerequisites / ## What's Next
            continue

        if in_step:
            out.append(line)

    result = "".join(out)

    # ── 6. Normalise blank lines (max one blank line between items) ────────
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result.strip()


def preprocess_to_temp(content: str, theme: str = "light") -> Path:
    """Pre-process *content* and write it to a temporary ``.md`` file.

    The caller is responsible for deleting the file when done.

    Returns
    -------
    Path
        Path to the temporary file that was written.
    """
    cleaned = preprocess_mdx(content, theme)
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        prefix="flowcast_",
        delete=False,
        encoding="utf-8",
    ) as fh:
        fh.write(cleaned)
        return Path(fh.name)


def extract_step_summary(content: str, theme: str = "light") -> list[dict]:
    """Return a list of step-summary dicts for GUI preview.

    Each dict has keys:
    ``title``   — step title string
    ``items``   — list of plain-text instruction strings

    Parameters
    ----------
    content:
        Raw MDX content (pre-processing is applied internally).
    theme:
        GIF variant to use (passed to :func:`preprocess_mdx`).
    """
    from .parser import parse_markdown, instruction_lines
    import tempfile, os

    cleaned = preprocess_mdx(content, theme)
    if not cleaned:
        return []

    # Write to temp, parse, clean up
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="fc_prev_",
        delete=False, encoding="utf-8",
    ) as fh:
        fh.write(cleaned)
        tmp = Path(fh.name)

    try:
        steps = parse_markdown(tmp)
    except Exception:
        steps = []
    finally:
        os.unlink(tmp)

    return [
        {
            "title": s.title,
            "items": instruction_lines(s.raw_instructions),
        }
        for s in steps
    ]
