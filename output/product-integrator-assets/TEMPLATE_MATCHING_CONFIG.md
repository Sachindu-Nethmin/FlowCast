# Template Matching Configuration for Product-Integrator Assets

## Overview
Use visual assets as template images for UI element detection in FlowCast automation.

## Setup Instructions

### 1. Template Asset Organization
```
detector_templates/
├── integration_artifacts/
│   ├── automation.svg
│   ├── http-service.svg
│   ├── api.svg
│   └── database.svg
├── cloud_connectors/
│   ├── bi-asb.svg
│   ├── bi-rabbitmq.svg
│   ├── bi-kafka.svg
│   └── ... (15+ cloud connector icons)
├── databases/
│   ├── postgresql.svg
│   ├── mysql.svg
│   ├── mongodb.svg
│   └── ... (9+ database icons)
├── endpoints/
│   ├── http-endpoint.svg
│   ├── jms-endpoint.svg
│   └── ... (9+ endpoint icons)
├── ui_components/
│   ├── checkbox.svg
│   ├── radio.svg
│   ├── input.svg
│   └── ... (form elements)
├── status_icons/
│   ├── success.svg
│   ├── error.svg
│   ├── warning.svg
│   └── info.svg
└── utilities/
    ├── settings.svg
    ├── start.svg
    └── task-list.svg
```

### 2. Template Matching Strategy

#### Icon Detection (SVG Templates)
```python
Template Matching Parameters:
- Method: cv2.TM_CCOEFF (correlation coefficient)
- Match Threshold: 0.50-0.65 (adjust per icon complexity)
- Scale Variants: 0.5x, 1.0x, 1.5x, 2.0x
- Color Channels: BGR, HSV for dark/light variants
```

#### Component Card Detection (Multiple Icons)
```python
# Automation Card Example
- Primary Icon: bi-automation.svg (centered)
- Label Text: "Automation"
- Click Region: Card center (not just text)
- Confidence: Require both icon + text match
```

### 3. Integration with detector.py

#### Add Template Asset Loading
```python
class TemplateDetector:
    def __init__(self):
        self.templates = {}
        self.load_templates('detector_templates/')
    
    def load_templates(self, template_dir):
        for category in os.listdir(template_dir):
            category_path = os.path.join(template_dir, category)
            self.templates[category] = {}
            
            for svg_file in os.listdir(category_path):
                if svg_file.endswith('.svg'):
                    # Convert SVG to PNG at multiple scales
                    name = svg_file.replace('.svg', '')
                    self.templates[category][name] = self.load_and_scale_template(
                        os.path.join(category_path, svg_file)
                    )
```

#### Template Matching Function
```python
def match_template(self, screenshot, template_name, category):
    """Match template against screenshot"""
    template = self.templates[category][template_name]
    
    # Try multiple scales
    for scale in [0.5, 0.75, 1.0, 1.25, 1.5]:
        scaled_template = cv2.resize(template, 
            (int(template.shape[1]*scale), int(template.shape[0]*scale)))
        
        result = cv2.matchTemplate(screenshot, scaled_template, cv2.TM_CCOEFF)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        if max_val > self.threshold:
            return {
                'matched': True,
                'confidence': max_val,
                'location': max_loc,
                'scale': scale
            }
    
    return {'matched': False}
```

### 4. KB Configuration for Template-Based Detection

#### Update icon_prompts.json
```json
{
  "icons": [
    {
      "id": "bi-automation-artifact",
      "element_label": "Automation",
      "screen": "add_artifact_picker",
      "position_hint": "center grid card in artifact picker",
      "action": "Select Automation artifact",
      "template_file": "integration_artifacts/automation.svg",
      "template_category": "integration_artifacts",
      "match_threshold": 0.60,
      "scale_variants": [0.8, 1.0, 1.2],
      "click_offset": { "x": -30, "y": -20 }
    },
    {
      "id": "http-service-artifact",
      "element_label": "HTTP Service",
      "template_file": "integration_artifacts/http-service.svg",
      "template_category": "integration_artifacts",
      "match_threshold": 0.60
    },
    {
      "id": "database-connector",
      "element_label": "Database",
      "template_file": "databases/database.svg",
      "template_category": "databases",
      "match_threshold": 0.55
    }
  ]
}
```

#### Update ui_elements.json
```json
{
  "element_hints": {
    "Automation": {
      "label": "Automation",
      "type": "icon_card",
      "position": "Add Artifact picker — center grid",
      "icon": "automation-artifact",
      "template_match": "integration_artifacts/automation.svg",
      "confidence_threshold": 0.60,
      "click_offset": { "x": -30, "y": -20 },
      "note": "Detected via icon template matching"
    }
  }
}
```

### 5. Detection Workflow

```
┌─────────────────────┐
│  Screenshot Capture │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────┐
│  Template Asset Database    │
│  (235 SVG icons loaded)     │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Multi-Scale Template Match │
│  • Scale: 0.5x - 2.0x       │
│  • Threshold: 0.50-0.65     │
│  • Color variants: RGB, HSV │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  OCR Text Verification      │
│  (Confirm label near icon)  │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Element Location & Bounds  │
│  • Position: (x, y)         │
│  • Confidence: 0.0-1.0      │
│  • Click offset applied     │
└─────────────────────────────┘
```

### 6. Artifact Card Detection Example

```python
def detect_artifact_card(self, screenshot, artifact_type):
    """
    Detect artifact picker card by:
    1. Icon template matching
    2. Text label verification
    3. Card boundary detection
    """
    
    # Match icon template
    icon_match = self.match_template(
        screenshot, 
        f'bi-{artifact_type}.svg',
        'integration_artifacts'
    )
    
    if not icon_match['matched']:
        return None
    
    icon_loc = icon_match['location']
    
    # Find text label near icon
    text_region = screenshot[
        icon_loc[1]-50:icon_loc[1]+150,
        icon_loc[0]-100:icon_loc[0]+200
    ]
    
    text = self.ocr.recognize(text_region)
    
    if artifact_type.lower() in text.lower():
        # Find card boundaries
        card_bounds = self.find_card_boundaries(screenshot, icon_loc)
        
        return {
            'type': artifact_type,
            'icon_location': icon_loc,
            'card_bounds': card_bounds,
            'center': self.calculate_card_center(card_bounds),
            'confidence': icon_match['confidence']
        }
    
    return None
```

### 7. Configuration Parameters

#### Template Matching Thresholds
```yaml
HIGH_CONFIDENCE:
  threshold: 0.75
  examples: [clear logos, distinct UI elements]
  
MEDIUM_CONFIDENCE:
  threshold: 0.60
  examples: [artifact icons, buttons, standard components]
  
LOW_CONFIDENCE:
  threshold: 0.45
  examples: [low contrast, small icons, icons with variants]
```

#### Scale Variants
```yaml
Icon Matching Scales:
  - 0.5x   (50% - tiny/compressed)
  - 0.75x  (75% - small)
  - 1.0x   (100% - standard)
  - 1.25x  (125% - large)
  - 1.5x   (150% - extra large)
  - 2.0x   (200% - double size)

Recommended:
  Small icons (<32px):    [0.5x, 0.75x, 1.0x]
  Medium icons (32-64px): [0.75x, 1.0x, 1.25x, 1.5x]
  Large icons (>64px):    [1.0x, 1.25x, 1.5x]
```

### 8. Integration with detector.py

#### Add to IconDetector class:
```python
class EnhancedDetector:
    def __init__(self):
        self.icon_matcher = IconTemplateMatcher(
            template_dir='detector_templates/',
            fallback_to_ocr=True  # Fallback to text if icon fails
        )
    
    def detect_element(self, screenshot, element_config):
        """Detect UI element using template matching + OCR"""
        
        # Try template matching first
        if 'template_match' in element_config:
            result = self.icon_matcher.match(
                screenshot,
                element_config['template_match'],
                threshold=element_config.get('match_threshold', 0.60)
            )
            
            if result['confidence'] > element_config.get('confidence_threshold', 0.60):
                return result
        
        # Fallback to OCR
        return self.ocr_detect(screenshot, element_config)
```

### 9. Performance Optimization

#### Template Caching
```python
# Pre-load and cache templates at startup
self.template_cache = {}
self.load_and_cache_templates('detector_templates/')

# Reuse cached templates
def get_cached_template(self, name, category):
    key = f"{category}/{name}"
    if key not in self.template_cache:
        self.template_cache[key] = self.load_template(name, category)
    return self.template_cache[key]
```

#### Parallel Matching
```python
from concurrent.futures import ThreadPoolExecutor

def match_multiple_templates(self, screenshot, templates_list):
    """Match multiple templates in parallel"""
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(
            lambda t: self.match_template(screenshot, t['name'], t['category']),
            templates_list
        ))
    return results
```

### 10. Testing & Validation

#### Unit Tests
```python
def test_automation_icon_detection(self):
    # Load test screenshot
    screenshot = cv2.imread('test_images/artifact_picker.png')
    
    # Test automation icon detection
    result = self.detector.detect_artifact_card(screenshot, 'automation')
    
    assert result is not None
    assert result['confidence'] > 0.60
    assert result['center'] is not None

def test_database_icon_detection(self):
    screenshot = cv2.imread('test_images/connector_picker.png')
    result = self.detector.match_template(screenshot, 'database.svg', 'databases')
    
    assert result['matched']
    assert result['confidence'] > 0.55
```

#### Integration Tests
```python
def test_artifact_selection_workflow(self):
    # Full workflow test
    screenshot = self.take_screenshot()
    
    # Detect artifact picker
    picker = self.detector.detect_element(screenshot, {
        'label': 'Add Artifact',
        'template_match': 'integration_artifacts/add-artifact.svg'
    })
    assert picker is not None
    
    # Detect automation card
    card = self.detector.detect_artifact_card(screenshot, 'automation')
    assert card is not None
    
    # Click card
    self.click(card['center'])
```

---

## Asset Template Mapping

### Integration Artifacts
| Artifact | Template | Threshold | Scale |
|----------|----------|-----------|-------|
| Automation | `bi-automation.svg` | 0.60 | 1.0x |
| HTTP Service | `http-service.svg` | 0.60 | 1.0x |
| API | `api.svg` | 0.60 | 1.0x |
| Database | `database.svg` | 0.55 | 1.0x |
| Data Service | `bi-data-service.svg` | 0.60 | 1.0x |

### Cloud Connectors
| Service | Template | Threshold |
|---------|----------|-----------|
| Azure Service Bus | `bi-asb.svg` | 0.55 |
| RabbitMQ | `bi-rabbitmq.svg` | 0.55 |
| Kafka | `bi-kafka.svg` | 0.55 |
| MongoDB | `bi-mongodb.svg` | 0.55 |
| PostgreSQL | `bi-postgres.svg` | 0.55 |

---

## Implementation Checklist

- [ ] Create `detector_templates/` directory structure
- [ ] Convert SVG templates to PNG at multiple scales
- [ ] Update `icon_prompts.json` with template references
- [ ] Update `ui_elements.json` with template configurations
- [ ] Implement `TemplateDetector` class in detector.py
- [ ] Add template matching functions to IconDetector
- [ ] Implement multi-scale matching logic
- [ ] Add fallback OCR detection
- [ ] Create unit tests for template matching
- [ ] Create integration tests for workflows
- [ ] Profile performance and optimize
- [ ] Document template naming conventions
- [ ] Create template maintenance guide

---

## Benefits

✅ More reliable UI element detection  
✅ Less dependent on OCR for icons  
✅ Handles dark/light theme variants  
✅ Works at different screen resolutions  
✅ Platform-independent icon matching  
✅ Can detect exact component types  
✅ Faster than pure OCR for graphics  

