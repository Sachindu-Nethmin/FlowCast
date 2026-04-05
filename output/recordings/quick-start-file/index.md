## Step 1: Create the Project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `FileTracker`.
4. Set **Project Name** to `Quick_Start`.
5. Select **Browse**.
6. Select the project location and select **Open**.
7. Select **Create Integration**.

<ThemedImage
    alt="Create the Project"
    sources={{
        light: '/img/get-started/quick-start-file/create-the-project-light.gif',
        dark: '/img/get-started/quick-start-file/create-the-project-dark.gif',
    }}
/>

## Step 2: Add a File Integration Artifact

1. Select **FileTracker**.
2. In the design view, select **+ Add Artifact**.
3. Select **Local Files** under **File Integration**.
4. Set path **/tmp**.
5. Set recursive to **False**.
6. Select **Create**.

<ThemedImage
    alt="Add a File Integration Artifact"
    sources={{
        light: '/img/get-started/quick-start-file/add-a-file-integration-artifact-light.gif',
        dark: '/img/get-started/quick-start-file/add-a-file-integration-artifact-dark.gif',
    }}
/>

## Step 3: Tracking modified files

1. Select **File Handler**.
2. Select **onModify**.
3. Select **Create**.
2. Select **onModify**.
4. Select **+** .
5. Search **printInfo** and select **printInfo**.
6. Set **Msg** to `File modified`.
7. Select **Save**.

<ThemedImage
    alt="Tracking modified files"
    sources={{
        light: '/img/get-started/quick-start-file/tracking-modified-files-light.gif',
        dark: '/img/get-started/quick-start-file/tracking-modified-files-dark.gif',
    }}
/>

## Step 4: Run and Test

1. Select **Run** in the toolbar.
2. open new terminal and type `echo "test" > /tmp/testfile.txt` to test.

<ThemedImage
    alt="Run and Test"
    sources={{
        light: '/img/get-started/quick-start-file/run-and-test-light.gif',
        dark: '/img/get-started/quick-start-file/run-and-test-dark.gif',
    }}
/>
