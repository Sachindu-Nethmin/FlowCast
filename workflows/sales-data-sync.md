## Step 1: Create a new integration project

1. Select **BI** icon on the sidebar.
2. Select **Create New Integration**.
3. Set **Project Name** to `sales-data-sync`.
4. Select **Select Location** and choose the directory.
5. Select **Create New Integration**.

## Step 2: Create an FTP Integration

1. Select **+ Add Artifact** in the design view.
2. Select **FTP / SFTP** from the **File Integration** category.
3. Select **FTP** protocol.
4. Set **Host** to `localhost`.
5. Set **Port Number** to `21`.
6. Set **Folder Path** to `/sales/new`.
7. Set **Authentication** to **Basic Authentication**.
8. Set **Username** to `ftpuser` and **Password** to `ftppass`.
9. Select **Create**.

## Step 3: Add file handler

1. Select **+ Add File Handler** and select **onCreate**.
2. Select **JSON** as the **File Format**.
3. Select **+ Define Content Schema** -> **Import Header**.
4. Paste the following JSON sample data:
   ```json
   {
     "storeId": "S001",
     "storeLocation": "New York",
     "saleDate": "2023-10-01",
     "items": [
       {
         "itemId": "I001",
         "quantity": 10,
         "totalAmount": 100.00
       }
     ]
   }
   ```
5. Set **Type Name** to `SalesReport` and select **Import Type**.
6. Select **Save**.
7. Select **+** and add **Log Info**.
8. Set **Msg** to `Processing file from store` and map **Inputs** -> **content** -> **storeId**.

## Step 4: Add a MySQL connection

1. Select **+** and add **Connection**.
2. Select **MySQL** from the list.
3. In **Advanced Configurations**, set:
   - **Host**: `localhost`
   - **User**: `root`
   - **Password**: `root@123`
   - **Database**: `sales_db`
   - **Port**: `3307`
4. Select **Save Connection**.

## Step 5: Implement business logic

1. Select **+** and add a **Foreach** loop.
2. For **Collection**, map **Inputs** -> **content** -> **items**.
3. Set **Variable Name** to `item` and **Variable Type** to `ItemsItem`.
4. Select **Save**.
5. Select **+** inside the loop and select **mysqlClient** -> **Execute**.
6. Set the SQL query:
   ```sql
   INSERT INTO Sales (store_id, store_location, sale_date, item_id, quantity, total_amount)
   VALUES (${content.storeId}, ${content.storeLocation}, ${content.saleDate}, 
           ${item.itemId}, ${item.quantity}, ${item.totalAmount})
   ```
7. Select **Save**.

## Step 6: Post-processing

1. Select **+** and select **caller** -> **Move**.
2. Set **Source Path** to `Inputs -> fileInfo -> pathDecoded`.
3. Set **Destination Path** to `/sales/processed/` + `Inputs -> fileInfo -> name`.
4. Add **Log Info** with message `File moved to processed: ` + `Inputs -> fileInfo -> name`.

## Step 7: Error handling

1. Select **Error Handler**.
2. Remove the **Return error** node.
3. Select **+** and select **caller** -> **Move**.
4. Set **Source Path** to `Inputs -> fileInfo -> pathDecoded`.
5. Set **Destination Path** to `/sales/error/` + `Inputs -> fileInfo -> name`.
6. Add **Log Info** with message `File moved to error: ` + `Inputs -> fileInfo -> name`.
