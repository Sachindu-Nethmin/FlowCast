# Detailed Product-Integrator Visual Assets Inventory

## Asset Breakdown by Type

### Extension Icons (5 assets)
```
wi/wi-extension/resources/icons/
├── integrator-activity-icon.svg
├── integrator-activity-icon-dark.svg
├── preview-command-icon.svg
├── preview-command-icon-dark.svg
└── wso2-integrator-logo.png
```

### WebView SVG Assets (211 assets)

#### Ballerina Integration (BI) Components
- `bi-api.svg`, `bi-api-light.svg`
- `bi-asb.svg`, `bi-asb-light.svg`
- `bi-automation.svg`, `bi-automation-light.svg`
- `bi-config.svg`, `bi-config-light.svg`
- `bi-database.svg`, `bi-database-light.svg`
- `bi-data-service.svg`, `bi-data-service-light.svg`
- `bi-db.svg`, `bi-db-light.svg`
- `bi-function.svg`, `bi-function-light.svg`
- `bi-type.svg`, `bi-type-light.svg`
- `bi-ai-agent.svg`, `bi-ai-agent-light.svg`
- `bi-docker.svg`, `bi-docker-light.svg`
- `bi-github.svg`, `bi-github-light.svg`
- `bi-kubernetes.svg`, `bi-kubernetes-light.svg`
- `bi-kafka.svg`, `bi-kafka-light.svg`
- `bi-mongodb.svg`, `bi-mongodb-light.svg`
- `bi-mysql.svg`, `bi-mysql-light.svg`
- `bi-postgres.svg`, `bi-postgres-light.svg`
- `bi-rabbitmq.svg`, `bi-rabbitmq-light.svg`
- `bi-redis.svg`, `bi-redis-light.svg`
- `bi-s3.svg`, `bi-s3-light.svg`
- `bi-slack.svg`, `bi-slack-light.svg`
- `bi-salesforce.svg`, `bi-salesforce-light.svg`
- `bi-sap.svg`, `bi-sap-light.svg`
- `bi-swagger.svg`, `bi-swagger-light.svg`

#### HTTP/API Components
- `get-api.svg`, `get-api-light.svg`
- `post-api.svg`, `post-api-light.svg`
- `put-api.svg`, `put-api-light.svg`
- `delete-api.svg`, `delete-api-light.svg`
- `patch-api.svg`, `patch-api-light.svg`
- `http-service.svg`, `http-service-light.svg`
- `http-client.svg`, `http-client-light.svg`
- `http-endpoint.svg`, `http-endpoint-light.svg`

#### Database & Data Components
- `database.svg`, `database-light.svg`
- `postgresql.svg`, `postgresql-light.svg`
- `mysql.svg`, `mysql-light.svg`
- `oracle.svg`, `oracle-light.svg`
- `mssql.svg`, `mssql-light.svg`
- `mongodb.svg`, `mongodb-light.svg`
- `elasticsearch.svg`, `elasticsearch-light.svg`
- `cassandra.svg`, `cassandra-light.svg`
- `dynamodb.svg`, `dynamodb-light.svg`

#### Endpoint Components
- `address-endpoint.svg`, `address-endpoint-light.svg`
- `address-endpoint-template.svg`, `address-endpoint-template-light.svg`
- `file-endpoint.svg`, `file-endpoint-light.svg`
- `failover-endpoint.svg`, `failover-endpoint-light.svg`
- `load-balance-endpoint.svg`, `load-balance-endpoint-light.svg`
- `jms-endpoint.svg`, `jms-endpoint-light.svg`
- `cxf-ws-rm-endpoint.svg`, `cxf-ws-rm-endpoint-light.svg`
- `jms-transport-sender.svg`, `jms-transport-sender-light.svg`
- `message-broker-endpoint.svg`, `message-broker-endpoint-light.svg`

#### Message Processing & Routing
- `sequence.svg`, `sequence-light.svg`
- `sequence-template.svg`, `sequence-template-light.svg`
- `custom-message-processor.svg`, `custom-message-processor-light.svg`
- `message-sampling-processor.svg`, `message-sampling-processor-light.svg`
- `message-store.svg`, `message-store-light.svg`
- `jms-message-store.svg`, `jms-message-store-light.svg`
- `rabbitmq-message-store.svg`, `rabbitmq-message-store-light.svg`
- `jdbc-message-store.svg`, `jdbc-message-store-light.svg`
- `custom-message-store.svg`, `custom-message-store-light.svg`

#### Registry & Storage
- `registry.svg`, `registry-light.svg`
- `local-entry.svg`, `local-entry-light.svg`
- `configuration.svg`, `configuration-light.svg`
- `policy.svg`, `policy-light.svg`

#### UI Form Components
- `checkbox.svg`, `checkbox-light.svg`
- `radio.svg`, `radio-light.svg`
- `input.svg`, `input-light.svg`
- `dropdown.svg`, `dropdown-light.svg`
- `toggle.svg`, `toggle-light.svg`
- `textarea.svg`, `textarea-light.svg`

#### Utility & Status Icons
- `start.svg`, `start-light.svg`
- `settings.svg`, `settings-light.svg`
- `tasklist.svg`, `tasklist-light.svg`
- `error.svg`, `error-light.svg`
- `success.svg`, `success-light.svg`
- `warning.svg`, `warning-light.svg`
- `info.svg`, `info-light.svg`

### VS Code Theme Resources (12 assets)
```
resources/vscode/src/vs/workbench/browser/parts/editor/media/
├── letterpress-light.svg
├── letterpress-dark.svg
├── letterpress-hcLight.svg
├── letterpress-hcDark.svg
├── integrator-activity-icon-dark.svg
└── wso2.png

resources/vscode/src/vs/workbench/browser/media/
└── code-icon.svg

resources/vscode/resources/
├── server/
│   ├── code-192.png
│   ├── code-512.png
│   └── icon files
├── linux/
│   └── code.png
└── win32/
    ├── code_70x70.png
    └── code_150x150.png
```

### Codicons
```
wi/wi-extension/resources/codicons/
└── codicon.svg (VSCode icon library - used for standard UI controls)
```

---

## Usage Mapping

### Components Using These Assets

#### Creation View Components
- `ProjectCreationView.tsx` - Uses BI type icons, form field icons
- `LibraryCreationView.tsx` - Uses library, form field icons
- `ProjectFormFields.tsx` - Uses form component icons
- `AdvancedConfigurationSection.tsx` - Uses organization, package, version icons

#### Artifact Picker
- `Automation` artifact card - `bi-automation.svg`
- `HTTP Service` card - `http-service.svg`
- `API` card - `api-*.svg`
- `Database` card - `database.svg`

#### Import Wizard
- `WizardAIEnhancementView.tsx` - Uses status and processing icons
- Platform selection cards - Provider logos
- Migration progress - Status indicators

#### Sample Browser
- `SamplesContainer.tsx` - Uses artifact type icons
- Sample cards - Technology icons (cloud, databases, messaging)

#### Component Design View
- Flow canvas - Endpoint, sequence, processor icons
- Node palette - All BI component icons
- Connection picker - Database and connector icons

---

## Asset File Statistics

| Category | Count | Format | Purpose |
|----------|-------|--------|---------|
| Extension Icons | 5 | SVG, PNG | VS Code UI |
| WebView SVG Assets | 211 | SVG | Component visualization |
| VS Code Resources | 12 | SVG, PNG | Theme & resources |
| Codicons | 1 | SVG | Standard UI icons |
| **Total** | **235** | Mixed | Complete visual system |

---

## Implementation Details

### Dark/Light Theme Support
Most assets have variants:
- `asset.svg` - Default (light) theme
- `asset-light.svg` - Explicit light variant
- `dark-asset.svg` - Dark theme variant
- `light-asset.svg` - Light theme variant

### Asset Integration Points
1. **Extension manifest** (`package.json`) - References icons
2. **React components** - Import SVGs directly
3. **Styled components** - Reference icons in CSS
4. **Theme context** - Switches between dark/light variants

### Performance Optimization
- SVG assets inline for small icons
- Base64 encoding for some frequently used icons
- CSS variable references for theming
- Lazy loading for large asset sets

---

## Directory Structure

```
product-integrator/
├── wi/
│   ├── wi-extension/
│   │   ├── resources/icons/ (5 files)
│   │   ├── resources/codicons/ (1 file)
│   │   └── assets/ (211 SVG files)
│   └── wi-webviews/
│       └── src/ (component references)
└── resources/
    └── vscode/ (12 files)
```

