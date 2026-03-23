# Create Hello World Automation

app: WSO2 Integrator
app_path: $HOME/Applications/WSO2 Integrator.app
workspace_git: $HOME/wso2mi/workspace

## Steps

### Step 1: Launch WSO2 Integrator and Create a New Project

Open the app and maximize the window.
Click **Get Started**.
Click **Create**.
In the **Integration Name** field, enter '{project_name}'.
Click **Browse** to open the folder picker.
Navigate to the desired folder and click **Open**.
Click **Create Integration**.

<img src="{{base_path}}/assets/create-hello-world-project/create-integration-project.gif" alt="Create Integration Project" width="80%" />

### Step 2: Design the Automation

In the sidebar, click **Add Artifact**.
Select **Automation** and click **Create**.
Click **+** after the Start node.
Select **Call Function** → **println**.
Click **Initialize Array**.
Click **Fx** offset 200px right to click inside the value input field.
Enter '"Hello World"'.
Click **Save**.

<img src="{{base_path}}/assets/design-automation/design-automation.gif" alt="Design Automation" width="80%" />

### Step 3: Run the Automation

Click **Run** in the top-right toolbar to execute the automation.
Verify the output in the console.

<img src="{{base_path}}/assets/run-automation/run-automation.gif" alt="Run Automation" width="80%" />