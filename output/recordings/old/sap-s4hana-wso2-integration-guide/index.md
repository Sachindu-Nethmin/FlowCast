## Step 1: Create a New Integration Project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `sales-manager`.
4. Select **Browse**.
5. Select the project location and select **Open**.
6. Select **Create Integration**.

<ThemedImage
    alt="Create a New Integration Project"
    sources={{
        light: '/img/get-started/sap-s4hana-wso2-integration-guide/create-a-new-integration-project-light.gif',
        dark: '/img/get-started/sap-s4hana-wso2-integration-guide/create-a-new-integration-project-dark.gif',
    }}
/>

## Step 2: Add an HTTP Service Artifact

1. Select **sales-manager**.
2. In the design view, select **+ Add Artifact**.
3. Select **HTTP Service** under **Integration as API**.
4. Keep the **Service contract** as **Design from scratch**.
5. Set **Service base path** to `/salesorder`.
6. Select **Create**.

<ThemedImage
    alt="Add an HTTP Service Artifact"
    sources={{
        light: '/img/get-started/sap-s4hana-wso2-integration-guide/add-an-http-service-artifact-light.gif',
        dark: '/img/get-started/sap-s4hana-wso2-integration-guide/add-an-http-service-artifact-dark.gif',
    }}
/>

## Step 3: Configure the HTTP Service and Add a Resource

1. In the HTTP Service Designer view, select **Add Resources**.
2. Select **POST** as the HTTP method.
3. Set the **resource path** to `.`.
4. Select **Save**.

<ThemedImage
    alt="Configure the HTTP Service and Add a Resource"
    sources={{
        light: '/img/get-started/sap-s4hana-wso2-integration-guide/configure-the-http-service-and-add-a-resource-light.gif',
        dark: '/img/get-started/sap-s4hana-wso2-integration-guide/configure-the-http-service-and-add-a-resource-dark.gif',
    }}
/>

## Step 4: Open the Resource Flow and Add the SAP Connector

1. Select **+** inside the resource flow.
2. Select **Add Connection**.
3. Set **Connection Name** to `api_sales_order_srv`.
4. Select **Api_sales_order_srv**.
5. Select **Add**.

<ThemedImage
    alt="Open the Resource Flow and Add the SAP Connector"
    sources={{
        light: '/img/get-started/sap-s4hana-wso2-integration-guide/open-the-resource-flow-and-add-the-sap-connector-light.gif',
        dark: '/img/get-started/sap-s4hana-wso2-integration-guide/open-the-resource-flow-and-add-the-sap-connector-dark.gif',
    }}
/>

## Step 5: Configure the SAP Connector Connection

1. Set **Auth** to `WS02_MAIN_DEV`.
2. Set **Password** to `your-sap-password`.
3. Set **Hostname** to `my401785.s4hana.cloud.sap`.
4. Select **Save**.

<ThemedImage
    alt="Configure the SAP Connector Connection"
    sources={{
        light: '/img/get-started/sap-s4hana-wso2-integration-guide/configure-the-sap-connector-connection-light.gif',
        dark: '/img/get-started/sap-s4hana-wso2-integration-guide/configure-the-sap-connector-connection-dark.gif',
    }}
/>

## Step 6: Define the Request Payload

1. Select **Configure**.
2. Select **Import**.
3. Set **Data Format** to `JSON`.
4. Select **Save**.

<ThemedImage
    alt="Define the Request Payload"
    sources={{
        light: '/img/get-started/sap-s4hana-wso2-integration-guide/define-the-request-payload-light.gif',
        dark: '/img/get-started/sap-s4hana-wso2-integration-guide/define-the-request-payload-dark.gif',
    }}
/>

## Step 7: Select the Create Sales Order Operation

1. Select **+** inside the resource flow.
2. Select **apiSalesOrderSrvClient**.
3. Select **Create A Sales Order**.

<ThemedImage
    alt="Select the Create Sales Order Operation"
    sources={{
        light: '/img/get-started/sap-s4hana-wso2-integration-guide/select-the-create-sales-order-operation-light.gif',
        dark: '/img/get-started/sap-s4hana-wso2-integration-guide/select-the-create-sales-order-operation-dark.gif',
    }}
/>

## Step 8: Map the Payload to the SAP API Fields

1. Set **SalesOrderType** to `OR`.
2. Set **SalesOrganization** to `1710`.
3. Set **DistributionChannel** to `10`.
4. Set **OrganizationDivision** to `00`.
5. Select **Save**.

<ThemedImage
    alt="Map the Payload to the SAP API Fields"
    sources={{
        light: '/img/get-started/sap-s4hana-wso2-integration-guide/map-the-payload-to-the-sap-api-fields-light.gif',
        dark: '/img/get-started/sap-s4hana-wso2-integration-guide/map-the-payload-to-the-sap-api-fields-dark.gif',
    }}
/>

## Step 9: Return the SAP Response

1. Select **+** inside the resource flow.
2. Select **Return**.
3. Set **return expression** to `apiSalesOrderSrvASalesorderwrapper.toJson()`.
4. Select **Save**.

<ThemedImage
    alt="Return the SAP Response"
    sources={{
        light: '/img/get-started/sap-s4hana-wso2-integration-guide/return-the-sap-response-light.gif',
        dark: '/img/get-started/sap-s4hana-wso2-integration-guide/return-the-sap-response-dark.gif',
    }}
/>

## Step 10: Run and Test the Integration

1. Select **Run**.
2. The integration starts locally and listens on `http://localhost:9090/salesorder/`.
3. Use Postman or cURL to send a POST request to that URL with body `{"item": "ELE_FAN", "qty": "12"}`.

<ThemedImage
    alt="Run and Test the Integration"
    sources={{
        light: '/img/get-started/sap-s4hana-wso2-integration-guide/run-and-test-the-integration-light.gif',
        dark: '/img/get-started/sap-s4hana-wso2-integration-guide/run-and-test-the-integration-dark.gif',
    }}
/>
