import SwiftUI

struct AutonomousView: View {
    @EnvironmentObject var ble: KamigamiBLEManager

    var body: some View {
        Form {
            Section {
                VStack(spacing: 14) {
                    Image(systemName: ble.cockroachActive ? "ant.fill" : "ant")
                        .font(.system(size: 54))
                        .foregroundStyle(ble.cockroachActive ? Theme.cyan : Color.secondary)
                        .symbolEffectIfAvailable(active: ble.cockroachActive)
                    Text(ble.cockroachActive ? ble.cockroachStatus : "Idle")
                        .font(.headline)
                    if let ev = ble.cockroachLastEvent {
                        Text("Last event: \(ev)").font(.caption).foregroundStyle(.secondary)
                    }
                    Button {
                        ble.cockroachActive ? ble.stopCockroach() : ble.startCockroach()
                    } label: {
                        Text(ble.cockroachActive ? "Stop Cockroach Mode" : "Start Cockroach Mode")
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 6)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(ble.cockroachActive ? Theme.danger : Theme.purple)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
            } footer: {
                Text("Darts forward, detects collisions with the 6-axis IMU, freezes for 2 s, backs up, turns randomly and runs again. Touching any drive control takes over.")
            }

            Section {
                VStack(alignment: .leading) {
                    HStack {
                        Text("Speed")
                        Spacer()
                        Text("\(ble.cockroachSpeed)").monospacedDigit().foregroundStyle(.secondary)
                    }
                    Slider(value: Binding(get: { Double(ble.cockroachSpeed) },
                                          set: { ble.cockroachSpeed = Int($0) }),
                           in: 15...63, step: 1)
                }
                VStack(alignment: .leading) {
                    HStack {
                        Text("Collision threshold")
                        Spacer()
                        Text(String(format: "%.2fg", ble.bumpThreshold))
                            .monospacedDigit().foregroundStyle(.secondary)
                    }
                    Slider(value: $ble.bumpThreshold, in: 0.20...0.90, step: 0.05)
                    Text(String(format: "Stops at shock > %.2fg or yaw > %.0f°/s",
                                2.6 + ble.bumpThreshold * 2.0, 240 + ble.bumpThreshold * 200))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } header: {
                Text("Tuning")
            } footer: {
                Text("Lower = gentle taps stop the robot. Higher = only hard impacts. Normal walking strides peak near 2.5g.")
            }

            Section {
                Toggle("Upside-down safety cutoff", isOn: $ble.safetyCutoffEnabled)
                Toggle("Auto-reconnect to last robot", isOn: $ble.autoReconnect)
            } header: {
                Text("Safety")
            } footer: {
                Text("When the robot is picked up and flipped (az < −0.45g), motors are halted and drive commands ignored until it is upright again.")
            }
        }
    }
}

private extension View {
    @ViewBuilder
    func symbolEffectIfAvailable(active: Bool) -> some View {
        if #available(iOS 17.0, *) {
            self.symbolEffect(.pulse, isActive: active)
        } else {
            self
        }
    }
}
