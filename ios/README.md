# Kamigami Controller for iOS

A native SwiftUI + CoreBluetooth controller for the **Kamigami robot** (`KRB0002`, Firmware 2.0.2).
It talks directly to the robot over Bluetooth LE using the protocol documented in
[`../KAMIGAMI_HARDWARE_AND_PROTOCOL.md`](../KAMIGAMI_HARDWARE_AND_PROTOCOL.md). No computer or server is needed.

## Features

| Tab | What it does |
| :-- | :-- |
| **Connect** | Scans for robots by name (`KRB*`), Dash Robotics company ID (`0x02C0`), or the control service UUID. Signal bars, one-tap connect, auto-reconnect to the last robot. |
| **Drive** | Three modes: **Joystick** (arcade mix, same as the web deck), **Tank** (independent left/right sliders), **Tilt** (hold the button and steer by tilting the phone). Max power limiter (15–63) and live L/R motor bars. |
| **Lights & IR** | Eye LED presets plus a full color picker. Fire IR battle tags with a player ID and command. Incoming IR hits trigger a haptic. Demo routine. Power down. |
| **Cockroach** | Autonomous obstacle-avoidance mode, ported from `cockroach_sim.py`: dart forward, detect impacts (IMU shock, yaw spike, stall, BMI160 HighG/tap interrupts), freeze 2 s, back up, turn randomly. Speed and collision-threshold sliders. |
| **Sensors** | Live 10 Hz accelerometer/gyroscope bars, motor state, IMU range, hardware IMU events, battery, firmware, and an event log. |

Safety:
- A **STOP** button is always visible. It halts motors and stops any autonomous routine.
- **Upside-down cutoff**: if the robot is flipped (`az < −0.45g` for 2 samples), motors stop and drive commands are ignored until it is upright (`az > 0.35g`). Stale telemetry never triggers it.
- Motors stop when the app goes to the background.
- Drive commands are resent as a heartbeat every 90 ms while a control is held, and stop is sent as an acknowledged write when it is released.

## Build & run

Requirements: Xcode 15+ and an iPhone or iPad running iOS 16+. Bluetooth doesn't work in the Simulator, so use a real device.

1. Open `ios/KamigamiController.xcodeproj`.
2. Select the **KamigamiController** target, go to **Signing & Capabilities**, choose your Team, and change the bundle identifier (`com.example.kamigamicontroller`) to something unique.
3. Plug in your device and press **Run**.
4. Unplug the robot from USB (it does not advertise while charging) and switch it on. It appears in the list.

App icon: the asset catalog has an empty 1024×1024 `AppIcon` slot. Drag any 1024×1024 PNG onto it in Xcode to give the app an icon.

## Project layout

```
ios/
├── KamigamiController.xcodeproj
├── KamigamiController/
│   ├── KamigamiControllerApp.swift   App entry, theme, background safety stop
│   ├── Core/                         Pure Swift, no UIKit/CoreBluetooth (unit tested)
│   │   ├── KamigamiProtocol.swift    UUIDs, command encoder, telemetry decoder, drive mixers
│   │   └── Behaviors.swift           Upside-down SafetyMonitor + CockroachBehavior state machine
│   ├── BLE/
│   │   ├── KamigamiBLEManager.swift  CoreBluetooth central: scan, connect, handshake, drive heartbeat
│   │   └── TiltController.swift      CoreMotion tilt to joystick
│   ├── Views/                        SwiftUI screens
│   └── Resources/                    Info.plist, asset catalog
├── Package.swift                     SwiftPM package exposing Core/ for `swift test`
└── Tests/KamigamiCoreTests/          Protocol / mixer / safety / cockroach tests
```

## Tests

The protocol and behavior logic is platform independent:

```bash
cd ios && swift test
```

CI (`.github/workflows/ios.yml`) runs these tests and builds the app for the iOS Simulator on every push that touches `ios/`.

## Protocol summary (Firmware 2.0.2)

| Command | Bytes |
| :-- | :-- |
| Eye LED | `[0x01, 0x00, R, G, B, 0x00, 0x00]` |
| Drive (direct) | `[0x02, 0x00, L, R, 0x00, 0x00]` with L/R as `int8` in `−63…63` |
| IR | `[0x03, id, cmd]` |
| Stream config | `[0x21, imu_hz, motor_hz]` |
| IMU config | `[0x40, acc, gyro, filter]` |
| Power down | `[0x00]` |

On connect, the app sends the same handshake as the official app: `ConfigIMU ±4g/±2000dps`, `ReadResponse(IMUConfig)`, then enables 10 Hz IMU and 4 Hz motor streaming.
