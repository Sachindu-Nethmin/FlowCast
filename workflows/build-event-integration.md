## Step 1: Create the integration

1. Open WSO2 Integrator.
2. Select **Skip for now**.
3. Select **Create New Integration**.
4. Set **Integration Name** to `OrderProcessor`.
5. Set **Project Name** to `event-integration`.
6. Select **Create Integration**.

## Step 2: Add a RabbitMQ event listener

1. Select **OrderProcessor**.
2. Select **+ Add Artifact**.
3. Select **RabbitMQ** under **Event Integration**.
4. Set **Host** to `localhost`.
5. Set **Port** to `5672`.
6. Set **Queue Name** to `Orders`.
7. Select **Create**.

## Step 3: Add onMessage event handler

1. In the RabbitMQ service design view, select **+ Add Handler**.
2. Select **onMessage**.
3. Select **Save**.

## Step 4: Add message processing logic

1. Select **+** inside the resource flow.
2. Select **Call Function**.
3. Select **printInfo** under **log**.
4. Set **Msg** to `Received order`.
5. Select **Save**.

## Step 5: Run and test the integration

1. Select **Run** in the toolbar.
2. Wait 10 seconds.
3. Run the shell command `tools/rmq_publish.sh Orders order-1001` to publish a message to the Orders queue.
4. Wait 8 seconds.
5. Confirm the integration log displays `Received order`.
