// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "FlowCastStudio",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "FlowCastStudio",
            path: "Sources/FlowCastStudio"
        )
    ]
)
