import Foundation

/// Kamigami (KRB0002, Firmware 2.0.2) binary BLE protocol.
///
/// See `KAMIGAMI_HARDWARE_AND_PROTOCOL.md` at the repository root for the full
/// specification. This file is pure Swift (no CoreBluetooth) so it can be unit
/// tested with `swift test` on any platform.
public enum KamigamiUUID {
    /// Primary robot control service.
    public static let controlService = "708A96F0-F200-4E2F-96F0-9BC43C3A31C8"
    /// Host -> Robot command characteristic (write / write-without-response).
    public static let commandCharacteristic = "708A96F1-F200-4E2F-96F0-9BC43C3A31C8"
    /// Robot -> Host telemetry characteristic (notify).
    public static let telemetryCharacteristic = "708A96F2-F200-4E2F-96F0-9BC43C3A31C8"

    public static let batteryService = "180F"
    public static let batteryLevelCharacteristic = "2A19"

    public static let deviceInfoService = "180A"
    public static let firmwareRevisionCharacteristic = "2A26"
    public static let modelNumberCharacteristic = "2A24"
    public static let hardwareRevisionCharacteristic = "2A27"
    public static let manufacturerNameCharacteristic = "2A29"

    /// Bluetooth SIG company identifier of Dash Robotics, Inc.
    public static let dashCompanyID: UInt16 = 0x02C0
    /// Advertised name prefix of Kamigami robots (e.g. "KRB0002").
    public static let namePrefix = "KRB"
}

// MARK: - Commands (Host -> Robot)

public enum AccelRange: UInt8, CaseIterable, Sendable {
    case g2 = 3, g4 = 5, g8 = 8, g16 = 12

    public var scale: Double {
        switch self {
        case .g2: return 2
        case .g4: return 4
        case .g8: return 8
        case .g16: return 16
        }
    }
}

public enum GyroRange: UInt8, CaseIterable, Sendable {
    case dps2000 = 0, dps1000 = 1, dps500 = 2, dps250 = 3, dps125 = 4

    public var scale: Double {
        switch self {
        case .dps2000: return 2000
        case .dps1000: return 1000
        case .dps500: return 500
        case .dps250: return 250
        case .dps125: return 125
        }
    }
}

public enum ReadTarget: UInt8, Sendable {
    case imuConfig = 0x40
    case imu2Config = 0x41
}

public enum KamigamiCommand: Equatable, Sendable {
    /// Maximum absolute motor power accepted by the firmware.
    public static let maxPower = 63

    case powerDown
    case eyeColor(r: UInt8, g: UInt8, b: UInt8)
    case driveDirect(left: Int, right: Int)
    case driveStabilized(left: Int, right: Int, referenceYaw: Int16)
    case infrared(id: UInt8, command: UInt8)
    case readResponse(ReadTarget)
    case configUpdates(imuHz: UInt8, motorHz: UInt8)
    case configIMU(accel: AccelRange, gyro: GyroRange, filtered: Bool)

    public static let stop = KamigamiCommand.driveDirect(left: 0, right: 0)

    /// Exact byte payload. The firmware rejects packets of the wrong length.
    public var bytes: [UInt8] {
        switch self {
        case .powerDown:
            return [0x00]
        case let .eyeColor(r, g, b):
            return [0x01, 0x00, r, g, b, 0x00, 0x00]
        case let .driveDirect(left, right):
            return [0x02, 0x00, Self.powerByte(left), Self.powerByte(right), 0x00, 0x00]
        case let .driveStabilized(left, right, yaw):
            let y = UInt16(bitPattern: yaw)
            return [0x02, 0x01, Self.powerByte(left), Self.powerByte(right),
                    UInt8(y & 0xFF), UInt8(y >> 8)]
        case let .infrared(id, command):
            return [0x03, id, command]
        case let .readResponse(target):
            return [0x20, target.rawValue]
        case let .configUpdates(imuHz, motorHz):
            return [0x21, imuHz, motorHz]
        case let .configIMU(accel, gyro, filtered):
            return [0x40, accel.rawValue, gyro.rawValue, filtered ? 1 : 0]
        }
    }

    public var data: Data { Data(bytes) }

    /// Whether this is a motor command (eligible for coalescing / no-response writes).
    public var isDrive: Bool {
        switch self {
        case .driveDirect, .driveStabilized: return true
        default: return false
        }
    }

    public static func clampPower(_ value: Int) -> Int {
        max(-maxPower, min(maxPower, value))
    }

    static func powerByte(_ value: Int) -> UInt8 {
        UInt8(bitPattern: Int8(clampPower(value)))
    }
}

// MARK: - Telemetry (Robot -> Host)

public struct IMUSample: Equatable, Sendable {
    public var ax: Double, ay: Double, az: Double   // g
    public var gx: Double, gy: Double, gz: Double   // deg/s
    public var timestamp: Date

    public init(ax: Double, ay: Double, az: Double, gx: Double, gy: Double, gz: Double, timestamp: Date = Date()) {
        self.ax = ax; self.ay = ay; self.az = az
        self.gx = gx; self.gy = gy; self.gz = gz
        self.timestamp = timestamp
    }

    public var accelMagnitude: Double { (ax * ax + ay * ay + az * az).squareRoot() }
}

public enum MotorMode: String, Sendable { case direct = "DIRECT", stabilized = "STABILIZED" }

public struct MotorState: Equatable, Sendable {
    public var mode: MotorMode
    public var leftPower: Int
    public var rightPower: Int
    public var leftPWM: Int
    public var rightPWM: Int
    public var yawRate: Int?
}

public enum IRDirection: UInt8, Sendable {
    case front = 1, back = 2
    public var label: String { self == .front ? "FRONT" : "BACK" }
}

public struct IRHit: Equatable, Sendable {
    public var direction: IRDirection?
    public var id: UInt8
    public var command: UInt8
}

public enum IMUFeature: UInt8, CaseIterable, Sendable {
    case anyMotion = 0, significantMotion, singleTap, doubleTap, orientation,
         flat, lowG, highG, slowMotion, noMotion

    public var name: String {
        switch self {
        case .anyMotion: return "AnyMotion"
        case .significantMotion: return "SignificantMotion"
        case .singleTap: return "SingleTap"
        case .doubleTap: return "DoubleTap"
        case .orientation: return "Orientation"
        case .flat: return "Flat"
        case .lowG: return "LowG"
        case .highG: return "HighG"
        case .slowMotion: return "SlowMotion"
        case .noMotion: return "NoMotion"
        }
    }

    /// Hardware events that indicate an impact.
    public var isImpact: Bool { self == .highG || self == .singleTap || self == .doubleTap }
}

public struct IMUConfig: Equatable, Sendable {
    public var accel: AccelRange
    public var gyro: GyroRange
    public var filtered: Bool
}

public enum KamigamiTelemetry: Equatable, Sendable {
    case led(r: UInt8, g: UInt8, b: UInt8)
    case motor(MotorState)
    case infrared(IRHit)
    case imu(IMUSample)
    case imuFeature(IMUFeature, raw: [UInt8])
    case imuConfig(IMUConfig)
    case imu2Config(raw: [UInt8])
    case unknown(type: UInt8, raw: [UInt8])
}

/// Stateful decoder: tracks the accelerometer / gyroscope full-scale ranges
/// reported by `IMUConfig` responses so IMU samples are scaled correctly.
public struct TelemetryDecoder: Sendable {
    public var accelScale: Double = 4.0
    public var gyroScale: Double = 2000.0

    public init() {}

    static func scale(_ raw: Int16, _ factor: Double) -> Double {
        raw > 0 ? Double(raw) * factor / 32767.0 : Double(raw) * factor / 32768.0
    }

    static func int16LE(_ b: [UInt8], _ i: Int) -> Int16 {
        Int16(bitPattern: UInt16(b[i]) | (UInt16(b[i + 1]) << 8))
    }

    public mutating func decode(_ data: Data, now: Date = Date()) -> KamigamiTelemetry? {
        let bytes = [UInt8](data)
        guard let type = bytes.first else { return nil }
        let p = Array(bytes.dropFirst())

        switch type {
        case 0x01 where p.count >= 3:
            return .led(r: p[0], g: p[1], b: p[2])

        case 0x02 where p.count >= 9:
            let mode: MotorMode = (p[0] & 1) == 0 ? .direct : .stabilized
            var state = MotorState(
                mode: mode,
                leftPower: Int(Int8(bitPattern: p[1])),
                rightPower: Int(Int8(bitPattern: p[2])),
                leftPWM: Int(Int8(bitPattern: p[5] &- p[6])),
                rightPWM: Int(Int8(bitPattern: p[7] &- p[8])),
                yawRate: nil
            )
            if mode == .stabilized {
                state.yawRate = Int(Int16(bitPattern: (UInt16(p[3]) << 8) | UInt16(p[4])))
            }
            return .motor(state)

        case 0x03 where p.count >= 3:
            return .infrared(IRHit(direction: IRDirection(rawValue: p[0]), id: p[1], command: p[2]))

        case 0x05 where p.count >= 12:
            let raw = (0..<6).map { Self.int16LE(p, $0 * 2) }
            return .imu(IMUSample(
                ax: Self.scale(raw[0], accelScale),
                ay: Self.scale(raw[1], accelScale),
                az: Self.scale(raw[2], accelScale),
                gx: Self.scale(raw[3], gyroScale),
                gy: Self.scale(raw[4], gyroScale),
                gz: Self.scale(raw[5], gyroScale),
                timestamp: now
            ))

        case 0x06 where p.count >= 1:
            guard let feature = IMUFeature(rawValue: p[0]) else {
                return .unknown(type: type, raw: p)
            }
            return .imuFeature(feature, raw: p)

        case 0x40 where p.count >= 3:
            let accel = AccelRange(rawValue: p[0]) ?? .g4
            let gyro = GyroRange(rawValue: p[1]) ?? .dps2000
            accelScale = accel.scale
            gyroScale = gyro.scale
            return .imuConfig(IMUConfig(accel: accel, gyro: gyro, filtered: p[2] != 0))

        case 0x41:
            return .imu2Config(raw: p)

        default:
            return .unknown(type: type, raw: p)
        }
    }
}

// MARK: - Drive mixing

public enum DriveMixer {
    /// Arcade mix used by the web control deck joystick.
    /// - Parameters:
    ///   - x: turn, -1 (left) ... +1 (right)
    ///   - y: throttle, -1 (back) ... +1 (forward)
    ///   - maxPower: power limit (15...63)
    public static func arcade(x: Double, y: Double, maxPower: Int, turnGain: Double = 0.8) -> (left: Int, right: Int) {
        let p = Double(maxPower)
        let l = (y + x * turnGain) * p
        let r = (y - x * turnGain) * p
        return (KamigamiCommand.clampPower(Int(l.rounded())), KamigamiCommand.clampPower(Int(r.rounded())))
    }

    /// Tank mix: each side driven independently from -1...+1.
    public static func tank(left: Double, right: Double, maxPower: Int) -> (left: Int, right: Int) {
        let p = Double(maxPower)
        return (KamigamiCommand.clampPower(Int((left * p).rounded())),
                KamigamiCommand.clampPower(Int((right * p).rounded())))
    }
}
