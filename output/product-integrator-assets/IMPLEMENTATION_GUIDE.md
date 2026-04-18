# Template Matching Implementation Guide

## Quick Start

### 1. Available Visual Assets
- **235 total assets** from Product-Integrator
- **211 WebView component icons** (SVGs with dark/light variants)
- **5 VS Code extension icons**
- **12 VS Code theme resources**
- **7 utility categories** pre-organized

### 2. Key Template Categories for Detection

```python
# Use these categories for UI element detection:

'integration_artifacts'  # Automation, HTTP Service, API, Database
'cloud_connectors'       # Azure, RabbitMQ, Kafka, Slack, etc.
'databases'              # PostgreSQL, MySQL, Oracle, MongoDB
'endpoints'              # JMS, HTTP, Address, File endpoints
'ui_components'          # Checkboxes, radio buttons, inputs, dropdowns
'status_icons'           # Error, Success, Warning, Info
'utilities'              # Settings, Start, Task list
```

### 3. Setup Steps

#### Step 1: Copy SVG Assets
```bash
# SVGs are already in: output/product-integrator-assets/webview-assets/
cp output/product-integrator-assets/webview-assets/*.svg detector_templates/

# Or organize by category (recommended):
mkdir -p detector_templates/{integration_artifacts,cloud_connectors,databases,endpoints,ui_components,status_icons}
```

#### Step 2: Load Template Detector
```python
from template_detector import TemplateDetector

detector = TemplateDetector(
    asset_dir='output/product-integrator-assets/webview-assets'
)

# Get available templates
templates = detector.get_available_templates()
print(templates)
```

#### Step 3: Match Templates in Screenshots
```python
# Match a specific template
result = detector.match_template(
    screenshot=my_screenshot,
    template_path='output/product-integrator-assets/webview-assets/bi-automation.svg',
    threshold=0.60
)

if result['matched']:
    print(f"Found at: {result['location']}, confidence: {result['confidence']}")
```

#### Step 4: Detect UI Elements
```python
# Detect artifact card (icon + label)
card = detector.detect_artifact_card(screenshot, artifact_type='automation')

if card:
    print(f"Card center: {card['center']}")
    print(f"Confidence: {card['confidence']}")
    # Now click the card center
    click(card['center'])
```

---

## Integration with detector.py

### Update detector.py

```python
# In detector.py, add template detector

from template_detector import TemplateDetector

class EnhancedUIDetector:
    def __init__(self):
        self.template_detector = TemplateDetector()
        self.ocr_detector = OCRDetector()  # Fallback
    
    def detect_element(self, screenshot, element_config):
        """Detect UI element using templates first, then OCR fallback."""
        
        # Try template matching if configured
        if 'template_match' in element_config:
            result = self.template_detector.match_template(
                screenshot,
                template_path=element_config['template_match'],
                threshold=element_config.get('match_threshold', 0.60)
            )
            
            if result['matched']:
                return result
        
        # Fallback to OCR
        return self.ocr_detector.detect(screenshot, element_config)
```

---

## Configuration Files Updated

### icon_prompts.json
```json
{
  "icons": [
    {
      "id": "bi-automation-artifact",
      "element_label": "Automation",
      "template_match": "bi-automation.svg",
      "template_category": "integration_artifacts",
      "match_threshold": 0.60,
      "scale_variants": [0.8, 1.0, 1.2],
      "click_offset": { "x": -30, "y": -20 }
    }
  ]
}
```

### ui_elements.json
```json
{
  "element_hints": {
    "Automation": {
      "type": "icon_card",
      "template_match": "bi-automation.svg",
      "confidence_threshold": 0.60,
      "note": "Detected via icon template matching"
    }
  }
}
```

---

## Asset File Locations

```
output/product-integrator-assets/
├── webview-assets/          (211 SVG files - Main asset source)
│   ├── bi-*.svg             (BI component icons)
│   ├── *-api.svg            (API method icons)
│   ├── *-endpoint.svg       (Endpoint icons)
│   ├── *-processor.svg      (Message processor icons)
│   ├── database*.svg        (Database icons)
│   ├── checkbox.svg, radio.svg  (Form components)
│   └── [dark-*.svg, light-*.svg] (Dark/light variants)
│
├── extension-icons/         (5 VS Code UI icons)
├── vs-code-resources/       (12 theme resources)
├── ASSET_CATALOG.md         (Complete descriptions)
├── DETAILED_INVENTORY.md    (Full categorization)
└── TEMPLATE_MATCHING_CONFIG.md (This config)
```

---

## Template File Naming Convention

### Dark/Light Variants
```
bi-automation.svg           → Standard/Light theme
dark-bi-automation.svg      → Dark theme
bi-automation-light.svg     → Explicit light variant
```

### Component Icons
```
bi-*.svg                    → Ballerina Integration components
*-api.svg                   → REST API methods
*-endpoint.svg              → Integration endpoints
*-processor.svg             → Message processors
*-store.svg                 → Message stores
```

### Status Icons
```
error.svg, success.svg, warning.svg, info.svg
```

---

## Threshold Recommendations

### Detection Confidence Levels
```
HIGH:   threshold >= 0.75  (clear logos, distinct UI)
MEDIUM: threshold = 0.60   (typical icons, buttons)
LOW:    threshold <= 0.45  (low contrast, small icons)
```

### Per-Category Thresholds
```
integration_artifacts:  0.60  (clear, medium-sized icons)
cloud_connectors:       0.55  (varied complexity)
databases:              0.55  (similar icon styles)
endpoints:              0.55  (small/intricate designs)
ui_components:          0.60  (simple form elements)
status_icons:           0.65  (simple shapes, high contrast)
```

---

## Performance Tips

### 1. Template Caching
```python
# Cache templates in memory at startup
detector.load_all_templates()

# Reuse cached templates
detector.template_cache[category][name]
```

### 2. Multi-Scale Matching
```python
# Test at multiple scales for different UI sizes
scales = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

# Or use category-specific scales:
scales = detector.config[category]['scales']
```

### 3. Region-Based Matching
```python
# Only search in relevant region to speed up
region = screenshot[y1:y2, x1:x2]
result = detector.match_template(region, template, threshold)
```

---

## Troubleshooting

### Template Not Matching
1. **Check threshold**: Lower it from 0.60 to 0.50
2. **Try different scales**: Add scale variants [0.5, 1.0, 1.5]
3. **Dark/light variant**: Try dark-*. svg instead of *.svg
4. **Verify SVG exists**: Check output/product-integrator-assets/webview-assets/

### Low Confidence Score
- Image might be scaled differently
- Theme color might not match (try dark variant)
- Icon might be partially hidden
- Increase tolerance or fallback to OCR

### False Positives
- Increase threshold above 0.65
- Add verification (OCR label nearby)
- Combine with color histogram matching
- Use multiple template variants for AND condition

---

## Test Configuration

```python
# Test template matching
import cv2
from template_detector import TemplateDetector

detector = TemplateDetector()

# Load test screenshot
test_image = cv2.imread('test_screenshot.png')

# Test artifact detection
result = detector.detect_artifact_card(test_image, 'automation')
assert result is not None, "Failed to detect automation artifact"
assert result['confidence'] > 0.60, "Low confidence score"
assert result['center'] is not None, "No center location"

print(f"✅ Test passed! Found artifact at {result['center']}")
```

---

## Available Templates by Purpose

### Artifact Types (8 icons)
- Automation
- HTTP Service
- API
- Database
- Data Service
- Function
- Config
- Type

### Cloud Services (15+ icons)
- Azure Service Bus (ASB)
- RabbitMQ
- Kafka
- Slack
- Salesforce
- SAP
- Redis
- S3
- MongoDB
- MySQL
- PostgreSQL
- Docker
- Kubernetes
- GitHub
- Swagger

### Endpoints & Processing (9+ icons)
- JMS Endpoint
- HTTP Endpoint
- Address Endpoint
- File Endpoint
- Failover Endpoint
- Sequence
- Custom Processor
- Message Store

### Form Elements (6 icons)
- Checkbox
- Radio Button
- Input/Text Field
- Dropdown
- Toggle Switch
- Text Area

### Status & Utilities (7+ icons)
- Success
- Error
- Warning
- Info
- Settings
- Start
- Task List

---

## Next Steps

1. ✅ Download & organize 235 visual assets
2. ✅ Review ASSET_CATALOG.md for details
3. **→ Implement template_detector.py** (Done)
4. **→ Update detector.py to use templates**
5. **→ Test on actual UI screenshots**
6. **→ Fine-tune thresholds per environment**
7. **→ Document template maintenance**

---

## Documentation References

- **ASSET_CATALOG.md** - Complete descriptions
- **DETAILED_INVENTORY.md** - Full categorization  
- **TEMPLATE_MATCHING_CONFIG.md** - Technical setup
- **README.md** - Quick start

