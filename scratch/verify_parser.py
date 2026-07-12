import sys
from pathlib import Path

# Add project root to path
sys.path.append("/Users/sachindu/Desktop/Repos/wso2/FlowCast")

from src.parser import _parse_instructions

test_lines = [
    "3. Scroll down to the bottom and select **Local Files** under **File Integration**.",
    "3. Scroll all the way and select **Local Files**.",
    "3. Scroll down and select **Local Files**." # Should NOW be -60 by default
]

for line in test_lines:
    print(f"\nInstruction: {line}")
    actions = _parse_instructions(line)
    for i, a in enumerate(actions):
        print(f"  Action {i}: {a}")
