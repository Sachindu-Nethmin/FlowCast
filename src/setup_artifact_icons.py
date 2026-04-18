#!/usr/bin/env python3
"""Setup script to copy artifact icons for template-based detection.

Copies theme-aware SVG icons from product-integrator-assets to kb/icons/
so they can be used for icon-based artifact card detection.
"""

import shutil
from pathlib import Path
import sys


def setup_artifact_icons():
    """Copy artifact icons to KB directory."""
    print("\n" + "=" * 80)
    print("ARTIFACT ICON SETUP")
    print("=" * 80)

    # Define paths
    assets_dir = Path("output/product-integrator-assets/webview-assets")
    kb_icons_dir = Path("kb/icons")

    # Ensure kb/icons exists
    kb_icons_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n[setup] KB icons directory: {kb_icons_dir}")

    # List of artifact-related icons (bi- prefix = building integration)
    artifact_icons = [
        # Core automation nodes
        "dark-bi-task.svg",
        "light-bi-task.svg",
        "dark-bi-function.svg",
        "light-bi-function.svg",

        # Data sources
        "dark-bi-db.svg",
        "light-bi-db.svg",
        "dark-bi-mssql.svg",
        "light-bi-mssql.svg",
        "dark-bi-postgresql.svg",
        "light-bi-postgresql.svg",

        # Services
        "dark-bi-http-service.svg",
        "light-bi-http-service.svg",
        "dark-bi-graphql.svg",
        "light-bi-graphql.svg",
        "dark-bi-grpc.svg",
        "light-bi-grpc.svg",

        # Message queues
        "dark-bi-kafka.svg",
        "light-bi-kafka.svg",
        "dark-bi-rabbitmq.svg",
        "light-bi-rabbitmq.svg",
        "dark-bi-nats.svg",
        "light-bi-nats.svg",

        # Other services
        "dark-bi-ai-agent.svg",
        "light-bi-ai-agent.svg",
        "dark-bi-github.svg",
        "light-bi-github.svg",
        "dark-bi-salesforce.svg",
        "light-bi-salesforce.svg",
        "dark-bi-config.svg",
        "light-bi-config.svg",
    ]

    print(f"\n[setup] Copying {len(artifact_icons)} artifact icons...")
    print("-" * 80)

    copied = 0
    skipped = 0
    failed = 0

    for icon_name in artifact_icons:
        source = assets_dir / icon_name
        dest = kb_icons_dir / icon_name

        # Check if source exists
        if not source.exists():
            print(f"✗ {icon_name:40} - NOT FOUND in assets")
            skipped += 1
            continue

        # Skip if already copied
        if dest.exists():
            print(f"✓ {icon_name:40} - Already exists")
            skipped += 1
            continue

        # Copy the icon
        try:
            shutil.copy2(source, dest)
            print(f"✓ {icon_name:40} - Copied")
            copied += 1
        except Exception as e:
            print(f"✗ {icon_name:40} - ERROR: {e}")
            failed += 1

    print("-" * 80)
    print(f"\n[setup] Summary:")
    print(f"  Copied: {copied}")
    print(f"  Already present: {skipped}")
    print(f"  Failed: {failed}")

    # Verify copied icons
    print(f"\n[setup] Verifying icons in {kb_icons_dir}...")
    actual_icons = list(kb_icons_dir.glob("*-bi-*.svg"))
    print(f"  Total icons in kb/icons: {len(actual_icons)}")

    # Show sample
    if actual_icons:
        print(f"\n[setup] Sample icons:")
        for icon in sorted(actual_icons)[:10]:
            size_kb = icon.stat().st_size / 1024
            print(f"  - {icon.name:40} ({size_kb:.1f} KB)")
        if len(actual_icons) > 10:
            print(f"  ... and {len(actual_icons) - 10} more")

    print("\n" + "=" * 80)
    if failed == 0:
        print("✓ ICON SETUP COMPLETE")
        print("\nArtifact icons are now available for template-based detection.")
        print("Icons will be used as primary detection method, with OCR as fallback.")
    else:
        print(f"⚠️  SETUP INCOMPLETE - {failed} icons failed to copy")
        print("Please check error messages above and retry.")
    print("=" * 80)

    return 0 if failed == 0 else 1


def verify_icon_detection_ready():
    """Verify that icon detection is properly configured."""
    print("\n" + "=" * 80)
    print("VERIFYING ICON DETECTION CONFIGURATION")
    print("=" * 80)

    # Check KB config has icon patterns
    import json
    config_path = Path("kb/quick_start_automation_artifacts.json")

    if not config_path.exists():
        print("✗ Config file not found: kb/quick_start_automation_artifacts.json")
        return False

    with open(config_path) as f:
        config = json.load(f)

    print("\n[verify] Checking artifact cards have icon patterns...")

    artifact_cards = []
    for step_id, step_data in config.get("steps", {}).items():
        for artifact_id, artifact_config in step_data.get("artifacts", {}).items():
            if artifact_config.get("type") == "artifact_card":
                artifact_cards.append((artifact_id, artifact_config))

    print(f"[verify] Found {len(artifact_cards)} artifact card(s)")

    for artifact_id, artifact_config in artifact_cards:
        label = artifact_config.get("label")
        icon = artifact_config.get("icon")

        print(f"\n[verify] {artifact_id}: {label}")
        print(f"  Icon: {icon}")

        methods = artifact_config.get("detection_methods", [])
        icon_method = None
        for method in methods:
            if method.get("method") == "card_with_icon":
                icon_method = method
                break

        if icon_method:
            patterns = icon_method.get("icon_patterns", [])
            print(f"  Icon patterns: {patterns}")

            # Check if icons exist
            kb_icons = Path("kb/icons")
            for pattern in patterns:
                icon_path = kb_icons / pattern
                if icon_path.exists():
                    size_kb = icon_path.stat().st_size / 1024
                    print(f"    ✓ {pattern} ({size_kb:.1f} KB)")
                else:
                    print(f"    ✗ {pattern} - NOT FOUND")
        else:
            print(f"  ⚠️  No card_with_icon method found")

    print("\n" + "=" * 80)
    return True


if __name__ == "__main__":
    try:
        result = setup_artifact_icons()
        verify_icon_detection_ready()
        sys.exit(result)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
