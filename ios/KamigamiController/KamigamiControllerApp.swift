import SwiftUI

@main
struct KamigamiControllerApp: App {
    @StateObject private var ble = KamigamiBLEManager()
    @StateObject private var tilt = TiltController()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(ble)
                .environmentObject(tilt)
                .preferredColorScheme(.dark)
                .tint(Theme.cyan)
        }
        .onChange(of: scenePhase) { phase in
            // Never leave the robot running when the app is not in the foreground.
            if phase != .active {
                tilt.stop()
                if ble.isReady { ble.emergencyStop() }
            }
        }
    }
}

enum Theme {
    static let cyan = Color(red: 0, green: 0.898, blue: 1)
    static let purple = Color(red: 0.486, green: 0.302, blue: 1)
    static let panel = Color(white: 0.11)
    static let stroke = Color(white: 0.22)
    static let danger = Color(red: 0.86, green: 0.15, blue: 0.15)
}
