import XCTest
@testable import KamigamiCore

final class CommandEncodingTests: XCTestCase {
    func testPowerDown() {
        XCTAssertEqual(KamigamiCommand.powerDown.bytes, [0x00])
    }

    func testEyeColorIsSevenBytes() {
        XCTAssertEqual(KamigamiCommand.eyeColor(r: 255, g: 0, b: 128).bytes,
                       [0x01, 0x00, 0xFF, 0x00, 0x80, 0x00, 0x00])
    }

    func testDriveDirectEncodesSignedPower() {
        XCTAssertEqual(KamigamiCommand.driveDirect(left: 40, right: -40).bytes,
                       [0x02, 0x00, 40, 0xD8, 0x00, 0x00])
    }

    func testDriveClampsToPlusMinus63() {
        XCTAssertEqual(KamigamiCommand.driveDirect(left: 200, right: -200).bytes,
                       [0x02, 0x00, 63, 0xC1, 0x00, 0x00])
    }

    func testStop() {
        XCTAssertEqual(KamigamiCommand.stop.bytes, [0x02, 0, 0, 0, 0, 0])
    }

    func testDriveStabilizedLittleEndianYaw() {
        XCTAssertEqual(KamigamiCommand.driveStabilized(left: 10, right: 10, referenceYaw: -2).bytes,
                       [0x02, 0x01, 10, 10, 0xFE, 0xFF])
        XCTAssertEqual(KamigamiCommand.driveStabilized(left: 0, right: 0, referenceYaw: 0x1234).bytes,
                       [0x02, 0x01, 0, 0, 0x34, 0x12])
    }

    func testInfraredReadAndConfig() {
        XCTAssertEqual(KamigamiCommand.infrared(id: 1, command: 42).bytes, [0x03, 1, 42])
        XCTAssertEqual(KamigamiCommand.readResponse(.imuConfig).bytes, [0x20, 0x40])
        XCTAssertEqual(KamigamiCommand.readResponse(.imu2Config).bytes, [0x20, 0x41])
        XCTAssertEqual(KamigamiCommand.configUpdates(imuHz: 10, motorHz: 4).bytes, [0x21, 10, 4])
        XCTAssertEqual(KamigamiCommand.configIMU(accel: .g4, gyro: .dps2000, filtered: true).bytes,
                       [0x40, 0x05, 0x00, 0x01])
    }
}

final class TelemetryDecodingTests: XCTestCase {
    private func le(_ v: Int16) -> [UInt8] {
        let u = UInt16(bitPattern: v)
        return [UInt8(u & 0xFF), UInt8(u >> 8)]
    }

    func testIMUDefaultScale() throws {
        var d = TelemetryDecoder()
        let raw: [Int16] = [8192, -8192, 32767, 0, 16384, -32768]
        let packet = [UInt8(0x05)] + raw.flatMap(le)
        guard case let .imu(s)? = d.decode(Data(packet)) else { return XCTFail("not IMU") }
        XCTAssertEqual(s.ax, 1.0, accuracy: 0.001)     // 8192 * 4 / 32767
        XCTAssertEqual(s.ay, -1.0, accuracy: 0.001)    // -8192 * 4 / 32768
        XCTAssertEqual(s.az, 4.0, accuracy: 0.0001)
        XCTAssertEqual(s.gx, 0)
        XCTAssertEqual(s.gy, 1000.0, accuracy: 0.1)
        XCTAssertEqual(s.gz, -2000.0, accuracy: 0.0001)
    }

    func testIMUConfigChangesScale() {
        var d = TelemetryDecoder()
        guard case let .imuConfig(cfg)? = d.decode(Data([0x40, 0x08, 0x02, 0x00])) else { return XCTFail() }
        XCTAssertEqual(cfg.accel, .g8)
        XCTAssertEqual(cfg.gyro, .dps500)
        XCTAssertFalse(cfg.filtered)
        let packet = [UInt8(0x05)] + [Int16(16384), 0, 0, Int16(16384), 0, 0].flatMap(le)
        guard case let .imu(s)? = d.decode(Data(packet)) else { return XCTFail() }
        XCTAssertEqual(s.ax, 4.0, accuracy: 0.001)
        XCTAssertEqual(s.gx, 250.0, accuracy: 0.01)
    }

    func testMotorDirect() {
        var d = TelemetryDecoder()
        // mode, pwrL, pwrR, yawHi, yawLo, pwmL1, pwmL2, pwmR1, pwmR2
        let p: [UInt8] = [0x02, 0x00, 40, 0xD8, 0, 0, 50, 10, 5, 30]
        guard case let .motor(m)? = d.decode(Data(p)) else { return XCTFail() }
        XCTAssertEqual(m.mode, .direct)
        XCTAssertEqual(m.leftPower, 40)
        XCTAssertEqual(m.rightPower, -40)
        XCTAssertEqual(m.leftPWM, 40)
        XCTAssertEqual(m.rightPWM, -25)
        XCTAssertNil(m.yawRate)
    }

    func testMotorStabilizedYaw() {
        var d = TelemetryDecoder()
        let p: [UInt8] = [0x02, 0x01, 10, 10, 0xFF, 0xF6, 0, 0, 0, 0, 0, 0, 0, 0]
        guard case let .motor(m)? = d.decode(Data(p)) else { return XCTFail() }
        XCTAssertEqual(m.mode, .stabilized)
        XCTAssertEqual(m.yawRate, -10)
    }

    func testInfraredHit() {
        var d = TelemetryDecoder()
        guard case let .infrared(hit)? = d.decode(Data([0x03, 0x02, 7, 99])) else { return XCTFail() }
        XCTAssertEqual(hit.direction, .back)
        XCTAssertEqual(hit.id, 7)
        XCTAssertEqual(hit.command, 99)
    }

    func testIMUFeature() {
        var d = TelemetryDecoder()
        guard case let .imuFeature(f, _)? = d.decode(Data([0x06, 0x07, 0, 1, 0, 0])) else { return XCTFail() }
        XCTAssertEqual(f, .highG)
        XCTAssertTrue(f.isImpact)
    }

    func testShortPacketsAreUnknownNotCrash() {
        var d = TelemetryDecoder()
        XCTAssertNil(d.decode(Data()))
        if case .unknown? = d.decode(Data([0x05, 1, 2])) {} else { XCTFail() }
        if case .unknown? = d.decode(Data([0x02, 0])) {} else { XCTFail() }
    }
}

final class DriveMixerTests: XCTestCase {
    private func assertMix(_ m: (left: Int, right: Int), _ l: Int, _ r: Int, line: UInt = #line) {
        XCTAssertEqual(m.left, l, "left", line: line)
        XCTAssertEqual(m.right, r, "right", line: line)
    }

    func testArcade() {
        assertMix(DriveMixer.arcade(x: 0, y: 1, maxPower: 45), 45, 45)
        assertMix(DriveMixer.arcade(x: 1, y: 0, maxPower: 50), 40, -40)
        assertMix(DriveMixer.arcade(x: 1, y: 1, maxPower: 63), 63, 13)
        assertMix(DriveMixer.arcade(x: 0, y: 0, maxPower: 63), 0, 0)
    }

    func testTank() {
        assertMix(DriveMixer.tank(left: 1, right: -0.5, maxPower: 40), 40, -20)
    }
}

final class SafetyMonitorTests: XCTestCase {
    private func imu(az: Double, at t: Date) -> IMUSample {
        IMUSample(ax: 0, ay: 0, az: az, gx: 0, gy: 0, gz: 0, timestamp: t)
    }

    func testRequiresTwoInvertedSamplesAndClearsWhenUpright() {
        var m = SafetyMonitor()
        let t = Date()
        m.ingest(imu(az: -0.9, at: t))
        XCTAssertFalse(m.isUpsideDown(now: t))
        m.ingest(imu(az: -0.9, at: t))
        XCTAssertTrue(m.isUpsideDown(now: t))
        m.ingest(imu(az: 0.1, at: t))       // in hysteresis band: still latched
        XCTAssertTrue(m.isUpsideDown(now: t))
        m.ingest(imu(az: 0.9, at: t))
        XCTAssertFalse(m.isUpsideDown(now: t))
    }

    func testStaleTelemetryDoesNotLatch() {
        var m = SafetyMonitor()
        let t = Date()
        m.ingest(imu(az: -0.9, at: t))
        m.ingest(imu(az: -0.9, at: t))
        XCTAssertFalse(m.isUpsideDown(now: t.addingTimeInterval(2)))
    }
}

final class CockroachBehaviorTests: XCTestCase {
    private let level = IMUSample(ax: 0, ay: 0, az: 1, gx: 0, gy: 0, gz: 0)

    func testFullCycle() {
        let t0 = Date()
        var b = CockroachBehavior(speed: 40, threshold: 0.45, now: t0)
        var a = b.tick(now: t0, imu: level, feature: nil, upsideDown: false)
        XCTAssertTrue(a.contains(.drive(left: 40, right: 40)))
        XCTAssertEqual(b.phase, .forward)

        // Ignores shocks during the settle window.
        let shock = IMUSample(ax: 4, ay: 0, az: 1, gx: 0, gy: 0, gz: 0)
        _ = b.tick(now: t0.addingTimeInterval(0.2), imu: shock, feature: nil, upsideDown: false)
        XCTAssertEqual(b.phase, .forward)

        a = b.tick(now: t0.addingTimeInterval(0.5), imu: shock, feature: nil, upsideDown: false)
        XCTAssertEqual(b.phase, .paused)
        XCTAssertTrue(a.contains(.stop))

        _ = b.tick(now: t0.addingTimeInterval(2.6), imu: level, feature: nil, upsideDown: false)
        XCTAssertEqual(b.phase, .backingUp)
        a = b.tick(now: t0.addingTimeInterval(2.7), imu: level, feature: nil, upsideDown: false)
        XCTAssertTrue(a.contains(.drive(left: -40, right: -40)))

        _ = b.tick(now: t0.addingTimeInterval(3.1), imu: nil, feature: nil, upsideDown: false, random: { 0.2 })
        XCTAssertEqual(b.phase, .turning(left: true))
        a = b.tick(now: t0.addingTimeInterval(3.2), imu: nil, feature: nil, upsideDown: false)
        XCTAssertTrue(a.contains(.drive(left: 40, right: -40)))

        _ = b.tick(now: t0.addingTimeInterval(3.8), imu: nil, feature: nil, upsideDown: false)
        XCTAssertEqual(b.phase, .forward)
    }

    func testHardwareImpactInterrupt() {
        let t0 = Date()
        var b = CockroachBehavior(now: t0)
        _ = b.tick(now: t0, imu: nil, feature: nil, upsideDown: false)
        _ = b.tick(now: t0.addingTimeInterval(1), imu: nil, feature: .highG, upsideDown: false)
        XCTAssertEqual(b.phase, .paused)
    }

    func testUpsideDownHaltsAndRecovers() {
        let t0 = Date()
        var b = CockroachBehavior(now: t0)
        _ = b.tick(now: t0, imu: level, feature: nil, upsideDown: false)
        let a = b.tick(now: t0.addingTimeInterval(1), imu: nil, feature: nil, upsideDown: true)
        XCTAssertEqual(b.phase, .upsideDown)
        XCTAssertTrue(a.contains(.stop))
        XCTAssertTrue(b.tick(now: t0.addingTimeInterval(1.1), imu: nil, feature: nil, upsideDown: true).isEmpty)
        _ = b.tick(now: t0.addingTimeInterval(2), imu: level, feature: nil, upsideDown: false)
        XCTAssertEqual(b.phase, .recovering)
        _ = b.tick(now: t0.addingTimeInterval(3.1), imu: level, feature: nil, upsideDown: false)
        XCTAssertEqual(b.phase, .forward)
    }
}
