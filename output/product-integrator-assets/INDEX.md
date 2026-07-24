# Product-Integrator Visual Assets - Complete Index

## 📦 What You Have

**235 visual assets** from WSO2 Product-Integrator, including:
- SVG icons for integration components
- UI element icons
- VS Code theme resources
- Extension branding assets
- Complete documentation

**Total Size:** 1.8 MB  
**Date:** 2026-04-18

---

## 🗂️ Folder Structure

```
output/product-integrator-assets/
│
├── 📁 extension-icons/          (60 KB, 5 files)
│   ├── VS Code activity bar icons
│   ├── Preview command icons
│   ├── WSO2 branding assets
│   └── Light/dark variants
│
├── 📁 webview-assets/           (1.1 MB, 211 files)
│   ├── BI Component Icons (automation, HTTP, API, database, etc.)
│   ├── Cloud Connector Icons (Azure, RabbitMQ, Kafka, Slack, SAP, etc.)
│   ├── Database Icons (PostgreSQL, MySQL, Oracle, MongoDB, etc.)
│   ├── Endpoint Icons (JMS, HTTP, address, file, failover, etc.)
│   ├── Message Processing Icons (sequence, processors, stores)
│   ├── UI Form Icons (checkbox, radio, input, dropdown, toggle)
│   ├── Utility Icons (settings, start, error, success, warning, info)
│   └── All with dark/light variants
│
├── 📁 vs-code-resources/        (236 KB, 12 files)
│   ├── Theme letterpress graphics (light, dark, hcLight, hcDark)
│   ├── Code editor icons
│   ├── App icons (192px, 512px)
│   ├── Activity bar icons
│   └── Platform-specific variants (Linux, Windows, Server)
│
├── 📁 icons/                    (272 KB, 1 file)
│   └── codicon.svg (VSCode icon library for standard UI controls)
│
├── 📁 media/                    (144 KB, 5 files)
│   └── Platform server resources and app icons
│
├── 📁 theme-resources/          (empty - placeholder for future resources)
│
└── 📄 Documentation Files       (35 KB total)
    ├── INDEX.md (this file)
    ├── README.md (quick start guide)
    ├── ASSET_CATALOG.md (comprehensive descriptions)
    ├── DETAILED_INVENTORY.md (full categorization)
    └── ASSET_MANIFEST.txt (complete file listing)
```

---

## 📖 Documentation Guide

### Start Here
**→ README.md**
- Overview of asset bundle
- Quick navigation
- Key asset groups
- Usage examples

### Detailed Information
**→ ASSET_CATALOG.md**
- Complete asset descriptions
- Component mapping
- Implementation notes
- Theme support details
- Size variants

### Complete Reference
**→ DETAILED_INVENTORY.md**
- Exhaustive list of all assets
- Categorization
- Directory structure
- Asset file statistics
- Implementation details

### Raw File List
**→ ASSET_MANIFEST.txt**
- Complete path listing
- All 235 files
- Sorted by directory

---

## 🎯 Quick Access by Purpose

### Finding Extension UI Icons
**Folder:** `extension-icons/`

Includes:
- Integrator VS Code activity bar icon
- Preview command buttons
- WSO2 logo and branding

### Finding Integration Component Icons
**Folder:** `webview-assets/`

Categories:
- **BI Types**: `bi-automation.svg`, `bi-api.svg`, `bi-database.svg`
- **Cloud**: `bi-asb.svg`, `bi-rabbitmq.svg`, `bi-kafka.svg`
- **Databases**: `postgresql.svg`, `mysql.svg`, `mongodb.svg`
- **APIs**: `get-api.svg`, `post-api.svg`, `put-api.svg`
- **Endpoints**: `jms-endpoint.svg`, `http-endpoint.svg`
- **UI Forms**: `checkbox.svg`, `radio.svg`, `input.svg`
- **Status**: `error.svg`, `success.svg`, `warning.svg`

### Finding VS Code Resources
**Folder:** `vs-code-resources/`

Includes:
- Theme graphics (letterpress variants)
- App icons
- Code editor branding
- Platform-specific resources

### Finding Icon Libraries
**Folder:** `icons/`

Includes:
- VSCode codicon.svg library

---

## 📊 Asset Categories

### By Type
| Type | Count | Location |
|------|-------|----------|
| SVG Icons | ~220 | webview-assets/, extension-icons/, vs-code-resources/ |
| PNG/Raster | ~10 | media/, vs-code-resources/ |
| Icon Libraries | 1 | icons/ |
| **Total** | **235** | All folders |

### By Purpose
| Purpose | Count | Examples |
|---------|-------|----------|
| BI Components | 8 | Automation, HTTP, API, Database, etc. |
| Cloud Connectors | 15+ | Azure, RabbitMQ, Kafka, SAP, Slack |
| Databases | 9+ | PostgreSQL, MySQL, Oracle, MongoDB |
| API Methods | 5 | GET, POST, PUT, DELETE, PATCH |
| Endpoints | 9 | JMS, HTTP, Address, File, Failover, etc. |
| UI Forms | 6 | Checkbox, Radio, Input, Dropdown, Toggle |
| Status/Utility | 7+ | Error, Success, Warning, Info, Settings |
| Theme Resources | 12 | Letterpress variants, app icons |
| **Total** | **235+** | - |

---

## 🔗 Using These Assets

### 1. Direct File Reference
```
webview-assets/bi-automation.svg
extension-icons/integrator-activity-icon.svg
vs-code-resources/code-icon.svg
```

### 2. In React Components
```typescript
import BiAutomationIcon from 'assets/bi-automation.svg';

// Use in component
<img src={BiAutomationIcon} alt="Automation" />
```

### 3. Theme Switching
```typescript
// Dark mode
import { ReactComponent as Icon } from 'assets/dark-bi-automation.svg';

// Light mode
import { ReactComponent as Icon } from 'assets/bi-automation.svg';
```

### 4. CSS Background
```css
.automation {
  background-image: url('../assets/bi-automation.svg');
  background-size: contain;
}
```

---

## 📋 Asset Naming Conventions

### Dark/Light Variants
- `asset.svg` → Default (light) theme
- `asset-light.svg` → Explicit light variant
- `dark-asset.svg` → Dark theme variant

### Component Icons
- `bi-*.svg` → Ballerina Integration components
- `*-api.svg` → REST API methods/types
- `*-endpoint.svg` → Integration endpoints
- `*-processor.svg` → Message processors
- `*-store.svg` → Message stores

### Status Icons
- `error.svg` → Error state
- `success.svg` → Success state
- `warning.svg` → Warning state
- `info.svg` → Information state

---

## 🎨 Theme Support

### Variants Available
- **Light Theme**: Light background, dark text
- **Dark Theme**: Dark background, light text
- **High Contrast**: `hcLight.svg`, `hcDark.svg` variants
- **Accessibility**: Support for color-blind palettes

### CSS Variables
Assets use VSCode CSS variables for theming:
```css
--vscode-editor-background
--vscode-editor-foreground
--vscode-list-activeSelectionBackground
--vscode-list-hoverBackground
```

---

## 📈 Statistics

### File Count by Category
- Extension Icons: 5
- WebView SVG Assets: 211 (with variants)
- VS Code Resources: 12
- Codicons: 1
- Media Resources: 5
- **Total: 235**

### File Size Distribution
- SVG Assets: ~1.3 MB (scalable)
- PNG/Raster: ~0.5 MB (fixed size)
- **Total: 1.8 MB**

### Theme Variants
- ~106 light theme variants
- ~106 dark theme variants
- Multiple high-contrast variants

---

## ✅ Verification Checklist

After extracting/using this bundle, verify:

- [ ] All folders present (extension-icons, webview-assets, etc.)
- [ ] Documentation files readable (*.md, *.txt)
- [ ] SVG files viewable in image viewer
- [ ] PNG files not corrupted
- [ ] Total: 235+ files
- [ ] Total size: ~1.8 MB
- [ ] Asset manifest complete

---

## 🔍 Finding Specific Assets

### By Component Type
See **DETAILED_INVENTORY.md** for complete categorization

### By Naming Pattern
```bash
# Find all automation-related icons
find . -name "*automation*"

# Find all light theme variants
find . -name "*-light.svg"

# Find all API icons
find . -name "*api*"
```

### By File Size
```bash
# Find largest assets
du -sh webview-assets/* | sort -rh | head -20

# Find all PNG files
find . -name "*.png"
```

---

## 📝 Notes

- All SVG files are vector-based and scalable
- PNG files have fixed dimensions (see DETAILED_INVENTORY.md)
- Most assets include dark/light theme variants
- Assets are optimized for VS Code integration
- WSO2 branding consistent across all resources
- Recommended minimum VSCode version: 1.60+

---

## 🚀 Next Steps

1. **Review Documentation**
   - Start with README.md for overview
   - Check ASSET_CATALOG.md for detailed descriptions

2. **Explore Assets**
   - Browse organized folders
   - Use ASSET_MANIFEST.txt to find specific files

3. **Integrate into Your Project**
   - Reference assets by folder path
   - Use theme variants for dark/light modes
   - Follow naming conventions for consistency

4. **Additional Resources**
   - Check product-integrator source code for usage examples
   - Review React component imports for best practices
   - Reference VS Code documentation for icon guidelines

---

## 📞 Support

For questions about specific assets:
1. Check ASSET_CATALOG.md for descriptions
2. Review DETAILED_INVENTORY.md for categorization
3. Examine source code references in product-integrator
4. Check VSCode and Ballerina documentation

---

**Generated:** 2026-04-18  
**Source:** WSO2 Product-Integrator  
**Total Assets:** 235 files  
**Complete Index:** ✓
