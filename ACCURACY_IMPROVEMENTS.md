# Detection Accuracy Improvements

**Date:** 2026-07-12

## What changed

### 1. Apple Vision OCR (biggest win) — `src/ocr_engine.py`
EasyOCR is replaced as the primary OCR engine by macOS-native Apple Vision
(`VNRecognizeTextRequest`). Vision is far more accurate on small anti-aliased
UI text: correct casing, correct word grouping (labels like "Integration Name"
arrive as one block instead of merged/split fragments), and it's faster.
EasyOCR remains as automatic fallback.

- Select engine: `FLOWCAST_OCR=vision | easyocr | auto` (default `auto`)
- Results are **cached per screenshot**, so the multi-method detection chain
  sees one consistent OCR result set instead of re-running OCR 5–15× per action.
- New dependency: `pyobjc-framework-Vision` → run `uv sync`

### 2. DOM-based detection via CDP (exact coordinates) — `src/dom_detector.py`
WSO2 Integrator is VS Code-based. Launch it with remote debugging and FlowCast
reads element/field positions directly from the webview DOM — no OCR guessing:

```bash
open -a "WSO2 Integrator" --args --remote-debugging-port=9222
export FLOWCAST_CDP_PORT=9222
uv sync --extra dom          # installs requests + websocket-client
```

`find_element` / `find_input_field` try the DOM first and fall back to
OCR/template detection on any failure. Spatial hints (`under:`, `right_of:`,
`next_to:`) and short symbols like `+` keep the OCR path.

### 3. More robust input-box detection — `src/detector.py`
- New `_detect_input_boxes()`: dilated-edge contour detection closes the 1–3px
  gaps that anti-aliased rounded borders leave in the Canny edge map — the main
  reason input fields were missed (especially dark mode). Includes same-row
  fragment merging and containment dedupe.
- Used by `_find_input_by_placeholder`, `_find_input_by_visual` (union with the
  legacy contour pass), and `_is_inside_input` now dilates its edge map.

## Benchmarking

Validate against the saved failure screenshots (`output/heal_debug`,
`output/debug_detection`):

```bash
uv run python tools/benchmark_detection.py            # EasyOCR vs Vision
uv run python tools/benchmark_detection.py --engine vision --limit 10
```

Prints found/miss + timing per engine and writes annotated hit images to
`output/benchmark/<engine>/` for visual verification.

## Perceive-first execution (2026-07-12, second pass)

### 4. Screen-state awareness — `src/navigator.py` (new)
FlowCast no longer blindly replays instructions:

- **Before each step** it reports what buttons/fields/labels are actually
  visible (`describe_screen`) — logged as `[perceive]` lines.
- **Auto-resume:** on start (without `--step`/`--from-step`), it detects which
  workflow step the WSO2 Integrator is currently at and resumes from there.
  Disable with `FLOWCAST_NO_RESUME=1` or force full run with `--from-step 1`.
- **Skip already-done actions:** a `type` action whose value is already inside
  its input box is skipped; a `click` whose target is gone but whose NEXT
  action's target is visible is treated as already performed.

### 5. Fullscreen enforcement — `runner.ensure_fullscreen()`
The WSO2 Integrator window is maximized to the full screen before any change:
at run start, at each step start, and inside `runner.resolve()` (30s-memoized,
no-op when already maximized). Generated `full_script.py` files call it too.

### 6. Recording only captures changes (already present, confirmed)
Recording starts exactly at cursor move (pre-move callback), `wait` actions
are never recorded, and `recorder.trim()` (ffmpeg mpdecimate) drops static
frames — so mouse movement, typing, clicking, and loading are kept while idle
time is removed.

## Learn-while-running with interactive fallback (2026-07-12, third pass)

### 7. No separate teach mode — automatic terminal fallback (`src/interactive.py`)
Normal runs are unguided. Only when an action FAILS (element not found, UI
didn't change after a click, typed text ended up blue-selected) does the run
pause and wait on the terminal:

```
NEED GUIDANCE: could not click 'Create Integration' automatically
what next> click create button
   ✓ learned. Another command, or press Enter to continue the workflow.
```

Natural language: `click create button`, `enter myfile in the file name
field`, `select GET from method`, `press cmd+s`, `at 512,300`, `where`,
`undo`, `ok` (already done), `skip`, `abort` — type `help` for all.
Recovery actions are screen-recorded too, so the step's GIF stays complete;
failed attempts' clips are discarded. Disabled when stdin is not a terminal
or with `FLOWCAST_NO_PROMPT=1` (then behaves like the old abort/skip).

### 8. Learned KB — `src/kb_learn.py` → `kb/learned_actions.json`
EVERY action (automatic or user-guided) is recorded as screen-fingerprint →
target → relative position with win/fail counts. User-guided fixes are stored
under BOTH the user's phrasing and the original workflow target, so the next
run resolves the original instruction unguided. `runner._find` consults this
KB first (OCR-verified near the learned point); fail-dominant entries are
never reused.

### 9. Error signals (checked on every action)
- **UI did not change after a click** → the click hit a label / wrong place;
  recorded as a failure, clip discarded, terminal asked for the correct way.
- **Typed text is blue-highlighted** (`detector.is_text_selected_blue`, light
  + dark themes) → the value was entered without the right field focused;
  auto-undo (cmd+z), failure recorded, terminal asked.

## Files touched
- `src/ocr_engine.py` (new), `src/dom_detector.py` (new)
- `src/detector.py` — shared cached OCR, morphological input boxes, DOM hooks
- `src/runner.py`, `src/healer.py` — use shared OCR entry point
- `pyproject.toml` — `pyobjc-framework-Vision`, optional `dom` extra
- `tools/benchmark_detection.py` (new)
