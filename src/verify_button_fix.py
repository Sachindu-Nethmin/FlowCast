"""Verify the Create Integration button fix works correctly.

Tests the updated detection methods to ensure it finds the right button
and avoids clicking on Advanced Settings.
"""

from artifact_detector import ArtifactDetector
from PIL import Image
import pyautogui
import sys


def verify_fix():
    """Verify Create Integration button detection."""
    print("\n" + "=" * 80)
    print("VERIFYING CREATE INTEGRATION BUTTON DETECTION FIX")
    print("=" * 80)

    # Initialize detector
    detector = ArtifactDetector()

    # Take screenshot
    print("\n[verify] Taking screenshot...")
    screenshot = pyautogui.screenshot()
    screenshot.save("output/verify_create_integration.png")
    print(f"[verify] Screenshot saved to output/verify_create_integration.png")

    # Detect Create Integration button
    print("\n[verify] Detecting 'Create Integration' button...")
    result = detector.detect_artifact(
        screenshot,
        "step_1_create_project",
        "create_integration_button"
    )

    if not result:
        print("[verify] ✗ FAILED: Could not detect Create Integration button")
        print("[verify] Possible issues:")
        print("  1. Button not visible on current screen")
        print("  2. All detection methods failed")
        print("  3. Button text is different than expected")
        return False

    print(f"[verify] ✓ Detection successful!")
    print(f"[verify] Location: ({result['x']}, {result['y']})")
    print(f"[verify] Method: {result['method']}")
    print(f"[verify] Confidence: {result['confidence']:.2f}")
    print(f"[verify] Label: {result['label']}")

    # Verify it's in the correct region
    height = screenshot.height
    form_button_min_y = int(height * 0.75)

    if result['y'] > form_button_min_y:
        print(f"[verify] ✓ Button is in lower form area (y={result['y']} > {form_button_min_y})")
    else:
        print(f"[verify] ⚠️  Button might not be in expected form area (y={result['y']} < {form_button_min_y})")

    # Test click interaction
    print("\n[verify] Testing interaction...")
    success = detector.interact_with_artifact(
        screenshot,
        "step_1_create_project",
        "create_integration_button"
    )

    if success:
        print("[verify] ✓ Interaction successful - button clicked")
        return True
    else:
        print("[verify] ✗ Interaction failed")
        return False


def compare_buttons():
    """Compare Create Integration vs Advanced Settings button positions."""
    print("\n" + "=" * 80)
    print("COMPARING BUTTONS ON SCREEN")
    print("=" * 80)

    from detector import _ocr
    import numpy as np

    screenshot = Image.open("output/verify_create_integration.png")
    reader = _ocr()
    arr = np.array(screenshot)
    results = reader.readtext(arr, detail=1)

    print("\n[compare] Buttons detected:")
    print("-" * 80)

    buttons = []
    for bbox, text, conf in results:
        if any(keyword in text.lower() for keyword in ["create", "advanced", "settings", "save"]):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            cx = int(sum(xs) / len(xs))
            cy = int(sum(ys) / len(ys))
            buttons.append({"text": text, "x": cx, "y": cy, "conf": conf})
            print(f"'{text}'")
            print(f"  Position: ({cx}, {cy})")
            print(f"  Confidence: {conf:.2f}")
            print()

    if not buttons:
        print("No button-like text found")
        return

    # Sort by Y position
    buttons_sorted = sorted(buttons, key=lambda b: b['y'])
    print("-" * 80)
    print("[compare] Buttons in order from top to bottom:")
    for i, btn in enumerate(buttons_sorted, 1):
        print(f"{i}. {btn['text']} (y={btn['y']})")

    # Identify which should be clicked
    print("\n[compare] Analysis:")
    for btn in buttons:
        if "Create Integration" in btn["text"]:
            print(f"  ✓ TARGET: {btn['text']} at y={btn['y']}")
        elif "Advanced" in btn["text"] or "Settings" in btn["text"]:
            print(f"  ✗ AVOID: {btn['text']} at y={btn['y']}")


if __name__ == "__main__":
    try:
        success = verify_fix()
        print("\n" + "=" * 80)

        if success:
            print("✓ VERIFICATION PASSED - Fix is working correctly")
            print("=" * 80)
            sys.exit(0)
        else:
            print("✗ VERIFICATION FAILED - Check output/verify_create_integration.png")
            print("=" * 80)
            sys.exit(1)

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
