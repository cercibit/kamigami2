import CoreMotion
import Foundation

/// Converts phone tilt (held in portrait, screen up) into joystick values.
final class TiltController: ObservableObject {
    @Published private(set) var x: Double = 0   // -1 left ... +1 right
    @Published private(set) var y: Double = 0   // -1 back ... +1 forward
    @Published private(set) var isActive = false

    private let motion = CMMotionManager()
    private var reference: (pitch: Double, roll: Double)?

    /// Tilt in radians that maps to full deflection.
    var fullScale: Double = 0.45
    /// Ignore small tilts around the calibrated rest position.
    var deadZone: Double = 0.08

    var isAvailable: Bool { motion.isDeviceMotionAvailable }

    func start() {
        guard motion.isDeviceMotionAvailable, !isActive else { return }
        reference = nil
        motion.deviceMotionUpdateInterval = 1.0 / 30.0
        motion.startDeviceMotionUpdates(to: .main) { [weak self] data, _ in
            guard let self, let att = data?.attitude else { return }
            if self.reference == nil { self.reference = (att.pitch, att.roll) }
            guard let ref = self.reference else { return }
            // Tilting the top edge away (pitch decreasing) drives forward.
            self.y = self.shape(-(att.pitch - ref.pitch))
            self.x = self.shape(att.roll - ref.roll)
        }
        isActive = true
    }

    func stop() {
        motion.stopDeviceMotionUpdates()
        isActive = false
        x = 0
        y = 0
    }

    /// Re-zero on the phone's current orientation.
    func recalibrate() { reference = nil }

    private func shape(_ angle: Double) -> Double {
        let v = max(-1, min(1, angle / fullScale))
        guard abs(v) > deadZone else { return 0 }
        return (v - (v > 0 ? deadZone : -deadZone)) / (1 - deadZone)
    }
}
