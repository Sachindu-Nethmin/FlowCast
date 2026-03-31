from pathlib import Path
import os

SOURCE_DIR = Path("/Users/sachindu/Desktop/Repos/wso2/FlowCast/product-integrator/wi/wi-webviews/src")

def is_clickable(label: str) -> bool:
    """Read through the local React source code to classify if a label is intended to be clicked.
    
    Returns True if the label is wrapped in a clickable component like <Button>, <Card>, or <Link>.
    Returns False if the label is strictly an input label (like <TextField label="...">).
    Returns True (fallback) if the label is not found or ambiguous, to prevent false negatives.
    """
    if not SOURCE_DIR.exists() or not label:
        return True

<<<<<<< HEAD
<<<<<<< HEAD
=======
>>>>>>> ce266e7 (API test working)
    # Bypass verification for elements handled via icon detection (not React text nodes)
    import json
    _kb_path = Path(__file__).parent.parent / "kb" / "ui_elements.json"
    if _kb_path.exists():
        _hints = json.loads(_kb_path.read_text()).get("element_hints", {})
        _entry = _hints.get(label, {})
        if isinstance(_entry, dict) and _entry.get("type") in ("checkbox_icon", "ocr_text_offset"):
            return True

<<<<<<< HEAD
=======
>>>>>>> 9e44480 (Light (#6))
=======
>>>>>>> ce266e7 (API test working)
    contexts = []
    # Search all .tsx / .jsx files
    for root, _, files in os.walk(SOURCE_DIR):
        for f in files:
            if f.endswith(('.tsx', '.jsx')):
                path = Path(root) / f
                try:
                    lines = path.read_text(encoding='utf-8').splitlines()
                except UnicodeDecodeError:
                    continue
                
                for i, line in enumerate(lines):
                    if label.lower() in line.lower():
                        # Capture a small context window to analyze the component type
                        start = max(0, i - 2)
                        end = min(len(lines), i + 3)
                        ctx = " ".join(lines[start:end]).lower()
                        contexts.append(ctx)

    if not contexts:
        print(f"[verifier] Label '{label}' not found in React source code. Falling back to default click behavior.")
        return True

    # 1. Strong Positive Indicators
    for ctx in contexts:
        if any(keyword in ctx for keyword in ["button", "card", "onclick", "link", "<a ", "option", "tab", "menu"]):
            return True

    # 2. Strong Negative Indicators (exclusively found within input fields)
    for ctx in contexts:
        if "textfield" in ctx or "textarea" in ctx or "typography" in ctx or "description" in ctx:
            return False

    # 3. Default Fallback
    return True
