## Step 1: Create a New Integration Project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `NewsAlertSystem`.
4. Set **Project Name** to `NewsAlert`.
5. Select **Browse**.
6. Select the project location and select **Open**.
7. Select **Create Integration**.

<ThemedImage
    alt="Create a New Integration Project"
    sources={{
        light: '/img/get-started/news-alert-system-guide/create-a-new-integration-project-light.gif',
        dark: '/img/get-started/news-alert-system-guide/create-a-new-integration-project-dark.gif',
    }}
/>

## Step 2: Add an GraphQL Service Artifact

1. Select **NewsAlertSystem**.
2. In the design view, select **Add Artifact**.
3. Select **GraphQL Service** under **Integration as API**.
4. Set **Base path** to `/news`.
5. Set **Port** to `8080`.
6. Select **Create**.

<ThemedImage
    alt="Add an GraphQL Service Artifact"
    sources={{
        light: '/img/get-started/news-alert-system-guide/add-an-graphql-service-artifact-light.gif',
        dark: '/img/get-started/news-alert-system-guide/add-an-graphql-service-artifact-dark.gif',
    }}
/>

## Step 3: Configure the GraphQL Service Logic

1. Select **+** next to the **Query** section.

<ThemedImage
    alt="Configure the GraphQL Service Logic"
    sources={{
        light: '/img/get-started/news-alert-system-guide/configure-the-graphql-service-logic-light.gif',
        dark: '/img/get-started/news-alert-system-guide/configure-the-graphql-service-logic-dark.gif',
    }}
/>

## Step 4: Create News Data Types

1. Select **** view and select the `main.bal` file.
2. Set the in-memory storage array to `News[] newsStorage = [];`.
3. Set the `@graphql:ServiceConfig` annotation above the service declaration to enable the GraphiQL explorer.
4. Select the **Project Design** view.

<ThemedImage
    alt="Create News Data Types"
    sources={{
        light: '/img/get-started/news-alert-system-guide/create-news-data-types-light.gif',
        dark: '/img/get-started/news-alert-system-guide/create-news-data-types-dark.gif',
    }}
/>

## Step 5: Create News Data Types

1. Select the **Types** icon on the left-side Activity Bar.
2. Select **+ Add Type**.
3. Set **Kind** to `Record`.
4. Set **Name** to `News`.
5. Select **+** to add a field.
6. Set **Field Name** to `Headline` and set **Type** to `string`.
7. Select **+** to add a field.
8. Set **Field Name** to `Content` and set **Type** to `string`.
9. Select **Save**.

<ThemedImage
    alt="Create News Data Types"
    sources={{
        light: '/img/get-started/news-alert-system-guide/create-news-data-types-light.gif',
        dark: '/img/get-started/news-alert-system-guide/create-news-data-types-dark.gif',
    }}
/>

## Step 6: Define the allNews Query Operation

1. Select the **GraphQL Diagram** view for the `/news` service.
2. Select **+ Create Operations**.
3. Select **+** next to the **Query** section.
4. Set **Field Name** to `allNews`.
5. Set **Field Type** to `News[]`.
6. Select **Save**.
7. Select the **Edit** icon next to the `allNews` query.
8. Select **+** on the flow and select **Return**.
9. Set **Expression** to `newsStorage`.
10. Select **Save**.

<ThemedImage
    alt="Define the allNews Query Operation"
    sources={{
        light: '/img/get-started/news-alert-system-guide/define-the-allnews-query-operation-light.gif',
        dark: '/img/get-started/news-alert-system-guide/define-the-allnews-query-operation-dark.gif',
    }}
/>

## Step 7: Define the publishNews Mutation

1. Select **+** next to the **Mutation** section.
2. Set **Field Name** to `publishNews`.
3. Select **+ Add Argument**.
4. Set **Argument Type** to `string` and set **Argument Name** to `Headline`.
5. Select **Add**.
6. Select **+ Add Argument**.
7. Set **Argument Type** to `string` and set **Argument Name** to `Content`.
8. Select **Add**.
9. Set **Field Type** to `News`.
10. Select **Save**.

<ThemedImage
    alt="Define the publishNews Mutation"
    sources={{
        light: '/img/get-started/news-alert-system-guide/define-the-publishnews-mutation-light.gif',
        dark: '/img/get-started/news-alert-system-guide/define-the-publishnews-mutation-dark.gif',
    }}
/>

## Step 8: Implement the publishNews Mutation Logic

1. Select the **Edit** icon next to the `publishNews` mutation.
2. Select **+** on the flow and select **Declare Variable**.
3. Set **Name** to `newNews` and set **Type** to `News`.
4. Select **Expression** and select **Record Configuration**.
5. Set **Headline** to the `Headline` input and set **Content** to the `Content` input.
6. Select **Save**.
7. Select **+** below the variable and select **Return**.
8. Set **Expression** to `newNews`.
9. Select **Save**.

<ThemedImage
    alt="Implement the publishNews Mutation Logic"
    sources={{
        light: '/img/get-started/news-alert-system-guide/implement-the-publishnews-mutation-logic-light.gif',
        dark: '/img/get-started/news-alert-system-guide/implement-the-publishnews-mutation-logic-dark.gif',
    }}
/>

## Step 9: Complete the Mutation Logic in Code

1. Select the **Explorer** view and select the `main.bal` file.
2. Set `newsStorage.push(newNews);` immediately before the `return` statement in `remote function publishNews`.
3. Select **Save**.

<ThemedImage
    alt="Complete the Mutation Logic in Code"
    sources={{
        light: '/img/get-started/news-alert-system-guide/complete-the-mutation-logic-in-code-light.gif',
        dark: '/img/get-started/news-alert-system-guide/complete-the-mutation-logic-in-code-dark.gif',
    }}
/>

## Step 10: Create the NewsGenerator Service Class

1. Select the **Types** icon on the left-side Activity Bar.
2. Select **+ Add Type**.
3. Set **Kind** to `Service Class`.
4. Set **Name** to `NewsGenerator`.
5. Select **Save**.
6. Select the `NewsGenerator` class node.
7. Select **+ Variable**.
8. Set **Variable Name** to `newsItems` and set **Variable Type** to `News[]`.
9. Select **Save**.
10. Select **+ Method** and select **Remote**.
11. Set **Function Name** to `next`.
12. Set **Return Type** to `record {| News value; |}|error?`.
13. Select **Save**.

<ThemedImage
    alt="Create the NewsGenerator Service Class"
    sources={{
        light: '/img/get-started/news-alert-system-guide/create-the-newsgenerator-service-class-light.gif',
        dark: '/img/get-started/news-alert-system-guide/create-the-newsgenerator-service-class-dark.gif',
    }}
/>

## Step 11: Finalize the Service Class in Code

1. Select the **Explorer** view and select the `types.bal` file.
2. Set the `newsItems` variable to `private`.
3. Set the `init` function to `isolated function init(News[] newsItems) { self.newsItems = newsItems.clone(); }`.
4. Select **Save**.

<ThemedImage
    alt="Finalize the Service Class in Code"
    sources={{
        light: '/img/get-started/news-alert-system-guide/finalize-the-service-class-in-code-light.gif',
        dark: '/img/get-started/news-alert-system-guide/finalize-the-service-class-in-code-dark.gif',
    }}
/>

## Step 12: Implement the NewsGenerator Stream Logic

1. Select the **Edit** icon next to the `next` method in the `NewsGenerator` class designer.
2. Select **+** on the flow and select **If**.
3. Set **Condition** to `self.newsItems.length() == 0`.
4. Select **Save**.
5. Select **+** inside the **If** block and select **Return**.
6. Set **Expression** to `()`.
7. Select **Save**.

<ThemedImage
    alt="Implement the NewsGenerator Stream Logic"
    sources={{
        light: '/img/get-started/news-alert-system-guide/implement-the-newsgenerator-stream-logic-light.gif',
        dark: '/img/get-started/news-alert-system-guide/implement-the-newsgenerator-stream-logic-dark.gif',
    }}
/>

## Step 13: Implement the Stream Iteration Logic

1. Select **+** after the **If** block in the `next` method flow.
2. Select **Call Function** and select `sleep` under `lang.runtime`.
3. Set **Seconds** to `2`.
4. Select **Save**.
5. Select **+** below the sleep statement and select **Declare Variable**.
6. Set **Name** to `currentNews` and set **Type** to `News`.
7. Set **Expression** to `self.newsItems.shift()`.
8. Select **Save**.
9. Select **+** at the end of the flow and select **Return**.
10. Set **Expression** to `{value: currentNews}`.
11. Select **Save**.

<ThemedImage
    alt="Implement the Stream Iteration Logic"
    sources={{
        light: '/img/get-started/news-alert-system-guide/implement-the-stream-iteration-logic-light.gif',
        dark: '/img/get-started/news-alert-system-guide/implement-the-stream-iteration-logic-dark.gif',
    }}
/>

## Step 14: Define the GraphQL Subscription Operation

1. Select the **GraphQL Diagram** view for the `/news` service.
2. Select **+** next to the **Subscription** section.
3. Set **Field Name** to `generateNews`.
4. Set **Field Type** to `stream`.
5. Select **Save**.

<ThemedImage
    alt="Define the GraphQL Subscription Operation"
    sources={{
        light: '/img/get-started/news-alert-system-guide/define-the-graphql-subscription-operation-light.gif',
        dark: '/img/get-started/news-alert-system-guide/define-the-graphql-subscription-operation-dark.gif',
    }}
/>

## Step 15: Finalize the Subscription Implementation in Code

1. Select the **Explorer** view and select the `types.bal` file.
2. Set the `next` method of `NewsGenerator` to `public isolated`.
3. Select the `main.bal` file.
4. Set `resource function subscribe generateNews` to initialize `NewsGenerator` with `newsStorage`, create a new `stream`, and return it.
5. Select **Save**.

<ThemedImage
    alt="Finalize the Subscription Implementation in Code"
    sources={{
        light: '/img/get-started/news-alert-system-guide/finalize-the-subscription-implementation-in-code-light.gif',
        dark: '/img/get-started/news-alert-system-guide/finalize-the-subscription-implementation-in-code-dark.gif',
    }}
/>

## Step 16: Run and Test the Service

1. Select **Run** on the Project Design view.
2. Select the link in the terminal or select **Test** to open the GraphiQL interface.
3. Select the **publishNews** mutation to add a news item.
4. Select the **generateNews** subscription to receive real-time news updates.
5. Select the **allNews** query to verify stored news items.

<ThemedImage
    alt="Run and Test the Service"
    sources={{
        light: '/img/get-started/news-alert-system-guide/run-and-test-the-service-light.gif',
        dark: '/img/get-started/news-alert-system-guide/run-and-test-the-service-dark.gif',
    }}
/>
