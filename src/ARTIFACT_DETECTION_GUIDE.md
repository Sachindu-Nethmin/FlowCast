# Artifact Detection System - Complete Guide

## Overview

The artifact detection system is a unified framework for detecting and interacting with all UI artifacts in workflow automations. It supports:

- **Input fields** (with label, placeholder, visual pattern detection)
- **Buttons** (OCR text, blue buttons, play buttons)
- **Node cards** (in automation flow diagrams)
- **Artifact cards** (selectable UI components)
- **Output elements** (terminal output, logs)

## Architecture

### Components

1. **`quick_start_automation_artifacts.json`** - KB Configuration
   - Defines all detectable artifacts for each workflow step
   - Specifies detection methods and action sequences
   - Maps artifact types to detection strategies

2. **`artifact_detector.py`** - Core Detection Module
   - `ArtifactDetector` class: Main detection engine
   - Loads configuration and executes detection methods
   - Provides artifact location (x, y coordinates)
   - Executes action sequences (click, type, etc.)

3. **`workflow_automation_complete.py`** - Workflow Bot
   - `QuickStartAutomationBot` class: Complete workflow executor
   - Executes all 4 steps of quick-start-automation
   - Takes screenshots and tracks progress
   - Provides detailed output and error reporting

## Quick Start

### Run Complete Workflow

```python
from workflow_automation_complete import QuickStartAutomationBot

bot = QuickStartAutomationBot()
success = bot.run_complete_workflow()
```

### Detect Single Artifact

```python
from artifact_detector import ArtifactDetector
from PIL import Image

detector = ArtifactDetector()
screenshot = Image.open("screenshot.png")

# Detect integration name field in step 1
result = detector.detect_artifact(
    screenshot, 
    "step_1_create_project",
    "integration_name_field"
)

if result:
    print(f"Found at ({result['x']}, {result['y']})")
    print(f"Confidence: {result['confidence']}")
```

### List All Artifacts in a Step

```python
from artifact_detector import ArtifactDetector

detector = ArtifactDetector()

# List step 1 artifacts
artifacts = detector.list_artifacts("step_1_create_project")
for artifact_id in artifacts:
    config = detector.get_artifact_config("step_1_create_project", artifact_id)
    print(f"- {artifact_id}: {config['label']}")
```

## Detection Methods

Each artifact can use multiple detection methods with fallback support:

### 1. `label_offset`
Finds input field by OCR-detected label + pixel offset.

```json
{
  "method": "label_offset",
  "label_text": "Integration Name",
  "confidence_threshold": 0.75
}
```

**Use for:** Standard form fields with labels.

### 2. `placeholder`
Finds field by placeholder text visible inside the field.

```json
{
  "method": "placeholder",
  "placeholder_text": "Enter an integration name",
  "confidence_threshold": 0.70
}
```

**Use for:** Fields where the label is optional but placeholder is always visible.

### 3. `visual_pattern`
Detects elements by HSV color range (e.g., light gray inputs, blue buttons).

```json
{
  "method": "visual_pattern",
  "hsv_range": {
    "h": [0, 255],
    "s": [0, 30],
    "v": [200, 255]
  }
}
```

**Use for:** Color-based detection (buttons, input boxes, highlights).

### 4. `ocr_label`
Finds elements by OCR text matching.

```json
{
  "method": "ocr_label",
  "text": "Create Integration",
  "confidence_threshold": 0.80
}
```

**Use for:** Buttons and labels with distinctive text.

### 5. `template`
Matches SVG or image template from asset library.

```json
{
  "method": "template",
  "template_asset": "input.svg",
  "threshold": 0.60
}
```

**Use for:** Visual elements with consistent appearance (icons, SVG shapes).

### 6. `blue_button`
Specialized detection for blue buttons using HSV.

```json
{
  "method": "blue_button",
  "description": "Blue button element"
}
```

**Use for:** WSO2 standard blue action buttons.

### 7. `green_play_button`
Detects the green run/play button.

```json
{
  "method": "green_play_button",
  "description": "Green play button in toolbar"
}
```

**Use for:** Run/execute buttons.

### 8. `plus_after_node`
Finds + button relative to anchor node in diagrams.

```json
{
  "method": "plus_after_node",
  "anchor_text": "Start",
  "offset": [50, 0]
}
```

**Use for:** Diagram nodes with floating action buttons.

### 9. `card_with_icon`
Detects artifact card by both icon and label.

```json
{
  "method": "card_with_icon",
  "icon_asset": "automation.svg",
  "label_text": "Automation",
  "threshold": 0.65
}
```

**Use for:** Selectable artifact/component cards.

### 10. `card_with_label`
Detects card by label text only.

```json
{
  "method": "card_with_label",
  "label_text": "Call Function",
  "confidence_threshold": 0.80
}
```

**Use for:** Node cards in diagram panels.

### 11. `ocr_text`
General OCR text search.

```json
{
  "method": "ocr_text",
  "search_text": "Hello World",
  "confidence_threshold": 0.85
}
```

**Use for:** Finding any visible text on screen.

### 12. `region_scan`
Scans a specific screen region for content.

```json
{
  "method": "region_scan",
  "region": "bottom_terminal",
  "search_text": "Hello World"
}
```

**Regions:**
- `bottom_terminal` - Lower 30% of screen
- `top_toolbar` - Upper 15% of screen
- `left_panel` - Left 20% of screen
- `right_panel` - Right 20% of screen
- `center_canvas` - Main central area

**Use for:** Output verification, multi-region searches.

## Action Sequences

Artifacts can define action sequences executed after detection:

```json
"actions": [
  {"action": "click", "description": "Focus the field"},
  {"action": "select_all", "description": "Clear existing text"},
  {"action": "type", "value": "My Integration", "description": "Type the value"}
]
```

### Supported Actions

- **`click`** - Click at detected location
- **`select_all`** - Select all text (Cmd+A / Ctrl+A)
- **`type`** - Type text value
- **`wait`** - Wait specified duration (ms)

## Artifact Configuration Format

```json
{
  "type": "input_field",
  "label": "Integration Name",
  "placeholder": "Enter an integration name",
  "detection_methods": [
    {
      "method": "label_offset",
      "label_text": "Integration Name",
      "confidence_threshold": 0.75
    },
    {
      "method": "visual_pattern",
      "hsv_range": {"h": [0, 255], "s": [0, 30], "v": [200, 255]}
    }
  ],
  "actions": [
    {"action": "click"},
    {"action": "select_all"},
    {"action": "type", "value": "Get Started"}
  ],
  "expected_location": {"x": 320, "y": 120}
}
```

## Extending for New Workflows

### 1. Create Workflow Configuration

Create `kb/your_workflow_artifacts.json`:

```json
{
  "version": 1,
  "workflow": "your-workflow-name",
  "steps": {
    "step_1_unique_id": {
      "title": "Step 1 Title",
      "artifacts": {
        "artifact_1_id": {
          "type": "input_field",
          "label": "Field Label",
          "detection_methods": [...]
        }
      }
    }
  },
  "detection_strategies": { ... }
}
```

### 2. Initialize Detector

```python
from artifact_detector import ArtifactDetector

detector = ArtifactDetector("kb/your_workflow_artifacts.json")
```

### 3. Use in Workflow Bot

```python
from artifact_detector import ArtifactDetector
from PIL import Image

class YourWorkflowBot:
    def __init__(self):
        self.detector = ArtifactDetector("kb/your_workflow_artifacts.json")
    
    def step_1(self):
        screenshot = Image.open("step1.png")
        self.detector.interact_with_artifact(
            screenshot,
            "step_1_unique_id",
            "artifact_1_id"
        )
```

## Troubleshooting

### Artifact Not Detected

**Check detection methods in priority order:**

1. **Verify first method works** - Take screenshot, check if label/template visible
2. **Adjust thresholds** - Lower confidence_threshold if text is blurry
3. **Try visual pattern** - If OCR fails, use HSV color detection
4. **Check coordinates** - Print detection result coordinates match expected position

### Action Execution Fails

1. **Verify artifact detected** - Add debug print of detection result
2. **Check click coordinates** - Ensure x, y are within screen bounds
3. **Add wait delays** - UI may need time to render between actions
4. **Use hotkey mapping** - For Cmd/Ctrl, detector handles platform differences

### OCR Not Working

1. **Check image quality** - Blurry images fail OCR
2. **Try different threshold** - Adjust confidence_threshold down (0.5-0.7)
3. **Use similarity scoring** - `_fuzzy()` and `_similarity_score()` handle variations
4. **Fallback to visual pattern** - Use HSV detection for buttons/fields

## Performance Tuning

### Optimize Detection Speed

```python
# Cache screenshot across multiple detections
screenshot = Image.open("screenshot.png")

for artifact_id in ["field1", "field2", "button1"]:
    detection = detector.detect_artifact(screenshot, "step_1", artifact_id)
```

### Reduce False Positives

```python
# Increase thresholds for noisy screens
config = detector.get_artifact_config("step_1", "field1")
for method in config["detection_methods"]:
    method["confidence_threshold"] = 0.85  # Stricter matching
```

## API Reference

### ArtifactDetector Class

#### Methods

- **`__init__(kb_path)`** - Initialize with configuration file
- **`list_artifacts(step_id)`** - Get all artifact IDs in a step
- **`get_artifact_config(step_id, artifact_id)`** - Get artifact configuration
- **`detect_artifact(screenshot, step_id, artifact_id)`** - Detect artifact location
- **`interact_with_artifact(screenshot, step_id, artifact_id)`** - Detect and execute actions

#### Returns

Detection returns `Optional[Dict]`:
```python
{
    "x": 320,                    # X coordinate
    "y": 450,                    # Y coordinate
    "method": "label_offset",    # Detection method used
    "confidence": 0.85,          # Confidence score 0.0-1.0
    "label": "Integration Name", # Artifact label
    "content": "text"            # Optional: detected content
}
```

## Examples

### Complete Workflow Execution

```python
from workflow_automation_complete import QuickStartAutomationBot

bot = QuickStartAutomationBot()
bot.run_complete_workflow()
```

### Step-by-Step Automation

```python
from artifact_detector import ArtifactDetector
from PIL import Image
import pyautogui
import time

detector = ArtifactDetector()
screenshot = Image.open("ui.png")

# 1. Detect integration name field
result = detector.detect_artifact(screenshot, "step_1_create_project", "integration_name_field")
if result:
    pyautogui.click(result['x'], result['y'])
    time.sleep(0.2)
    pyautogui.hotkey('cmd', 'a')
    pyautogui.typewrite('My Integration')

# 2. Detect and interact with project name
detector.interact_with_artifact(screenshot, "step_1_create_project", "project_name_field")
```

### Custom Detection for New Artifact

```json
{
  "type": "custom_element",
  "label": "My Custom Element",
  "detection_methods": [
    {
      "method": "ocr_label",
      "text": "Custom Text",
      "confidence_threshold": 0.75
    },
    {
      "method": "visual_pattern",
      "hsv_range": {
        "h": [0, 255],
        "s": [100, 150],
        "v": [100, 200]
      }
    }
  ],
  "actions": [
    {"action": "click"},
    {"action": "wait", "duration": 500}
  ]
}
```

## Best Practices

1. **Always provide fallback detection** - Use 2-3 detection methods per artifact
2. **Test with both themes** - Verify detection works in light and dark modes
3. **Use high-confidence thresholds** - 0.75+ for production use
4. **Add wait delays** - Give UI time to render between actions (0.5-1.0s)
5. **Take diagnostic screenshots** - Help with debugging detection failures
6. **Verify expected output** - Check results after interactions
7. **Handle edge cases** - Consider different content lengths, languages

## Integration with Existing Detector

The artifact detector complements the existing `detector.py`:

```python
from detector import _find_ocr, _find_template, find_input_field
from artifact_detector import ArtifactDetector

# Use existing functions for specific cases
ocr_result = _find_ocr(screenshot, "Target Label")

# Use artifact detector for workflow-based detection
artifact_detector = ArtifactDetector()
result = artifact_detector.detect_artifact(screenshot, "step_1", "my_field")
```

## Limitations and Future Improvements

### Current Limitations

- No multi-step interactions (drag-drop, multi-click sequences)
- Limited custom action support (only click, type, select_all)
- No state persistence between steps
- No retry logic on detection failure

### Planned Improvements

- Add drag-drop actions
- Implement custom action callbacks
- Add state machine for multi-step workflows
- Implement automatic retry with modified thresholds
- Add natural language action descriptions
- Support for dynamic regions and offsets

## Support

For issues or questions:

1. Check screenshot in `output/workflow_screenshots/`
2. Verify artifact config in `kb/quick_start_automation_artifacts.json`
3. Test individual detection methods with `ArtifactDetector.detect_artifact()`
4. Review `src/detector.py` for underlying detection functions
