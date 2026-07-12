import re

body = """## Step 1: Create the project

1. Open WSO2 Integrator.
2. Select **Create**.

<ThemedImage
    alt="Create the project"
    sources={{
        light: useBaseUrl('/img/get-started/build-automation/create-the-project-light.gif'),
        dark: useBaseUrl('/img/get-started/build-automation/create-the-project-dark.gif'),
    }}
/>
"""

instructions = re.sub(r'<[^>]+>', '', body).strip()
print(f"Instructions:\n{instructions}")
