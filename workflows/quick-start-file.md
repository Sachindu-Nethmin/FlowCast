## Step 1: Create the Project

1. Open WSO2 Integrator.
2. Select **Create**.
3. Set **Integration Name** to `FileProcessor`.
4. Select **Browse**.
5. Select the project location and select **Open**.
6. Select **Create Integration**.

## Step 2: Add a File Integration Artifact

1. Select **FileProcessor**.
2. In the design view, select **+ Add Artifact**.
3. Select **Directory Service** (for local files) or **FTP Service** (for remote files) under **Integration as API**.
4. Configure the directory path to watch.
5. Select **Create**.

## Step 3: Process Incoming Files

Add logic to read and process files when they arrive:

```ballerina
import ballerina/file;
import ballerina/io;
import ballerina/log;

listener file:Listener dirListener = new ({
    path: "/data/inbox",
    recursive: false
});

service on dirListener {
    remote function onCreate(file:FileEvent event) returns error? {
        string filePath = event.name;
        log:printInfo("New file detected", path = filePath);

        // Read CSV content
        string content = check io:fileReadString(filePath);
        log:printInfo("File content", content = content);

        // Process and write output
        check io:fileWriteString("/data/processed/" + filePath, content);
    }
}
```

## Step 4: Run and Test

1. Select **Run** in the toolbar.
2. Drop a file into the watched directory (`/data/inbox`).
3. Verify the processed output appears in `/data/processed/`.
