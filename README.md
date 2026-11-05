# Kamigami Robot (KRB0002 - Firmware 2.0.2) Linux BLE SDK & Web Control Deck

Complete hardware reverse-engineering documentation, binary Bluetooth Low Energy (BLE) protocol specification (`Firmware 2.0.2` / `com.dashrobotics.kamigami2`), Python CLI SDK, and interactive Web Control Deck for the **Kamigami Robot** (`KRB0002`).

## Repository Contents

* **[`KAMIGAMI_HARDWARE_AND_PROTOCOL.md`](KAMIGAMI_HARDWARE_AND_PROTOCOL.md)** — Full hardware scan report, GATT UUID & BlueZ path map, Firmware `2.0.2` vs. legacy Firmware `0.34` binary command/telemetry protocol tables, Bosch BMI160 `IMU2Config` bitfields, and verified live telemetry logs.
* **[`kamigami_cli.py`](kamigami_cli.py)** — Linux BlueZ D-Bus Python SDK and CLI tool with automatic BLE robot discovery (`Company ID 0x02C0` / Service `708a96f0-...`), motor control (`drive_direct`, `drive_stabilized`), RGB LED control (`set_led`), Infrared laser tag (`send_ir`), and live 6-axis IMU/Motor/IR/Battery sensor streaming (`monitor`).
* **[`kamigami_ui.py`](kamigami_ui.py)** — Local web control dashboard (`http://localhost:8765`) with a 2D virtual joystick, `WASD`/Arrow-key driving, throttle limiter, RGB LED color picker, IR trigger, Cockroach Mode with real-time Collision Stop Threshold slider, Inverted Orientation Safety Cutoff, and live 6-axis IMU + Motor telemetry readout.
* **[`cockroach_sim.py`](cockroach_sim.py)** — Autonomous cockroach behavior simulator: darts forward, uses 6-axis IMU shock sensing for collision detection, freezes for 2.0s upon hitting obstacles, reverses, turns randomly, and features automatic motor safety cutoff when picked up or turned upside down.

## Quick Start

### 1. Launch Interactive Web Control Deck (`http://localhost:8765`)
```bash
python3 kamigami_ui.py
```

### 2. CLI Commands (`kamigami_cli.py`)
The CLI automatically discovers any nearby awake Kamigami robot over BLE (or you can specify `--mac XX:XX:XX:XX:XX:XX` / `KAMIGAMI_MAC=XX:XX:XX:XX:XX:XX`):

```bash
# Stream live 6-axis IMU, Motor, IR, and Battery telemetry
python3 kamigami_cli.py monitor --duration 15

# Change RGB Eye LED color
python3 kamigami_cli.py led 0 255 255

# Drive Left and Right leg motors (-63 to +63)
python3 kamigami_cli.py drive --left 40 --right 40 --duration 1.0

# Fire Infrared battle tag packet
python3 kamigami_cli.py ir --id 1 --cmd 42
```

### 3. Cockroach Obstacle Avoidance & Inverted Safety Cutoff
```bash
# Run standalone cockroach behavior with custom bump sensitivity threshold
python3 cockroach_sim.py --speed 40 --threshold 0.45
```
* **Collision Avoidance**: Uses high-rate (10Hz) IMU dynamic acceleration and gyroscope shock tracking to detect impacts against walls or obstacles. Upon impact, the robot immediately stops, freezes for 2.0s (mimicking cautious insect behavior), backs up slightly, turns randomly left or right, and darts forward again.
* **Sensitivity Slider (UI)**: Adjust collision sensitivity live on the Web Deck from `0.20g` (gentle tap) to `0.90g` (hard impact).
* **Inverted Orientation Safety Cutoff**: If the robot is picked up and turned upside down (`az < -0.15g`), motor power is immediately halted, eye LEDs flash magenta/red alert, and manual/autonomous drive commands are disabled until the robot is safely placed right-side up.

---

## Disclaimer

This is an independent, unofficial open-source project created for educational and hardware interoperability purposes. It is not affiliated with, endorsed by, or sponsored by Dash Robotics, Inc. or Mattel, Inc. All product and company names are trademarks or registered trademarks of their respective holders.
