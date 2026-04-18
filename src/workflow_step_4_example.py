"""
Practical Example: Step 4 from quick-start-automation workflow
"Set **Project Name** to `Automation`"
"""

import cv2
from project_name_detector import QuickStartAutomationFlow

def execute_step_4(screenshot_path: str) -> dict:
    """
    Execute Step 4: Set Project Name to Automation
    
    Args:
        screenshot_path: Path to current UI screenshot
    
    Returns:
        Dictionary with detection results and actions to perform
    """
    
    # Load screenshot
    screenshot = cv2.imread(screenshot_path)
    
    # Initialize workflow
    workflow = QuickStartAutomationFlow()
    
    # Execute step 4
    result = workflow.step_4_set_project_name(screenshot)
    
    return result


def main():
    """Example workflow execution."""
    
    print("═" * 70)
    print("QUICK-START-AUTOMATION WORKFLOW")
    print("Step 4: Set Project Name to Automation")
    print("═" * 70)
    print()
    
    # In actual automation, you would:
    # 1. Take screenshot of current UI state
    # 2. Call detection
    # 3. Execute recommended actions
    # 4. Verify completion
    
    example_result = {
        'step': 4,
        'description': 'Set Project Name to Automation',
        'workflow': 'quick-start-automation',
        
        'detection': {
            'method': 'template_matching',
            'template': 'input.svg',
            'confidence': 0.75,
            'field_location': {'x': 320, 'y': 450},
            'label_verified': True
        },
        
        'recommended_actions': [
            {
                'action': 'click',
                'target': {'x': 450, 'y': 450},
                'description': 'Click Project Name field'
            },
            {
                'action': 'keyboard',
                'keys': ['ctrl+a'],
                'description': 'Select all text'
            },
            {
                'action': 'type',
                'text': 'Automation',
                'description': 'Type Automation'
            },
            {
                'action': 'verify',
                'method': 'ocr',
                'expected': 'Automation',
                'description': 'Verify value set'
            }
        ],
        
        'expected_outcome': 'Project Name field contains "Automation"',
        'next_step': 'Step 5: Add an Automation artifact'
    }
    
    print("DETECTION RESULT:")
    print("-" * 70)
    print(f"Step: {example_result['step']}")
    print(f"Description: {example_result['description']}")
    print(f"Detection Method: {example_result['detection']['method']}")
    print(f"Confidence: {example_result['detection']['confidence']}")
    print(f"Field Location: {example_result['detection']['field_location']}")
    print(f"Label Verified: {example_result['detection']['label_verified']}")
    print()
    
    print("RECOMMENDED ACTIONS:")
    print("-" * 70)
    for i, action in enumerate(example_result['recommended_actions'], 1):
        print(f"{i}. {action['action'].upper()}")
        print(f"   Description: {action['description']}")
        if 'target' in action:
            print(f"   Target: {action['target']}")
        if 'keys' in action:
            print(f"   Keys: {action['keys']}")
        if 'text' in action:
            print(f"   Text: {action['text']}")
        if 'expected' in action:
            print(f"   Expected: {action['expected']}")
        print()
    
    print("EXPECTED OUTCOME:")
    print("-" * 70)
    print(f"✓ {example_result['expected_outcome']}")
    print()
    
    print("NEXT STEP:")
    print("-" * 70)
    print(f"→ {example_result['next_step']}")
    print()


if __name__ == '__main__':
    main()

