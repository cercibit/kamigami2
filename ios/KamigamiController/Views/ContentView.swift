import CoreBluetooth
import SwiftUI

struct ContentView: View {
    @EnvironmentObject var ble: KamigamiBLEManager

    var body: some View {
        Group {
            if ble.isReady {
                ControlView()
            } else {
                ConnectView()
            }
        }
        .animation(.default, value: ble.connectionState)
    }
}

// MARK: - Connect / scan screen

struct ConnectView: View {
    @EnvironmentObject var ble: KamigamiBLEManager

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 14) {
                        Image(systemName: "ladybug.fill")
                            .font(.system(size: 34))
                            .foregroundStyle(Theme.cyan)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Wake your Kamigami").font(.headline)
                            Text("Unplug USB (the robot doesn't advertise while charging) and press its power button. It will show up below.")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 6)
                }

                if let warning = bluetoothWarning {
                    Section {
                        Label(warning, systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange)
                    }
                }

                if ble.connectionState != .disconnected {
                    Section {
                        HStack {
                            ProgressView()
                            Text(ble.connectionState.label).padding(.leading, 8)
                            Spacer()
                            Button("Cancel") { ble.disconnect() }
                        }
                    }
                }

                Section {
                    if ble.discovered.isEmpty {
                        HStack {
                            if ble.isScanning { ProgressView().padding(.trailing, 8) }
                            Text(ble.isScanning ? "Searching…" : "No robots found")
                                .foregroundStyle(.secondary)
                        }
                    }
                    ForEach(ble.discovered.sorted(by: { $0.rssi > $1.rssi })) { robot in
                        Button {
                            ble.connect(robot)
                        } label: {
                            HStack {
                                Image(systemName: "dot.radiowaves.left.and.right")
                                    .foregroundStyle(Theme.purple)
                                VStack(alignment: .leading) {
                                    Text(robot.name).font(.body.weight(.semibold))
                                    Text(String(robot.id.uuidString.prefix(8)) + "…")
                                        .font(.caption.monospaced())
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                SignalBars(rssi: robot.rssi)
                            }
                        }
                        .disabled(ble.connectionState != .disconnected)
                    }
                } header: {
                    Text("Nearby robots")
                }

                if !ble.log.isEmpty {
                    Section("Log") {
                        ForEach(ble.log.prefix(8)) { entry in
                            Text(entry.text).font(.caption.monospaced()).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .navigationTitle("Kamigami")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(ble.isScanning ? "Stop" : "Scan") {
                        ble.isScanning ? ble.stopScan() : ble.startScan()
                    }
                    .disabled(ble.bluetoothState != .poweredOn)
                }
            }
            .refreshable { ble.startScan() }
        }
    }

    private var bluetoothWarning: String? {
        switch ble.bluetoothState {
        case .poweredOff: return "Bluetooth is turned off."
        case .unauthorized: return "Bluetooth permission denied. Enable it in Settings › Kamigami."
        case .unsupported: return "This device does not support Bluetooth LE."
        default: return nil
        }
    }
}

struct SignalBars: View {
    let rssi: Int
    private var level: Int {
        switch rssi {
        case (-60)...: return 4
        case (-70)...: return 3
        case (-80)...: return 2
        default: return 1
        }
    }
    var body: some View {
        HStack(alignment: .bottom, spacing: 2) {
            ForEach(1...4, id: \.self) { i in
                RoundedRectangle(cornerRadius: 1)
                    .fill(i <= level ? Theme.cyan : Color.gray.opacity(0.3))
                    .frame(width: 4, height: CGFloat(4 + i * 3))
            }
        }
        .accessibilityLabel("Signal \(rssi) dBm")
    }
}

// MARK: - Main control screen

struct ControlView: View {
    @EnvironmentObject var ble: KamigamiBLEManager

    var body: some View {
        VStack(spacing: 0) {
            StatusBar()
            if ble.isUpsideDown && ble.safetyCutoffEnabled {
                Label("Robot is upside down — motors disabled until it is set upright.",
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(10)
                    .frame(maxWidth: .infinity)
                    .background(Theme.danger)
            }
            TabView {
                DriveView()
                    .tabItem { Label("Drive", systemImage: "gamecontroller.fill") }
                LightsIRView()
                    .tabItem { Label("Lights & IR", systemImage: "lightbulb.fill") }
                AutonomousView()
                    .tabItem { Label("Cockroach", systemImage: "ant.fill") }
                TelemetryView()
                    .tabItem { Label("Sensors", systemImage: "waveform.path.ecg") }
            }
        }
    }
}

struct StatusBar: View {
    @EnvironmentObject var ble: KamigamiBLEManager

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(ble.robotName ?? "Kamigami").font(.headline)
                Text(ble.firmware.map { "FW \($0)" } ?? ble.connectionState.label)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            if let b = ble.battery {
                Label("\(b)%", systemImage: batteryIcon(b))
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(b < 20 ? Color.red : Color.primary)
            }
            Button(role: .destructive) {
                ble.emergencyStop()
            } label: {
                Text("STOP")
                    .font(.subheadline.weight(.heavy))
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(Theme.danger, in: Capsule())
                    .foregroundStyle(.white)
            }
            .accessibilityLabel("Emergency stop")
            Menu {
                Button { ble.disconnect() } label: { Label("Disconnect", systemImage: "xmark.circle") }
            } label: {
                Image(systemName: "ellipsis.circle").font(.title3)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 10)
        .background(.bar)
    }

    private func batteryIcon(_ b: Int) -> String {
        switch b {
        case 88...: return "battery.100"
        case 63...: return "battery.75"
        case 38...: return "battery.50"
        case 13...: return "battery.25"
        default: return "battery.0"
        }
    }
}
