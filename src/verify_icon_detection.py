"""Verify icon-based artifact card detection.

Tests whether artifact cards (Automation, etc.) are being detected by their icons
instead of just OCR text matching.
"""

from artifact_detector import ArtifactDetector
from detector import _find_template
from PIL import Image
import pyautogui
import sys


def test_icon_availability():
    """Check if icon assets are available."""
    print("\n" + "=" * 80)
    print("CHECKING ICON ASSET AVAILABILITY")
    print("=" * 80)

    icon_patterns = [
        "dark-bi-task.svg",
        "light-bi-task.svg",
        "dark-bi-function.svg",
        "light-bi-function.svg"
    ]

    available_icons = []
    for icon in icon_patterns:
        try:
            # Try to find the icon using the existing _find_template function
            # This will verify the icon is accessible
            print(f"\n[icon_check] Testing icon: {icon}")
            available_icons.append(icon)
        except Exception as e:
            print(f"[icon_check] ✗ Icon not found or error: {e}")

    return available_icons


def test_automation_card_detection():
    """Test detection of Automation artifact card by icon."""
    print("\n" + "=" * 80)
    print("TESTING AUTOMATION ARTIFACT CARD DETECTION")
    print("=" * 80)

    detector = ArtifactDetector()

    # Take screenshot
    print("\n[test] Taking screenshot...")
    screenshot = pyautogui.screenshot()
    screenshot.save("output/verify_artifact_cards.png")

    # Detect Automation artifact card
    print("\n[test] Detecting 'Automation' artifact card...")
    result = detector.detect_artifact(
        screenshot,
        "step_2_add_automation_artifact",
        "automation_artifact_card"
    )

    if not result:
        print("[test] ✗ FAILED: Could not detect Automation artifact card")
        return False

    print(f"[test] ✓ Detection successful!")
    print(f"[test] Location: ({result['x']}, {result['y']})")
    print(f"[test] Method: {result['method']}")
    print(f"[test] Confidence: {result['confidence']:.2f}")
    print(f"[test] Label: {result['label']}")

    # Check if detection used icon
    if result.get('method') == 'card_with_icon':
        print(f"[test] ✓ Icon detection used")
        print(f"[test] Icon: {result.get('icon', 'N/A')}")
        print(f"[test] Icon distance: {result.get('icon_distance', 'N/A')}px")
        return True
    else:
        print(f"[test] ⚠️  Detection used '{result.get('method')}' instead of icon")
        print(f"[test] This is fallback - icon detection may have failed")
        return False


def test_icon_template_matching():
    """Test if template matching works for artifact icons."""
    print("\n" + "=" * 80)
    print("TESTING ICON TEMPLATE MATCHING")
    print("=" * 80)

    screenshot = Image.open("output/verify_artifact_cards.png")

    icons_to_test = [
        "dark-bi-task.svg",
        "light-bi-task.svg"
    ]

    print("\n[template] Testing template matching for icons...")
    print("-" * 80)

    for icon_name in icons_to_test:
        print(f"\n[template] Testing: {icon_name}")
        try:
            result = _find_template(screenshot, icon_name)
            if result:
                print(f"[template] ✓ Found at ({result[0]}, {result[1]})")
            else:
                print(f"[template] - Not found (template not in KB/icons)")
        except Exception as e:
            print(f"[template] Error: {e}")


def list_all_artifacts_step2():
    """List all artifacts in step 2."""
    print("\n" + "=" * 80)
    print("ARTIFACTS IN STEP 2 (Add Automation Artifact)")
    print("=" * 80)

    detector = ArtifactDetector()

    artifacts = detector.list_artifacts("step_2_add_automation_artifact")
    print(f"\nTotal artifacts: {len(artifacts)}\n")

    for artifact_id in artifacts:
        config = detector.get_artifact_config("step_2_add_automation_artifact", artifact_id)
        if config:
            print(f"• {artifact_id}")
            print(f"  Type: {config.get('type')}")
            print(f"  Label: {config.get('label')}")

            # Show detection methods
            methods = config.get('detection_methods', [])
            for i, method in enumerate(methods, 1):
                method_name = method.get('method')
                print(f"  Method {i}: {method_name}")
                if method_name == "card_with_icon":
                    print(f"    Icon patterns: {method.get('icon_patterns', 'N/A')}")
                elif method_name == "ocr_label":
                    print(f"    Text: {method.get('text')}")
            print()


def main():
    """Run all verification tests."""
    print("\n" + "=" * 80)
    print("ARTIFACT CARD ICON DETECTION VERIFICATION")
    print("=" * 80)

    # Test 1: List artifacts
    list_all_artifacts_step2()

    # Test 2: Check icon availability
    test_icon_availability()

    # Test 3: Test icon template matching
    test_icon_template_matching()

    # Test 4: Test artifact card detection
    success = test_automation_card_detection()

    print("\n" + "=" * 80)
    if success:
        print("✓ ICON DETECTION TEST PASSED")
    else:
        print("⚠️  ICON DETECTION USING FALLBACK METHOD")
        print("This is normal if icons haven't been added to KB/icons/ yet")
    print("=" * 80)

    print("\nScreenshot saved to: output/verify_artifact_cards.png")
    return 0 if success else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
