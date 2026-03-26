## Step 1: Create the project

1. Open WSO2 Integrator.
2. Select **Create New Integration**.
3. Set the **Integration Name** to `Hello_World_API`.
4. Select **Browse**.
5. Select the project location and select **Open**.
6. Select **Create Integration**.

## Step 2: Add an HTTP service

1. In the design view, select **Add Artifact**.
2. Select **HTTP Service** under **Integration as API**.
3. Keep **Service contract** as **Design from scratch**.
4. Set **Service base path** to `/hello`.
5. Select **Create**.

## Step 3: Design the integration flow

1. In the HTTP service design view, select **+ Add Resouses** resource.
2. Select **GET**.
2. Set the **resource path** to `greeting`.
3. Select **Save**.
4. Select **+** inside the resource flow.
5. Select **Add Connection**.
6. Select **HTTP**.

## Step 4: Configure HTTP

1. Set the **Url** to `https://apis.wso2.com/zvdz/mi-qsg/v1.0`.
2. Set the **Connection Name** to `externalApi` and select **Save Connection**.
3. Select **externalApi**.
4. Select **GET**.
4. Set **Path** to `/`.
5. Set **Result** to `response` and set **Target Type** to `json`.
6. Select **Save**.
7. Select **+** inside the resource flow.
8. Select **Return** node.
9. Set the **return expression** to `response`.
10. Select **Save**.
