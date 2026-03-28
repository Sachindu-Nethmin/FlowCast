## Step 1: Create the project

1. Open WSO2 Integrator.
<<<<<<< HEAD
<<<<<<< HEAD
2. Select **Create**.
3. Set **Integration Name** to `Hello_World_API`.
=======
2. Select **Create New Integration**.
<<<<<<< HEAD
3. Enter the integration name (for example, `HelloWorld`).
>>>>>>> 7d1f240 (improved text files)
=======
3. Enter the integration name (for example, `Hello_World_API`).
>>>>>>> b856107 (1.0)
=======
2. Select **Create**.
3. Set **Integration Name** to `Hello_World_API`.
>>>>>>> 4ae97b6 (Light)
4. Select **Browse**.
5. Select the project location and select **Open**.
6. Select **Create Integration**.

## Step 2: Add an HTTP service

<<<<<<< HEAD
1. Select **Hello_World_API**.
2. In the design view, select **Add Artifact**.
3. Select **HTTP Service** under **Integration as API**.
4. Keep **Service contract** as **Design from scratch**.
5. Set **Service base path** to `/hello`.
6. Select **Create**.
=======
1. In the design view, select **Add Artifact**.
2. Select **HTTP Service** under **Integration as API**.
3. Keep **Service contract** as **Design from scratch**.
4. Set **Service base path** to `/hello`.
5. Select **Create**.
>>>>>>> 9e44480 (Light (#6))

## Step 3: Design the integration flow

<<<<<<< HEAD
<<<<<<< HEAD
=======
>>>>>>> b856107 (1.0)
1. In the HTTP service design view, select **+ Add Resouses** resource.
2. Select **GET**.
2. Set the **resource path** to `greeting`.
3. Select **Save**.
4. Select **+** inside the resource flow.
5. Select **Add Connection**.
6. Select **HTTP**.
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
1. Set the **Url** to `https://apis.wso2.com/zvdz/mi-qsg/v1.0`.
2. Set the **Connection Name** to `externalApi` and select **Save Connection**.
3. Select **externalApi**.

## Step 4: Configure HTTP

1. Select **Get**.
2. Set **Path** to `/`.
3. Set **Result** to `response`
4. Set **Target Type** to `json`.
5. Select **Target Type**.
5. Select **Save**.

## Step 5: Return the response

1. Select **+** inside the resource flow.
2. Select **Return** node.
3. Set **Expression** to `response`.
4. Select **Save**.

## Step 6: Run and test

1. Select **Run**.
2. Select **Try it**.
2. Select **Execute Cell**.  
4. The automation executes immediately and give 200 response "Hello World".
=======
=======
>>>>>>> 59739ff (1.0)
=======
=======
>>>>>>> 1d91d33 (Add api md)
=======
>>>>>>> 4d665b4 (1.1)
>>>>>>> 37cea1a (1.1)

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
<<<<<<< HEAD
<<<<<<< HEAD
>>>>>>> 9e44480 (Light (#6))
=======
=======
>>>>>>> 37cea1a (1.1)
=======
1. In the HTTP service design view, add a **GET** resource.
2. Set the resource path to `/greeting` and save.
3. Select **+** inside the resource flow.
4. Add a new **HTTP** connection.
5. Set the base URL to `https://apis.wso2.com/zvdz/mi-qsg/v1.0`.
6. Name the connection `externalApi` and save.
7. Add the `get` action from the `externalApi` connection.
8. Set the action path to `/`.
9. Store the action result in a variable named `response` with type `json`.
10. Add a **Return** node.
11. Set the return expression to `response`.
>>>>>>> 7d1f240 (improved text files)
<<<<<<< HEAD
>>>>>>> ee262bc (improved text files)
=======
=======
7. Set the base **URL** to `https://apis.wso2.com/zvdz/mi-qsg/v1.0`.
8. Set the **Connection Name** to `externalApi` and save.
9. Add the `get` action from the `externalApi` connection.
10. Set the action path to `/`.
11. Store the action result in a variable named `response` with type `json`.
12. Add a **Return** node.
13. Set the return expression to `response`.
>>>>>>> b856107 (1.0)
<<<<<<< HEAD
>>>>>>> 59739ff (1.0)
=======
=======
>>>>>>> 4d665b4 (1.1)
<<<<<<< HEAD
>>>>>>> 37cea1a (1.1)
=======
=======
1. Set the **Url** to `https://apis.wso2.com/zvdz/mi-qsg/v1.0`.
2. Set the **Connection Name** to `externalApi` and select **Save Connection**.
3. Select **externalApi**.

## Step 4: Configure HTTP

1. Select **Get**.
2. Set **Path** to `/`.
3. Set **Result** to `response`
4. Set **Target Type** to `json`.
5. Select **Save**.

## Step 5: Return the response

1. Select **+** inside the resource flow.
2. Select **Return** node.
3. Set the **return expression** to `response`.
4. Select **Save**.
>>>>>>> 331e4f5 (Add api md)
>>>>>>> 1d91d33 (Add api md)
