import Combine
import CoreBluetooth
import Foundation
import UIKit

/// A robot seen while scanning.
struct DiscoveredRobot: Identifiable, Equatable {
    let id: UUID
    let peripheral: CBPeripheral
    var name: String
    var rssi: Int
    var lastSeen: Date

    static func == (a: DiscoveredRobot, b: DiscoveredRobot) -> Bool {
        a.id == b.id && a.name == b.name && a.rssi == b.rssi
    }
}

enum ConnectionState: Equatable {
    case disconnected, connecting, discovering, ready

    var label: String {
        switch self {
        case .disconnected: return "Disconnected"
        case .connecting: return "Connecting…"
        case .discovering: return "Setting up…"
        case .ready: return "Connected"
        }
    }
}

struct LogEntry: Identifiable {
    let id = UUID()
    let date = Date()
    let text: String
}

/// CoreBluetooth central that discovers, connects to, and drives a Kamigami robot.
///
/// All CoreBluetooth callbacks are delivered on the main queue, so every property
/// here is only touched from the main thread.
final class KamigamiBLEManager: NSObject, ObservableObject {
    // MARK: Published state
    @Published private(set) var bluetoothState: CBManagerState = .unknown
    @Published private(set) var isScanning = false
    @Published private(set) var discovered: [DiscoveredRobot] = []
    @Published private(set) var connectionState: ConnectionState = .disconnected
    @Published private(set) var robotName: String?
    @Published private(set) var firmware: String?
    @Published private(set) var battery: Int?
    @Published private(set) var imu: IMUSample?
    @Published private(set) var motor: MotorState?
    @Published private(set) var lastIRHit: (hit: IRHit, date: Date)?
    @Published private(set) var lastFeature: (feature: IMUFeature, date: Date)?
    @Published private(set) var imuConfig: IMUConfig?
    @Published private(set) var isUpsideDown = false
    @Published private(set) var log: [LogEntry] = []
    @Published private(set) var commandedDrive: (left: Int, right: Int) = (0, 0)

    @Published private(set) var cockroachActive = false
    @Published private(set) var cockroachStatus: String = "Idle"
    @Published private(set) var cockroachLastEvent: String?
    @Published private(set) var demoRunning = false

    // MARK: User settings
    @Published var maxPower: Int = UserDefaults.standard.object(forKey: "maxPower") as? Int ?? 45 {
        didSet { UserDefaults.standard.set(maxPower, forKey: "maxPower") }
    }
    @Published var bumpThreshold: Double = UserDefaults.standard.object(forKey: "bumpThreshold") as? Double ?? 0.45 {
        didSet {
            UserDefaults.standard.set(bumpThreshold, forKey: "bumpThreshold")
            cockroach?.threshold = bumpThreshold
        }
    }
    @Published var cockroachSpeed: Int = UserDefaults.standard.object(forKey: "cockroachSpeed") as? Int ?? 40 {
        didSet {
            UserDefaults.standard.set(cockroachSpeed, forKey: "cockroachSpeed")
            cockroach?.speed = cockroachSpeed
        }
    }
    @Published var safetyCutoffEnabled: Bool = UserDefaults.standard.object(forKey: "safetyCutoff") as? Bool ?? true {
        didSet { UserDefaults.standard.set(safetyCutoffEnabled, forKey: "safetyCutoff") }
    }
    @Published var autoReconnect: Bool = UserDefaults.standard.object(forKey: "autoReconnect") as? Bool ?? true {
        didSet { UserDefaults.standard.set(autoReconnect, forKey: "autoReconnect") }
    }

    // MARK: Private
    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var commandChar: CBCharacteristic?
    private var telemetryChar: CBCharacteristic?
    private var batteryChar: CBCharacteristic?
    private var decoder = TelemetryDecoder()
    private var safety = SafetyMonitor()

    private var driveTimer: Timer?
    private var pendingDrive: (left: Int, right: Int) = (0, 0)
    private var cockroach: CockroachBehavior?
    private var cockroachTimer: Timer?
    private var unconsumedIMU: IMUSample?
    private var unconsumedFeature: IMUFeature?
    private var lastLED: (UInt8, UInt8, UInt8)?
    private var demoTask: Task<Void, Never>?
    private var userInitiatedDisconnect = false
    private var safetyWatchdog: Timer?

    private let controlServiceUUID = CBUUID(string: KamigamiUUID.controlService)
    private let commandUUID = CBUUID(string: KamigamiUUID.commandCharacteristic)
    private let telemetryUUID = CBUUID(string: KamigamiUUID.telemetryCharacteristic)
    private let batteryServiceUUID = CBUUID(string: KamigamiUUID.batteryService)
    private let batteryUUID = CBUUID(string: KamigamiUUID.batteryLevelCharacteristic)
    private let disServiceUUID = CBUUID(string: KamigamiUUID.deviceInfoService)
    private let firmwareUUID = CBUUID(string: KamigamiUUID.firmwareRevisionCharacteristic)

    private static let lastPeripheralKey = "lastPeripheralID"
    /// Heartbeat interval for drive commands (matches the web deck's 90 ms).
    private static let driveInterval: TimeInterval = 0.09

    override init() {
        super.init()
        central = CBCentralManager(delegate: self, queue: nil,
                                   options: [CBCentralManagerOptionShowPowerAlertKey: true])
    }

    var isReady: Bool { connectionState == .ready }

    // MARK: - Logging

    func addLog(_ text: String) {
        log.insert(LogEntry(text: text), at: 0)
        if log.count > 200 { log.removeLast(log.count - 200) }
    }

    // MARK: - Scanning & connection

    func startScan() {
        guard central.state == .poweredOn else {
            addLog("Bluetooth is not powered on")
            return
        }
        discovered.removeAll()
        // The robot does not always include the 128-bit service UUID in its
        // advertisement, so scan for everything and filter by name / company ID.
        central.scanForPeripherals(withServices: nil,
                                   options: [CBCentralManagerScanOptionAllowDuplicatesKey: true])
        isScanning = true
        addLog("Scanning for Kamigami robots…")
    }

    func stopScan() {
        if central.isScanning { central.stopScan() }
        isScanning = false
    }

    func connect(_ robot: DiscoveredRobot) {
        connect(peripheral: robot.peripheral)
    }

    private func connect(peripheral p: CBPeripheral) {
        stopScan()
        userInitiatedDisconnect = false
        peripheral = p
        p.delegate = self
        connectionState = .connecting
        robotName = p.name
        addLog("Connecting to \(p.name ?? p.identifier.uuidString)…")
        central.connect(p, options: nil)
    }

    func disconnect() {
        userInitiatedDisconnect = true
        stopCockroach()
        cancelDemo()
        if isReady {
            stopMotors()
            send(.configUpdates(imuHz: 0, motorHz: 0))
        }
        if let p = peripheral {
            central.cancelPeripheralConnection(p)
            if p.state != .connected {
                // A pending connection may not produce a didDisconnect callback.
                resetConnection()
                peripheral = nil
            }
        } else {
            resetConnection()
        }
    }

    private func resetConnection() {
        driveTimer?.invalidate(); driveTimer = nil
        safetyWatchdog?.invalidate(); safetyWatchdog = nil
        stopCockroach()
        commandChar = nil
        telemetryChar = nil
        batteryChar = nil
        connectionState = .disconnected
        battery = nil
        imu = nil
        motor = nil
        isUpsideDown = false
        safety.reset()
        decoder = TelemetryDecoder()
        lastLED = nil
        commandedDrive = (0, 0)
        pendingDrive = (0, 0)
    }

    private func tryAutoReconnect() {
        guard autoReconnect, connectionState == .disconnected,
              let idString = UserDefaults.standard.string(forKey: Self.lastPeripheralKey),
              let id = UUID(uuidString: idString),
              let known = central.retrievePeripherals(withIdentifiers: [id]).first else { return }
        addLog("Reconnecting to last robot…")
        connect(peripheral: known)
    }

    private func finishHandshake() {
        guard let p = peripheral, commandChar != nil, telemetryChar != nil else { return }
        if let t = telemetryChar { p.setNotifyValue(true, for: t) }
        if let b = batteryChar {
            p.setNotifyValue(true, for: b)
            p.readValue(for: b)
        }
        // Mirrors BleRobotManager.deviceConnected in the official app.
        send(.configIMU(accel: .g4, gyro: .dps2000, filtered: true))
        send(.readResponse(.imuConfig))
        send(.configUpdates(imuHz: 10, motorHz: 4))
        connectionState = .ready
        UserDefaults.standard.set(p.identifier.uuidString, forKey: Self.lastPeripheralKey)
        addLog("Ready — telemetry streaming at 10 Hz")
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        setLED(0, 229, 255)

        safetyWatchdog?.invalidate()
        safetyWatchdog = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            self?.refreshSafetyState()
        }
    }

    // MARK: - Writing

    private func send(_ command: KamigamiCommand, preferNoResponse: Bool = false) {
        guard let p = peripheral, let c = commandChar else { return }
        let canNoResponse = c.properties.contains(.writeWithoutResponse)
        if preferNoResponse && canNoResponse {
            // Drop rather than queue: the next heartbeat carries the latest value.
            guard p.canSendWriteWithoutResponse else { return }
            p.writeValue(command.data, for: c, type: .withoutResponse)
        } else {
            p.writeValue(command.data, for: c, type: .withResponse)
        }
    }

    // MARK: - Commands

    /// Continuously drive (re-sent every 90 ms until set back to zero).
    func drive(left: Int, right: Int) {
        let l = KamigamiCommand.clampPower(left)
        let r = KamigamiCommand.clampPower(right)
        if cockroachActive || demoRunning, l != 0 || r != 0 {
            stopCockroach()
            cancelDemo()
        }
        applyDrive(l, r)
    }

    private func applyDrive(_ left: Int, _ right: Int) {
        guard isReady else { return }
        var l = left, r = right
        if safetyCutoffEnabled && isUpsideDown && (l != 0 || r != 0) {
            l = 0; r = 0
        }
        let changed = l != pendingDrive.left || r != pendingDrive.right
        pendingDrive = (l, r)
        commandedDrive = (l, r)
        if l == 0 && r == 0 {
            driveTimer?.invalidate(); driveTimer = nil
            if changed { send(.stop) }  // reliable write for stop
            return
        }
        if changed { send(.driveDirect(left: l, right: r), preferNoResponse: true) }
        if driveTimer == nil {
            let t = Timer(timeInterval: Self.driveInterval, repeats: true) { [weak self] _ in
                guard let self else { return }
                let (l, r) = self.pendingDrive
                self.send(.driveDirect(left: l, right: r), preferNoResponse: true)
            }
            RunLoop.main.add(t, forMode: .common)
            driveTimer = t
        }
    }

    func stopMotors() {
        driveTimer?.invalidate(); driveTimer = nil
        pendingDrive = (0, 0)
        commandedDrive = (0, 0)
        send(.stop)
    }

    /// Emergency stop: halts motors and any autonomous behavior.
    func emergencyStop() {
        stopCockroach()
        cancelDemo()
        stopMotors()
        UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
        addLog("ALL STOP")
    }

    func setLED(_ r: UInt8, _ g: UInt8, _ b: UInt8) {
        lastLED = (r, g, b)
        send(.eyeColor(r: r, g: g, b: b))
    }

    func fireIR(id: UInt8, command: UInt8) {
        send(.infrared(id: id, command: command))
        UIImpactFeedbackGenerator(style: .rigid).impactOccurred()
        addLog("IR fired (id \(id), cmd \(command))")
    }

    func powerDown() {
        emergencyStop()
        send(.powerDown)
        addLog("Power down sent")
    }

    // MARK: - Demo routine

    func runDemo() {
        guard isReady, !demoRunning else { return }
        stopCockroach()
        demoRunning = true
        addLog("Running demo routine…")
        demoTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.demoRunning = false }
            for (r, g, b) in [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 255)] {
                self.setLED(UInt8(r), UInt8(g), UInt8(b))
                try? await Task.sleep(nanoseconds: 250_000_000)
                if Task.isCancelled { return }
            }
            for (l, r, dur) in [(42, 42, 0.7), (-42, -42, 0.6), (-45, 45, 0.6), (45, -45, 0.6)] {
                self.applyDrive(l, r)
                try? await Task.sleep(nanoseconds: UInt64(dur * 1_000_000_000))
                if Task.isCancelled { return }
            }
            self.stopMotors()
            self.send(.infrared(id: 1, command: 99))
            self.setLED(0, 255, 255)
            self.addLog("Demo finished")
        }
    }

    func cancelDemo() {
        guard demoRunning else { return }
        demoTask?.cancel()
        demoTask = nil
        demoRunning = false
        stopMotors()
    }

    // MARK: - Cockroach mode

    func startCockroach() {
        guard isReady, !cockroachActive else { return }
        cancelDemo()
        cockroach = CockroachBehavior(speed: cockroachSpeed, threshold: bumpThreshold)
        unconsumedIMU = nil
        unconsumedFeature = nil
        cockroachActive = true
        addLog("🪳 Cockroach mode started")
        let t = Timer(timeInterval: 0.05, repeats: true) { [weak self] _ in self?.tickCockroach() }
        RunLoop.main.add(t, forMode: .common)
        cockroachTimer = t
    }

    func stopCockroach() {
        guard cockroachActive else { return }
        cockroachTimer?.invalidate(); cockroachTimer = nil
        cockroach = nil
        cockroachActive = false
        cockroachStatus = "Idle"
        stopMotors()
        addLog("Cockroach mode stopped")
    }

    private func tickCockroach() {
        guard var behavior = cockroach else { return }
        let upside = safetyCutoffEnabled && safety.isUpsideDown()
        let actions = behavior.tick(now: Date(), imu: unconsumedIMU, feature: unconsumedFeature, upsideDown: upside)
        unconsumedIMU = nil
        unconsumedFeature = nil
        let previousPhase = cockroach?.phase
        cockroach = behavior
        cockroachStatus = behavior.phase.label
        if behavior.phase != previousPhase,
           [CockroachBehavior.Phase.paused, .upsideDown, .recovering].contains(behavior.phase),
           let ev = behavior.lastEvent {
            cockroachLastEvent = ev
            addLog("🪳 \(ev)")
            if behavior.phase == .paused {
                UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
            }
        }
        for action in actions {
            switch action {
            case let .drive(l, r): applyDrive(l, r)
            case .stop: applyDrive(0, 0)
            case let .led(r, g, b):
                if let cur = lastLED, cur.0 == r, cur.1 == g, cur.2 == b { continue }
                setLED(r, g, b)
            }
        }
    }

    // MARK: - Telemetry

    private func refreshSafetyState() {
        let upside = safety.isUpsideDown()
        if upside != isUpsideDown {
            isUpsideDown = upside
            if upside {
                addLog("⚠️ Upside down — motors disabled")
                if safetyCutoffEnabled {
                    driveTimer?.invalidate(); driveTimer = nil
                    pendingDrive = (0, 0)
                    commandedDrive = (0, 0)
                    send(.stop)
                    UINotificationFeedbackGenerator().notificationOccurred(.warning)
                }
            } else {
                addLog("Robot upright again")
            }
        }
    }

    private func handleTelemetry(_ data: Data) {
        guard let packet = decoder.decode(data) else { return }
        switch packet {
        case let .imu(sample):
            imu = sample
            unconsumedIMU = sample
            safety.ingest(sample)
            refreshSafetyState()
        case let .motor(state):
            motor = state
        case let .infrared(hit):
            lastIRHit = (hit, Date())
            addLog("🎯 IR hit from \(hit.direction?.label ?? "?") — id \(hit.id), cmd \(hit.command)")
            UINotificationFeedbackGenerator().notificationOccurred(.error)
        case let .imuFeature(feature, _):
            lastFeature = (feature, Date())
            unconsumedFeature = feature
        case let .imuConfig(config):
            imuConfig = config
        case .led, .imu2Config, .unknown:
            break
        }
    }
}

// MARK: - CBCentralManagerDelegate

extension KamigamiBLEManager: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        bluetoothState = central.state
        if central.state == .poweredOn {
            tryAutoReconnect()
            if connectionState == .disconnected { startScan() }
        } else {
            isScanning = false
            if connectionState != .disconnected { resetConnection() }
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        let name = (advertisementData[CBAdvertisementDataLocalNameKey] as? String) ?? peripheral.name ?? ""
        let services = (advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID]) ?? []
        var isDash = false
        if let mfg = advertisementData[CBAdvertisementDataManufacturerDataKey] as? Data, mfg.count >= 2 {
            let company = UInt16(mfg[mfg.startIndex]) | (UInt16(mfg[mfg.startIndex + 1]) << 8)
            isDash = company == KamigamiUUID.dashCompanyID
        }
        guard isDash || services.contains(controlServiceUUID)
                || name.uppercased().hasPrefix(KamigamiUUID.namePrefix) else { return }

        let rssi = RSSI.intValue == 127 ? -100 : RSSI.intValue
        let display = name.isEmpty ? "Kamigami" : name
        if let i = discovered.firstIndex(where: { $0.id == peripheral.identifier }) {
            // Throttle UI updates from duplicate advertisements.
            if Date().timeIntervalSince(discovered[i].lastSeen) > 0.5 {
                discovered[i].rssi = rssi
                discovered[i].name = display
                discovered[i].lastSeen = Date()
            }
        } else {
            discovered.append(DiscoveredRobot(id: peripheral.identifier, peripheral: peripheral,
                                              name: display, rssi: rssi, lastSeen: Date()))
            addLog("Found \(display) (\(rssi) dBm)")
        }
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        connectionState = .discovering
        addLog("Connected — discovering services…")
        peripheral.discoverServices([controlServiceUUID, batteryServiceUUID, disServiceUUID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        addLog("Failed to connect: \(error?.localizedDescription ?? "unknown error")")
        resetConnection()
        self.peripheral = nil
        startScan()
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        addLog(error.map { "Disconnected: \($0.localizedDescription)" } ?? "Disconnected")
        resetConnection()
        if !userInitiatedDisconnect && autoReconnect {
            // Keep a pending connection; iOS completes it when the robot is back in range.
            connect(peripheral: peripheral)
        } else {
            self.peripheral = nil
            startScan()
        }
    }
}

// MARK: - CBPeripheralDelegate

extension KamigamiBLEManager: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error { addLog("Service discovery failed: \(error.localizedDescription)") }
        for service in peripheral.services ?? [] {
            switch service.uuid {
            case controlServiceUUID:
                peripheral.discoverCharacteristics([commandUUID, telemetryUUID], for: service)
            case batteryServiceUUID:
                peripheral.discoverCharacteristics([batteryUUID], for: service)
            case disServiceUUID:
                peripheral.discoverCharacteristics([firmwareUUID], for: service)
            default:
                break
            }
        }
        if !(peripheral.services ?? []).contains(where: { $0.uuid == controlServiceUUID }) {
            addLog("This device has no Kamigami control service")
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        for c in service.characteristics ?? [] {
            switch c.uuid {
            case commandUUID: commandChar = c
            case telemetryUUID: telemetryChar = c
            case batteryUUID: batteryChar = c
            case firmwareUUID: peripheral.readValue(for: c)
            default: break
            }
        }
        if service.uuid == controlServiceUUID && connectionState == .discovering {
            // Battery service may arrive later; it is subscribed to when found.
            finishHandshake()
        } else if service.uuid == batteryServiceUUID, isReady, let b = batteryChar {
            peripheral.setNotifyValue(true, for: b)
            peripheral.readValue(for: b)
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let value = characteristic.value else { return }
        switch characteristic.uuid {
        case telemetryUUID:
            handleTelemetry(value)
        case batteryUUID:
            if let b = value.first { battery = Int(b) }
        case firmwareUUID:
            firmware = String(data: value, encoding: .utf8)?
                .trimmingCharacters(in: .controlCharacters.union(.whitespaces))
        default:
            break
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        if let error { addLog("Write error: \(error.localizedDescription)") }
    }

    func peripheralIsReady(toSendWriteWithoutResponse peripheral: CBPeripheral) {
        // Nothing queued: drive heartbeats always carry the latest value.
    }
}
