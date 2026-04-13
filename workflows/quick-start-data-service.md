## Step 1: Create the Project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `InventoryService`.
4. Set **Project Name** to `Quick_Start`.
5. Select **Browse**.
6. Select the project location and select **Open**.
7. Select **Create Integration**.

## Step 2: Initialize Database Connection

1. Select **InventoryService**.
2. In the design view, select **+ Add Artifact**.
3. Scroll down and select **Connection** under **Other Artifacts**.
4. Select **Connect to a Database**.

## Step 3: Configure Database Settings

1. Set **Host** to `localhost`.
2. Set **Port** to `3306`.
3. Set **Database** to `simple_db`.
4. Set **User** to `start`.
5. Set **Password** to `start`.
6. Select **Connect & Introspect Database**.
7. Select **inventory**.
8. Select **Continue to Connection Details**.
9. Set **Connection Name** to `inventoryDB`.
10. Select **Save Connection**.

## Step 4: Bootstrap Automation Flow

1. Select **InventoryService**.
2. In the design view, select **+ Add Artifact**.
3. Select **Automation** and select **Create**.
4. Select **+** after the **Start** node to open the node panel.

## Step 5: Configure Data Selection

1. Select **inventoryDB**.
2. Select **Get rows from inventory table**.
4. Set **Result** to `ItemsNames`.
5. Select **ItemName**.
6. Select **Save**.

## Step 6: Implement Logic Loop

1. Select **+**.
5. Search `println` and select **println**.
4. Select **Initialize Array** from the node panel.
5. Set **Values** to `itemsNames` and select **Save**.

## Step 7: Run and Test

1. Select **Run**.
2. If prompted, generate the `Config.toml` and supply your database password.
3. Check the terminal output for the low stock alerts.
