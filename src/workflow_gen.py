"""
workflow_gen.py — Generate a Docusaurus-style workflow .md from a simple prompt.

Uses LLM + WSO2 Integrator UI knowledge to produce step-by-step
documentation markdown that FlowCast can both:
  1. Publish as Docusaurus docs (frontmatter, imports, ThemedImage, Tabs)
  2. Execute to record GIFs and generate PyAutoGUI scripts

Usage:
    from src.workflow_gen import generate_workflow
    md_path = generate_workflow("create hello world automation")
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

WORKFLOWS_DIR = Path("workflows")

# ---------------------------------------------------------------------------
# WSO2 Integrator UI Knowledge
# Extracted from the product-integrator source (wi-webviews React components
# and VS Code extension package.json).
# ---------------------------------------------------------------------------

WSO2_UI_KNOWLEDGE = """\
## WSO2 Integrator UI Reference

### Welcome View (Home Screen)
- Badge: "Get Started"
- Title: "WSO2 Integrator"
- Three action cards:
  1. "Create New Project" → button label: **Create**
  2. "Explore Samples" → button label: **Explore**
  3. "Import External Integration" → button label: **Import**
- Bottom: "Already have a project?" with **Open** link
- Top-right: **Configure** button

### Create Your Integration View
- Back arrow button
- Heading: "Create Your Integration"
- Integration type selector: **WSO2: BI** or **WSO2: MI**

### BI Project Form Fields
1. **Integration Name** — placeholder: "Enter an integration name" (auto-focus, required)
2. **Package Name** — auto-filled from integration name
3. **Select Path** — with **Browse** button to open folder picker (required)
4. **Create Directory** checkbox — checked by default
5. Optional: "Create as workspace" checkbox, Workspace Name, Organization Name, Package Version
6. Submit button: **Create Integration** (or **Create Workspace** if workspace mode)

### Folder Picker (macOS native dialog)
- Navigate to desired folder
- Click **Open** to confirm

### Design View (after project creation)
- Sidebar: WSO2 Integrator → Integrations tree
  - Connections, Entry Points, Services, Functions, Automations, Types,
    Configurations, Data Mappers, Natural Functions, Custom Connectors
- **Add Artifact** button opens construct menu
- Constructs menu items: Automation, Service, Function, Connection, Type, etc.
- After selecting a construct → **Create** button

### Low-Code Editor (Automation/Service)
- Canvas with Start node and End/Error Handler nodes
- **+** button between nodes to add new nodes
- Node panel categories: Call Function, Logging, Variables, Control Flow, etc.
- After adding a node, a configuration panel opens
- Common buttons: **Save**, **Cancel**
- **Run** button in top-right toolbar to execute

### Common println Flow
- Click **+** after Start node
- Select **Call Function** → **println**
- Click **Initialize Array**
- Click **Fx** offset 200px right to click inside the value input field
- Type the value (e.g. '"Hello World"')
- Click **Save**
- Click **Run**

### VS Code Commands
- Open Welcome: wso2.integrator.openWelcome
- Refresh: wso2-integrator.explorer.refresh
- Add Connection, Add Entry Point, Add Function, Add Type, etc.

### App Details
- App name: "WSO2 Integrator"
- Default app path: "$HOME/Applications/WSO2 Integrator.app"
- Default workspace: "$HOME/wso2mi/workspace"
"""

# ---------------------------------------------------------------------------
# Docusaurus doc template (example for the LLM to follow)
# ---------------------------------------------------------------------------

_DOCUSAURUS_EXAMPLE = r'''
---
sidebar_position: 10
title: "Quick Start: Build an Automation"
description: Create a scheduled automation that runs tasks on a timer.
---

import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';
import ThemedImage from '@theme/ThemedImage';
import useBaseUrl from '@docusaurus/useBaseUrl';

# Quick start: Build an automation

app: WSO2 Integrator
app_path: $HOME/Applications/WSO2 Integrator.app
workspace_git: $HOME/wso2mi/workspace

**Time:** Under 10 minutes | **What you'll build:** A scheduled automation that runs tasks on a timer or manual trigger.

Automations are ideal for data synchronization, report generation, and routine maintenance jobs.

## Prerequisites

- [WSO2 Integrator installed](install.md)

## Architecture

<ThemedImage
  alt="Architecture Diagram"
  sources={{
    light: useBaseUrl('/img/get-started/quick-start-automation/automation-light.svg'),
    dark: useBaseUrl('/img/get-started/quick-start-automation/automation-dark.svg'),
  }}
/>

## Step 1: Create the project

1. Open WSO2 Integrator.
2. Select **Create New Integration**.
3. Enter the integration name (for example, `{project_name}`).
4. Select the project location.
5. Select **Create Integration**.

## Step 2: Add an automation artifact

1. In the design view, select **Add Artifact**.
2. Select **Automation** from the Constructs menu.
3. Click **Create** to create an automation. This directs you to the automation diagram view.
4. Click **+** after the **Start** node to open the node panel.

## Step 3: Add logic

1. Add a **Call Function** node to the flow.
2. Select **println**.
3. Click **Initialize Array**.
4. Click **Fx** offset 200px right to click inside the value input.
5. Enter '"Hello World"'.
6. Click **Save**.

## Step 4: Run and test

1. Select **Run** in the toolbar.
2. The automation executes immediately and prints output to the terminal.
3. Check the terminal output for `Hello World`.

## Scheduling automations

For production use, configure a cron schedule to trigger the automation periodically:

<Tabs>
<TabItem value="code" label="Source View" default>

```ballerina
import ballerina/task;

listener task:Listener timer = new ({
    intervalInMillis: 60000  // Run every 60 seconds
});

service on timer {
    remote function onTrigger() {
        // Your automation logic here
    }
}
```

</TabItem>
<TabItem value="ui" label="Design View">

<ThemedImage
  alt="Design View"
  sources={{
    light: useBaseUrl('/img/get-started/quick-start-automation/design-view-light.png'),
    dark: useBaseUrl('/img/get-started/quick-start-automation/design-view-dark.png'),
  }}
/>

</TabItem>
</Tabs>

## What's next

- [Quick start: Integration as API](quick-start-api.md) -- Build an HTTP service
- [Quick start: Event integration](quick-start-event.md) -- React to messages from brokers
- [Quick start: AI agent](quick-start-ai-agent.md) -- Build an intelligent agent
'''

# ---------------------------------------------------------------------------
# LLM system prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = f"""\
You are a WSO2 Integrator documentation author. Given a simple task description,
generate a complete Docusaurus-style documentation page.

The generated doc serves two purposes:
1. Published as professional Docusaurus documentation
2. Used by FlowCast to auto-record GIF demos and generate PyAutoGUI scripts

{WSO2_UI_KNOWLEDGE}

## Output Format

Return ONLY the markdown content. No code fences wrapping the whole output.
Generate docs in **Docusaurus MDX format** following this exact structure:

### Required sections:
1. **YAML frontmatter** (---) with sidebar_position, title, description
2. **Docusaurus imports**: Always import useBaseUrl. Add Tabs/TabItem/ThemedImage if used.
3. **H1 title** matching the frontmatter title
4. **Metadata lines** (app:, app_path:, workspace_git:) — these tell FlowCast which app to automate
5. **Intro paragraph** with Time estimate, What you'll build, and a short description
6. **Prerequisites** section
7. **Architecture** section (optional) with ThemedImage for light/dark diagrams
8. **Step sections** (## Step N: title) — each with numbered list instructions
9. **Extra content** (optional) — Tabs with code examples, configuration guides, etc.
10. **What's next** section with links to related docs

### Step instruction format (numbered lists):
Each step uses a numbered list. Each list item is one UI action:
- `1. Open WSO2 Integrator.` — launch app
- `2. Select **Create New Integration**.` — click button (bold = exact label)
- `3. Enter the integration name (for example, \`{{project_name}}\`).` — type value
- `4. Select the project location.` — browse/select
- `5. Select **Create Integration**.` — submit
- `Click **+** after the **Start** node to open the node panel.` — icon with context
- `Click **Fx** offset 200px right to click inside the value input.` — offset click
- `Enter '"Hello World"'.` — type into focused field

### Key rules:
- Do NOT include <img> GIF references in the steps — FlowCast auto-generates GIFs per step section
- Use **bold** for exact UI labels (button text, menu items, field names)
- Use backticks for values to type (e.g. \`MyProject\`, \`9090\`, \`/hello\`)
- Use numbered lists (1. 2. 3.) inside each step
- Keep each step focused on one logical task (3-6 actions)
- Use {{project_name}} as placeholder for the integration/project name
- Steps that aren't UI actions (like "Check the terminal output") are informational — FlowCast skips them

### Optional Docusaurus features (use when they add value):
- `<Tabs>` / `<TabItem>` for code vs UI alternatives
- `<ThemedImage>` for architecture diagrams with light/dark variants
- Code blocks (```ballerina, ```json, etc.) for source view examples

### Example output:
{_DOCUSAURUS_EXAMPLE}

### More rules:
- Use **exact** UI labels from the WSO2 UI Reference above
- The doc should be publishable as-is on a Docusaurus site
- Keep the tone professional but approachable
- Break complex workflows into logical steps (create project, add artifact, add logic, run)
"""


def _call_llm(prompt: str) -> str:
    """Route to the configured LLM provider."""
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()

    if provider == "groq":
        from groq import Groq

        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content.strip()

    elif provider == "ollama":
        import requests

        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3.1")
        payload = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        resp = requests.post(f"{host}/api/chat", json=payload, timeout=(30, 120))
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()

    else:  # gemini
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY not set in .env")
        client = genai.Client(api_key=api_key)
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
        response = client.models.generate_content(
            model=model,
            contents=[
                {"role": "user", "parts": [{"text": _SYSTEM_PROMPT + "\n\n" + prompt}]},
            ],
        )
        return response.text.strip()


def _title_to_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())
    return slug.strip("-")


def generate_workflow(prompt: str, output_dir: Path | None = None) -> Path:
    """
    Generate a Docusaurus-style workflow .md file from a simple prompt.

    Args:
        prompt: Simple task description, e.g. "create hello world automation"
        output_dir: Where to create the workflow folder. Defaults to workflows/

    Returns:
        Path to the generated .md file.
    """
    print(f"[workflow_gen] Generating workflow for: {prompt}")

    user_prompt = (
        f"Task: {prompt}\n\n"
        f"Generate a complete Docusaurus documentation page with step-by-step "
        f"instructions for this task in WSO2 Integrator. Include frontmatter, "
        f"imports, GIF references, and a What's Next section."
    )

    raw = _call_llm(user_prompt)

    # Strip markdown code fences if the LLM wrapped the whole thing
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    # Extract title from frontmatter or H1
    fm_title = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', raw, re.MULTILINE)
    h1_title = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
    title = (fm_title.group(1).strip() if fm_title
             else h1_title.group(1).strip() if h1_title
             else prompt)
    folder_slug = _title_to_slug(title)

    # Create output directory
    base = output_dir or WORKFLOWS_DIR
    workflow_dir = base / folder_slug
    workflow_dir.mkdir(parents=True, exist_ok=True)

    # Write the markdown file
    md_path = workflow_dir / f"{folder_slug}.md"
    md_path.write_text(raw)

    print(f"[workflow_gen] Workflow saved → {md_path}")
    print(f"[workflow_gen] Title: {title}")

    # Count steps and GIF refs
    step_count = len(re.findall(r"^##\s+Step\s+\d+", raw, re.MULTILINE))
    gif_count = len(re.findall(r"\.gif", raw, re.IGNORECASE))
    print(f"[workflow_gen] Steps: {step_count}  |  GIF refs: {gif_count}")

    return md_path
