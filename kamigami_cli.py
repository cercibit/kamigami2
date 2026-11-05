#!/usr/bin/env python3
"""
Kamigami Robot (Firmware 2.0.2) Linux BlueZ BLE Controller & Telemetry SDK
"""
import argparse
import os
import struct
import sys
import time
import dbus
import dbus.mainloop.glib
from gi.repository import GLib

KAMIGAMI_SERVICE_UUID = "708a96f0-f200-4e2f-96f0-9bc43c3a31c8"
DASH_COMPANY_ID = 0x02C0
DEFAULT_MAC = os.environ.get("KAMIGAMI_MAC", "")


def discover_kamigami_mac(bus: dbus.SystemBus, timeout_sec: float = 6.0) -> str:
    """Auto-discover a Kamigami robot via BlueZ ObjectManager by Service UUID, Manufacturer ID (0x02C0), or Name (KRB*)."""
    om = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
    adapter = dbus.Interface(bus.get_object("org.bluez", "/org/bluez/hci0"), "org.bluez.Adapter1")

    def find_in_objects():
        objects = om.GetManagedObjects()
        for path, ifaces in objects.items():
            dev = ifaces.get("org.bluez.Device1")
            if not dev:
                continue
            addr = str(dev.get("Address", ""))
            name = str(dev.get("Name", dev.get("Alias", "")))
            uuids = [str(u).lower() for u in dev.get("UUIDs", [])]
            mfg = dev.get("ManufacturerData", {})
            if (
                KAMIGAMI_SERVICE_UUID in uuids
                or DASH_COMPANY_ID in mfg
                or name.upper().startswith("KRB")
            ):
                return addr
        return ""

    mac = find_in_objects()
    if mac:
        return mac

    try:
        adapter.StartDiscovery()
    except Exception:
        pass
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        mac = find_in_objects()
        if mac:
            break
        time.sleep(0.3)
    try:
        adapter.StopDiscovery()
    except Exception:
        pass
    return mac


class KamigamiRobot:
    def __init__(self, mac: str = DEFAULT_MAC):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.loop = GLib.MainLoop()

        if not mac:
            mac = discover_kamigami_mac(self.bus)
        self.mac = mac.upper()
        self.dev_path = ""
        self.rx_path = ""
        self.tx_path = ""
        self.batt_path = ""
        if self.mac:
            self._set_mac(self.mac)

        self.accel_scale = 4.0
        self.rot_scale = 2000.0
        self.last_telemetry = {
            "battery": None,
            "imu": None,
            "imu_feature": None,
            "motor": None,
            "ir": None,
            "imu_config": None,
        }

    def _set_mac(self, mac: str):
        self.mac = mac.upper()
        self.dev_path = f"/org/bluez/hci0/dev_{self.mac.replace(':', '_')}"
        self.rx_path = f"{self.dev_path}/service0023/char0024"
        self.tx_path = f"{self.dev_path}/service0023/char0027"
        self.batt_path = f"{self.dev_path}/service000c/char000d"

    @staticmethod
    def _scale(raw_short: int, factor: float) -> float:
        return (raw_short * factor) / 32767.0 if raw_short > 0 else (raw_short * factor) / 32768.0

    def connect(self, timeout_sec: float = 10.0) -> bool:
        if not self.mac:
            found = discover_kamigami_mac(self.bus, timeout_sec=timeout_sec)
            if not found:
                print("[!] Could not find any Kamigami robot via BLE. Wake the robot or pass --mac.", file=sys.stderr)
                return False
            self._set_mac(found)

        adapter = dbus.Interface(self.bus.get_object("org.bluez", "/org/bluez/hci0"), "org.bluez.Adapter1")
        try:
            dev_props = dbus.Interface(self.bus.get_object("org.bluez", self.dev_path), "org.freedesktop.DBus.Properties")
            connected = bool(dev_props.Get("org.bluez.Device1", "Connected"))
        except Exception:
            connected = False

        if not connected:
            print(f"[*] Scanning for Kamigami robot ({self.mac})...", flush=True)
            try:
                adapter.StartDiscovery()
            except Exception:
                pass
            t0 = time.time()
            while time.time() - t0 < timeout_sec:
                try:
                    dev_obj = self.bus.get_object("org.bluez", self.dev_path)
                    dev_props = dbus.Interface(dev_obj, "org.freedesktop.DBus.Properties")
                    try:
                        _ = dev_props.Get("org.bluez.Device1", "RSSI")
                        try:
                            adapter.StopDiscovery()
                        except Exception:
                            pass
                        dev = dbus.Interface(dev_obj, "org.bluez.Device1")
                        dev.Connect()
                        connected = True
                        break
                    except Exception:
                        pass
                except Exception:
                    pass
                time.sleep(0.3)

            if not connected:
                try:
                    dev = dbus.Interface(self.bus.get_object("org.bluez", self.dev_path), "org.bluez.Device1")
                    dev.Connect()
                    connected = True
                except Exception as e:
                    print(f"[!] Could not connect to {self.mac}: {e}", file=sys.stderr)
                    return False

        dev_props = dbus.Interface(self.bus.get_object("org.bluez", self.dev_path), "org.freedesktop.DBus.Properties")
        for _ in range(30):
            if bool(dev_props.Get("org.bluez.Device1", "ServicesResolved")):
                break
            time.sleep(0.1)

        self.rx_char = dbus.Interface(self.bus.get_object("org.bluez", self.rx_path), "org.bluez.GattCharacteristic1")
        self.tx_char = dbus.Interface(self.bus.get_object("org.bluez", self.tx_path), "org.bluez.GattCharacteristic1")
        self.batt_char = dbus.Interface(self.bus.get_object("org.bluez", self.batt_path), "org.bluez.GattCharacteristic1")
        print(f"[+] Connected to {self.mac}", flush=True)
        return True

    def disconnect(self):
        try:
            dev = dbus.Interface(self.bus.get_object("org.bluez", self.dev_path), "org.bluez.Device1")
            dev.Disconnect()
        except Exception:
            pass

    def write_cmd(self, payload: list, write_type: str = "request"):
        arr = [dbus.Byte(b & 0xFF) for b in payload]
        self.tx_char.WriteValue(arr, {"type": dbus.String(write_type)})

    def read_battery(self) -> int:
        val = bytes(self.batt_char.ReadValue({}))
        b = val[0] if val else 0
        self.last_telemetry["battery"] = b
        return b

    def power_down(self):
        """Opcode 0x00: PowerDown [0x00] (1 byte) - Puts robot into deep sleep"""
        self.write_cmd([0x00])

    def set_led(self, r: int, g: int, b: int):
        """Opcode 0x01: EyeColor [0x01, 0x00, R, G, B, 0x00, 0x00] (7 bytes in Firmware 2.0.2)"""
        self.write_cmd([0x01, 0x00, r & 0xFF, g & 0xFF, b & 0xFF, 0x00, 0x00])

    def drive_direct(self, left: int, right: int):
        """Opcode 0x02: MotorDirect [0x02, 0x00, left(-63..63), right(-63..63), 0x00, 0x00] (6 bytes in Firmware 2.0.2)"""
        l_val = max(-63, min(63, int(left)))
        r_val = max(-63, min(63, int(right)))
        self.write_cmd([0x02, 0x00, l_val & 0xFF, r_val & 0xFF, 0x00, 0x00])

    def drive_stabilized(self, left: int, right: int, ref_yaw: int = 0):
        """Opcode 0x02: MotorDirect stabilized [0x02, 0x01, left(-63..63), right(-63..63), yaw_lo, yaw_hi] (6 bytes)"""
        l_val = max(-63, min(63, int(left)))
        r_val = max(-63, min(63, int(right)))
        self.write_cmd([0x02, 0x01, l_val & 0xFF, r_val & 0xFF, ref_yaw & 0xFF, (ref_yaw >> 8) & 0xFF])

    def stop_motors(self):
        """Opcode 0x02: Stop driving [0x02, 0, 0, 0, 0, 0]"""
        self.write_cmd([0x02, 0x00, 0x00, 0x00, 0x00, 0x00])

    def send_ir(self, player_id: int, command: int):
        """Opcode 0x03: IR [0x03, id, cmd] (3 bytes in Firmware 2.0.2)"""
        self.write_cmd([0x03, player_id & 0xFF, command & 0xFF])

    def request_read_response(self, target_code: int):
        """Opcode 0x20 (32): ReadResponse [0x20, target_code] (2 bytes in Firmware 2.0.2)"""
        self.write_cmd([0x20, target_code & 0xFF])

    def set_update_frequencies(self, imu_hz: int = 10, motor_hz: int = 4, **_kwargs):
        """Opcode 0x21 (33): ConfigUpdates [0x21, imu_hz, motor_hz] (3 bytes in Firmware 2.0.2)"""
        self.write_cmd([0x21, imu_hz & 0xFF, motor_hz & 0xFF])

    def configure_imu(self, accel_scale_code: int = 5, rot_scale_code: int = 0, filtered: bool = True):
        """Opcode 0x40 (64): ConfigIMU [0x40, accelScale(3=2g,5=4g,8=8g,12=16g), rotScale(0=2000dps), isFiltered]"""
        self.write_cmd([0x40, accel_scale_code & 0xFF, rot_scale_code & 0xFF, 1 if filtered else 0])
        self.request_read_response(0x40)

    def decode_packet(self, val: bytes, quiet: bool = False):
        if not val:
            return
        msg_type = val[0]
        payload = val[1:]
        if msg_type == 5 and len(payload) >= 12:
            ax, ay, az, gx, gy, gz = struct.unpack("<6h", payload[:12])
            ax_g = round(self._scale(ax, self.accel_scale), 3)
            ay_g = round(self._scale(ay, self.accel_scale), 3)
            az_g = round(self._scale(az, self.accel_scale), 3)
            gx_dps = round(self._scale(gx, self.rot_scale), 2)
            gy_dps = round(self._scale(gy, self.rot_scale), 2)
            gz_dps = round(self._scale(gz, self.rot_scale), 2)
            self.last_telemetry["imu"] = {
                "ax_g": ax_g,
                "ay_g": ay_g,
                "az_g": az_g,
                "gx_dps": gx_dps,
                "gy_dps": gy_dps,
                "gz_dps": gz_dps,
                "ts": time.time(),
            }
            if not quiet:
                print(
                    f"[IMU     ] Accel(g): X={ax_g:+6.3f} Y={ay_g:+6.3f} Z={az_g:+6.3f} | "
                    f"Gyro(dps): X={gx_dps:+7.2f} Y={gy_dps:+7.2f} Z={gz_dps:+7.2f}",
                    flush=True,
                )
        elif msg_type == 6 and len(payload) >= 1:
            feat_names = {
                0: "AnyMotion",
                1: "SignificantMotion",
                2: "SingleTap",
                3: "DoubleTap",
                4: "Orientation",
                5: "Flat",
                6: "LowG",
                7: "HighG",
                8: "SlowMotion",
                9: "NoMotion",
            }
            feat_str = feat_names.get(payload[0], f"Unknown({payload[0]})")
            self.last_telemetry["imu_feature"] = {"type": feat_str, "raw": payload.hex(" "), "ts": time.time()}
            if not quiet:
                print(f"[IMU_FEAT] Event={feat_str} raw={payload.hex(' ')}", flush=True)
        elif msg_type == 2 and len(payload) >= 9:
            mode = "DIRECT" if (payload[0] & 1) == 0 else "STABILIZED"
            l_pwr = struct.unpack("<b", bytes([payload[1]]))[0]
            r_pwr = struct.unpack("<b", bytes([payload[2]]))[0]
            l_pwm = struct.unpack("<b", bytes([(payload[5] - payload[6]) & 0xFF]))[0]
            r_pwm = struct.unpack("<b", bytes([(payload[7] - payload[8]) & 0xFF]))[0]
            self.last_telemetry["motor"] = {
                "mode": mode,
                "left_power": l_pwr,
                "right_power": r_pwr,
                "left_pwm": l_pwm,
                "right_pwm": r_pwm,
                "ts": time.time(),
            }
            if not quiet:
                print(
                    f"[MOTOR   ] Mode={mode} LeftPwr={l_pwr} RightPwr={r_pwr} LeftPWM={l_pwm} RightPWM={r_pwm}",
                    flush=True,
                )
        elif msg_type == 3 and len(payload) >= 3:
            dirs = {1: "FRONT", 2: "BACK"}
            d_str = dirs.get(payload[0], f"NONE({payload[0]})")
            self.last_telemetry["ir"] = {"dir": d_str, "id": payload[1], "cmd": payload[2], "ts": time.time()}
            if not quiet:
                print(f"[INFRARED] Dir={d_str} ID={payload[1]} Cmd={payload[2]}", flush=True)
        elif msg_type == 64 and len(payload) >= 3:
            acc_map = {3: 2, 5: 4, 8: 8, 12: 16}
            rot_map = {0: 2000, 1: 1000, 2: 500, 3: 250, 4: 125}
            self.accel_scale = float(acc_map.get(payload[0], 4))
            self.rot_scale = float(rot_map.get(payload[1], 2000))
            filt = bool(payload[2])
            self.last_telemetry["imu_config"] = {
                "accel_scale_g": int(self.accel_scale),
                "gyro_scale_dps": int(self.rot_scale),
                "filtered": filt,
            }
            if not quiet:
                print(
                    f"[IMU_CFG ] AccelScale=±{int(self.accel_scale)}g, "
                    f"GyroScale=±{int(self.rot_scale)}dps, Filtered={filt}",
                    flush=True,
                )
        elif msg_type == 65:
            if not quiet:
                print(f"[IMU2_CFG] raw={payload.hex(' ')}", flush=True)
        else:
            if not quiet:
                print(f"[TYPE {msg_type:2d} ] raw={val.hex(' ')}", flush=True)

    def monitor(self, duration: float = 15.0):
        def on_prop(iface, changed, inv, path):
            if "Value" in changed:
                b = bytes(changed["Value"])
                if path.endswith("char0024"):
                    self.decode_packet(b)
                elif path.endswith("char000d") and b:
                    self.last_telemetry["battery"] = b[0]
                    print(f"[BATTERY ] {b[0]}%", flush=True)

        self.bus.add_signal_receiver(
            on_prop,
            dbus_interface="org.freedesktop.DBus.Properties",
            signal_name="PropertiesChanged",
            path_keyword="path",
        )
        print(f"[+] Battery Level: {self.read_battery()}%", flush=True)
        try:
            self.rx_char.StartNotify()
        except Exception:
            pass
        try:
            self.batt_char.StartNotify()
        except Exception:
            pass

        self.configure_imu(accel_scale_code=5, rot_scale_code=0, filtered=True)
        self.set_update_frequencies(imu_hz=10, motor_hz=4)
        print(f"[*] Streaming live sensors for {duration}s...", flush=True)

        def on_done():
            try:
                self.set_update_frequencies(0, 0)
            except Exception:
                pass
            self.loop.quit()
            return False

        GLib.timeout_add(int(duration * 1000), on_done)
        self.loop.run()


def main():
    parser = argparse.ArgumentParser(description="Kamigami Robot BLE CLI (Firmware 2.0.2)")
    parser.add_argument("--mac", default=DEFAULT_MAC, help="BLE MAC address of the Kamigami robot (auto-discovered if omitted)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mon = sub.add_parser("monitor", help="Stream live IMU, Motor, IR, and Battery telemetry")
    p_mon.add_argument("--duration", type=float, default=15.0, help="Duration in seconds")

    p_led = sub.add_parser("led", help="Set RGB eye LED color")
    p_led.add_argument("r", type=int, help="Red (0-255)")
    p_led.add_argument("g", type=int, help="Green (0-255)")
    p_led.add_argument("b", type=int, help="Blue (0-255)")

    p_drv = sub.add_parser("drive", help="Drive left and right leg motors (-63 to +63)")
    p_drv.add_argument("--left", type=int, default=30, help="Left motor power (-63 to 63)")
    p_drv.add_argument("--right", type=int, default=30, help="Right motor power (-63 to 63)")
    p_drv.add_argument("--duration", type=float, default=1.0, help="Drive duration in seconds")

    p_ir = sub.add_parser("ir", help="Transmit an Infrared battle/tag packet")
    p_ir.add_argument("--id", type=int, default=1, help="Player ID (0-255)")
    p_ir.add_argument("--cmd", type=int, default=1, help="IR command byte (0-255)")

    args = parser.parse_args()
    bot = KamigamiRobot(args.mac)
    if not bot.connect():
        sys.exit(1)

    if args.cmd == "monitor":
        bot.monitor(args.duration)
    elif args.cmd == "led":
        bot.set_led(args.r, args.g, args.b)
        print(f"[+] Set LED to RGB({args.r}, {args.g}, {args.b})")
    elif args.cmd == "drive":
        print(f"[*] Driving Left={args.left}, Right={args.right} for {args.duration}s...")
        bot.drive_direct(args.left, args.right)
        time.sleep(args.duration)
        bot.stop_motors()
        print("[+] Stopped motors.")
    elif args.cmd == "ir":
        bot.send_ir(args.id, args.cmd)
        print(f"[+] Sent IR packet (ID={args.id}, Cmd={args.cmd})")


if __name__ == "__main__":
    main()
