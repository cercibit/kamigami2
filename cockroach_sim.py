#!/usr/bin/env python3
"""
Kamigami Robot Cockroach Simulator
Mimics cockroach obstacle avoidance behavior:
- Runs forward at brisk speed
- Uses high-rate IMU monitoring to detect collisions (sudden deceleration or impact shock)
- When obstacle/hit detected:
  1. Stops immediately
  2. Freezes / stays still for 2.0 seconds (mimicking cautious insect pause)
  3. Reverses backward slightly
  4. Randomly turns sharply Left or Right (simulating erratic cockroach darting)
  5. Continues running forward
"""

import argparse
import math
import random
import signal
import sys
import time

from kamigami_cli import DEFAULT_MAC, KamigamiRobot


class CockroachBot:
    def __init__(self, mac: str = DEFAULT_MAC, speed: int = 42, threshold: float = 0.45):
        self.bot = KamigamiRobot(mac)
        self.running = True
        self.speed = speed
        self.threshold = threshold
        self.last_hit_time = 0

    def connect(self) -> bool:
        if not self.bot.connect(timeout_sec=8.0):
            return False

        try:
            self.bot.rx_char.StartNotify()
        except Exception:
            pass

        # Configure IMU: 4g range, 2000 dps, filtered
        self.bot.configure_imu(accel_scale_code=5, rot_scale_code=0, filtered=True)
        # 10Hz IMU stream, 4Hz motor status stream
        self.bot.set_update_frequencies(imu_hz=10, motor_hz=4)
        return True

    def process_events(self):
        ctx = self.bot.loop.get_context()
        while ctx.pending():
            ctx.iteration(False)

    def run(self):
        print("🪳 Cockroach behavior mode activated!")
        print("   - Moving forward...")
        print("   - Watching for collisions/impacts via 6-axis IMU...")
        print("   - Press Ctrl+C to stop.")

        # Set eyes to insect amber / green
        self.bot.set_led(255, 120, 0)

        # Baseline acceleration filter
        baseline_ax = 0.0
        baseline_ay = 0.0
        baseline_az = 1.0

        state = "FORWARD"
        state_timer = time.time()
        turn_dir = 1
        turn_duration = 0.4

        while self.running:
            self.process_events()
            now = time.time()
            imu = self.bot.last_telemetry.get("imu")
            feature = self.bot.last_telemetry.get("imu_feature")

            hit_detected = False

            if imu:
                ax = imu["ax_g"]
                ay = imu["ay_g"]
                az = imu["az_g"]
                gx = imu["gx_dps"]
                gy = imu["gy_dps"]
                gz = imu["gz_dps"]

                # Safety Cutoff: Inverted orientation (held upside down)
                if az < -0.15:
                    if state != "UPSIDE_DOWN":
                        state = "UPSIDE_DOWN"
                        print("\n⚠️ [UPSIDE DOWN DETECTED!] Inverted orientation (az < 0). Cutting motors immediately for safety.")
                        self.bot.stop_motors()
                        self.bot.set_led(255, 0, 128)
                    time.sleep(0.08)
                    continue

                if state == "UPSIDE_DOWN":
                    if az > 0.35:
                        print("✅ Robot upright again! Resuming in 1.0s...")
                        self.bot.stop_motors()
                        self.bot.set_led(255, 200, 0)
                        time.sleep(1.0)
                        state = "FORWARD"
                        state_timer = time.time()
                        self.bot.set_led(0, 255, 80)
                    else:
                        time.sleep(0.08)
                        continue

                # Track rolling baseline
                baseline_ax = 0.9 * baseline_ax + 0.1 * ax
                baseline_ay = 0.9 * baseline_ay + 0.1 * ay
                baseline_az = 0.9 * baseline_az + 0.1 * az

                # Delta from expected running baseline
                d_ax = ax - baseline_ax
                d_ay = ay - baseline_ay
                d_az = az - baseline_az

                accel_shock = math.hypot(d_ax, d_ay, d_az)
                gyro_shock = math.hypot(gx, gy, gz)

                # Collision spike detection dynamically scaled by self.threshold
                if state == "FORWARD" and (now - state_timer > 0.35):
                    if accel_shock > self.threshold or abs(d_ax) > (self.threshold * 0.85) or gyro_shock > (self.threshold * 400.0):
                        hit_detected = True
                        print(f"\n💥 [BUMP DETECTED!] Shock={accel_shock:.2f}g (threshold {self.threshold:.2f}g), Gyro={gyro_shock:.1f}°/s")

            # Check BMI160 hardware interrupt feature as well
            if feature and state == "FORWARD" and (now - state_timer > 0.35):
                f_type = feature.get("type", "")
                if f_type in ["SingleTap", "DoubleTap", "HighG", "SignificantMotion"]:
                    if now - self.last_hit_time > 1.0:
                        hit_detected = True
                        print(f"\n💥 [HARDWARE IMU INTERRUPT: {f_type}]")

            # State Machine Transitions
            if hit_detected and state == "FORWARD":
                self.last_hit_time = now
                state = "STOP_WAIT"
                state_timer = now
                self.bot.stop_motors()
                # Flash red eyes on impact
                self.bot.set_led(255, 0, 0)
                print("🛑 Hit obstacle! Stopping & waiting 2.0s...")

            if state == "STOP_WAIT":
                self.bot.stop_motors()
                if now - state_timer >= 2.0:
                    state = "BACKWARD"
                    state_timer = now
                    # Reverse slightly
                    print("⬅️ Backing up slightly...")
                    self.bot.set_led(255, 120, 0)

            elif state == "BACKWARD":
                # Back up for ~0.45 seconds
                self.bot.drive_direct(-self.speed, -self.speed)
                if now - state_timer >= 0.45:
                    self.bot.stop_motors()
                    state = "TURN"
                    state_timer = now
                    # Pick left (-1) or right (+1) randomly with variable duration (cockroach erratic angle)
                    turn_dir = random.choice([-1, 1])
                    turn_duration = random.uniform(0.35, 0.65)
                    dir_name = "LEFT" if turn_dir < 0 else "RIGHT"
                    print(f"🔄 Darting {dir_name} ({turn_duration:.2f}s)...")

            elif state == "TURN":
                # Spin in place
                left_pwr = -int(self.speed * turn_dir)
                right_pwr = int(self.speed * turn_dir)
                self.bot.drive_direct(left_pwr, right_pwr)
                if now - state_timer >= turn_duration:
                    self.bot.stop_motors()
                    state = "FORWARD"
                    state_timer = now
                    # Cockroach green/amber eyes
                    self.bot.set_led(0, 255, 80)
                    print("🏃 Moving forward again...")

            elif state == "FORWARD":
                # Drive forward
                self.bot.drive_direct(self.speed, self.speed)
                # Random occasional pause or straight run; keep moving forward
                time.sleep(0.05)

            time.sleep(0.04)

        self.bot.stop_motors()
        self.bot.set_update_frequencies(0, 0)
        self.bot.set_led(0, 0, 0)
        print("\n[+] Stopped cockroach simulation.")


def main():
    parser = argparse.ArgumentParser(description="Kamigami Cockroach Simulator")
    parser.add_argument("--mac", default=DEFAULT_MAC, help="Robot MAC address (optional)")
    parser.add_argument("--speed", type=int, default=40, help="Forward motor power (15-63, default 40)")
    parser.add_argument("--threshold", type=float, default=0.45, help="Collision bump shock threshold in g (default 0.45)")
    args = parser.parse_args()

    bot = CockroachBot(mac=args.mac, speed=args.speed, threshold=args.threshold)

    def signal_handler(sig, frame):
        bot.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if not bot.connect():
        sys.exit(1)

    try:
        bot.run()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        bot.bot.stop_motors()
        bot.bot.set_update_frequencies(0, 0)


if __name__ == "__main__":
    main()
