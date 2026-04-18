# Product-Integrator Visual Assets Catalog

## Summary
- **Total Assets**: 235
- **Extension Icons**: 5
- **WebView Assets**: 211 (SVG icons for integration components)
- **VS Code Resources**: 12 (theme icons and resources)
- **Codicons**: 1 (VSCode icon set)
- **Media Files**: 5 (PNG/JPG resources)

---

## Asset Categories

### 1. Extension Icons (5 files)
Location: `wi/wi-extension/resources/icons/`

Used for:
- VS Code activity bar icon
- Preview command buttons
- WSO2 branding
- Dark/light theme variants

Key files:
- `integrator-activity-icon.svg` - Main activity bar icon
- `integrator-activity-icon-dark.svg` - Dark theme variant
- `preview-command-icon.svg` - Preview feature button
- `preview-command-icon-dark.svg` - Preview dark variant
- `wso2-integrator-logo.png` - WSO2 logo

---

### 2. WebView Assets (211 files)
Location: `wi/wi-extension/assets/`

Used for:
- Integration artifact type icons
- Service icons (HTTP, API, etc.)
- Database connection icons
- Endpoint type indicators
- Data source icons
- Processing node icons
- Configuration element icons

**Asset Categories:**

#### Ballerina Integration (BI) Types
- `bi-api.svg`, `bi-automation.svg`, `bi-database.svg`
- `bi-data-service.svg`, `bi-function.svg`
- `bi-config.svg`, `bi-type.svg`
- Cloud connectors: `bi-asb.svg`, `bi-rabbitmq.svg`, `bi-postgresql.svg`
- AI agent: `bi-ai-agent.svg`

#### API & HTTP
- `put-api.svg`, `post-api.svg`, `get-api.svg`, `delete-api.svg`, `patch-api.svg`
- `http-service.svg`, `http-client.svg`

#### Databases
- `database.svg`, `bi-db.svg`
- Database-specific: `postgresql.svg`, `mysql.svg`, `oracle.svg`

#### Endpoints
- `address-endpoint.svg`, `address-endpoint-template.svg`
- `file-endpoint.svg`, `failover-endpoint.svg`
- `load-balance-endpoint.svg`, `http-endpoint.svg`
- `jms-endpoint.svg`, `cxf-ws-rm-endpoint.svg`

#### Message Processing
- `sequence.svg`, `sequence-template.svg`
- `custom-message-processor.svg`, `message-sampling-processor.svg`
- `message-store.svg`, `jms-message-store.svg`

#### Storage & Registry
- `registry.svg`, `local-entry.svg`
- `custom-message-store.svg`

#### UI Components
- `checkbox.svg`, `radio.svg`, `input.svg`, `dropdown.svg`
- `start.svg`, `settings.svg`, `tasklist.svg`

#### Theme Variants
- Dark theme: `dark-*.svg`
- Light theme: `light-*.svg`

---

### 3. VS Code Resources (12 files)
Location: `resources/vscode/`

Includes:
- Code editor icons
- Integrator activity icons
- Letterpress theme variants
- Code branding assets

Files:
- `code-icon.svg` - Main code editor icon
- `integrator-activity-icon-dark.svg` - Activity indicator
- `letterpress-*.svg` - Theme letterpress graphics (light, dark, hcLight, hcDark)
- `wso2.png` - WSO2 branding

---

### 4. Codicons (1 file)
Location: `wi/wi-extension/resources/codicons/`

- `codicon.svg` - VSCode official icon set (used for standard UI icons)

---

### 5. Server Resources (5 files)
Location: `resources/vscode/resources/`

- `code-192.png` - App icon (192x192)
- `code-512.png` - App icon (512x512)
- Linux, Windows variants
- Platform-specific icons

---

## Component Mapping

### Integration Types
| Icon | Purpose | File |
|------|---------|------|
| Automation | Automation artifact | `bi-automation.svg` |
| HTTP Service | REST API service | `http-service.svg` |
| API | API artifact | `api-*.svg` |
| Database | Database integration | `database.svg` |
| Data Service | Data service | `bi-data-service.svg` |

### Cloud Connectors
| Icon | Purpose | File |
|------|---------|------|
| Azure Service Bus | Azure integration | `bi-asb.svg` |
| RabbitMQ | Message queue | `bi-rabbitmq.svg` |
| PostgreSQL | PostgreSQL DB | `bi-postgresql.svg` |

### Endpoints
| Icon | Purpose | File |
|------|---------|------|
| HTTP Endpoint | HTTP service | `http-endpoint.svg` |
| JMS Endpoint | Message queue | `jms-endpoint.svg` |
| File Endpoint | File I/O | `file-endpoint.svg` |
| Address Endpoint | Named endpoint | `address-endpoint.svg` |

---

## Usage in Source Code

### Visual Elements Referenced in TypeScript/TSX

Located in: `wi/wi-webviews/src/`

**Artifact Type Icons:**
- Automation artifact picker
- HTTP Service card
- API card
- Database connector

**UI Component Icons:**
- Collapsible section indicators (chevron icons)
- Form field icons
- Button icons (+ Add, Settings, Back)
- Theme toggle icons

**Custom Styled Components:**
- Gradient buttons
- Card layouts
- Section headers
- Status indicators

---

## Implementation Notes

### Asset Loading
- SVGs are imported directly in React components
- Icons use CSS variables for theming
- Dark/light mode variants available

### Theme Support
- Dark theme: `dark-*.svg`
- Light theme: `light-*.svg`
- High contrast: `hc*.svg` variants

### Size Variants
- Icons: Scalable (SVG)
- App icons: 192px, 512px (PNG)
- Embedded base64 in some components

---

## Files Generated
- `ASSET_MANIFEST.txt` - Complete file listing
- `ASSET_CATALOG.md` - This document
- Organized folders with all assets organized by category

