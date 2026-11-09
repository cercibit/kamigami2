import SwiftUI

enum DriveMode: String, CaseIterable, Identifiable {
    case joystick = "Joystick", tank = "Tank", tilt = "Tilt"
    var id: String { rawValue }
}

struct DriveView: View {
    @EnvironmentObject var ble: KamigamiBLEManager
    @EnvironmentObject var tilt: TiltController
    @AppStorage("driveMode") private var mode: DriveMode = .joystick
    @State private var tiltEngaged = false

    var body: some View {
        VStack(spacing: 16) {
            Picker("Mode", selection: $mode) {
                ForEach(DriveMode.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)

            Spacer(minLength: 0)

            switch mode {
            case .joystick:
                JoystickView { x, y in
                    let mix = DriveMixer.arcade(x: x, y: y, maxPower: ble.maxPower)
                    ble.drive(left: mix.left, right: mix.right)
                }
                .frame(width: 260, height: 260)
            case .tank:
                HStack(spacing: 60) {
                    TankSlider(label: "LEFT") { v in
                        tankLeft = v; sendTank()
                    }
                    TankSlider(label: "RIGHT") { v in
                        tankRight = v; sendTank()
                    }
                }
                .frame(height: 280)
            case .tilt:
                tiltPanel
            }

            Spacer(minLength: 0)

            MotorReadout(left: ble.commandedDrive.left, right: ble.commandedDrive.right)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("Max power")
                    Spacer()
                    Text("\(ble.maxPower) / 63").monospacedDigit().foregroundStyle(.secondary)
                }
                .font(.subheadline)
                Slider(value: Binding(get: { Double(ble.maxPower) },
                                      set: { ble.maxPower = Int($0) }),
                       in: 15...63, step: 1)
            }
        }
        .padding()
        .onChange(of: mode) { _ in
            endTilt()
            ble.drive(left: 0, right: 0)
        }
        .onDisappear {
            endTilt()
            ble.drive(left: 0, right: 0)
        }
        .onChange(of: tilt.x) { _ in sendTilt() }
        .onChange(of: tilt.y) { _ in sendTilt() }
    }

    // MARK: Tank

    @State private var tankLeft: Double = 0
    @State private var tankRight: Double = 0

    private func sendTank() {
        let mix = DriveMixer.tank(left: tankLeft, right: tankRight, maxPower: ble.maxPower)
        ble.drive(left: mix.left, right: mix.right)
    }

    // MARK: Tilt

    private var tiltPanel: some View {
        VStack(spacing: 20) {
            ZStack {
                Circle().stroke(Theme.stroke, lineWidth: 2)
                Circle()
                    .fill(tiltEngaged ? Theme.cyan : Theme.purple)
                    .frame(width: 44, height: 44)
                    .offset(x: tilt.x * 100, y: -tilt.y * 100)
            }
            .frame(width: 220, height: 220)

            if !tilt.isAvailable {
                Text("Motion sensors unavailable on this device.").foregroundStyle(.secondary)
            }

            Text(tiltEngaged ? "Tilt the phone to steer. Release to stop."
                             : "Hold the button and tilt your phone to drive.")
                .font(.footnote)
                .foregroundStyle(.secondary)

            Text(tiltEngaged ? "DRIVING" : "HOLD TO DRIVE")
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 18)
                .background(tiltEngaged ? Theme.cyan : Theme.purple, in: RoundedRectangle(cornerRadius: 14))
                .foregroundStyle(.black)
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { _ in
                            if !tiltEngaged {
                                tiltEngaged = true
                                tilt.start()   // calibrates to the current orientation
                            }
                        }
                        .onEnded { _ in endTilt() }
                )
        }
    }

    private func sendTilt() {
        guard mode == .tilt, tiltEngaged else { return }
        let mix = DriveMixer.arcade(x: tilt.x, y: tilt.y, maxPower: ble.maxPower)
        ble.drive(left: mix.left, right: mix.right)
    }

    private func endTilt() {
        guard tiltEngaged || tilt.isActive else { return }
        tiltEngaged = false
        tilt.stop()
        ble.drive(left: 0, right: 0)
    }
}

// MARK: - Joystick

struct JoystickView: View {
    /// Called with normalized x (-1 left…1 right) and y (-1 back…1 forward).
    var onChange: (Double, Double) -> Void
    @State private var knob: CGSize = .zero
    @State private var dragging = false

    var body: some View {
        GeometryReader { geo in
            let radius = min(geo.size.width, geo.size.height) / 2
            let knobRadius = radius * 0.3
            let travel = radius - knobRadius / 2
            ZStack {
                Circle().fill(Theme.panel)
                Circle().stroke(Theme.stroke, lineWidth: 2)
                Path { p in
                    p.move(to: CGPoint(x: radius, y: radius - travel))
                    p.addLine(to: CGPoint(x: radius, y: radius + travel))
                    p.move(to: CGPoint(x: radius - travel, y: radius))
                    p.addLine(to: CGPoint(x: radius + travel, y: radius))
                }
                .stroke(Theme.stroke, lineWidth: 1)
                Circle()
                    .fill(dragging ? Theme.cyan : Theme.purple)
                    .frame(width: knobRadius * 2, height: knobRadius * 2)
                    .shadow(color: (dragging ? Theme.cyan : Theme.purple).opacity(0.6), radius: 12)
                    .offset(knob)
            }
            .frame(width: radius * 2, height: radius * 2)
            .contentShape(Circle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        if !dragging {
                            dragging = true
                            UIImpactFeedbackGenerator(style: .light).impactOccurred()
                        }
                        var dx = value.location.x - radius
                        var dy = value.location.y - radius
                        let dist = (dx * dx + dy * dy).squareRoot()
                        if dist > travel {
                            dx = dx / dist * travel
                            dy = dy / dist * travel
                        }
                        knob = CGSize(width: dx, height: dy)
                        onChange(Double(dx / travel), Double(-dy / travel))
                    }
                    .onEnded { _ in
                        dragging = false
                        withAnimation(.spring(response: 0.25, dampingFraction: 0.6)) { knob = .zero }
                        onChange(0, 0)
                    }
            )
        }
        .aspectRatio(1, contentMode: .fit)
        .accessibilityLabel("Drive joystick")
    }
}

// MARK: - Tank slider

struct TankSlider: View {
    let label: String
    /// Called with -1 (full reverse) … 1 (full forward).
    var onChange: (Double) -> Void
    @State private var offset: CGFloat = 0
    @State private var dragging = false

    var body: some View {
        VStack(spacing: 8) {
            GeometryReader { geo in
                let half = geo.size.height / 2 - 30
                ZStack {
                    Capsule().fill(Theme.panel)
                    Capsule().stroke(Theme.stroke, lineWidth: 2)
                    Rectangle().fill(Theme.stroke).frame(height: 1)
                    Circle()
                        .fill(dragging ? Theme.cyan : Theme.purple)
                        .frame(width: 56, height: 56)
                        .offset(y: offset)
                }
                .contentShape(Capsule())
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { v in
                            dragging = true
                            offset = max(-half, min(half, v.location.y - geo.size.height / 2))
                            onChange(Double(-offset / half))
                        }
                        .onEnded { _ in
                            dragging = false
                            withAnimation(.spring(response: 0.25, dampingFraction: 0.6)) { offset = 0 }
                            onChange(0)
                        }
                )
            }
            .frame(width: 72)
            Text(label).font(.caption.weight(.bold)).foregroundStyle(.secondary)
        }
    }
}

struct MotorReadout: View {
    let left: Int
    let right: Int

    var body: some View {
        HStack(spacing: 24) {
            bar("L", left)
            bar("R", right)
        }
        .font(.caption.monospacedDigit())
    }

    private func bar(_ name: String, _ value: Int) -> some View {
        HStack(spacing: 6) {
            Text(name).foregroundStyle(.secondary)
            GeometryReader { geo in
                let w = geo.size.width / 2
                let frac = CGFloat(value) / 63
                ZStack(alignment: .leading) {
                    Capsule().fill(Theme.panel)
                    Rectangle()
                        .fill(value >= 0 ? Theme.cyan : Theme.purple)
                        .frame(width: abs(frac) * w)
                        .offset(x: value >= 0 ? w : w - abs(frac) * w)
                }
                .clipShape(Capsule())
            }
            .frame(height: 8)
            Text(String(format: "%+3d", value)).frame(width: 34, alignment: .trailing)
        }
    }
}
