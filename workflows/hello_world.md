# Hello World

app: WSO2 Integrator
app_path: $HOME/Applications/WSO2 Integrator.app
workspace_git: $HOME/wso2mi/workspace
workspace_test_branch: test
workspace_branch: guide

## Steps

### Step 1: Open the app and create a project

Open the app and maximize the window.
Click the Create button to open the project creation wizard.
In the Integration Name field, enter {project_name}.
Click Browse to open the folder picker.
Click wso2mi.
Click workspace.
Click Open to confirm the directory.
Click the Create Integration button to initialize your integration project.

<div style="text-align: center;">
   <a href="{{base_path}}/assets/hello-world/create-integration-project.gif">
      <img
      src="{{base_path}}/assets/hello-world/create-integration-project.gif"
         alt="Creating an integration project in WSO2 Integrator"
         width="80%"
      />
   </a>
</div>

### Step 2: Add Automation artifact

In WSO2 Integrator: BI design view, click Add Artifact.
Select Automation from the Constructs menu.
Click Create to create an automation.

<div style="text-align: center;">
   <a href="{{base_path}}/assets/hello-world/add-automation-artifact.gif">
      <img
      src="{{base_path}}/assets/hello-world/add-automation-artifact.gif"
         alt="Adding an Automation artifact in WSO2 Integrator"
         width="80%"
      />
   </a>
</div>

### Step 3: Add println node

Click + after the Start node to open the node panel.
Select Call Function and select println.
Click Initialize Array.
Click Fx offset 100px right to click inside the value input "Hello World".
Enter '"Hello World"'.
Click Save.
Click the Run button in the top right to run the integration.

<div style="text-align: center;">
   <a href="{{base_path}}/assets/hello-world/add-println-node.gif">
      <img
      src="{{base_path}}/assets/hello-world/add-println-node.gif"
         alt="Adding a println node with Hello World value"
         width="80%"
      />
   </a>
</div>
