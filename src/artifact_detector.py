"""Unified artifact detector for quick-start-automation workflow.

Detects and interacts with all artifacts (fields, buttons, nodes) in the workflow
using configuration-based detection strategies.
"""

import json
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import cv2
import numpy as np
from PIL import Image
import pyautogui

# Import existing detector functions
from detector import (
    _ocr, _fuzzy, _similarity_score, _find_ocr, _find_template,
    _find_green_play_button, find_input_field, identify_screen,
    _is_light_mode, _merge_ocr_results
)


class ArtifactDetector:
    """Unified detector for all workflow artifacts using KB configuration."""

    def __init__(self, kb_path: str = "kb/quick_start_automation_artifacts.json"):
        """Initialize with artifact configuration."""
        self.kb_path = Path(kb_path)
        self.config = self._load_config()
        self.steps = self.config.get("steps", {})
        self.strategies = self.config.get("detection_strategies", {})

    def _load_config(self) -> dict:
        """Load artifact configuration from KB."""
        if not self.kb_path.exists():
            raise FileNotFoundError(f"Config not found: {self.kb_path}")
        with open(self.kb_path) as f:
            return json.load(f)

    def list_artifacts(self, step_id: str) -> List[str]:
        """List all detectable artifacts in a step."""
        step = self.steps.get(step_id)
        if not step:
            return []
        return list(step.get("artifacts", {}).keys())

    def get_artifact_config(self, step_id: str, artifact_id: str) -> Optional[Dict]:
        """Get configuration for a specific artifact."""
        step = self.steps.get(step_id)
        if not step:
            return None
        return step.get("artifacts", {}).get(artifact_id)

    def detect_artifact(
        self,
        screenshot: Image.Image,
        step_id: str,
        artifact_id: str
    ) -> Optional[Dict]:
        """Detect a specific artifact and return its location and properties.

        Returns:
            Dict with keys:
            - x, y: Center coordinates of the artifact
            - type: artifact type (button, field, etc.)
            - method: detection method used
            - confidence: detection confidence (0.0-1.0)
            - label: artifact label
        """
        config = self.get_artifact_config(step_id, artifact_id)
        if not config:
            return None

        artifact_type = config.get("type")
        detection_methods = config.get("detection_methods", [])
        label = config.get("label")

        # Try each detection method in priority order
        for method_config in detection_methods:
            result = self._detect_by_method(screenshot, method_config, label, artifact_type)
            if result:
                return result

        return None

    def _detect_by_method(
        self,
        screenshot: Image.Image,
        method_config: Dict,
        label: Optional[str] = None,
        artifact_type: Optional[str] = None
    ) -> Optional[Dict]:
        """Detect artifact using a specific method."""
        method = method_config.get("method")

        if method == "label_offset":
            return self._detect_label_offset(screenshot, method_config, label)
        elif method == "placeholder":
            return self._detect_placeholder(screenshot, method_config, label)
        elif method == "visual_pattern":
            return self._detect_visual_pattern(screenshot, method_config)
        elif method == "ocr_label":
            return self._detect_ocr_label(screenshot, method_config)
        elif method == "template":
            return self._detect_template(screenshot, method_config)
        elif method == "blue_button":
            return self._detect_blue_button(screenshot, method_config)
        elif method == "green_play_button":
            return self._detect_green_play_button_method(screenshot, method_config)
        elif method == "plus_after_node":
            return self._detect_plus_after_node(screenshot, method_config)
        elif method == "card_with_icon":
            return self._detect_card_with_icon(screenshot, method_config)
        elif method == "card_with_label":
            return self._detect_card_with_label(screenshot, method_config)
        elif method == "ocr_text":
            return self._detect_ocr_text(screenshot, method_config)
        elif method == "region_scan":
            return self._detect_region_scan(screenshot, method_config)

        return None

    def _detect_label_offset(
        self,
        screenshot: Image.Image,
        config: Dict,
        label: str
    ) -> Optional[Dict]:
        """Detect field by label and pixel offset."""
        label_text = config.get("label_text", label)
        if not label_text:
            return None

        # Find the label using OCR
        reader = _ocr()
        arr = np.array(screenshot)
        results = reader.readtext(arr, detail=1)

        for bbox, text, conf in results:
            if _fuzzy(text, label_text) and conf >= config.get("confidence_threshold", 0.75):
                # Get label center
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                label_cx = sum(xs) / len(xs)
                label_cy = sum(ys) / len(ys)

                # Apply offset
                offset_y = self.strategies.get("label_offset", {}).get("offset_y", 30)
                offset_x = self.strategies.get("label_offset", {}).get("offset_x", 0)

                return {
                    "x": int(label_cx + offset_x),
                    "y": int(label_cy + offset_y),
                    "method": "label_offset",
                    "confidence": float(conf),
                    "label": label_text
                }

        return None

    def _detect_placeholder(
        self,
        screenshot: Image.Image,
        config: Dict,
        label: str
    ) -> Optional[Dict]:
        """Detect field by placeholder text."""
        placeholder = config.get("placeholder_text")
        if not placeholder:
            return None

        reader = _ocr()
        arr = np.array(screenshot)
        results = reader.readtext(arr, detail=1)

        for bbox, text, conf in results:
            if _fuzzy(text, placeholder) and conf >= config.get("confidence_threshold", 0.70):
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                return {
                    "x": int(sum(xs) / len(xs)),
                    "y": int(sum(ys) / len(ys)),
                    "method": "placeholder",
                    "confidence": float(conf),
                    "label": placeholder
                }

        return None

    def _detect_visual_pattern(
        self,
        screenshot: Image.Image,
        config: Dict
    ) -> Optional[Dict]:
        """Detect elements by HSV color range."""
        hsv_range = config.get("hsv_range")
        if not hsv_range:
            return None

        arr = np.array(screenshot)
        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)

        h_range = hsv_range.get("h", [0, 255])
        s_range = hsv_range.get("s", [0, 255])
        v_range = hsv_range.get("v", [0, 255])

        mask = cv2.inRange(
            hsv,
            np.array([h_range[0], s_range[0], v_range[0]]),
            np.array([h_range[1], s_range[1], v_range[1]])
        )

        # Find contours
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None

        # Get largest contour
        largest = max(contours, key=cv2.contourArea)
        M = cv2.moments(largest)

        if M["m00"] == 0:
            return None

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])

        return {
            "x": cx,
            "y": cy,
            "method": "visual_pattern",
            "confidence": 0.70,
            "label": config.get("description", "visual_pattern")
        }

    def _detect_ocr_label(
        self,
        screenshot: Image.Image,
        config: Dict
    ) -> Optional[Dict]:
        """Detect element by OCR text."""
        text = config.get("text")
        if not text:
            return None

        reader = _ocr()
        arr = np.array(screenshot)
        results = reader.readtext(arr, detail=1)

        best_match = None
        best_score = 0

        # Get position constraints
        min_y = config.get("position_constraint", {}).get("min_y") if isinstance(config.get("position_constraint"), dict) else config.get("min_y")
        max_y = config.get("position_constraint", {}).get("max_y") if isinstance(config.get("position_constraint"), dict) else config.get("max_y")

        for bbox, detected_text, conf in results:
            if _fuzzy(detected_text, text):
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                cy = int(sum(ys) / len(ys))

                # Check position constraints
                if min_y and cy < min_y:
                    continue
                if max_y and cy > max_y:
                    continue

                score = _similarity_score(detected_text, text) * conf
                if score > best_score:
                    best_score = score
                    best_match = {
                        "x": int(sum(xs) / len(xs)),
                        "y": cy,
                        "method": "ocr_label",
                        "confidence": float(conf),
                        "label": text
                    }

        if best_score >= config.get("confidence_threshold", 0.80):
            return best_match

        return None

    def _detect_template(
        self,
        screenshot: Image.Image,
        config: Dict
    ) -> Optional[Dict]:
        """Detect element by template matching."""
        template_asset = config.get("template_asset")
        threshold = config.get("threshold", 0.60)

        if not template_asset:
            return None

        # Use existing _find_template if available
        try:
            result = _find_template(screenshot, template_asset)
            if result:
                return {
                    "x": result[0],
                    "y": result[1],
                    "method": "template",
                    "confidence": threshold,
                    "label": template_asset
                }
        except Exception as e:
            print(f"[artifact_detector] Template matching failed: {e}")

        return None

    def _detect_blue_button(
        self,
        screenshot: Image.Image,
        config: Dict
    ) -> Optional[Dict]:
        """Detect blue buttons by color."""
        hsv_range = self.strategies.get("blue_button", {}).get("hsv_range", {})
        if not hsv_range:
            return None

        arr = np.array(screenshot)
        height, width = arr.shape[:2]

        # Support search region filtering
        search_region = config.get("search_region")
        if search_region == "bottom_half":
            arr = arr[height // 2:, :]
            height_offset = height // 2
        else:
            height_offset = 0

        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)

        h_range = hsv_range.get("h", [100, 135])
        s_range = hsv_range.get("s", [60, 255])
        v_range = hsv_range.get("v", [60, 255])

        mask = cv2.inRange(
            hsv,
            np.array([h_range[0], s_range[0], v_range[0]]),
            np.array([h_range[1], s_range[1], v_range[1]])
        )

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        # Filter by area (buttons have reasonable size)
        valid_contours = [c for c in contours if cv2.contourArea(c) > 500]
        if not valid_contours:
            return None

        largest = max(valid_contours, key=cv2.contourArea)
        M = cv2.moments(largest)

        if M["m00"] == 0:
            return None

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"]) + height_offset

        # Check position constraint if specified
        min_y = config.get("min_y")
        if min_y and cy < min_y:
            return None

        return {
            "x": cx,
            "y": cy,
            "method": "blue_button",
            "confidence": config.get("confidence_threshold", 0.75),
            "label": "blue_button"
        }

    def _detect_green_play_button_method(
        self,
        screenshot: Image.Image,
        config: Dict
    ) -> Optional[Dict]:
        """Detect green play button."""
        try:
            result = _find_green_play_button(screenshot)
            if result:
                return {
                    "x": result[0],
                    "y": result[1],
                    "method": "green_play_button",
                    "confidence": 0.85,
                    "label": "play_button"
                }
        except Exception as e:
            print(f"[artifact_detector] Green play button detection failed: {e}")

        return None

    def _detect_plus_after_node(
        self,
        screenshot: Image.Image,
        config: Dict
    ) -> Optional[Dict]:
        """Detect + button after anchor node."""
        anchor_text = config.get("anchor_text", "Start")

        # Find anchor node by OCR
        reader = _ocr()
        arr = np.array(screenshot)
        results = reader.readtext(arr, detail=1)

        anchor_pos = None
        for bbox, text, conf in results:
            if _fuzzy(text, anchor_text):
                xs = [p[0] for p in bbox]
                anchor_pos = (sum(xs) / len(xs), max(p[1] for p in bbox))
                break

        if not anchor_pos:
            return None

        # Search for + button to the right and below
        offset = config.get("offset", [50, 0])
        search_x = anchor_pos[0] + offset[0]
        search_y = anchor_pos[1] + offset[1]

        # Look for + symbol
        for bbox, text, conf in results:
            if text == "+" and conf >= 0.7:
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)

                # Check if near expected position
                dist = ((cx - search_x) ** 2 + (cy - search_y) ** 2) ** 0.5
                if dist < 150:  # Within reasonable distance
                    return {
                        "x": int(cx),
                        "y": int(cy),
                        "method": "plus_after_node",
                        "confidence": float(conf),
                        "label": "+"
                    }

        return None

    def _detect_card_with_icon(
        self,
        screenshot: Image.Image,
        config: Dict
    ) -> Optional[Dict]:
        """Detect artifact card by icon and label (theme-aware)."""
        label_text = config.get("label_text")
        threshold = config.get("threshold", 0.60)

        # Support both single icon_asset and icon_patterns (multiple theme variants)
        icon_asset = config.get("icon_asset")
        icon_patterns = config.get("icon_patterns", [])

        if not label_text:
            return None

        # Build list of icon assets to try
        icon_assets_to_try = []
        if icon_patterns:
            icon_assets_to_try.extend(icon_patterns)
        if icon_asset:
            icon_assets_to_try.append(icon_asset)

        if not icon_assets_to_try:
            return None

        reader = _ocr()
        arr = np.array(screenshot)
        ocr_results = reader.readtext(arr, detail=1)

        # Find label positions first
        label_positions = []
        for bbox, text, conf in ocr_results:
            if _fuzzy(text, label_text) and conf >= 0.70:
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                label_pos = (sum(xs) / len(xs), sum(ys) / len(ys))
                label_positions.append((label_pos, text, conf))

        if not label_positions:
            # No label found, fallback to trying icons alone
            print(f"[artifact_detector] Label '{label_text}' not found, trying icon-only detection")
            for icon_asset in icon_assets_to_try:
                try:
                    icon_result = _find_template(screenshot, icon_asset)
                    if icon_result:
                        return {
                            "x": icon_result[0],
                            "y": icon_result[1],
                            "method": "card_with_icon",
                            "confidence": threshold,
                            "label": icon_asset,
                            "detection_type": "icon_only"
                        }
                except Exception as e:
                    print(f"[artifact_detector] Icon matching {icon_asset} failed: {e}")
            return None

        # Try to match icon + label together
        best_match = None
        best_score = 0

        for icon_asset in icon_assets_to_try:
            try:
                icon_result = _find_template(screenshot, icon_asset)
                if icon_result:
                    # Check which label is closest to this icon
                    for label_pos, label_text_detected, label_conf in label_positions:
                        # Calculate distance between icon and label
                        dist = ((icon_result[0] - label_pos[0]) ** 2 +
                               (icon_result[1] - label_pos[1]) ** 2) ** 0.5

                        # Label should be near icon (within reasonable card size)
                        # Typical card: icon above label, distance ~60-100px vertically
                        if dist < 150:
                            score = label_conf * threshold
                            if score > best_score:
                                best_score = score
                                best_match = {
                                    "x": int(label_pos[0]),
                                    "y": int(label_pos[1]),
                                    "method": "card_with_icon",
                                    "confidence": float(label_conf),
                                    "label": label_text,
                                    "icon": icon_asset,
                                    "icon_distance": int(dist)
                                }

            except Exception as e:
                print(f"[artifact_detector] Icon matching {icon_asset} failed: {e}")

        return best_match if best_score > 0.5 else None

    def _detect_card_with_label(
        self,
        screenshot: Image.Image,
        config: Dict
    ) -> Optional[Dict]:
        """Detect node card by label."""
        label_text = config.get("label_text")
        if not label_text:
            return None

        reader = _ocr()
        arr = np.array(screenshot)
        results = reader.readtext(arr, detail=1)

        for bbox, text, conf in results:
            if _fuzzy(text, label_text) and conf >= config.get("confidence_threshold", 0.80):
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                return {
                    "x": int(sum(xs) / len(xs)),
                    "y": int(sum(ys) / len(ys)),
                    "method": "card_with_label",
                    "confidence": float(conf),
                    "label": label_text
                }

        return None

    def _detect_ocr_text(
        self,
        screenshot: Image.Image,
        config: Dict
    ) -> Optional[Dict]:
        """Detect by searching for OCR text."""
        search_text = config.get("search_text")
        if not search_text:
            return None

        reader = _ocr()
        arr = np.array(screenshot)
        results = reader.readtext(arr, detail=1)

        for bbox, text, conf in results:
            if _fuzzy(text, search_text) and conf >= config.get("confidence_threshold", 0.85):
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                return {
                    "x": int(sum(xs) / len(xs)),
                    "y": int(sum(ys) / len(ys)),
                    "method": "ocr_text",
                    "confidence": float(conf),
                    "label": search_text,
                    "content": text
                }

        return None

    def _detect_region_scan(
        self,
        screenshot: Image.Image,
        config: Dict
    ) -> Optional[Dict]:
        """Scan a region for content."""
        region = config.get("region")
        search_text = config.get("search_text")

        if not region:
            return None

        # Define regions
        height, width = np.array(screenshot).shape[:2]
        regions = {
            "bottom_terminal": (0, int(height * 0.7), width, height),
            "bottom_half": (0, int(height * 0.5), width, height),
            "bottom_buttons": (0, int(height * 0.75), width, height),
            "form_buttons": (int(width * 0.1), int(height * 0.8), int(width * 0.9), height),
            "top_toolbar": (0, 0, width, int(height * 0.15)),
            "left_panel": (0, 0, int(width * 0.2), height),
            "right_panel": (int(width * 0.8), 0, width, height),
            "center_canvas": (int(width * 0.2), int(height * 0.15), int(width * 0.8), int(height * 0.7))
        }

        region_bounds = regions.get(region)
        if not region_bounds:
            return None

        x1, y1, x2, y2 = region_bounds
        region_img = np.array(screenshot)[y1:y2, x1:x2]

        reader = _ocr()
        results = reader.readtext(region_img, detail=1)

        if search_text:
            for bbox, text, conf in results:
                if _fuzzy(text, search_text) and conf >= config.get("confidence_threshold", 0.85):
                    xs = [p[0] for p in bbox]
                    ys = [p[1] for p in bbox]
                    return {
                        "x": int(x1 + sum(xs) / len(xs)),
                        "y": int(y1 + sum(ys) / len(ys)),
                        "method": "region_scan",
                        "confidence": float(conf),
                        "label": search_text,
                        "region": region,
                        "content": text
                    }

        # If no search text, return region center with content summary
        if results:
            all_text = " ".join([text for _, text, _ in results])
            return {
                "x": (x1 + x2) // 2,
                "y": (y1 + y2) // 2,
                "method": "region_scan",
                "confidence": 0.70,
                "region": region,
                "content": all_text
            }

        return None

    def interact_with_artifact(
        self,
        screenshot: Image.Image,
        step_id: str,
        artifact_id: str
    ) -> bool:
        """Detect and interact with an artifact.

        Executes the action sequence defined in the artifact configuration.
        """
        config = self.get_artifact_config(step_id, artifact_id)
        if not config:
            return False

        # Detect the artifact
        detection = self.detect_artifact(screenshot, step_id, artifact_id)
        if not detection:
            print(f"[artifact_detector] Failed to detect {artifact_id}")
            return False

        print(f"[artifact_detector] Detected {artifact_id} at ({detection['x']}, {detection['y']})")

        # Execute action sequence
        actions = config.get("actions", [])
        for action_config in actions:
            action_type = action_config.get("action")

            if action_type == "click":
                pyautogui.click(detection["x"], detection["y"])
                print(f"[artifact_detector] Clicked {artifact_id}")

            elif action_type == "select_all":
                pyautogui.hotkey("cmd" if pyautogui._pyautogui_x11 is None else "ctrl", "a")
                print(f"[artifact_detector] Selected all")

            elif action_type == "type":
                value = action_config.get("value", "")
                pyautogui.typewrite(value, interval=0.05)
                print(f"[artifact_detector] Typed '{value}'")

            elif action_type == "wait":
                import time
                wait_time = action_config.get("duration", 1)
                time.sleep(wait_time)

        return True


def main():
    """Example usage."""
    detector = ArtifactDetector()

    # List all artifacts in step 1
    print("Step 1 Artifacts:")
    artifacts = detector.list_artifacts("step_1_create_project")
    for artifact_id in artifacts:
        config = detector.get_artifact_config("step_1_create_project", artifact_id)
        print(f"  - {artifact_id}: {config.get('label')}")


if __name__ == "__main__":
    main()
