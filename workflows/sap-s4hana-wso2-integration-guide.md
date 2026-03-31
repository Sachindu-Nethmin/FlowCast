## Step 1: Create a New Integration Project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `sales-manager`.
4. Select **Browse**.
5. Select the project location and select **Open**.
6. Select **Create Integration**.

## Step 2: Add an HTTP Service Artifact

1. Select **sales-manager**.
2. In the design view, select **+ Add Artifact**.
3. Select **HTTP Service** under **Integration as API**.
4. Keep the **Service contract** as **Design from scratch**.
5. Set **Service base path** to `/salesorder`.
6. Select **Create**.

## Step 3: Configure the HTTP Service and Add a Resource

1. In the HTTP Service Designer view, select **Add Resources**.
2. Select **POST** as the HTTP method.
3. Set the **resource path** to `.`.
4. Select **Save**.

## Step 4: Open the Resource Flow and Add the SAP Connector

1. Select **+** inside the resource flow.
2. Select **Add Connection**.
3. Search in the **Add Connection** for **api_sales_order**.
3. Set **Connection Name** to `api_sales_order_srv`.
4. Select **Api_sales_order_srv**.
5. Select **Add**.

## Step 5: Configure the SAP Connector Connection

1. Set **Auth** to `WS02_MAIN_DEV`.
2. Set **Password** to `your-sap-password`.
3. Set **Hostname** to `my401785.s4hana.cloud.sap`.
4. Select **Save**.

## Step 6: Define the Request Payload

1. Select **Configure**.
2. Select **Import**.
3. Set **Data Format** to `JSON`.
4. Select **Save**.

## Step 7: Select the Create Sales Order Operation

1. Select **+** inside the resource flow.
2. Select **apiSalesOrderSrvClient**.
3. Select **Create A Sales Order**.

## Step 8: Map the Payload to the SAP API Fields

1. Set **SalesOrderType** to `OR`.
2. Set **SalesOrganization** to `1710`.
3. Set **DistributionChannel** to `10`.
4. Set **OrganizationDivision** to `00`.
5. Select **Save**.

## Step 9: Return the SAP Response

1. Select **+** inside the resource flow.
2. Select **Return**.
3. Set **return expression** to `apiSalesOrderSrvASalesorderwrapper.toJson()`.
4. Select **Save**.

## Step 10: Run and Test the Integration

1. Select **Run**.
2. The integration starts locally and listens on `http://localhost:9090/salesorder/`.
3. Use Postman or cURL to send a POST request to that URL with body `{"item": "ELE_FAN", "qty": "12"}`.
