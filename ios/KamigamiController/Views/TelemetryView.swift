import SwiftUI

struct TelemetryView: View {
    @EnvironmentObject var ble: KamigamiBLEManager

    var body: some View {
        List {
            Section {
                if let imu = ble.imu {
                    AxisRow(name: "Accel X", value: imu.ax, range: 4, unit: "g", format: "%+.3f")
                    AxisRow(name: "Accel Y", value: imu.ay, range: 4, unit: "g", format: "%+.3f")
                    AxisRow(name: "Accel Z", value: imu.az, range: 4, unit: "g", format: "%+.3f")
                    AxisRow(name: "Gyro X", value: imu.gx, range: 500, unit: "°/s", format: "%+.1f")
                    AxisRow(name: "Gyro Y", value: imu.gy, range: 500, unit: "°/s", format: "%+.1f")
                    AxisRow(name: "Gyro Z", value: imu.gz, range: 500, unit: "°/s", format: "%+.1f")
                    LabeledRow("|a|", String(format: "%.2f g", imu.accelMagnitude))
                } else {
                    Text("Waiting for IMU data…").foregroundStyle(.secondary)
                }
                if let cfg = ble.imuConfig {
                    LabeledRow("Range", "±\(Int(cfg.accel.scale))g · ±\(Int(cfg.gyro.scale))°/s · filter \(cfg.filtered ? "on" : "off")")
                }
                if let f = ble.lastFeature {
                    LabeledRow("HW event", "\(f.feature.name) (\(f.date.formatted(date: .omitted, time: .standard)))")
                }
            } header: {
                Text("6-axis IMU (BMI160) · 10 Hz")
            }

            Section("Motors") {
                if let m = ble.motor {
                    LabeledRow("Mode", m.mode.rawValue)
                    LabeledRow("Power L / R", "\(m.leftPower) / \(m.rightPower)")
                    LabeledRow("PWM L / R", "\(m.leftPWM) / \(m.rightPWM)")
                    if let yaw = m.yawRate { LabeledRow("Yaw rate", "\(yaw)") }
                } else {
                    Text("Waiting for motor data…").foregroundStyle(.secondary)
                }
            }

            Section("Robot") {
                LabeledRow("Name", ble.robotName ?? "—")
                LabeledRow("Firmware", ble.firmware ?? "—")
                LabeledRow("Battery", ble.battery.map { "\($0)%" } ?? "—")
                LabeledRow("Orientation", ble.isUpsideDown ? "⚠️ Upside down" : "Upright")
            }

            Section("Log") {
                ForEach(ble.log.prefix(60)) { entry in
                    HStack(alignment: .firstTextBaseline) {
                        Text(entry.date.formatted(date: .omitted, time: .standard))
                            .foregroundStyle(.secondary)
                        Text(entry.text)
                    }
                    .font(.caption.monospaced())
                }
            }
        }
    }
}

struct LabeledRow: View {
    let title: String
    let value: String
    init(_ title: String, _ value: String) {
        self.title = title
        self.value = value
    }
    var body: some View {
        HStack {
            Text(title)
            Spacer()
            Text(value).monospacedDigit().foregroundStyle(.secondary).multilineTextAlignment(.trailing)
        }
    }
}

struct AxisRow: View {
    let name: String
    let value: Double
    let range: Double
    let unit: String
    let format: String

    var body: some View {
        HStack {
            Text(name).frame(width: 64, alignment: .leading)
            GeometryReader { geo in
                let half = geo.size.width / 2
                let frac = CGFloat(max(-1, min(1, value / range)))
                ZStack(alignment: .leading) {
                    Capsule().fill(Theme.panel)
                    Rectangle().fill(Theme.stroke).frame(width: 1).offset(x: half)
                    Rectangle()
                        .fill(value >= 0 ? Theme.cyan : Theme.purple)
                        .frame(width: abs(frac) * half)
                        .offset(x: frac >= 0 ? half : half - abs(frac) * half)
                }
                .clipShape(Capsule())
            }
            .frame(height: 8)
            Text(String(format: format, value) + " " + unit)
                .font(.caption.monospacedDigit())
                .frame(width: 84, alignment: .trailing)
        }
    }
}
