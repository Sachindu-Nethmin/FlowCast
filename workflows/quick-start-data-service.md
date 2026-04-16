# Quick Start: Data Service

Use this guide to create an integration that interacts with a MySQL database to monitor inventory levels and alert you of low stock.

## Prerequisites

Before you begin, ensure you have MySQL installed and configured on your machine.

### Set up the database

To set up the database and sample data, perform the following steps:

1. Save the following SQL script as `db_setup.sql`:
   ```sql
   -- Create the database
   CREATE DATABASE IF NOT EXISTS simple_db;
   USE simple_db;

   -- Create the 'start' user and grant permissions
   CREATE USER IF NOT EXISTS 'start'@'localhost' IDENTIFIED BY 'start';
   GRANT ALL PRIVILEGES ON simple_db.* TO 'start'@'localhost';
   FLUSH PRIVILEGES;

   -- Create the inventory table
   CREATE TABLE IF NOT EXISTS inventory (
       id INT AUTO_INCREMENT PRIMARY KEY,
       itemName VARCHAR(255) NOT NULL,
       quantity INT NOT NULL
   );

   -- Insert the sample data
   INSERT INTO inventory (itemName, quantity) VALUES ('Coffee Mugs', 15);
   INSERT INTO inventory (itemName, quantity) VALUES ('Desk Lamps', 4);   -- Low stock trigger
   INSERT INTO inventory (itemName, quantity) VALUES ('Notebooks', 25);
   ```

2. Open your terminal and run the following command to execute the script:
   ```bash
   mysql -u root -p < db_setup.sql
   ```

## Step 1: Create the Project

1. Open **WSO2 Integrator**.
2. Select **Create**.
3. In **Integration Name**, enter `InventoryService`.
4. In **Project Name**, enter `Quick_Start`.
5. Select **Browse**.
6. Select the project location, and then select **Open**.
7. Select **Create Integration**.

## Step 2: Initialize Database Connection

1. Select **InventoryService**.
2. In the design view, select **+ Add Artifact**.
3. Scroll down and select **Connection** under **Other Artifacts**.
4. Select **Connect to a Database**.

## Step 3: Configure Database Settings

1. In **Host**, enter `localhost`.
2. In **Port**, enter `3306`.
3. In **Database**, enter `simple_db`.
4. In **User**, enter `start`.
5. In **Password**, enter `start`.
6. Select **Connect & Introspect Database**.
7. Select **inventory**.
8. Select **Continue to Connection Details**.
9. In **Connection Name**, enter `inventoryDB`.
10. Select **Save Connection**.

## Step 4: Bootstrap Automation Flow

1. Select **InventoryService**.
2. In the design view, select **+ Add Artifact**.
3. Select **Automation**, and then select **Create**.
4. Select **+** after the **Start** node to open the node panel.

## Step 5: Configure Data Selection

1. Select **inventoryDB**.
2. Select **Get rows from inventory table**.
3. In **Result**, enter `ItemsNames`.
4. Select **itemName**.
5. Select **Save**.

## Step 6: Implement Logic Loop

1. Select **+**.
2. Search for `println`, and then select **println**.
3. Select **Initialize Array** from the node panel.
4. In **Values**, enter `ItemsNames`, and then select **Save**.

## Step 7: Run and Test

1. Select **Run**.
2. If prompted, generate the `Config.toml` and supply your database password.
3. Check the terminal output for the low stock alerts.
