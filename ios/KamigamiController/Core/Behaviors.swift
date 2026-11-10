import Foundation

/// Inverted-orientation safety cutoff (port of the Python `check_is_upside_down` logic).
///
/// The robot is considered upside down after two consecutive IMU samples with
/// `az < -0.45 g`, and upright again once `az > 0.35 g`. Stale telemetry (older than
/// `staleAfter`) never reports upside down, so a dropped stream cannot latch the cutoff.
public struct SafetyMonitor: Sendable {
    public var invertedThreshold: Double = -0.45
    public var uprightThreshold: Double = 0.35
    public var requiredSamples: Int = 2
    public var staleAfter: TimeInterval = 1.5

    public private(set) var latched = false
    private var invertedSamples = 0
    private var lastSampleTime: Date?

    public init() {}

    public mutating func ingest(_ imu: IMUSample) {
        lastSampleTime = imu.timestamp
        if imu.az < invertedThreshold {
            invertedSamples += 1
        } else {
            invertedSamples = 0
        }
        if invertedSamples >= requiredSamples {
            latched = true
        } else if latched && imu.az > uprightThreshold {
            latched = false
        }
    }

    public func isUpsideDown(now: Date = Date()) -> Bool {
        guard latched, let t = lastSampleTime else { return false }
        return now.timeIntervalSince(t) <= staleAfter
    }

    public mutating func reset() {
        latched = false
        invertedSamples = 0
        lastSampleTime = nil
    }
}

/// Output of a behavior tick.
public enum BehaviorAction: Equatable, Sendable {
    case drive(left: Int, right: Int)
    case stop
    case led(r: UInt8, g: UInt8, b: UInt8)
}

/// Autonomous "cockroach" obstacle-avoidance behavior (port of `cockroach_sim.py`).
///
/// Darts forward, detects collisions from IMU shock / yaw deflection / stall and
/// BMI160 hardware impact interrupts, freezes 2 s, backs up, turns randomly, repeats.
public struct CockroachBehavior: Sendable {
    public enum Phase: Equatable, Sendable {
        case forward, paused, backingUp, turning(left: Bool), upsideDown, recovering

        public var label: String {
            switch self {
            case .forward: return "Moving forward"
            case .paused: return "Hit! Freezing 2s"
            case .backingUp: return "Backing up"
            case let .turning(left): return left ? "Turning left" : "Turning right"
            case .upsideDown: return "Upside down — motors halted"
            case .recovering: return "Righted — recovering"
            }
        }
    }

    public var speed: Int
    /// Collision sensitivity (0.15 ... 1.5). Higher = needs a harder hit.
    public var threshold: Double

    public private(set) var phase: Phase = .forward
    public private(set) var lastEvent: String?
    private var phaseStart: Date
    private var turnDuration: TimeInterval = 0.45
    private var stallSamples = 0
    private var started = false

    public static let pauseDuration: TimeInterval = 2.0
    public static let backupDuration: TimeInterval = 0.45
    public static let recoverDuration: TimeInterval = 1.0
    public static let settleTime: TimeInterval = 0.40

    public init(speed: Int = 40, threshold: Double = 0.45, now: Date = Date()) {
        self.speed = speed
        self.threshold = threshold
        self.phaseStart = now
    }

    public var peakShockThreshold: Double { 2.6 + threshold * 2.0 }
    public var yawShockThreshold: Double { 240.0 + threshold * 200.0 }

    private mutating func enter(_ p: Phase, _ now: Date) {
        phase = p
        phaseStart = now
    }

    /// Advance the state machine.
    /// - Parameters:
    ///   - imu: latest IMU sample (only pass a sample once).
    ///   - feature: latest BMI160 hardware event (only pass an event once).
    ///   - upsideDown: result of the safety monitor.
    ///   - random: random source in [0, 1) — injectable for tests.
    public mutating func tick(now: Date,
                              imu: IMUSample?,
                              feature: IMUFeature?,
                              upsideDown: Bool,
                              random: () -> Double = { Double.random(in: 0..<1) }) -> [BehaviorAction] {
        var actions: [BehaviorAction] = []
        if !started {
            started = true
            phaseStart = now
            actions.append(.led(r: 0, g: 255, b: 80))
        }
        let elapsed = now.timeIntervalSince(phaseStart)

        // Safety cutoff overrides everything.
        if upsideDown {
            if phase != .upsideDown {
                enter(.upsideDown, now)
                lastEvent = "Upside down detected — motors cut"
                actions += [.stop, .led(r: 255, g: 0, b: 128)]
            }
            return actions
        }
        if phase == .upsideDown {
            enter(.recovering, now)
            lastEvent = "Upright again"
            return actions + [.stop, .led(r: 255, g: 200, b: 0)]
        }

        var hit: String?
        if phase == .forward && elapsed > Self.settleTime {
            if let imu {
                if imu.ax > 0.65 || imu.az < 0.20 { stallSamples += 1 } else { stallSamples = 0 }
                let mag = imu.accelMagnitude
                if mag > peakShockThreshold {
                    hit = String(format: "Shock %.2fg", mag)
                } else if abs(imu.gz) > yawShockThreshold {
                    hit = String(format: "Yaw deflection %.0f°/s", abs(imu.gz))
                } else if stallSamples >= 4 {
                    hit = "Blocked / climbing wall"
                }
            }
            if hit == nil, let feature, feature.isImpact {
                hit = "Hardware \(feature.name)"
            }
        }

        if let hit {
            lastEvent = hit
            stallSamples = 0
            enter(.paused, now)
            return actions + [.stop, .led(r: 255, g: 0, b: 0)]
        }

        switch phase {
        case .recovering:
            actions.append(.stop)
            if elapsed >= Self.recoverDuration {
                enter(.forward, now)
                stallSamples = 0
                actions.append(.led(r: 0, g: 255, b: 80))
            }
        case .paused:
            actions.append(.stop)
            if elapsed >= Self.pauseDuration {
                enter(.backingUp, now)
                actions.append(.led(r: 255, g: 120, b: 0))
            }
        case .backingUp:
            if elapsed >= Self.backupDuration {
                actions.append(.stop)
                turnDuration = 0.35 + random() * 0.30
                enter(.turning(left: random() < 0.5), now)
            } else {
                actions.append(.drive(left: -speed, right: -speed))
            }
        case let .turning(left):
            if elapsed >= turnDuration {
                actions += [.stop, .led(r: 0, g: 255, b: 80)]
                stallSamples = 0
                enter(.forward, now)
            } else {
                let dir = left ? -1 : 1
                actions.append(.drive(left: -speed * dir, right: speed * dir))
            }
        case .forward:
            actions.append(.drive(left: speed, right: speed))
        case .upsideDown:
            break
        }
        return actions
    }
}
