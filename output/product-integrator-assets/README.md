# Product-Integrator Visual Assets Bundle

## Overview
Complete collection of 235 visual assets from WSO2 Product-Integrator, organized by category and purpose.

**Generated:** 2026-04-18  
**Source:** WSO2 Product-Integrator GitHub Repository  
**Total Size:** See statistics below

---

## Quick Navigation

### 📁 Organized Assets Folders
- `extension-icons/` - VS Code extension UI icons (5 files)
- `webview-assets/` - Integration component SVG icons (211 files)
- `vs-code-resources/` - VS Code theme resources (12 files)
- `icons/` - Codicons and other icon sets (1 file)
- `media/` - Media resources (5 files)

### 📄 Documentation
- `ASSET_CATALOG.md` - Complete asset catalog with descriptions
- `DETAILED_INVENTORY.md` - Full inventory with categories and mappings
- `ASSET_MANIFEST.txt` - Complete file listing (all 235 files)
- `README.md` - This file

---

## Asset Categories Summary

| Category | Files | Format | Purpose |
|----------|-------|--------|---------|
| **Extension Icons** | 5 | SVG, PNG | VS Code activity bar, preview commands, branding |
| **WebView Assets** | 211 | SVG | BI components, APIs, databases, endpoints, processors |
| **VS Code Resources** | 12 | SVG, PNG | Theme graphics, letterpress, code icons, app icons |
| **Codicons** | 1 | SVG | VSCode standard icon library |
| **Media Files** | 5 | PNG, JPG | Server resources, platform-specific icons |
| **TOTAL** | **235** | Mixed | Complete visual system |

---

## Key Asset Groups

### 1. Ballerina Integration Components
- **Automation** - `bi-automation.svg`
- **HTTP Service** - `http-service.svg`
- **API** - `api-*.svg`
- **Database** - `database.svg`, `bi-db.svg`
- **Data Service** - `bi-data-service.svg`
- **AI Agent** - `bi-ai-agent.svg`
- **Config** - `bi-config.svg`
- **Type** - `bi-type.svg`

### 2. Cloud Connectors & Integrations
- Azure Service Bus (`bi-asb.svg`)
- RabbitMQ (`bi-rabbitmq.svg`)
- Kafka (`bi-kafka.svg`)
- Slack (`bi-slack.svg`)
- Salesforce (`bi-salesforce.svg`)
- SAP (`bi-sap.svg`)
- Redis (`bi-redis.svg`)
- S3 (`bi-s3.svg`)
- MongoDB (`bi-mongodb.svg`)
- MySQL (`bi-mysql.svg`)
- PostgreSQL (`bi-postgres.svg`)
- Docker (`bi-docker.svg`)
- Kubernetes (`bi-kubernetes.svg`)
- GitHub (`bi-github.svg`)
- Swagger (`bi-swagger.svg`)

### 3. API & HTTP Components
- GET API (`get-api.svg`)
- POST API (`post-api.svg`)
- PUT API (`put-api.svg`)
- DELETE API (`delete-api.svg`)
- PATCH API (`patch-api.svg`)
- HTTP Service (`http-service.svg`)
- HTTP Client (`http-client.svg`)
- HTTP Endpoint (`http-endpoint.svg`)

### 4. Database Components
- Generic Database (`database.svg`)
- PostgreSQL (`postgresql.svg`)
- MySQL (`mysql.svg`)
- Oracle (`oracle.svg`)
- MSSQL (`mssql.svg`)
- MongoDB (`mongodb.svg`)
- Elasticsearch (`elasticsearch.svg`)
- Cassandra (`cassandra.svg`)
- DynamoDB (`dynamodb.svg`)

### 5. Messaging & Endpoints
- JMS Endpoint (`jms-endpoint.svg`)
- Address Endpoint (`address-endpoint.svg`)
- File Endpoint (`file-endpoint.svg`)
- Failover Endpoint (`failover-endpoint.svg`)
- Load Balance Endpoint (`load-balance-endpoint.svg`)
- CXF WS-RM Endpoint (`cxf-ws-rm-endpoint.svg`)
- Message Store (`message-store.svg`)
- Sequence (`sequence.svg`)

### 6. UI Form Components
- Checkbox (`checkbox.svg`)
- Radio Button (`radio.svg`)
- Input Field (`input.svg`)
- Dropdown (`dropdown.svg`)
- Toggle Switch (`toggle.svg`)
- Text Area (`textarea.svg`)

### 7. Utility Icons
- Start (`start.svg`)
- Settings (`settings.svg`)
- Task List (`tasklist.svg`)
- Error (`error.svg`)
- Success (`success.svg`)
- Warning (`warning.svg`)
- Info (`info.svg`)

---

## Theme Support

### Dark/Light Variants
Most WebView assets include theme variants:

```
Naming Convention:
- asset.svg              → Default/Light theme
- asset-light.svg        → Explicit light variant
- dark-asset.svg         → Dark theme variant
- light-asset.svg        → Light theme variant
```

### VS Code Theme Resources
- **Letterpress Graphics**: light, dark, hcLight (high contrast light), hcDark (high contrast dark)
- **Activity Icons**: Dark and light variants for sidebar integration

---

## Usage in Source Code

### Main Component Files Using These Assets
1. **ProjectCreationView.tsx** - Creation flow UI with BI type selection
2. **LibraryCreationView.tsx** - Library creation with component icons
3. **AdvancedConfigurationSection.tsx** - Configuration with form icons
4. **SamplesContainer.tsx** - Sample browser with technology icons
5. **WizardAIEnhancementView.tsx** - AI-powered import wizard
6. **ComponentFormView.tsx** - Component design with endpoint icons
7. **Artifact Picker** - Automation, HTTP Service, API cards

---

## Asset Statistics

```
Extension Icons:    5 files
WebView SVG Assets: 211 files (with ~106 light variants)
VS Code Resources:  12 files (including theme variants)
Codicons:          1 file
Media Resources:    5 files
─────────────────────────
TOTAL:             235 files
```

### Size Breakdown
- SVG Assets: ~50-100KB per set (scalable)
- PNG Resources: ~10-100KB per file (fixed size)
- Icon Library: Variable (depends on usage)

---

## Integration Points

### VS Code Extension
- **Activity Bar Icon**: `integrator-activity-icon.svg`
- **Preview Commands**: `preview-command-icon*.svg`
- **Branding**: `wso2-integrator-logo.png`

### WebView Components
- **Artifact Types**: BI component icons
- **Cloud Connectors**: Integration platform icons
- **UI Elements**: Form and control icons
- **Status Indicators**: Success, warning, error icons

### Theme System
- **CSS Variables**: Dynamic color theming
- **SVG Variants**: Dark/light mode switching
- **High Contrast**: Accessibility support

---

## File Organization

```
output/product-integrator-assets/
├── extension-icons/              (5 files)
│   ├── integrator-activity-icon.svg
│   ├── integrator-activity-icon-dark.svg
│   ├── preview-command-icon.svg
│   ├── preview-command-icon-dark.svg
│   └── wso2-integrator-logo.png
├── webview-assets/               (211 files)
│   ├── bi-*.svg (light + dark variants)
│   ├── *-api.svg (light + dark variants)
│   ├── database*.svg
│   ├── endpoint*.svg
│   ├── sequence*.svg
│   ├── message*.svg
│   ├── *-processor.svg
│   ├── checkbox.svg, radio.svg, input.svg, etc.
│   └── status icons (error, success, warning, info)
├── vs-code-resources/            (12 files)
│   ├── letterpress-*.svg (4 theme variants)
│   ├── code-icon.svg
│   ├── code-192.png
│   ├── code-512.png
│   └── platform-specific variants
├── icons/                        (1 file)
│   └── codicon.svg (VSCode icon library)
├── media/                        (5 files)
│   └── Platform resources
├── ASSET_CATALOG.md
├── DETAILED_INVENTORY.md
├── ASSET_MANIFEST.txt
└── README.md
```

---

## How to Use

### 1. Reference Specific Assets
Use the asset filename from the appropriate folder:
```
webview-assets/bi-automation.svg
webview-assets/dark-bi-automation.svg
extension-icons/integrator-activity-icon.svg
```

### 2. Access Asset Catalogs
- **Full Listing**: See `ASSET_MANIFEST.txt`
- **Categorized View**: See `DETAILED_INVENTORY.md`
- **Usage Guide**: See `ASSET_CATALOG.md`

### 3. Integration Examples
```typescript
// React component
import BiAutomationIcon from 'path/to/bi-automation.svg';

// Or direct SVG import
import { ReactComponent as BiAutomation } from 'assets/bi-automation.svg';

// Template reference
<img src={require('assets/dark-bi-automation.svg')} alt="Automation" />
```

---

## Version Information

**Product-Integrator Version**: Latest (updated 2026-04-18)  
**Asset Collection Date**: 2026-04-18  
**Total Assets Cataloged**: 235  
**Manifest Format**: Markdown + text inventory

---

## Notes

- All SVG assets are scalable and vector-based
- PNG assets are bitmap/raster images
- Dark/light variants support theme switching
- Assets are optimized for VS Code and web rendering
- Codicons library provides standard VSCode UI icons

---

## Next Steps

1. Review `ASSET_CATALOG.md` for detailed descriptions
2. Check `DETAILED_INVENTORY.md` for complete categorization
3. Reference specific files from `ASSET_MANIFEST.txt`
4. Use the organized folders for asset imports/integration

