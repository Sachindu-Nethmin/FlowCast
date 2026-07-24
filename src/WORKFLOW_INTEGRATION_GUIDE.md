# Workflow Integration Guide: Using Template Matching for Automation

## Overview

Using the 235 Product-Integrator visual assets as templates, you can reliably detect and interact with UI elements in the quick-start-automation workflow.

---

## Example: Step 4 - "Set Project Name to Automation"

### From: `workflows/quick-start-automation.md`

```markdown
4. Set **Project Name** to `Automation`.
```

### How Template Matching Identifies This

#### Method 1: Input Field Template Matching
```python
from template_detector import TemplateDetector

detector = TemplateDetector()

# Match input field template
result = detector.match_template(
    screenshot=screenshot,
    template_path='output/product-integrator-assets/webview-assets/input.svg',
    threshold=0.60
)

# Result: {'matched': True, 'location': (x, y), 'confidence': 0.75}
```

#### Method 2: OCR Label Verification
```python
# Search for "Project Name" label text
# If found, look for input field below it
# This confirms we found the right field, not just any input
```

#### Method 3: Visual Pattern Recognition
```python
# Detect light gray input box with border
# HSV color range: H(0-255), S(0-30), V(200-255)
# Confirms field is an editable input
```

---

## Complete Workflow Automation Script

```python
#!/usr/bin/env python3
"""
Automate quick-start-automation workflow
Using template matching for reliable UI element detection
"""

import cv2
from template_detector import TemplateDetector
from project_name_detector import ProjectNameDetector

class QuickStartAutomationBot:
    def __init__(self):
        self.template_detector = TemplateDetector()
        self.project_name_detector = ProjectNameDetector()
    
    def step_1_create_new_project(self, screenshot):
        """Step 1: Click 'Create New Project' card"""
        result = self.template_detector.detect_artifact_card(screenshot, 'automation')
        return result
    
    def step_2_select_project_name(self, screenshot):
        """Step 2: Enter Integration Name"""
        # Detect Integration Name field
        return self._fill_text_field(screenshot, 'Integration Name', 'My Automation')
    
    def step_3_select_automation_artifact(self, screenshot):
        """Step 3: Select Automation artifact"""
        result = self.template_detector.detect_artifact_card(screenshot, 'automation')
        if result:
            return {'action': 'click', 'location': result['center']}
        return None
    
    def step_4_set_project_name(self, screenshot):
        """Step 4: Set Project Name to Automation"""
        result = self.project_name_detector.set_project_name(screenshot, 'Automation')
        return result
    
    def step_5_add_automation_artifact(self, screenshot):
        """Step 5: Add an Automation artifact"""
        # Detect "+ Add Artifact" button
        return self._find_and_click_button(screenshot, 'Add Artifact')
    
    def run_workflow(self):
        """Execute entire workflow"""
        steps = [
            ('step_1', self.step_1_create_new_project),
            ('step_2', self.step_2_select_project_name),
            ('step_3', self.step_3_select_automation_artifact),
            ('step_4', self.step_4_set_project_name),
            ('step_5', self.step_5_add_automation_artifact),
        ]
        
        results = {}
        for step_name, step_func in steps:
            # Take screenshot
            screenshot = self._take_screenshot()
            
            # Execute step
            result = step_func(screenshot)
            results[step_name] = result
            
            # Check for errors
            if not result.get('success', True):
                print(f"⚠️  {step_name} failed: {result.get('error')}")
                break
            
            print(f"✅ {step_name} completed")
        
        return results

# Usage
if __name__ == '__main__':
    bot = QuickStartAutomationBot()
    results = bot.run_workflow()
    print("Workflow complete!")
```

---

## Detection Configuration for Step 4

### File: `kb/project_name_detection.json`

```json
{
  "step": 4,
  "description": "Set Project Name to Automation",
  
  "element": {
    "name": "Project Name",
    "type": "text_input",
    "section": "Project Structure",
    "conditional": "Visible when 'Create within a project' is checked"
  },
  
  "detection": {
    "primary": "template_matching",
    "template": "input.svg",
    "threshold": 0.60,
    "fallback": ["ocr_label", "visual_pattern"],
    "confidence_min": 0.55
  },
  
  "verification": {
    "method": "ocr",
    "verify_label": "Project Name",
    "label_confidence": 0.80
  },
  
  "interaction": {
    "click": "field_center",
    "clear": "select_all_delete",
    "type": "Automation",
    "verify": "ocr_read_value"
  }
}
```

---

## Asset Templates Used Per Step

| Step | Description | Template(s) | Category | Threshold |
|------|-------------|-----------|----------|-----------|
| 1 | Click Create card | - | - | - |
| 2 | Enter Integration Name | input.svg | ui_components | 0.60 |
| 3 | Select Automation | bi-automation.svg | integration_artifacts | 0.60 |
| 4 | Set Project Name | input.svg | ui_components | 0.60 |
| 5 | Add Artifact | + Add Artifact button | - | - |

---

## Troubleshooting Detection Issues

### Issue: Field Not Detected

**Checklist:**
```
□ Is "Create within a project" checkbox checked?
  → If not, field won't be visible
  → Check step 2 completion first

□ Is "Project Structure" section expanded?
  → Field is inside a collapsible section
  → May need to click section header

□ Is input.svg template file present?
  → Check: output/product-integrator-assets/webview-assets/input.svg
  → May need to use alternative: dark-input.svg or light-input.svg
```

**Solution:**
```python
# Check prerequisites first
if not project_structure_expanded:
    click_element("Project Structure")
    wait(500)  # Let animation complete

# Try with lower threshold
result = detector.match_template(
    screenshot,
    'input.svg',
    threshold=0.50  # Lower threshold
)
```

### Issue: OCR Cannot Verify Label

**Solution:**
```python
# Use direct visual detection instead
result = detector._detect_via_pattern(screenshot)
if result:
    print(f"Field found at: {result['field_center']}")
```

### Issue: Text Not Setting Correctly

**Solution:**
```python
# Add delay between actions
click(field_location)
wait(200)  # Wait for focus

keyboard.press('ctrl')
keyboard.press('a')
keyboard.release('ctrl')
wait(100)

keyboard.type('Automation')
wait(300)  # Wait for typing to complete

# Verify
ocr_result = ocr.read_field(field_location)
assert ocr_result == 'Automation'
```

---

## Integration with Detector System

### Update `src/detector.py`

```python
from project_name_detector import ProjectNameDetector
from template_detector import TemplateDetector

class EnhancedUIDetector:
    def __init__(self):
        self.template_detector = TemplateDetector()
        self.project_name_detector = ProjectNameDetector()
        self.workflow_config = self.load_workflow_config()
    
    def execute_workflow_step(self, screenshot, step_number):
        """Execute a workflow step using template matching"""
        
        step_config = self.workflow_config.get(f'step_{step_number}')
        
        if not step_config:
            return {'error': f'Step {step_number} not configured'}
        
        # Get detection method
        detection_method = step_config.get('detection_method')
        
        if detection_method == 'project_name':
            return self.project_name_detector.set_project_name(
                screenshot,
                value=step_config.get('value')
            )
        
        elif detection_method == 'template':
            return self.template_detector.detect_artifact_card(
                screenshot,
                artifact_type=step_config.get('artifact_type')
            )
        
        return None
    
    def load_workflow_config(self):
        """Load workflow configuration from KB files"""
        import json
        with open('kb/project_name_detection.json') as f:
            return json.load(f)
```

---

## Performance Optimization

### Template Caching
```python
# Cache templates at startup for faster detection
detector = TemplateDetector(use_cache=True)
detector.load_all_templates()

# Subsequent calls reuse cached templates
result = detector.match_template(screenshot, 'input.svg')
```

### Region-Based Detection
```python
# Only search relevant area instead of full screenshot
# Project Name field is below Integration Name
search_region = screenshot[y_start:y_end, x_start:x_end]

result = detector.match_template(
    search_region,
    'input.svg',
    threshold=0.60
)
```

---

## Documentation References

**For Step 4 specifically:**
- See: `kb/project_name_detection.json`
- Code: `src/project_name_detector.py`
- Example: `src/workflow_step_4_example.py`

**For template matching system:**
- See: `output/product-integrator-assets/IMPLEMENTATION_GUIDE.md`
- Code: `src/template_detector.py`
- Catalog: `output/product-integrator-assets/DETAILED_INVENTORY.md`

---

## Summary

Using the **235 visual assets as templates**, Step 4 ("Set Project Name to Automation") is detected and executed via:

1. **Template Matching**: Match input.svg (threshold 0.60)
2. **OCR Verification**: Confirm "Project Name" label nearby
3. **Visual Pattern**: Detect light gray input box
4. **Interaction**: Click, select all, type "Automation", verify

This approach is **more reliable** than pure OCR and works across:
- Different screen resolutions
- Dark/light UI themes
- UI scaling/zooming
- Various font sizes

