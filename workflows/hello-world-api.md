## Step 1: Create the integration

1. Open WSO2 Integrator.
2. Select **Create New Integration**.
3. Set **Integration Name** to `HelloWorldAPI`.
4. Set **Project Name** to `integration-as-api`.
5. Select **Create Integration**.

## Step 2: Add an HTTP service

1. Select **HelloWorldAPI**.
2. Select **+ Add Artifact**.
3. Select **HTTP Service** under **Integration as API**.
4. Keep Service Contract as Design From Scratch.
5. Set **Service Base Path** to `/hello`.
6. Select **Create**.

## Step 3: Add a resource

1. Select **+ Add Resource**.
2. Select **GET**.
3. Set **Resource Path** to `greeting`.
4. Select **Save**.

## Step 4: Connect to an external API

1. Select **+** inside the resource flow.
2. Select **Add Connection**.
3. Select **HTTP**.
4. Set **Url** to `https://apis.wso2.com/zvdz/mi-qsg/v1.0`.
5. Set **Connection Name** to `externalApi`.
6. Select **Save Connection**.

## Step 5: Call the external API

1. Select **+** inside the resource flow.
2. Select **externalApi**.
3. Select **Get**.
4. Set **Path** to `/`.
5. Set **Result** to `response`.
6. Set **Target Type** to `json`.
7. Select **Save**.

## Step 6: Return the response

1. Select **+** inside the resource flow after the external API call node.
2. Select **Return**.
3. Set **Expression** to `response`.
4. Select **Save**.

## Step 7: Run and test

1. Select **Run**.
2. Select **Test**.
3. Select **Execute**.
4. Confirm the response shows `200 OK` with a `Hello World` body.