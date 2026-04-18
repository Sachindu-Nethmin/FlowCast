"""Complete workflow automation for quick-start-automation workflow.

Demonstrates automated execution of all 4 steps:
1. Create the project
2. Add an automation artifact
3. Add logic
4. Run and test
"""

import time
from pathlib import Path
from PIL import Image
from artifact_detector import ArtifactDetector


class QuickStartAutomationBot:
    """Automated bot for quick-start-automation workflow."""

    def __init__(self):
        """Initialize the bot."""
        self.detector = ArtifactDetector()
        self.screenshot_dir = Path("output/workflow_screenshots")
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.step_count = 0

    def take_screenshot(self, filename: str = None) -> Image.Image:
        """Capture and save screenshot."""
        import pyautogui
        screenshot = pyautogui.screenshot()

        if filename is None:
            self.step_count += 1
            filename = f"step_{self.step_count:02d}.png"

        path = self.screenshot_dir / filename
        screenshot.save(path)
        print(f"[workflow] Screenshot saved: {path}")
        return screenshot

    def wait(self, seconds: float = 1.0):
        """Wait for UI to stabilize."""
        time.sleep(seconds)

    def detect_artifacts_in_step(self, step_id: str) -> Dict[str, dict]:
        """Detect all artifacts in a step."""
        screenshot = self.take_screenshot()
        artifacts = self.detector.list_artifacts(step_id)

        results = {}
        for artifact_id in artifacts:
            detection = self.detector.detect_artifact(screenshot, step_id, artifact_id)
            if detection:
                results[artifact_id] = detection
                print(f"✓ Detected {artifact_id}: {detection.get('label')} at ({detection['x']}, {detection['y']})")
            else:
                print(f"✗ Failed to detect {artifact_id}")

        return results

    def step_1_create_project(self) -> bool:
        """Step 1: Create the project.

        1. Open WSO2 Integrator.
        2. Select **Create**.
        3. Set **Integration Name** to `Get Started`.
        4. Set **Project Name** to `Automation`.
        5. Select **Browse**.
        6. Select the project location and select **Open**.
        7. Select **Create Integration**.
        """
        print("\n" + "="*70)
        print("STEP 1: Create the project")
        print("="*70)

        step_id = "step_1_create_project"

        # Detect all artifacts
        print("\n[step_1] Detecting artifacts...")
        artifacts = self.detect_artifacts_in_step(step_id)

        if not artifacts:
            print("[step_1] No artifacts detected in creation form")
            return False

        screenshot = self.take_screenshot()

        # 3. Set Integration Name
        print("\n[step_1] Setting Integration Name to 'Get Started'...")
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "integration_name_field"
        )
        if not success:
            print("[step_1] Failed to set integration name")
            return False

        self.wait(0.5)
        screenshot = self.take_screenshot()

        # 4. Set Project Name
        print("\n[step_1] Setting Project Name to 'Automation'...")
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "project_name_field"
        )
        if not success:
            print("[step_1] Failed to set project name")
            return False

        self.wait(0.5)
        screenshot = self.take_screenshot()

        # 5. Select Browse
        print("\n[step_1] Clicking Browse button...")
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "browse_button"
        )
        if not success:
            print("[step_1] Failed to click browse")
            return False

        self.wait(1.0)
        screenshot = self.take_screenshot()

        print("[step_1] Waiting for directory dialog (manual interaction may be needed)...")
        self.wait(3.0)
        screenshot = self.take_screenshot()

        # 7. Select Create Integration
        print("\n[step_1] Clicking Create Integration button...")
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "create_integration_button"
        )
        if not success:
            print("[step_1] Failed to click create integration")
            return False

        self.wait(2.0)
        print("[step_1] ✓ Project created successfully")
        return True

    def step_2_add_automation_artifact(self) -> bool:
        """Step 2: Add an automation artifact.

        1. Select **Get Started**.
        2. In the design view, select **+ Add Artifact**.
        3. Select **Automation** artifact.
        4. Select **Create** to create an automation.
        """
        print("\n" + "="*70)
        print("STEP 2: Add an automation artifact")
        print("="*70)

        step_id = "step_2_add_automation_artifact"
        screenshot = self.take_screenshot()

        # 1. Select Get Started project
        print("\n[step_2] Selecting 'Get Started' project...")
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "get_started_selector"
        )
        if not success:
            print("[step_2] Failed to select Get Started")
            # Continue anyway, might already be selected

        self.wait(1.0)
        screenshot = self.take_screenshot()

        # 2. Click Add Artifact
        print("\n[step_2] Clicking '+ Add Artifact' button...")
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "add_artifact_button"
        )
        if not success:
            print("[step_2] Failed to click add artifact")
            return False

        self.wait(1.0)
        screenshot = self.take_screenshot()

        # 3. Select Automation artifact
        print("\n[step_2] Selecting 'Automation' artifact...")
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "automation_artifact_card"
        )
        if not success:
            print("[step_2] Failed to select automation artifact")
            return False

        self.wait(1.0)
        screenshot = self.take_screenshot()

        # 4. Click Create
        print("\n[step_2] Clicking 'Create' button...")
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "create_button"
        )
        if not success:
            print("[step_2] Failed to click create")
            return False

        self.wait(2.0)
        print("[step_2] ✓ Automation artifact created successfully")
        return True

    def step_3_add_logic(self) -> bool:
        """Step 3: Add logic.

        1. Select **+** after the **Start** node.
        2. Select **Call Function** node.
        3. Select **Println** from the node panel.
        4. Select **Initialize Array** from the node panel.
        5. Set **Values** to `["Hello World"]` and select **Save**.
        """
        print("\n" + "="*70)
        print("STEP 3: Add logic")
        print("="*70)

        step_id = "step_3_add_logic"
        screenshot = self.take_screenshot()

        # 1. Find and click + after Start node
        print("\n[step_3] Finding '+' button after Start node...")
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "plus_button"
        )
        if not success:
            print("[step_3] Failed to find plus button")
            return False

        self.wait(1.0)
        screenshot = self.take_screenshot()

        # 2. Click Call Function node
        print("\n[step_3] Clicking 'Call Function' node...")
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "call_function_node"
        )
        if not success:
            print("[step_3] Failed to select call function")
            return False

        self.wait(0.5)

        # 3. Click Println node
        print("\n[step_3] Clicking 'Println' node...")
        screenshot = self.take_screenshot()
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "println_node"
        )
        if not success:
            print("[step_3] Failed to select println")
            return False

        self.wait(0.5)

        # 4. Click Initialize Array node
        print("\n[step_3] Clicking 'Initialize Array' node...")
        screenshot = self.take_screenshot()
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "initialize_array_node"
        )
        if not success:
            print("[step_3] Failed to select initialize array")
            return False

        self.wait(1.0)

        # 5. Set Values field
        print("\n[step_3] Setting 'Values' field to '[\"Hello World\"]'...")
        screenshot = self.take_screenshot()
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "values_field"
        )
        if not success:
            print("[step_3] Failed to set values")
            return False

        self.wait(0.5)

        # Click Save
        print("\n[step_3] Clicking 'Save' button...")
        screenshot = self.take_screenshot()
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "save_button"
        )
        if not success:
            print("[step_3] Failed to click save")
            return False

        self.wait(1.0)
        print("[step_3] ✓ Logic added successfully")
        return True

    def step_4_run_and_test(self) -> bool:
        """Step 4: Run and test.

        1. Select **Run**.
        2. The automation executes immediately.
        3. Check the terminal output for `Hello World`.
        """
        print("\n" + "="*70)
        print("STEP 4: Run and test")
        print("="*70)

        step_id = "step_4_run_and_test"
        screenshot = self.take_screenshot()

        # 1. Click Run button
        print("\n[step_4] Detecting and clicking 'Run' button...")
        success = self.detector.interact_with_artifact(
            screenshot, step_id, "run_button"
        )
        if not success:
            print("[step_4] Failed to click run button")
            return False

        print("[step_4] Waiting for automation to execute...")
        self.wait(3.0)
        screenshot = self.take_screenshot()

        # 3. Check terminal output
        print("\n[step_4] Checking terminal output for 'Hello World'...")
        detection = self.detector.detect_artifact(
            screenshot, step_id, "terminal_output"
        )

        if detection:
            content = detection.get("content", "")
            if "Hello World" in content:
                print(f"[step_4] ✓ Found expected output: '{content}'")
                return True
            else:
                print(f"[step_4] ✗ Output found but no 'Hello World': '{content}'")
                return False
        else:
            print("[step_4] ✗ Failed to detect terminal output")
            return False

    def run_complete_workflow(self) -> bool:
        """Execute the complete workflow."""
        print("\n" + "="*70)
        print("QUICK-START AUTOMATION WORKFLOW")
        print("="*70)

        steps = [
            ("Step 1: Create Project", self.step_1_create_project),
            ("Step 2: Add Artifact", self.step_2_add_automation_artifact),
            ("Step 3: Add Logic", self.step_3_add_logic),
            ("Step 4: Run & Test", self.step_4_run_and_test),
        ]

        results = {}
        for step_name, step_func in steps:
            try:
                success = step_func()
                results[step_name] = "✓ PASSED" if success else "✗ FAILED"
            except Exception as e:
                print(f"\n✗ Exception in {step_name}: {e}")
                import traceback
                traceback.print_exc()
                results[step_name] = f"✗ ERROR: {e}"

            self.wait(1.0)

        # Print summary
        print("\n" + "="*70)
        print("WORKFLOW SUMMARY")
        print("="*70)
        for step_name, result in results.items():
            print(f"{result} {step_name}")

        all_passed = all("PASSED" in v for v in results.values())
        print("\n" + ("="*70))
        print(f"Overall: {'✓ ALL STEPS PASSED' if all_passed else '✗ SOME STEPS FAILED'}")
        print("="*70)

        return all_passed


def main():
    """Run the complete workflow."""
    bot = QuickStartAutomationBot()
    success = bot.run_complete_workflow()
    return 0 if success else 1


if __name__ == "__main__":
    from typing import Dict
    import sys
    sys.exit(main())
