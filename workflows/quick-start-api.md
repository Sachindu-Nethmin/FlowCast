## Step 1: Create the project

1. Open WSO2 Integrator.
2. Select **Create New Integration**.
3. Enter the integration name (for example, `Hello_World_API`).
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
7. Set the base **URL** to `https://apis.wso2.com/zvdz/mi-qsg/v1.0`.
8. Set the **Connection Name** to `externalApi` and save.
9. Add the `get` action from the `externalApi` connection.
10. Set the action path to `/`.
11. Store the action result in a variable named `response` with type `json`.
12. Add a **Return** node.
13. Set the return expression to `response`.
