## Step 1: Create the project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `Hello_World_API`.
4. Set **Project Name** to `Quick_Start`.
5. Select **Browse**.
6. Select the project location and select **Open**.
7. Select **Create Integration**.

<ThemedImage
    alt="Create the project"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-api/create-the-project-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-api/create-the-project-dark.gif'),
    }}
/>

## Step 2: Add an HTTP service

1. Select **Hello_World_API**.
2. In the design view, select **Add Artifact**.
3. Select **HTTP Service** under **Integration as API**.
4. Keep **Service contract** as **Design from scratch**.
5. Set **Service Base Path** to `/hello`.
6. Select **Create**.

<ThemedImage
    alt="Add an HTTP service"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-api/add-an-http-service-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-api/add-an-http-service-dark.gif'),
    }}
/>

## Step 3: Design the integration flow

1. In the HTTP service design view, select **+ Add Resources**.
2. Select **GET**.
3. Set the **Resource Path** to `greeting`.
4. Select **Save**.
5. Select **+** inside the resource flow.
6. Select **Add Connection**.
7. Select **HTTP Service**.
8. Set the **Url** to `https://apis.wso2.com/zvdz/mi-qsg/v1.0`.
9. Set the **Connection Name** to `externalApi` and select **Save Connection**.
10. Select **externalApi**.

<ThemedImage
    alt="Design the integration flow"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-api/design-the-integration-flow-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-api/design-the-integration-flow-dark.gif'),
    }}
/>

## Step 4: Configure HTTP

1. Select **Get** under **externalApi**.
2. Set **Path** to `/`.
3. Set **Result** to `response`
4. Set **Target Type** to `json`.
5. Select **Save**.

<ThemedImage
    alt="Configure HTTP"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-api/configure-http-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-api/configure-http-dark.gif'),
    }}
/>

## Step 5: Return the response

1. Select **+** inside the resource flow.
2. Select **Return** node.
3. Set **Expression** to `response`.
4. Select **Save**.

<ThemedImage
    alt="Return the response"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-api/return-the-response-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-api/return-the-response-dark.gif'),
    }}
/>

## Step 6: Run and test

1. Select **Run**.
2. Select **Try It**.
3. Select **Run All**.
4. The automation executes immediately and give 200 response "Hello World".

<ThemedImage
    alt="Run and test"
    sources={{
        light: useBaseUrl('/img/get-started/quick-start-api/run-and-test-light.gif'),
        dark: useBaseUrl('/img/get-started/quick-start-api/run-and-test-dark.gif'),
    }}
/>
