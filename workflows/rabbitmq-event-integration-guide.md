## Step 1: Create a New Integration Project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `OrderProcessor`.
4. Set **Project Name** to `Quick_Start`.
5. Select **Browse**.
6. Select the project location and select **Open**.
7. Select **Create Integration**.

## Step 2: Add a RabbitMQ Event Integration Artifact

1. Select **OrderProcessor**.
2. In the design view, select **Add Artifact**.
3. Select **RabbitMQ** under Event Integration.

## Step 3: Configure the RabbitMQ Connection

1. Set **Queue Name** to `Orders`.
2. Set **Host** to `localhost`.
3. Set **Port** to `5672`.
4. Select **Create**.

## Step 4: Add Message Processing Logic

1. Select **+ Add Handler**.
2. Select **onMessage**.
3. Select **Save**.
4. Select **+** inside the resource flow.
5. Select **Call Function**.
6. Select **printInfo**.
7. Set **Msg** to `Received order`.
8. Select **Save**.

## Step 5: Run and Test the Integration

1. Select **Run**.
2. The integration starts and listens for messages on the `Orders` queue.
3. Publish a test message to the RabbitMQ `Orders` queue to see the log output.
