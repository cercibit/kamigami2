# Kamigami Robot (KRB0002) — Hardware Scan & BLE Protocol Specification (Firmware 2.0.2)

This document contains the complete hardware architecture report, Bluetooth Low Energy (BLE) GATT map, reverse-engineered binary command/telemetry protocol specification (`Firmware 2.0.2` vs. legacy `Firmware 0.34`), live sensor captures, and Linux/BlueZ Python SDK + Web UI documentation for the **Kamigami Robot** (`KRB0002`, manufactured by **Dash Robotics, Inc.** / **Mattel**).

---

## 1. Hardware & Connectivity Overview

### 1.1 Why USB Does Not Enumerate on a PC
The micro-USB port on the Kamigami robot chassis is **power-only** (`+5V` and `GND` routed directly to the onboard single-cell 3.7V LiPo battery charger IC). The USB data lines (`D+` and `D-`) are not connected to the microcontroller. In addition, the robot disables BLE radio advertising while charging over USB.

### 1.2 Onboard Electronics Architecture (Hardware Rev 2.0 / Firmware 2.0.2)
* **System-on-Chip (SoC):** Nordic Semiconductor **nRF51822** (32-bit ARM Cortex-M0 CPU + 2.4 GHz Bluetooth Low Energy transceiver, running Nordic SoftDevice S110/S130 `0x0064`).
* **6-Axis IMU:** **Bosch BMI160** I²C 3-axis accelerometer (`±2g` / `±4g` / `±8g` / `±16g`) + 3-axis gyroscope (`±125` / `±250` / `±500` / `±1000` / `±2000 deg/s`), with hardware interrupt detection (`AnyMotion`, `SignificantMotion`, `SingleTap`, `DoubleTap`, `Orientation`, `Flat`, `LowG`, `HighG`, `SlowMotion`, `NoMotion`).
* **Motor Actuators:** Dual H-bridge DC motor driver controlling independent Left and Right leg linkage gearmotors (PWM range `-63` to `+63`), with optional onboard yaw-rate PID stabilization.
* **Infrared (IR) Transceiver System:**
  * 1× IR transmitter LED (for robot-to-robot "battle" tags and communication).
  * Directional IR receivers (`FRONT = 1`, `BACK = 2`).
* **Status / Eye Indicator:** Full-color RGB LED (`8-bit` Red, Green, Blue channels).

---

## 2. Scanned Device Identity (`KRB0002`)

Interrogated over BLE via Linux BlueZ (`hci0`):

| Property | Value | Source |
| :--- | :--- | :--- |
| **BLE Device Name** | `KRB0002` | GAP `0x2A00` / Advertisement |
| **BLE MAC Address** | `XX:XX:XX:XX:XX:XX` (Random Static) | BLE Link Layer |
| **Manufacturer Name** | `Dash Robotics, Inc.` | DIS `0x2A29` |
| **Bluetooth SIG Company ID** | `0x02C0` (Dash Robotics, Inc.) | Advertisement Manufacturer Data |
| **Unique Serial Number (USN)** | `<16-byte-hex-usn>` (16 bytes) | Advertisement Manufacturer Payload |
| **Model Number** | `2.0` | DIS `0x2A24` |
| **Hardware Revision** | `2.0` | DIS `0x2A27` |
| **Firmware Revision** | `2.0.2 (Sep  5 2017 00:05:25)` | DIS `0x2A26` |
| **Software Revision** | `2.0` | DIS `0x2A28` |
| **DFU Bootloader Version** | `0x0100` (v0.1 Application Mode) | Nordic DFU `00001534-...` |
| **Preferred Conn. Parameters** | Interval `30.0–35.0 ms`, Latency `0`, Timeout `4000 ms` | GAP `0x2A04` (`18001c0000009001`) |
| **ATT MTU** | `23` bytes (max payload `20` bytes) | GATT Link |

---

## 3. Complete BLE GATT Service & Characteristic Map

| Service / Characteristic | UUID | BlueZ Path Suffix | Properties | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Generic Access (GAP)** | `00001800-0000-1000-8000-00805f9b34fb` | `service0001` | — | Standard BLE GAP Service |
| ├─ Device Name | `00002a00-0000-1000-8000-00805f9b34fb` | `char0002` | `read`, `write` | `"KRB0002"` |
| ├─ Appearance | `00002a01-0000-1000-8000-00805f9b34fb` | `char0004` | `read` | `0x0000` |
| └─ Preferred Conn Params | `00002a04-0000-1000-8000-00805f9b34fb` | `char0006` | `read` | `18 00 1c 00 00 00 90 01` |
| **Generic Attribute (GATT)** | `00001801-0000-1000-8000-00805f9b34fb` | `service0008` | — | Standard BLE GATT Service |
| └─ Service Changed | `00002a05-0000-1000-8000-00805f9b34fb` | `char0009` | `indicate` | GATT table change indicator |
| **Battery Service** | `0000180f-0000-1000-8000-00805f9b34fb` | `service000c` | — | Battery telemetry |
| └─ Battery Level | `00002a19-0000-1000-8000-00805f9b34fb` | `char000d` | `read`, `notify` | 1-byte percentage (`0`–`100%`) |
| **Device Information** | `0000180a-0000-1000-8000-00805f9b34fb` | `service0010` | — | Board & firmware strings |
| ├─ Manufacturer Name | `00002a29-0000-1000-8000-00805f9b34fb` | `char0011` | `read` | `"Dash Robotics, Inc."` |
| ├─ Model Number | `00002a24-0000-1000-8000-00805f9b34fb` | `char0013` | `read` | `"2.0"` |
| ├─ Hardware Revision | `00002a27-0000-1000-8000-00805f9b34fb` | `char0015` | `read` | `"2.0"` |
| ├─ Firmware Revision | `00002a26-0000-1000-8000-00805f9b34fb` | `char0017` | `read` | `"2.0.2 (Sep  5 2017 00:05:25)"` |
| └─ Software Revision | `00002a28-0000-1000-8000-00805f9b34fb` | `char0019` | `read` | `"2.0"` |
| **Nordic OTA DFU Service** | `00001530-6b09-45c8-be6d-4bb4e0471435` | `service001b` | — | Custom base UUID Nordic Legacy DFU |
| ├─ DFU Control Point | `00001531-6b09-45c8-be6d-4bb4e0471435` | `char001e` | `write`, `notify` | OTA state machine control |
| ├─ DFU Packet | `00001532-6b09-45c8-be6d-4bb4e0471435` | `char001c` | `write-without-response` | Firmware image data stream |
| └─ DFU Version | `00001534-6b09-45c8-be6d-4bb4e0471435` | `char0021` | `read` | `01 00` |
| **Kamigami Robot Control** | `708a96f0-f200-4e2f-96f0-9bc43c3a31c8` | `service0023` | — | Primary Robot Control & Sensor Service |
| ├─ **WRITE (Host → Robot)** | `708a96f1-f200-4e2f-96f0-9bc43c3a31c8` | `char0027` | `write`, `write-without-response` | Command packets (Motors, LED, IR, Config) |
| └─ **NOTIFY (Robot → Host)** | `708a96f2-f200-4e2f-96f0-9bc43c3a31c8` | `char0024` | `notify` | Telemetry packets (IMU, IMU2, IR, Motors) |

---

## 4. Kamigami Firmware 2.0.2 Binary BLE Protocol Specification

Reverse-engineered by decompiling the official Mattel/Dash Robotics **Kamigami Controller v1.4.0 APK** (`com.dashrobotics.kamigami2`, targeting Firmware `2.0.2`) and comparing it against the legacy 2016 Kickstarter **Dash Drive v0.11 APK** (`com.dashrobotics.kamigamiapp`, targeting Firmware `0.34`).

### 4.1 Protocol Version Comparison: Firmware `2.0.2` vs. Legacy Firmware `0.34`

| Feature / Command | **Firmware `2.0.2` (`com.dashrobotics.kamigami2` v1.4.0)** | Legacy Firmware `0.34` (`com.dashrobotics.kamigamiapp` v0.11) |
| :--- | :--- | :--- |
| **PowerDown** | **`0x00`** (`1` B): `[0x00]` *(puts robot into deep sleep)* | *(Not present)* |
| **EyeColor (RGB LED)** | **`0x01`** (`7` B): `[0x01, 0x00, R, G, B, 0x00, 0x00]` | `0x02` (`4` B): `[0x02, R, G, B]` |
| **MotorDirect / Stabilized** | **`0x02`** (`6` B): `[0x02, mode(0/1), L, R, yaw_lo, yaw_hi]` | `0x03` (`3` B direct) / `0x04` (`6` B stabilized) |
| **Infrared (IR)** | **`0x03`** (`3` B): `[0x03, id, cmd]` | `0x05` (`3` B): `[0x05, id, cmd]` |
| **ReadResponse** | **`0x20` (`32`)** (`2` B): `[0x20, target_code]` | `0x08` (`2` B): `[0x08, target_code]` |
| **ConfigUpdates (Stream)** | **`0x21` (`33`)** (`3` B): `[0x21, imu_hz, motor_hz]` | `0x0C` (`5` B): `[0x0C, imu_hz, lux_hz, motor_hz, filt_hz]` |
| **ConfigIMU** | **`0x40` (`64`)** (`4` B): `[0x40, acc_code, rot_code, filt_en]` | `0x0B` (`4` B): `[0x0B, acc_code, rot_code, filt_en]` |
| **ConfigIMU2 (BMI160 Ints)** | **`0x41` (`65`)** (`18` B): `[0x41, b0..b16]` | *(Not present)* |
| **UpdateUSN** | **`0x44` (`68`)** (`17` B): `[0x44, b0..b15]` | `0x0D` (`17` B): `[0x0D, b0..b15]` |

---

### 4.2 Commands (`Host → Robot` on `708a96f1-f200-4e2f-96f0-9bc43c3a31c8`)

All commands begin with a 1-byte `RobotCommand` opcode (`byte[0]`). Always send the exact byte length specified below; sending a truncated packet causes the nRF51 firmware parser to reject the write with `ATT Error 0x0e (Unlikely Error)`.

| Opcode | Enum Name | Length | Byte Layout | Field Details |
| :---: | :--- | :---: | :--- | :--- |
| **`0x00`** (`0`) | `PowerDown` | 1 B | `[0x00]` | **Immediately powers down the robot into deep sleep.** |
| **`0x01`** (`1`) | `EyeColor` | 7 B | `[0x01, 0x00, R, G, B, 0x00, 0x00]` | Sets RGB eye LED color (`R, G, B` each `0x00`–`0xFF`; `byte[1]`, `byte[5]`, `byte[6]` are `0x00`). |
| **`0x02`** (`2`) | `MotorDirect` | 6 B | **Direct:** `[0x02, 0x00, left, right, 0x00, 0x00]`<br>**Stabilized:** `[0x02, 0x01, left, right, yaw_lo, yaw_hi]` | Drives Left and Right leg motors:<br>• `byte[1]`: `0x00` = Direct open-loop, `0x01` = Gyro-stabilized<br>• `left`, `right`: signed `int8` in `[-63, +63]` (`power * 63.0f`)<br>• `yaw_lo, yaw_hi`: Little-Endian `int16` reference yaw (when `byte[1] == 0x01`).<br>• `[0x02, 0, 0, 0, 0, 0]` stops both motors. |
| **`0x03`** (`3`) | `IR` | 3 B | `[0x03, id, cmd]` | Transmits an Infrared packet with 8-bit `id` and 8-bit `cmd`. |
| **`0x0E`** (`14`) | `UpdateCommandCount` | 9 B | `[0x0E, 0, 0, 0, 0, 0, 0, 0, 0]` | Queries/resets the robot's internal command execution counter. |
| **`0x0F`** (`15`) | `Unified` | Var | `[0x0F, ...]` | Reserved unified command opcode. |
| **`0x11`** (`17`) | `MotorConfigStabilization` | 17 B | `[0x11, P(4B), I(4B), AWU(4B), dbLow(2B), dbHigh(2B)]` | Configures yaw stabilization PID gains (Little-Endian). |
| **`0x20`** (`32`) | `ReadResponse` | 2 B | `[0x20, target_code]` | Requests an immediate one-shot notification on `708a96f2-...` for `target_code` (e.g. `[0x20, 0x40]` for `IMUConfig` or `[0x20, 0x41]` for `IMU2Config`). |
| **`0x21`** (`33`) | `ConfigUpdates` | 3 B | `[0x21, imu_hz, motor_hz]` | **Enables or disables live sensor telemetry streaming!**<br>• `imu_hz`: IMU notification frequency in Hz (e.g. `10`)<br>• `motor_hz`: Motor state notification frequency in Hz (e.g. `4`)<br>*(Send `[0x21, 0, 0]` to stop streaming).* |
| **`0x40`** (`64`) | `ConfigIMU` | 4 B | `[0x40, acc_code, rot_code, filt_en]` | Configures the Bosch BMI160 IMU full-scale ranges and filtering:<br>• `acc_code` (BMI160 `ACC_RANGE`): `3` = ±2g, `5` = ±4g, `8` = ±8g, `12` = ±16g<br>• `rot_code` (BMI160 `GYR_RANGE`): `0` = ±2000 dps, `1` = ±1000 dps, `2` = ±500 dps, `3` = ±250 dps, `4` = ±125 dps<br>• `filt_en`: `1` = enabled, `0` = disabled. |
| **`0x41`** (`65`) | `ConfigIMU2` | 18 B | `[0x41, b0, ..., b16]` | Configures BMI160 hardware motion interrupt bitfields (`SigMotion` bytes `0..1`, `Tap` bytes `2..3`, `Orientation` bytes `4..5`, `Flat` bytes `6..7`, `LowG` bytes `8..10`, `HighG` bytes `11..13`, `LowMotion` bytes `14..16`). |
| **`0x44`** (`68`) | `UpdateUSN` | 17 B | `[0x44, b0, ..., b15]` | Writes a new 16-byte Unique Serial Number (USN) to the robot's BLE advertisement data. |

#### Connection Handshake Sequence (`BleRobotManager.deviceConnected`)
Upon connecting and enabling notifications on `708a96f2-...` (`NOTIFY`) and `00002a19-...` (`ROBOT_BATTERY_LEVEL`), the official `Kamigami Controller` app writes:
1. `ConfigIMU`: `[0x40, 0x05, 0x00, 0x01]` (±4g accelerometer, ±2000 dps gyroscope, filtering enabled)
2. `ReadResponse(IMUConfig)`: `[0x20, 0x40]`
3. `ConfigIMU2`: `[0x41, ...17 bytes]` (enables double-tap `enableTap2=1, threshold=8, tap2Duration=4` and X-axis crash/bump `highg.enableX=1, hysteresis=1, threshold=59, duration=9`)
4. `ReadResponse(IMU2Config)`: `[0x20, 0x41]`

---

### 4.3 Telemetry Notifications (`Robot → Host` on `708a96f2-f200-4e2f-96f0-9bc43c3a31c8`)

All notification packets emitted on `708a96f2-...` begin with a 1-byte `RobotReadResponse` type identifier (`byte[0]`), followed by the type-specific payload (`byte[1..N]`).

| Type Code | Enum Name | Total Length | Payload Structure (`byte[1..N]`) | Decoding Formula |
| :---: | :--- | :---: | :--- | :--- |
| **`0x01`** (`1`) | `LED` | 4 B | `[R, G, B]` | Current RGB LED state (`uint8` per channel). |
| **`0x02`** (`2`) | `Motor` | 10 B or 14 B | `[mode, pwrL, pwrR, yawHi, yawLo, pwmL1, pwmL2, pwmR1, pwmR2, ...]` | • `mode`: `(payload[0] & 1) == 0` → `DIRECT`, `1` → `STABILIZED`<br>• `leftPower = int8(payload[1])`, `rightPower = int8(payload[2])` in `[-63, +63]`<br>• `leftRawPWM = int8(payload[5] - payload[6])`<br>• `rightRawPWM = int8(payload[7] - payload[8])`<br>• If `STABILIZED`: `yawRate = int16_be(payload[3..4])`, `mix = int32_be(payload[9..12])`. |
| **`0x03`** (`3`) | `IR` | 4 B | `[direction, id, command]` | Triggered automatically when an IR packet is received:<br>• `direction`: `1` = `FRONT`, `2` = `BACK`<br>• `id`: 8-bit sender ID<br>• `command`: 8-bit IR command payload. |
| **`0x05`** (`5`) | `IMU` | 13 B | `6 × int16` (Little-Endian) | `[ax, ay, az, gx, gy, gz]` (`<6h`):<br>• `accel_{x,y,z} (g) = raw * AccelScale / 32767.0` (or `/ 32768.0` if `< 0`)<br>• `gyro_{x,y,z} (dps) = raw * GyroScale / 32767.0` (or `/ 32768.0` if `< 0`)<br>Default scales: `AccelScale = 4g`, `GyroScale = 2000 dps`. |
| **`0x06`** (`6`) | `IMU2` | 3–6 B | `[feature_type, ...]` | BMI160 hardware feature interrupt (`IMUFeatureType`):<br>• `feature_type`: `0`=AnyMotion, `1`=SignificantMotion, `2`=SingleTap, `3`=DoubleTap, `4`=Orientation, `5`=Flat, `6`=LowG, `7`=HighG, `8`=SlowMotion, `9`=NoMotion.<br>• For `AnyMotion`/`SingleTap`/`DoubleTap`/`HighG`: `payload[1]` = Sign (`0`=Positive, `1`=Negative), `payload[2..4]` = `triggeredX, triggeredY, triggeredZ` booleans.<br>• For `Orientation`: `payload[1]` = `OrientationZ` (`0`=Upside, `1`=Downside), `payload[2]` = `Orientation` (`0`=PortraitUp, `1`=PortraitDown, `2`=LandscapeLeft, `3`=LandscapeRight).<br>• For `Flat`: `payload[1]` = `FlatPosition` (`0`=NotFlat, `1`=Flat). |
| **`0x40`** (`64`) | `IMUConfig` | 4 B | `[acc_code, rot_code, filt_en]` | • `acc_code`: `3`=2g, `5`=4g, `8`=8g, `12`=16g<br>• `rot_code`: `0`=2000dps, `1`=1000dps, `2`=500dps, `3`=250dps, `4`=125dps<br>• `filt_en`: `0` or `1`. |
| **`0x41`** (`65`) | `IMU2Config` | 18 B | `17 × uint8` | 17-byte BMI160 interrupt configuration buffer. |

---

## 5. Verified Live Telemetry Capture from `KRB0002`

Captured directly from `KRB0002` immediately after pulsing the leg motors (`[0x02, 0, L, R, 0, 0]`) and enabling 10 Hz IMU + 4 Hz Motor updates (`[0x21, 10, 4]`):

```text
[BATTERY ] 75%
[IMU_CFG ] AccelScale=±4g, GyroScale=±2000dps, Filtered=False
[IMU     ] Accel(g): X=-0.068 Y=+0.050 Z=+1.164 | Gyro(dps): X=+268.32 Y= +67.69 Z= +32.23
[IMU     ] Accel(g): X=-0.220 Y=+0.221 Z=+1.264 | Gyro(dps): X=-268.92 Y= +47.00 Z= -55.73
[MOTOR   ] Mode=DIRECT LeftPwr=0 RightPwr=0 LeftPWM=0 RightPWM=0
[IMU     ] Accel(g): X=-0.197 Y=-0.043 Z=+0.129 | Gyro(dps): X= +22.95 Y=+384.90 Z= +65.61
[IMU     ] Accel(g): X=-0.082 Y=-0.031 Z=+1.067 | Gyro(dps): X=  +0.37 Y=  +0.12 Z=  -0.12
```

---

## 6. Python CLI & Web Control UI

### 6.1 Command-Line Interface (`kamigami_cli.py`)

A zero-dependency Python 3 script (using standard Linux BlueZ `dbus` and `PyGObject` / `GLib`) is provided in [`kamigami_cli.py`](kamigami_cli.py).

1. **Stream Live Sensors (IMU, Motor State, IR Hits, Battery):**
   ```bash
   python3 kamigami_cli.py monitor --duration 15
   ```
2. **Change Robot Eye LED Color:**
   ```bash
   python3 kamigami_cli.py led 255 0 128
   ```
3. **Test Walk / Spin Motors:**
   ```bash
   python3 kamigami_cli.py drive --left 35 --right 35 --duration 1.0
   ```
4. **Fire Infrared Tag Packet:**
   ```bash
   python3 kamigami_cli.py ir --id 1 --cmd 42
   ```

### 6.2 Interactive Web Dashboard (`kamigami_ui.py`)

Run [`kamigami_ui.py`](kamigami_ui.py) to launch a local web control deck on `http://localhost:8765`:
```bash
python3 kamigami_ui.py
```
Features:
* Virtual 2D touch/mouse joystick + `W` `A` `S` `D` / Arrow key driving (`[0x02, 0, L, R, 0, 0]`)
* Adjustable max motor power limit (`15`–`63`)
* RGB Eye LED presets and custom color picker (`[0x01, 0, R, G, B, 0, 0]`)
* Infrared battle laser trigger (`[0x03, id, cmd]`) and one-click choreographed demo routine
* Real-time 6-axis IMU (`Accel g` & `Gyro dps`), Motor state, and Battery percentage panel
