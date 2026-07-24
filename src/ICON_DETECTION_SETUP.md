# Icon-Based Artifact Detection Setup Guide

## Overview

Artifact cards (like Automation, API Endpoint, Database, etc.) should be detected by their **icons first**, with OCR text as fallback. This makes detection more reliable across themes and UI variations.

## Problem

Original detection was OCR-only, which fails when:
- Multiple cards show similar text
- OCR confidence is low
- Theme changes affect text color/contrast
- Card layout changes

## Solution

Icon-based detection using template matching:
1. **Primary method**: Match card icon by SVG template
2. **Fallback**: Verify with label text (OCR)
3. **Theme-aware**: Try both dark and light icon variants

## Implementation Steps

### 1. Identify Artifact Icons

Artifacts use "bi-" prefixed icons in webview-assets:

```
dark-bi-task.svg          ← Automation artifact
light-bi-task.svg         ← Automation (light theme)
dark-bi-function.svg      ← Call Function node
light-bi-function.svg     ← Call Function (light theme)
dark-bi-db.svg            ← Database
light-bi-db.svg           ← Database (light theme)
```

### 2. Copy Icons to KB

Icons need to be in `kb/icons/` for template matching to work:

```bash
# Copy artifact icons
cp output/product-integrator-assets/webview-assets/dark-bi-task.svg kb/icons/
cp output/product-integrator-assets/webview-assets/light-bi-task.svg kb/icons/
cp output/product-integrator-assets/webview-assets/dark-bi-function.svg kb/icons/
cp output/product-integrator-assets/webview-assets/light-bi-function.svg kb/icons/
```

Or use a script to copy all:

```bash
# Copy all theme-aware icons
for icon in output/product-integrator-assets/webview-assets/*-bi-*.svg; do
  cp "$icon" kb/icons/
done
```

### 3. Update Artifact Configuration

Update `kb/quick_start_automation_artifacts.json` to use icon-based detection:

```json
{
  "automation_artifact_card": {
    "type": "artifact_card",
    "label": "Automation",
    "icon": "bi-task",
    "detection_methods": [
      {
        "method": "card_with_icon",
        "icon_patterns": [
          "dark-bi-task.svg",  // Primary: dark theme
          "light-bi-task.svg"  // Fallback: light theme
        ],
        "label_text": "Automation",
        "threshold": 0.60
      },
      {
        "method": "ocr_label",
        "text": "Automation",
        "confidence_threshold": 0.85  // High threshold, fallback only
      }
    ]
  }
}
```

### 4. How Icon Detection Works

**Detection Flow:**

1. **Try primary icon** (dark-bi-task.svg)
   - Uses template matching from `kb/icons/`
   - If found, check for label nearby
   - If icon + label match, return success

2. **Try fallback icon** (light-bi-task.svg)
   - Same process for light theme variant
   - Useful when theme changes

3. **Fallback to OCR** (label text only)
   - If neither icon found, try text matching
   - Higher confidence requirement (0.85)
   - Used as safety net

## Artifact Icon Mapping

Create a mapping of artifacts to icons:

```json
{
  "automation": ["dark-bi-task.svg", "light-bi-task.svg"],
  "call_function": ["dark-bi-function.svg", "light-bi-function.svg"],
  "println": ["dark-bi-function.svg", "light-bi-function.svg"],
  "initialize_array": ["dark-bi-function.svg", "light-bi-function.svg"],
  "database": ["dark-bi-db.svg", "light-bi-db.svg"],
  "http_service": ["dark-bi-http-service.svg", "light-bi-http-service.svg"],
  "kafka": ["dark-bi-kafka.svg", "light-bi-kafka.svg"],
  "rabbitmq": ["dark-bi-rabbitmq.svg", "light-bi-rabbitmq.svg"]
}
```

## Testing Icon Detection

### Run Verification Script

```bash
python3 src/verify_icon_detection.py
```

Output:
```
========================================
TESTING ARTIFACT CARD DETECTION
========================================

[test] Detecting 'Automation' artifact card...
[test] ✓ Detection successful!
[test] Location: (300, 350)
[test] Method: card_with_icon
[test] Confidence: 0.85
[test] ✓ Icon detection used
[test] Icon: dark-bi-task.svg
[test] Icon distance: 45px
```

### Manual Test

```python
from artifact_detector import ArtifactDetector
from PIL import Image

detector = ArtifactDetector()
screenshot = Image.open("screenshot.png")

result = detector.detect_artifact(
    screenshot,
    "step_2_add_automation_artifact",
    "automation_artifact_card"
)

if result and result['method'] == 'card_with_icon':
    print("✓ Icon detection working!")
else:
    print("Using fallback method")
```

## Detection Method Comparison

| Method | Reliability | Speed | Robust |
|--------|------------|-------|--------|
| **Icon** (primary) | Very High | Fast | Theme-aware, position-aware |
| **OCR** (fallback) | Medium | Medium | Text-dependent |
| **Icon + Label** | Very High | Medium | Most reliable combo |

## Troubleshooting

### Icon Not Found

**Error:** `[artifact_detector] Icon matching dark-bi-task.svg failed`

**Solutions:**
1. Check icon file exists in `kb/icons/`:
   ```bash
   ls kb/icons/ | grep "bi-task"
   ```

2. If not found, copy it:
   ```bash
   cp output/product-integrator-assets/webview-assets/dark-bi-task.svg kb/icons/
   ```

3. Verify file permissions:
   ```bash
   ls -l kb/icons/dark-bi-task.svg
   ```

### Icon Matched But Label Not Found

**Error:** `Label 'Automation' not found, trying icon-only detection`

**Solutions:**
1. Check OCR can find the label:
   ```python
   reader = _ocr()
   results = reader.readtext(screenshot)
   # Search results for "Automation"
   ```

2. Lower OCR confidence threshold:
   ```json
   "label_text": "Automation",
   "threshold": 0.70  // From 0.80
   ```

### Icon Matched to Wrong Card

**Error:** Icon found but 100+ px away from label

**Solutions:**
1. Adjust distance threshold in _detect_card_with_icon:
   ```python
   if dist < 150:  # Change to 120 or 180
   ```

2. Check card layout in UI
3. Verify correct icons for each card type

## Performance Impact

- **Icon detection**: +100-200ms (template matching)
- **Icon + label**: +150-300ms total
- **OCR only**: +100-200ms

Overall workflow impact: **negligible** (still under 1s per step)

## Best Practices

1. **Always provide both dark + light icons**
   ```json
   "icon_patterns": [
     "dark-bi-task.svg",   // Try dark first
     "light-bi-task.svg"   // Fallback to light
   ]
   ```

2. **Set reasonable distance threshold**
   ```python
   if dist < 150:  # 150px allows for card padding
   ```

3. **Use high OCR threshold as fallback**
   ```json
   "confidence_threshold": 0.85  // Only match clear text
   ```

4. **Log detection method**
   ```python
   print(f"Method: {result['method']}")
   print(f"Icon: {result.get('icon')}")
   ```

5. **Test both themes**
   - Capture screenshot in dark theme
   - Capture screenshot in light theme
   - Verify detection works in both

## Future Improvements

- [ ] Auto-detect theme and try matching icon first
- [ ] Cache icon template matches
- [ ] Support icon rotation/scale variants
- [ ] Add icon confidence scoring
- [ ] Multi-icon fallback chains

## Summary

Icon-based detection provides:
✓ **Reliable** - Works regardless of text color/contrast
✓ **Theme-aware** - Handles dark and light themes
✓ **Robust** - Multiple icon variant support
✓ **Fast** - Template matching is quick
✓ **Fallback-safe** - OCR text matching as safety net

## Next Steps

1. Copy SVG icons from assets to `kb/icons/`
2. Update artifact configurations with `icon_patterns`
3. Run `verify_icon_detection.py` to test
4. Test on actual UI in both themes
5. Adjust thresholds based on results
