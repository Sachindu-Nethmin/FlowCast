"""Debug script to identify and analyze the Create Integration button issue.

Captures screenshot and analyzes all buttons/elements to find why
the wrong button is being clicked.
"""

import pyautogui
from PIL import Image
import numpy as np
import cv2
from detector import _ocr, _fuzzy


def debug_create_integration_detection():
    """Capture and analyze buttons on screen."""
    print("[debug] Taking screenshot...")
    screenshot = pyautogui.screenshot()
    screenshot.save("output/debug_create_integration.png")

    print("[debug] Analyzing all text on screen...")
    reader = _ocr()
    arr = np.array(screenshot)
    results = reader.readtext(arr, detail=1)

    print("\n[debug] All detected text elements:")
    print("-" * 80)

    # Find all button-like text
    button_keywords = ["Create", "Advanced", "Settings", "Next", "Save", "Submit"]

    for i, (bbox, text, conf) in enumerate(results):
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        cx = int(sum(xs) / len(xs))
        cy = int(sum(ys) / len(ys))

        # Check if this looks like a button (reasonable size, high confidence)
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)

        # Print all text
        print(f"{i:2d}. '{text}'")
        print(f"    Pos: ({cx}, {cy}) | Size: {width}x{height}")
        print(f"    Conf: {conf:.2f}")

        # Highlight button-related text
        for keyword in button_keywords:
            if keyword.lower() in text.lower():
                print(f"    ⚠️  BUTTON-LIKE: Contains '{keyword}'")
                break
        print()

    print("-" * 80)
    print(f"\nTotal elements detected: {len(results)}")

    # Now test detection methods
    print("\n[debug] Testing detection methods for 'Create Integration':")
    print("-" * 80)

    # Method 1: Direct OCR match
    print("\nMethod 1: Direct OCR text match")
    for bbox, text, conf in results:
        if _fuzzy(text, "Create Integration") and conf >= 0.80:
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            cx = int(sum(xs) / len(xs))
            cy = int(sum(ys) / len(ys))
            print(f"  ✓ Found: '{text}' at ({cx}, {cy}), conf={conf:.2f}")

    # Method 2: Match "Create" only
    print("\nMethod 2: Match 'Create' only")
    create_matches = []
    for bbox, text, conf in results:
        if _fuzzy(text, "Create") and conf >= 0.75:
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            cx = int(sum(xs) / len(xs))
            cy = int(sum(ys) / len(ys))
            create_matches.append((text, cx, cy, conf))
            print(f"  ✓ Found: '{text}' at ({cx}, {cy}), conf={conf:.2f}")

    # Method 3: Match "Integration" only
    print("\nMethod 3: Match 'Integration' only")
    for bbox, text, conf in results:
        if _fuzzy(text, "Integration") and conf >= 0.75:
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            cx = int(sum(xs) / len(xs))
            cy = int(sum(ys) / len(ys))
            print(f"  ✓ Found: '{text}' at ({cx}, {cy}), conf={conf:.2f}")

    # Method 4: Check for "Advanced Settings" that might be confused
    print("\nMethod 4: Check for 'Advanced Settings' confusion")
    for bbox, text, conf in results:
        if "Advanced" in text or "Settings" in text:
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            cx = int(sum(xs) / len(xs))
            cy = int(sum(ys) / len(ys))
            print(f"  ⚠️  Found: '{text}' at ({cx}, {cy}), conf={conf:.2f}")

    print("\n" + "-" * 80)
    print("\nRECOMMENDATIONS:")
    print("1. Check if 'Advanced Settings' is above 'Create Integration'")
    print("2. If so, adjust detection to search only in lower portion of screen")
    print("3. Or use blue_button detection to prefer blue buttons")
    print("4. Or add region_scan to specifically target bottom area")
    print("\nScreenshot saved to: output/debug_create_integration.png")


if __name__ == "__main__":
    debug_create_integration_detection()
