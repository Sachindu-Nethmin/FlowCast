## Step 1: Create the project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `HelloWorld`.
4. Set **Project Name** to `QuickStart`.
5. Select **Browse**.
6. Select the project location and select **Open**.
7. Select **Create Integration**.

<ThemedImage
    alt="Create the project"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-automation/step-01-create-the-project-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-automation/step-01-create-the-project-dark.gif'),
    }}
/>

## Step 2: Add an automation artifact

1. Select **Get Started**.
2. In the design view, select **+ Add Artifact**.
3. Select **Automation** artifact.
4. Select **Create** to create an automation. This directs you to the automation diagram view.

<ThemedImage
    alt="Add an automation artifact"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-automation/step-02-add-an-automation-artifact-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-automation/step-02-add-an-automation-artifact-dark.gif'),
    }}
/>

## Step 3: Add logic

1. Select **+** after the **Start** node to open the right panel.
2. Search **Println** from the right panel.
3. Select **Println**.
4. Select **Initialize Array** from the right panel.
5. Set **Values** to `"Hello World"` and select **Save**.

<ThemedImage
    alt="Add logic"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-automation/step-03-add-logic-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-automation/step-03-add-logic-dark.gif'),
    }}
/>

## Step 4: Run and test

1. Select **Run**.
2. The automation executes immediately and prints output to the terminal.
3. Check the terminal output for `Hello World`.

<ThemedImage
    alt="Run and test"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-automation/step-04-run-and-test-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-automation/step-04-run-and-test-dark.gif'),
    }}
/>
