import sys
from pathlib import Path
from PIL import Image

# Add src to path
sys.path.append(str(Path(__file__).parent.parent))

from src.detector import find_element, _icon_entry_for

def test_plus_anchors():
    print("Checking if 'Error Handler' is in potential anchors for '+'...")
    # This is a bit hard to test without running the actual code, 
    # but we can check if _icon_entry_for returns the right threshold now.
    entry = _icon_entry_for("+", theme="light")
    print(f"Icon entry for '+' (light): {entry}")
    
    if entry and entry.get("match_threshold") == 0.3:
        print("SUCCESS: match_threshold is updated to 0.3")
    else:
        print(f"FAILURE: match_threshold is {entry.get('match_threshold') if entry else 'N/A'}")

    entry_dark = _icon_entry_for("+", theme="dark")
    print(f"Icon entry for '+' (dark): {entry_dark}")
    if entry_dark and entry_dark.get("match_threshold") == 0.3:
        print("SUCCESS: match_threshold for dark theme is updated to 0.3")
    else:
        print(f"FAILURE: match_threshold for dark theme is {entry_dark.get('match_threshold') if entry_dark else 'N/A'}")

if __name__ == "__main__":
    test_plus_anchors()
