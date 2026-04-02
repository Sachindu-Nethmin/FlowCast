## Step 1: Create a New Integration Project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `OrderProcessor`.
4. Set **Project Name** to `Quick_Start`.
5. Select **Browse**.
6. Select the project location and select **Open**.
7. Select **Create Integration**.

<ThemedImage
    alt="Create a New Integration Project"
    sources={{
        light: '/img/get-started/rabbitmq-event-integration-guide/create-a-new-integration-project-light.gif',
        dark: '/img/get-started/rabbitmq-event-integration-guide/create-a-new-integration-project-dark.gif',
    }}
/>

## Step 2: Add a RabbitMQ Event Integration Artifact

1. Select **OrderProcessor**.
2. In the design view, select **Add Artifact**.
3. Select **RabbitMQ** under Event Integration.

<ThemedImage
    alt="Add a RabbitMQ Event Integration Artifact"
    sources={{
        light: '/img/get-started/rabbitmq-event-integration-guide/add-a-rabbitmq-event-integration-artifact-light.gif',
        dark: '/img/get-started/rabbitmq-event-integration-guide/add-a-rabbitmq-event-integration-artifact-dark.gif',
    }}
/>

## Step 3: Configure the RabbitMQ Connection

1. Set **Queue Name** to `Orders`.
2. Set **Host** to `localhost`.
3. Set **Port** to `5672`.
4. Select **Create**.

<ThemedImage
    alt="Configure the RabbitMQ Connection"
    sources={{
        light: '/img/get-started/rabbitmq-event-integration-guide/configure-the-rabbitmq-connection-light.gif',
        dark: '/img/get-started/rabbitmq-event-integration-guide/configure-the-rabbitmq-connection-dark.gif',
    }}
/>

## Step 4: Add Message Processing Logic

1. Select **+ Add Handler**.
2. Select **onMessage**.
3. Select **Save**.
4. Select **+** inside the resource flow.
5. Select **Call Function**.
6. Select **printInfo**.
7. Set **Msg** to `Received order`.
8. Select **Save**.

<ThemedImage
    alt="Add Message Processing Logic"
    sources={{
        light: '/img/get-started/rabbitmq-event-integration-guide/add-message-processing-logic-light.gif',
        dark: '/img/get-started/rabbitmq-event-integration-guide/add-message-processing-logic-dark.gif',
    }}
/>

## Step 5: Run and Test the Integration

1. Select **Run**.
2. The integration starts and listens for messages on the `Orders` queue.
3. Publish a test message to the RabbitMQ `Orders` queue to see the log output.

<ThemedImage
    alt="Run and Test the Integration"
    sources={{
        light: '/img/get-started/rabbitmq-event-integration-guide/run-and-test-the-integration-light.gif',
        dark: '/img/get-started/rabbitmq-event-integration-guide/run-and-test-the-integration-dark.gif',
    }}
/>
