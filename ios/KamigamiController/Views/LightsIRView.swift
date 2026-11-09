import SwiftUI
import UIKit

struct LightsIRView: View {
    @EnvironmentObject var ble: KamigamiBLEManager
    @State private var customColor = Color(red: 0, green: 0.9, blue: 1)
    @State private var colorTask: Task<Void, Never>?
    @AppStorage("irPlayerID") private var irID = 1
    @AppStorage("irCommand") private var irCommand = 42
    @State private var confirmPowerDown = false

    private struct Preset: Identifiable {
        let name: String
        let r: UInt8, g: UInt8, b: UInt8
        var id: String { name }
        var color: Color { Color(red: Double(r) / 255, green: Double(g) / 255, blue: Double(b) / 255) }
    }

    private let presets: [Preset] = [
        Preset(name: "Cyan", r: 0, g: 229, b: 255), Preset(name: "Purple", r: 124, g: 77, b: 255),
        Preset(name: "Red", r: 255, g: 0, b: 0), Preset(name: "Green", r: 0, g: 255, b: 80),
        Preset(name: "Blue", r: 0, g: 60, b: 255), Preset(name: "Amber", r: 255, g: 120, b: 0),
        Preset(name: "Pink", r: 255, g: 0, b: 128), Preset(name: "White", r: 255, g: 255, b: 255),
        Preset(name: "Off", r: 0, g: 0, b: 0),
    ]

    var body: some View {
        Form {
            Section("Eye LED") {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 3), spacing: 12) {
                    ForEach(presets) { preset in
                        Button {
                            ble.setLED(preset.r, preset.g, preset.b)
                            UISelectionFeedbackGenerator().selectionChanged()
                        } label: {
                            VStack(spacing: 6) {
                                Circle()
                                    .fill(preset.color)
                                    .overlay(Circle().stroke(Theme.stroke, lineWidth: 1))
                                    .frame(width: 38, height: 38)
                                Text(preset.name).font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.vertical, 6)

                ColorPicker("Custom color", selection: $customColor, supportsOpacity: false)
                    .onChange(of: customColor) { color in sendColor(color) }
            }

            Section {
                Stepper("Player ID: \(irID)", value: $irID, in: 0...255)
                Stepper("Command: \(irCommand)", value: $irCommand, in: 0...255)
                Button {
                    ble.fireIR(id: UInt8(irID), command: UInt8(irCommand))
                } label: {
                    Label("Fire IR", systemImage: "scope")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(Theme.danger)

                if let hit = ble.lastIRHit {
                    HStack {
                        Image(systemName: "target").foregroundStyle(.red)
                        VStack(alignment: .leading) {
                            Text("Hit from \(hit.hit.direction?.label ?? "unknown")")
                                .font(.subheadline.weight(.semibold))
                            Text("ID \(hit.hit.id) · cmd \(hit.hit.command) · \(hit.date, style: .relative) ago")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            } header: {
                Text("Infrared battle")
            } footer: {
                Text("Robots receive IR on front and back sensors. Incoming hits appear here and trigger a haptic.")
            }

            Section("Routines") {
                Button {
                    ble.demoRunning ? ble.cancelDemo() : ble.runDemo()
                } label: {
                    Label(ble.demoRunning ? "Stop demo" : "Run demo routine",
                          systemImage: ble.demoRunning ? "stop.fill" : "sparkles")
                }
                .disabled(ble.isUpsideDown && ble.safetyCutoffEnabled)
            }

            Section {
                Button(role: .destructive) {
                    confirmPowerDown = true
                } label: {
                    Label("Power down robot", systemImage: "power")
                }
            } footer: {
                Text("Puts the robot into deep sleep. Press its button to wake it again.")
            }
        }
        .confirmationDialog("Power down the robot?", isPresented: $confirmPowerDown, titleVisibility: .visible) {
            Button("Power down", role: .destructive) { ble.powerDown() }
        }
    }

    /// Throttle custom color writes so dragging the picker doesn't flood BLE.
    private func sendColor(_ color: Color) {
        colorTask?.cancel()
        colorTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 80_000_000)
            guard !Task.isCancelled else { return }
            var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
            UIColor(color).getRed(&r, green: &g, blue: &b, alpha: &a)
            func byte(_ v: CGFloat) -> UInt8 { UInt8(max(0, min(255, (v * 255).rounded()))) }
            ble.setLED(byte(r), byte(g), byte(b))
        }
    }
}
