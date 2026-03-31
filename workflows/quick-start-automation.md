## Step 1: Create the project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `Integration`.
4. Select **Browse**.
5. Select the project location and select **Open**.
6. Select **Create Integration**.

## Step 2: Add an automation artifact

1. Select **Integration**.
2. In the design view, select **+ Add Artifact**.
3. Select **Automation** artifact.
4. Select **Create** to create an automation. This directs you to the automation diagram view.
1. In the design view, select **+ Add Artifact**.
2. Select **Automation** artifact.
3. Select **Create** to create an automation. This directs you to the automation diagram view.

## Step 3: Add logic

1. Select **+** after the **Start** node to open the node panel.
2. Select **Call Function** node to the flow.
3. Select **Println** from the node panel.
4. Select **Initialize Array** from the node panel.
5. Set **Values** to `"Hello World"` and select **Save**.

## Step 4: Run and test

1. Select **Run**.
2. The automation executes immediately and prints output to the terminal.
3. Check the terminal output for `Hello World`.
