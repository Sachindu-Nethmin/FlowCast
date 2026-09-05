# Workflow markdown grammar (what `src/parser.py` actually understands)

FlowCast does not use an LLM at record time — every instruction line is matched
against fixed regexes in `src/parser.py::_parse_instructions`. A line that
matches nothing is silently skipped during recording, so the wording below is
not a style preference, it is the API.

Always verify with `python tools/check_workflow.py workflows/<slug>.md` before
recording.

## File shape

```markdown
## Step 1: Create the integration

1. Open WSO2 Integrator.
2. Select **Create**.
```

* Headings must match `## Step <n>: <Title>` (`###` also works). The title
  becomes the GIF/clip name and the YouTube chapter name, so keep it short and
  verb-first ("Add an HTTP service", not "Adding the service to the project").
* One instruction per numbered line. Ordinary sentences, not pseudo-code.
* Filename: `workflows/<kebab-slug>.md`; the slug becomes the recordings folder.

## Line forms

| Intent | Write exactly this | Parses to |
|---|---|---|
| Launch the app | `Open WSO2 Integrator.` | `open_app` |
| Click | `Select **Create**.` | `click "Create"` |
| Click, scoped | `Select **HTTP Service** under **Integration as API**.` | `click` + `under:` hint |
| Click a `+` by a section | `Select **+** next to the **Query** section.` | `click "+"` + `next_to:` hint |
| Click after scrolling | `Scroll down and select **AI Chat Agent**.` | `scroll -15` + `click` |
| Two clicks in one line | `Select the project location and select **Open**.` | one `click` per `select **…**` |
| Click (add phrasing) | `Add a **Connection**.` / `Add the \`log\` action.` | `click` |
| Type into a field | `Set **Integration Name** to \`HelloWorldAPI\`.` | `type` |
| Type (bold value) | `Set **Target Type** to **json**.` | `type` |
| Type (example phrasing) | `Enter the Hostname (for example, \`localhost\`).` | `type` |
| Name a connection | `Name the connection \`externalApi\`.` | `type Connection Name` |
| Variable + type | `Store the result in a variable named \`response\` of type \`json\`.` | `type` + `select` |
| Search | `Search **Println**.` / `Search **Connectors** for \`sap\`.` / `Search for \`sap\`.` | `search` |
| Search then click | `Search \`printInfo\` and select **printInfo**.` | `search` + `click` |
| Keyboard | `Press **command+s**.` — or append `and save` to any line | `hotkey` |
| Command input (learned popup) | `Give the command \`curl example.com\`.` | `command` |
| Command input (ask every time) | `Ask me for the next command.` | `command` |
| Deliberately no action | `Keep Service Contract as Design From Scratch.` | skipped, kept in docs |

## Command input steps (learned popup)

`Give the command \`<cmd>\`.` and `Ask me for the next command.` mark a point
where the recorder pauses and lets you type a command that runs **outside** the
WSO2 window (a terminal, curl, a deploy script). The first run:

1. Brings Terminal to the front and shows a macOS notification (the "popup").
2. Prompts `command>` for what to type.
3. Types the command into Terminal on screen — so it is still recorded.
4. **Learns it** in `kb/commands.json` keyed by (workflow, step, action index).

Later runs **replay the learned command automatically** — no prompt, no input.
The backticked value in `Give the command \`X\`.` is the default used when you
press Enter with nothing typed. Use `Ask me for the next command.` when there is
no sensible default.

## Traps that silently drop a line

* **A word between `Select` and the bold target.** `Select the **Create** card.`
  matches nothing. Write `Select **Create**.` — put the extra words *after* the
  bold target: `Select **Create** to open the wizard.`
* **Values not in backticks.** `Set **Port** to 8080.` does not parse.
  Write `` `8080` ``.
* **`__bold__` instead of `**bold**`.**
* **Field labels are title-cased** when they are not in `_FIELD_ALIASES`
  (`src/parser.py`), so write the label exactly as the UI shows it and add an
  alias to that dict when the UI casing is unusual (e.g. `URL`, `SalesOrderType`).

## Timing helpers

* Append `in the toolbar` to the Run line — `Select **Run** in the toolbar.` —
  and FlowCast keeps recording 5s longer, then waits 5s, so the GIF shows the
  server actually starting.
* A step with a slow dialog is easier to re-shoot than to fix: re-record just
  that step with `--step N`.

## Converting a docs page

Docs pages carry things the parser must not see:

* Tab markers (`* Ballerina Code`), `NOTE`/admonition blocks, cloud-editor
  asides → drop them (keep the useful ones as `Keep …` or `Confirm …` lines,
  which stay in the docs output but generate no action).
* "Select your integration from the project overview canvas" → name it:
  `Select **HelloWorldAPI**.`
* Desktop-only reality: the cloud editor is already inside a project, the
  desktop app is not. After the project name, add the two lines every existing
  workflow in `workflows/` uses:

  ```markdown
  5. Select **Browse**.
  6. Select the project location and select **Open**.
  ```
