#!/usr/bin/env python3
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path.cwd()))

from main import parse_markdown, _slug, _build_full_script, _build_themed_markdown, OUTPUT_DIR

def sync(md_path_str):
    md_path = Path(md_path_str)
    if not md_path.exists():
        print(f"Error: {md_path} not found")
        return
        
    steps = parse_markdown(md_path)
    slug = _slug(md_path.stem)
    out_dir = OUTPUT_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate for both themes
    for theme in ["light", "dark"]:
        _build_full_script(steps, out_dir, theme)
    
    _build_themed_markdown(steps, out_dir, slug)
    print(f"\nSuccessfully synced artifacts for {md_path.name}")

if __name__ == "__main__":
    sync("workflows/quick-start-ai-agent.md")
