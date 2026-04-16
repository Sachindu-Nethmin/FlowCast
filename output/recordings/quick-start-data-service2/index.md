## Step 1: Create the Project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `InventoryService`.
4. Set **Project Name** to `Quick_Start`.
5. Select **Browse**.
6. Select the project location and select **Open**.
7. Select **Create Integration**.

<ThemedImage
    alt="Create the Project"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-data-service/create-the-project-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-data-service/create-the-project-dark.gif'),
    }}
/>

## Step 2: Initialize Database Connection

1. Select **InventoryService**.
2. In the design view, select **+ Add Artifact**.
3. Scroll down and select **Connection** under **Other Artifacts**.
4. Select **Connect to a Database**.

<ThemedImage
    alt="Initialize Database Connection"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-data-service/initialize-database-connection-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-data-service/initialize-database-connection-dark.gif'),
    }}
/>

## Step 3: Configure Database Settings

1. Set **Host** to `localhost`.
2. Set **Port** to `3306`.
3. Set **Database** to `simple_db`.
4. Set **User** to `root`.
5. Select **Connect & Introspect Database**.
6. Select the **inventory** table.
7. Select **Continue to Connection Details**.

<ThemedImage
    alt="Configure Database Settings"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-data-service/configure-database-settings-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-data-service/configure-database-settings-dark.gif'),
    }}
/>

## Step 4: Bootstrap Automation Flow

1. In the design view, select **+ Add Artifact**.
2. Select **Automation** and select **Create**.
3. Select **+** after the **Start** node to open the node panel.

<ThemedImage
    alt="Bootstrap Automation Flow"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-data-service/bootstrap-automation-flow-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-data-service/bootstrap-automation-flow-dark.gif'),
    }}
/>

## Step 5: Configure Data Selection

1. Select **Get rows from inventory** action node using the `inventoryDB` connection.
2. Expand **Advanced Configurations** and set **Where Clause** to `stock_level < 10`.
3. Set **Result** to `lowStockItems`.
4. Select `item_name` and `stock_level` as the **Target Type** fields.
5. Select **Save**.

<ThemedImage
    alt="Configure Data Selection"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-data-service/configure-data-selection-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-data-service/configure-data-selection-dark.gif'),
    }}
/>

## Step 6: Implement Logic & Alerts

1. Select **+** to add a **Foreach** control node.
2. Set **Collection** to `lowStockItems` and **Result** to `item`.
3. Inside the Foreach block, select **+** and add a **Log Info** statement node.
4. Set the message to `Low stock alert!`.
5. Expand **Advanced Configurations** and add **Additional Values**:
- Set **Key** to `itemName` and **Value** to `item.item_name`.
- Set **Key** to `currentStock` and **Value** to `item.stock_level`.
6. Select **Save**.

<ThemedImage
    alt="Implement Logic & Alerts"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-data-service/implement-logic-alerts-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-data-service/implement-logic-alerts-dark.gif'),
    }}
/>

## Step 7: Run and Test

1. Select **Run**.
2. If prompted, generate the `Config.toml` and supply your database password.
3. Check the terminal output for the low stock alerts.

<ThemedImage
    alt="Run and Test"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-data-service/run-and-test-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-data-service/run-and-test-dark.gif'),
    }}
/>
