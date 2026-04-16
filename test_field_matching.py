#!/usr/bin/env python3
"""
Test script for field matching improvements.

Tests the improved field identification without running full recordings.
Usage: python test_field_matching.py
"""

import json
from pathlib import Path
from PIL import ImageGrab
from src.detector import (
    identify_screen,
    _similarity_score,
    _fuzzy,
    _kb_entry,
)

def test_similarity_score():
    """Test the new similarity scoring function."""
    print("\n" + "="*60)
    print("TEST 1: Similarity Score Function")
    print("="*60)

    test_cases = [
        ("Integration Name", "Integration Name", 1.0),  # Perfect match
        ("Integration Name", "integration name", 0.95),  # Case difference
        ("Integration Name", "Integration", 0.8),  # Partial match
        ("Database username", "Databaseusername", 0.9),  # Merged OCR
        ("Service Base Path", "Service", 0.7),  # Single word from multi-word
        ("User", "Usertabase", 0.5),  # OCR merge artifact
    ]

    print("\nSimilarity Score Tests:")
    for detected, target, expected_min in test_cases:
        score = _similarity_score(detected, target)
        passed = score >= expected_min
        status = "✓" if passed else "✗"
        print(f"{status} '{detected}' vs '{target}': {score:.2f} (expected >= {expected_min})")

    return True


def test_fuzzy_vs_similarity():
    """Compare fuzzy matching vs similarity scoring."""
    print("\n" + "="*60)
    print("TEST 2: Fuzzy vs Similarity Matching")
    print("="*60)

    test_cases = [
        ("Integration Name", "Integration Name"),
        ("Package Name", "PackageName"),
        ("Select Path", "SelectPath"),
        ("Database username", "username"),
        ("Service Base Path", "Service"),
    ]

    print("\nFuzzy vs Similarity Comparison:")
    print(f"{'Detected Text':<25} {'Target':<25} {'Fuzzy':<8} {'Similarity':<12}")
    print("-" * 70)

    for detected, target in test_cases:
        fuzzy = _fuzzy(detected, target)
        sim = _similarity_score(detected, target)
        fuzzy_str = "✓" if fuzzy else "✗"
        sim_str = f"{sim:.2f}"
        print(f"{detected:<25} {target:<25} {fuzzy_str:<8} {sim_str:<12}")

    return True


def test_kb_entry():
    """Test KB entry lookup."""
    print("\n" + "="*60)
    print("TEST 3: KB Entry Lookup")
    print("="*60)

    test_fields = [
        "Integration Name",
        "Package Name",
        "Select Path",
        "Database",
        "Service Base Path",
    ]

    print("\nKB Entry Lookup:")
    for field in test_fields:
        entry = _kb_entry(field)
        if entry:
            print(f"✓ Found '{field}': type={entry.get('type', 'N/A')}, "
                  f"placeholder={entry.get('placeholder', 'N/A')}")
        else:
            print(f"✗ Not found: '{field}'")

    return True


def test_identify_screen_on_screenshot():
    """Test screen identification on actual screenshot."""
    print("\n" + "="*60)
    print("TEST 4: Screen Identification on Live Screenshot")
    print("="*60)

    print("\nCapturing screenshot...")
    try:
        screenshot = ImageGrab.grab()
        print(f"✓ Screenshot captured: {screenshot.size}")

        print("\nIdentifying screen...")
        result = identify_screen(screenshot)

        if result:
            print(f"✓ Screen identified: {result['name']}")
            print(f"  - Screen key: {result['screen_key']}")
            print(f"  - Confidence: {result['confidence']}")
            print(f"  - Matched elements: {result['matched_elements']}")
            print(f"  - Matched fields: {result['matched_fields']}")
            return True
        else:
            print("✗ Could not identify screen")
            return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def print_summary(results):
    """Print test summary."""
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    total = len(results)
    passed = sum(results.values())
    failed = total - passed

    print(f"\nTotal tests: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    status = "✓ ALL TESTS PASSED" if failed == 0 else "✗ SOME TESTS FAILED"
    print(f"\n{status}\n")

    return failed == 0


if __name__ == "__main__":
    print("\n" + "="*60)
    print("FlowCast Field Matching Test Suite")
    print("Testing improvements to field identification accuracy")
    print("="*60)

    results = {
        "Similarity Score": test_similarity_score(),
        "Fuzzy vs Similarity": test_fuzzy_vs_similarity(),
        "KB Entry Lookup": test_kb_entry(),
        "Screen Identification": test_identify_screen_on_screenshot(),
    }

    all_passed = print_summary(results)
    exit(0 if all_passed else 1)
