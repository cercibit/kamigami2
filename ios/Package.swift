// swift-tools-version:5.9
// Swift package exposing the platform-independent protocol + behavior core of the
// iOS app so it can be unit tested with `swift test` (macOS or Linux).
// The iOS app itself is built from KamigamiController.xcodeproj.
import PackageDescription

let package = Package(
    name: "KamigamiCore",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [
        .library(name: "KamigamiCore", targets: ["KamigamiCore"]),
    ],
    targets: [
        .target(name: "KamigamiCore", path: "KamigamiController/Core"),
        .testTarget(name: "KamigamiCoreTests", dependencies: ["KamigamiCore"], path: "Tests/KamigamiCoreTests"),
    ]
)
