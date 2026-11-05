#!/usr/bin/env python3
"""
Kamigami Robot (Firmware 2.0.2) Interactive Web Dashboard & Controller UI
Features:
- Virtual 2D Joystick & WASD / Arrow-Key manual driving
- Throttle slider (15 - 63)
- RGB Eye LED color picker & quick presets
- Infrared (IR) battle laser trigger
- One-click Choreographed Test Run ("Dance / Patrol")
- Real-time Cockroach Autonomous Mode (bump detection -> stop 2s -> reverse -> turn -> forward)
- Live BLE connection status, battery monitor, and 6-axis IMU sensor readout
"""
import json
import math
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from kamigami_cli import DEFAULT_MAC, KamigamiRobot

PORT = 8765
bot_lock = threading.Lock()
bot = KamigamiRobot(DEFAULT_MAC)
notify_initialized = False

# Cockroach autonomous mode state & safety controls
cockroach_running = False
cockroach_thread = None
cockroach_state = "IDLE"
bump_threshold = 0.45


def check_is_upside_down() -> bool:
    imu = bot.last_telemetry.get("imu")
    if imu and "az_g" in imu:
        return imu["az_g"] < -0.15
    return False


def ensure_telemetry_stream():
    global notify_initialized
    if not notify_initialized:
        def on_prop(iface, changed, inv, path):
            if "Value" in changed:
                b = bytes(changed["Value"])
                if path.endswith("char0024"):
                    bot.decode_packet(b, quiet=True)
                elif path.endswith("char000d") and b:
                    bot.last_telemetry["battery"] = b[0]

        bot.bus.add_signal_receiver(
            on_prop,
            dbus_interface="org.freedesktop.DBus.Properties",
            signal_name="PropertiesChanged",
            path_keyword="path",
        )
        t = threading.Thread(target=bot.loop.run, daemon=True)
        t.start()
        notify_initialized = True

    try:
        bot.rx_char.StartNotify()
    except Exception:
        pass
    try:
        bot.batt_char.StartNotify()
    except Exception:
        pass
    try:
        bot.configure_imu(accel_scale_code=5, rot_scale_code=0, filtered=True)
        bot.set_update_frequencies(imu_hz=10, motor_hz=4)
    except Exception:
        pass


def cockroach_loop():
    global cockroach_running, cockroach_state, bump_threshold
    speed = 40
    baseline_ax = 0.0
    baseline_ay = 0.0
    baseline_az = 1.0

    state = "FORWARD"
    state_timer = time.time()
    turn_dir = 1
    turn_duration = 0.45
    last_hit_time = 0

    with bot_lock:
        try:
            bot.set_led(0, 255, 80)
        except Exception:
            pass

    while cockroach_running:
        now = time.time()
        imu = bot.last_telemetry.get("imu")
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
                    cockroach_state = "UPSIDE DOWN (SAFETY HALT)"
                    with bot_lock:
                        try:
                            bot.stop_motors()
                            bot.set_led(255, 0, 128)
                        except Exception:
                            pass
                time.sleep(0.08)
                continue

            if state == "UPSIDE_DOWN":
                if az > 0.35:
                    cockroach_state = "RIGHTED (RECOVERING...)"
                    with bot_lock:
                        try:
                            bot.stop_motors()
                            bot.set_led(255, 200, 0)
                        except Exception:
                            pass
                    time.sleep(1.0)
                    state = "FORWARD"
                    state_timer = time.time()
                    with bot_lock:
                        try:
                            bot.set_led(0, 255, 80)
                        except Exception:
                            pass
                else:
                    time.sleep(0.08)
                    continue

            baseline_ax = 0.9 * baseline_ax + 0.1 * ax
            baseline_ay = 0.9 * baseline_ay + 0.1 * ay
            baseline_az = 0.9 * baseline_az + 0.1 * az

            d_ax = ax - baseline_ax
            d_ay = ay - baseline_ay
            d_az = az - baseline_az

            accel_shock = math.hypot(d_ax, d_ay, d_az)
            gyro_shock = math.hypot(gx, gy, gz)

            if state == "FORWARD" and (now - state_timer > 0.35):
                # Dynamically scaled bump threshold configured via UI slider
                if accel_shock > bump_threshold or abs(d_ax) > (bump_threshold * 0.85) or gyro_shock > (bump_threshold * 400.0):
                    hit_detected = True

        feature = bot.last_telemetry.get("imu_feature")
        if feature and state == "FORWARD" and (now - state_timer > 0.35):
            f_type = feature.get("type", "")
            if f_type in ["SingleTap", "DoubleTap", "HighG", "SignificantMotion"]:
                if now - last_hit_time > 1.0:
                    hit_detected = True

        with bot_lock:
            if hit_detected and state == "FORWARD":
                last_hit_time = now
                state = "STOP_WAIT"
                state_timer = now
                cockroach_state = "PAUSED (WAITING 2S)"
                try:
                    bot.stop_motors()
                    bot.set_led(255, 0, 0)
                except Exception:
                    pass

            if state == "STOP_WAIT":
                try:
                    bot.stop_motors()
                except Exception:
                    pass
                if now - state_timer >= 2.0:
                    state = "BACKWARD"
                    state_timer = now
                    cockroach_state = "BACKING UP"
                    try:
                        bot.set_led(255, 120, 0)
                    except Exception:
                        pass

            elif state == "BACKWARD":
                try:
                    bot.drive_direct(-speed, -speed)
                except Exception:
                    pass
                if now - state_timer >= 0.45:
                    try:
                        bot.stop_motors()
                    except Exception:
                        pass
                    state = "TURN"
                    state_timer = now
                    turn_dir = random.choice([-1, 1])
                    turn_duration = random.uniform(0.35, 0.60)
                    cockroach_state = f"TURNING {'LEFT' if turn_dir < 0 else 'RIGHT'}"

            elif state == "TURN":
                left_pwr = -int(speed * turn_dir)
                right_pwr = int(speed * turn_dir)
                try:
                    bot.drive_direct(left_pwr, right_pwr)
                except Exception:
                    pass
                if now - state_timer >= turn_duration:
                    try:
                        bot.stop_motors()
                    except Exception:
                        pass
                    state = "FORWARD"
                    state_timer = now
                    cockroach_state = "MOVING FORWARD"
                    try:
                        bot.set_led(0, 255, 80)
                    except Exception:
                        pass

            elif state == "FORWARD":
                cockroach_state = "MOVING FORWARD"
                try:
                    bot.drive_direct(speed, speed)
                except Exception:
                    pass

        time.sleep(0.04)

    with bot_lock:
        cockroach_state = "STOPPED"
        try:
            bot.stop_motors()
            bot.set_led(0, 229, 255)
        except Exception:
            pass


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kamigami Robot Control Deck</title>
<style>
  :root {
    --bg: #0d1117;
    --panel: #161b22;
    --border: #30363d;
    --accent: #00e5ff;
    --accent2: #7c4dff;
    --text: #e6edf3;
    --muted: #8b949e;
    --success: #2ea043;
    --danger: #f85149;
    --warn: #d29922;
  }
  * { box-sizing: border-box; user-select: none; }
  body {
    margin: 0; padding: 24px;
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex; flex-direction: column; align-items: center;
  }
  header {
    width: 100%; max-width: 960px;
    display: flex; justify-content: space-between; align-items: center;
    padding: 16px 24px; background: var(--panel);
    border: 1px solid var(--border); border-radius: 12px;
    margin-bottom: 20px;
  }
  .title-block h1 { margin: 0; font-size: 20px; display: flex; align-items: center; gap: 10px; }
  .title-block p { margin: 4px 0 0; font-size: 13px; color: var(--muted); font-family: monospace; }
  .status-bar { display: flex; align-items: center; gap: 16px; }
  .badge {
    padding: 6px 12px; border-radius: 999px; font-size: 13px; font-weight: 600;
    background: #21262d; border: 1px solid var(--border);
    display: flex; align-items: center; gap: 8px;
  }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--danger); }
  .dot.online { background: var(--success); box-shadow: 0 0 8px var(--success); }
  .grid {
    width: 100%; max-width: 960px;
    display: grid; grid-template-columns: 1.1fr 0.9fr; gap: 20px;
  }
  @media (max-width: 760px) { .grid { grid-template-columns: 1fr; } }
  .card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 20px;
    display: flex; flex-direction: column; gap: 16px;
  }
  .card h2 { margin: 0; font-size: 16px; color: var(--accent); text-transform: uppercase; letter-spacing: 0.5px; }
  .joystick-wrap {
    display: flex; flex-direction: column; align-items: center; gap: 14px;
  }
  #joyCanvas {
    background: radial-gradient(circle, #1f2937 0%, #0f172a 100%);
    border: 2px solid var(--border); border-radius: 50%;
    cursor: grab; touch-action: none;
  }
  #joyCanvas:active { cursor: grabbing; border-color: var(--accent); }
  .dpad {
    display: grid; grid-template-columns: repeat(3, 64px); grid-template-rows: repeat(2, 52px);
    gap: 8px; justify-content: center;
  }
  button {
    background: #21262d; color: var(--text);
    border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; font-size: 14px; font-weight: 600;
    cursor: pointer; transition: all 0.12s ease;
  }
  button:hover { border-color: var(--accent); background: #292e36; }
  button:active, button.active { background: var(--accent); color: #000; border-color: var(--accent); }
  .btn-primary { background: var(--accent2); border-color: var(--accent2); color: #fff; }
  .btn-primary:hover { background: #651fff; }
  .btn-danger { background: #da3633; border-color: #f85149; color: #fff; }
  .btn-roach { background: #795548; border-color: #8d6e63; color: #fff; }
  .btn-roach:hover { background: #8d6e63; }
  .btn-roach.active { background: #4e342e; border-color: var(--accent); box-shadow: 0 0 10px rgba(0, 229, 255, 0.5); }
  .row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .color-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
  .swatch { height: 38px; border-radius: 8px; border: 2px solid rgba(255,255,255,0.15); }
  input[type="range"] { width: 100%; accent-color: var(--accent); }
  .telemetry-readout {
    font-family: monospace; font-size: 13px; background: #090d11;
    padding: 12px; border-radius: 8px; border: 1px solid var(--border);
    color: #7ee787; min-height: 76px; white-space: pre-wrap;
  }
  .imu-box {
    font-family: monospace; font-size: 12.5px; background: #090d11;
    padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border);
    color: #58a6ff; line-height: 1.5;
  }
  .roach-box {
    font-family: monospace; font-size: 13px; background: #1a1512;
    padding: 10px 14px; border-radius: 8px; border: 1px solid #5d4037;
    color: #ffcc80; display: flex; align-items: center; justify-content: space-between;
  }
  .kbd {
    background: #0d1117; border: 1px solid var(--border); border-radius: 4px;
    padding: 2px 6px; font-family: monospace; font-size: 12px; color: var(--muted);
  }
</style>
</head>
<body>

<header>
  <div class="title-block">
    <h1>🤖 Kamigami Robot Control Deck</h1>
    <p>Device: KRB0002 (BLE Auto-Discovery) • FW: 2.0.2 (v2 Protocol)</p>
  </div>
  <div class="status-bar">
    <div id="safetyBadge" class="badge" style="display:none;background:#7f1d1d;border-color:#f85149;color:#ffcdd2;font-weight:700">⚠️ UPSIDE DOWN: MOTORS HALTED</div>
    <div class="badge"><span id="connDot" class="dot"></span><span id="connText">Connecting...</span></div>
    <div class="badge">🔋 <span id="battText">--%</span></div>
    <button onclick="reconnectRobot()">Reconnect</button>
  </div>
</header>

<div class="grid">
  <!-- Left Column: Drive & Joystick -->
  <div class="card">
    <div class="row">
      <h2>🕹️ Manual Drive Control</h2>
      <span style="font-size:12px;color:var(--muted)">Keys: <span class="kbd">W</span> <span class="kbd">A</span> <span class="kbd">S</span> <span class="kbd">D</span> or Arrows, <span class="kbd">Space</span> Stop</span>
    </div>

    <div class="joystick-wrap">
      <canvas id="joyCanvas" width="220" height="220"></canvas>

      <div class="dpad">
        <div></div>
        <button id="btnW" onmousedown="startHold(1, 1)" onmouseup="stopHold()" onmouseleave="stopHold()" ontouchstart="startHold(1,1);event.preventDefault()" ontouchend="stopHold()">▲ Fwd</button>
        <div></div>
        <button id="btnA" onmousedown="startHold(-1, 1)" onmouseup="stopHold()" onmouseleave="stopHold()" ontouchstart="startHold(-1,1);event.preventDefault()" ontouchend="stopHold()">⟲ Left</button>
        <button id="btnS" onmousedown="startHold(-1, -1)" onmouseup="stopHold()" onmouseleave="stopHold()" ontouchstart="startHold(-1,-1);event.preventDefault()" ontouchend="stopHold()">▼ Back</button>
        <button id="btnD" onmousedown="startHold(1, -1)" onmouseup="stopHold()" onmouseleave="stopHold()" ontouchstart="startHold(1,-1);event.preventDefault()" ontouchend="stopHold()">⟳ Right</button>
      </div>
    </div>

    <div>
      <div class="row" style="margin-bottom:6px">
        <label for="throttle">Max Motor Power Limit</label>
        <span id="throttleVal" style="font-family:monospace;color:var(--accent)">48 / 63 (76%)</span>
      </div>
      <input type="range" id="throttle" min="15" max="63" value="48" oninput="updateThrottleLabel()">
    </div>

    <button class="btn-danger" onclick="emergencyStop()">⏹ ALL STOP (SPACE)</button>
  </div>

  <!-- Right Column: Cockroach Mode, LED, IR, & Routines -->
  <div class="card">
    <h2>🪳 Cockroach Autonomous Mode</h2>
    <div class="roach-box">
      <span>Status: <strong id="roachStatus">OFF</strong></span>
      <button id="btnRoach" class="btn-roach" onclick="toggleCockroach()">▶ Start Cockroach Mode</button>
    </div>
    <span style="font-size:12px;color:var(--muted)">
      Runs forward → On bump/impact: stops 2s → reverses a bit → turns L/R randomly → resumes forward.
    </span>

    <div style="background:#131a22;padding:12px;border:1px solid var(--border);border-radius:8px;display:flex;flex-direction:column;gap:8px">
      <div class="row">
        <label for="bumpThreshold" style="font-size:13px;font-weight:600">🛑 Collision Stop Threshold</label>
        <span id="bumpVal" style="font-family:monospace;color:var(--accent);font-size:13px;font-weight:bold">0.45 g</span>
      </div>
      <input type="range" id="bumpThreshold" min="0.20" max="0.90" step="0.05" value="0.45" oninput="onBumpSliderChange(this.value)">
      <div class="row" style="font-size:11px;color:var(--muted);margin-top:-2px">
        <span>0.20g (Light Tap)</span>
        <span>0.45g (Standard)</span>
        <span>0.90g (Hard Bump)</span>
      </div>
    </div>

    <div id="upsideDownWarning" style="display:none;padding:10px 14px;background:#450a0a;border:1px solid #dc2626;border-radius:8px;font-size:12.5px;color:#fca5a5;line-height:1.4">
      ⚠️ <strong>Safety Cutoff Triggered:</strong> Robot is turned upside down (<span style="font-family:monospace">az &lt; 0</span>). Motors are fully disabled until robot is set right-side up.
    </div>

    <hr style="border:0;border-top:1px solid var(--border);width:100%">

    <h2>💡 RGB Eye LED & Actions</h2>
    <div class="color-grid">
      <button class="swatch" style="background:#ff1744" onclick="setLed(255,0,0)" title="Red"></button>
      <button class="swatch" style="background:#ff9100" onclick="setLed(255,120,0)" title="Orange"></button>
      <button class="swatch" style="background:#ffea00" onclick="setLed(255,230,0)" title="Yellow"></button>
      <button class="swatch" style="background:#00e676" onclick="setLed(0,255,0)" title="Green"></button>
      <button class="swatch" style="background:#00e5ff" onclick="setLed(0,255,255)" title="Cyan"></button>
      <button class="swatch" style="background:#2979ff" onclick="setLed(0,80,255)" title="Blue"></button>
      <button class="swatch" style="background:#d500f9" onclick="setLed(255,0,255)" title="Magenta"></button>
      <button class="swatch" style="background:#ffffff" onclick="setLed(255,255,255)" title="White"></button>
    </div>

    <div class="row">
      <label for="colorPicker">Custom Color:</label>
      <input type="color" id="colorPicker" value="#00e5ff" onchange="pickCustomColor(this.value)" style="width:80px;height:34px;border:none;background:none;cursor:pointer">
      <button onclick="setLed(0,0,0)">LED Off</button>
    </div>

    <div class="row">
      <button class="btn-primary" style="flex:1" onclick="fireIR()">⚡ Fire IR Tag</button>
      <button class="btn-primary" style="flex:1;background:#00897b;border-color:#00897b" onclick="runDemo()">🎬 Run Choreographed Demo</button>
    </div>

    <h2>🧭 Live 6-Axis IMU & Motor Telemetry</h2>
    <div id="imuBox" class="imu-box">Waiting for live sensor telemetry...</div>

    <h2>📡 Command Log</h2>
    <div id="logBox" class="telemetry-readout">Ready. Use Joystick, WASD, or buttons to control KRB0002.</div>
  </div>
</div>

<script>
const logBox = document.getElementById('logBox');
const imuBox = document.getElementById('imuBox');
const roachStatus = document.getElementById('roachStatus');
const btnRoach = document.getElementById('btnRoach');

function log(msg) {
  const ts = new Date().toLocaleTimeString();
  logBox.textContent = `[${ts}] ${msg}\\n` + logBox.textContent.split('\\n').slice(0, 3).join('\\n');
}

function getMaxPower() {
  return parseInt(document.getElementById('throttle').value, 10);
}
function updateThrottleLabel() {
  const v = getMaxPower();
  const pct = Math.round((v / 63) * 100);
  document.getElementById('throttleVal').textContent = `${v} / 63 (${pct}%)`;
}

async function api(path, body) {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {})
    });
    const data = await res.json();
    if (data.connected !== undefined) updateStatusUI(data);
    return data;
  } catch (e) {
    updateStatusUI({connected: false});
  }
}

function updateStatusUI(data) {
  const dot = document.getElementById('connDot');
  const txt = document.getElementById('connText');
  if (data.connected) {
    dot.classList.add('online');
    txt.textContent = 'Connected';
  } else {
    dot.classList.remove('online');
    txt.textContent = 'Disconnected (Wake Robot)';
  }
  if (data.battery !== undefined && data.battery !== null) {
    document.getElementById('battText').textContent = data.battery + '%';
  }

  // Safety cutoff: Upside-down check
  const safetyBadge = document.getElementById('safetyBadge');
  const roachWarning = document.getElementById('upsideDownWarning');
  if (data.upside_down) {
    if (safetyBadge) safetyBadge.style.display = 'flex';
    if (roachWarning) roachWarning.style.display = 'block';
    if (holdTimer) stopHold(false);
  } else {
    if (safetyBadge) safetyBadge.style.display = 'none';
    if (roachWarning) roachWarning.style.display = 'none';
  }

  // Bump threshold slider sync
  if (data.bump_threshold !== undefined) {
    const slider = document.getElementById('bumpThreshold');
    if (document.activeElement !== slider) {
      slider.value = data.bump_threshold;
      document.getElementById('bumpVal').textContent = `${Number(data.bump_threshold).toFixed(2)} g`;
    }
  }

  if (data.telemetry && data.telemetry.imu) {
    const i = data.telemetry.imu;
    const m = data.telemetry.motor || {mode: 'DIRECT', left_power: 0, right_power: 0};
    const invNote = data.upside_down ? ' [⚠️ INVERTED]' : '';
    imuBox.textContent =
      `Accel (g) : X=${i.ax_g >= 0 ? '+' : ''}${i.ax_g.toFixed(3)}  Y=${i.ay_g >= 0 ? '+' : ''}${i.ay_g.toFixed(3)}  Z=${i.az_g >= 0 ? '+' : ''}${i.az_g.toFixed(3)}${invNote}\\n` +
      `Gyro (dps): X=${i.gx_dps >= 0 ? '+' : ''}${i.gx_dps.toFixed(1)}  Y=${i.gy_dps >= 0 ? '+' : ''}${i.gy_dps.toFixed(1)}  Z=${i.gz_dps >= 0 ? '+' : ''}${i.gz_dps.toFixed(1)}\\n` +
      `Motors    : Mode=${m.mode}  Left=${m.left_power}  Right=${m.right_power}`;
    if (data.upside_down) {
      imuBox.style.borderColor = '#dc2626';
    } else {
      imuBox.style.borderColor = 'var(--border)';
    }
  }
  if (data.cockroach !== undefined) {
    if (data.cockroach.active) {
      roachStatus.textContent = data.cockroach.state || 'ACTIVE';
      roachStatus.style.color = '#7ee787';
      btnRoach.textContent = '⏹ Stop Cockroach Mode';
      btnRoach.classList.add('active');
    } else {
      roachStatus.textContent = 'OFF';
      roachStatus.style.color = '#ffcc80';
      btnRoach.textContent = '▶ Start Cockroach Mode';
      btnRoach.classList.remove('active');
    }
  }
}

function onBumpSliderChange(val) {
  const v = parseFloat(val);
  document.getElementById('bumpVal').textContent = `${v.toFixed(2)} g`;
  api('/api/cockroach/settings', {bump_threshold: v});
}

async function pollStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    updateStatusUI(data);
  } catch (e) {}
}
setInterval(pollStatus, 800);
pollStatus();

async function reconnectRobot() {
  log('Scanning and connecting to robot...');
  const r = await api('/api/connect');
  log(r && r.connected ? 'Connected!' : 'Could not connect — wake robot first.');
}

async function toggleCockroach() {
  const isStarting = btnRoach.textContent.includes('Start');
  log(isStarting ? 'Starting Cockroach Mode...' : 'Stopping Cockroach Mode...');
  const res = await api('/api/cockroach', {action: isStarting ? 'start' : 'stop'});
  if (res && res.cockroach) {
    log(res.cockroach.active ? '🪳 Cockroach Mode running!' : 'Cockroach Mode stopped.');
  }
}

async function setLed(r, g, b) {
  log(`LED -> RGB(${r}, ${g}, ${b})`);
  await api('/api/led', {r, g, b});
}

function pickCustomColor(hex) {
  const r = parseInt(hex.slice(1,3), 16);
  const g = parseInt(hex.slice(3,5), 16);
  const b = parseInt(hex.slice(5,7), 16);
  setLed(r, g, b);
}

async function fireIR() {
  log('Firing IR Tag (ID=1, Cmd=42)...');
  await api('/api/ir', {id: 1, cmd: 42});
}

async function runDemo() {
  log('Running choreographed demo routine...');
  await api('/api/demo');
  log('Choreographed demo finished!');
}

let holdTimer = null;
function sendDrive(left, right) {
  api('/api/drive', {left: Math.round(left), right: Math.round(right)});
  log(`Drive -> Left: ${Math.round(left)}, Right: ${Math.round(right)}`);
}

function startHold(lSign, rSign) {
  stopHold(false);
  const p = getMaxPower();
  const l = lSign * p, r = rSign * p;
  sendDrive(l, r);
  holdTimer = setInterval(() => sendDrive(l, r), 90);
}

function stopHold(sendStop = true) {
  if (holdTimer) { clearInterval(holdTimer); holdTimer = null; }
  if (sendStop) sendDrive(0, 0);
}

function emergencyStop() {
  stopHold(true);
  api('/api/cockroach', {action: 'stop'});
  log('ALL STOP sent.');
}

// Keyboard WASD / Arrow control
const activeKeys = new Set();
window.addEventListener('keydown', (e) => {
  if (e.repeat) return;
  const k = e.key.toLowerCase();
  if (k === ' ') { emergencyStop(); e.preventDefault(); return; }
  if (['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright'].includes(k)) {
    activeKeys.add(k);
    updateKeyDrive();
    e.preventDefault();
  }
});
window.addEventListener('keyup', (e) => {
  const k = e.key.toLowerCase();
  if (activeKeys.has(k)) {
    activeKeys.delete(k);
    updateKeyDrive();
  }
});

function updateKeyDrive() {
  let fwd = 0, turn = 0;
  if (activeKeys.has('w') || activeKeys.has('arrowup')) fwd += 1;
  if (activeKeys.has('s') || activeKeys.has('arrowdown')) fwd -= 1;
  if (activeKeys.has('a') || activeKeys.has('arrowleft')) turn -= 1;
  if (activeKeys.has('d') || activeKeys.has('arrowright')) turn += 1;

  if (fwd === 0 && turn === 0) {
    stopHold(true);
    return;
  }
  const p = getMaxPower();
  let l = fwd * p + turn * (fwd === 0 ? p : p * 0.6);
  let r = fwd * p - turn * (fwd === 0 ? p : p * 0.6);
  l = Math.max(-63, Math.min(63, l));
  r = Math.max(-63, Math.min(63, r));
  if (holdTimer) clearInterval(holdTimer);
  sendDrive(l, r);
  holdTimer = setInterval(() => sendDrive(l, r), 90);
}

// 2D Virtual Joystick Canvas
const canvas = document.getElementById('joyCanvas');
const ctx = canvas.getContext('2d');
const cx = canvas.width / 2, cy = canvas.height / 2, maxR = 75;
let joyX = 0, joyY = 0, dragging = false, joyTimer = null;

function drawJoystick() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = '#30363d';
  ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.arc(cx, cy, maxR, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(cx - maxR, cy); ctx.lineTo(cx + maxR, cy); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(cx, cy - maxR); ctx.lineTo(cx, cy + maxR); ctx.stroke();

  ctx.fillStyle = dragging ? '#00e5ff' : '#7c4dff';
  ctx.beginPath();
  ctx.arc(cx + joyX, cy + joyY, 24, 0, Math.PI * 2);
  ctx.fill();
}
drawJoystick();

function updateJoyPos(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  let dx = clientX - rect.left - cx;
  let dy = clientY - rect.top - cy;
  const dist = Math.hypot(dx, dy);
  if (dist > maxR) { dx = (dx / dist) * maxR; dy = (dy / dist) * maxR; }
  joyX = dx; joyY = dy;
  drawJoystick();
}

function sendJoyDrive() {
  const normX = joyX / maxR;
  const normY = -joyY / maxR;
  const p = getMaxPower();
  const l = Math.max(-63, Math.min(63, (normY + normX * 0.8) * p));
  const r = Math.max(-63, Math.min(63, (normY - normX * 0.8) * p));
  sendDrive(l, r);
}

canvas.addEventListener('pointerdown', (e) => {
  dragging = true;
  canvas.setPointerCapture(e.pointerId);
  updateJoyPos(e.clientX, e.clientY);
  sendJoyDrive();
  if (joyTimer) clearInterval(joyTimer);
  joyTimer = setInterval(sendJoyDrive, 90);
});
canvas.addEventListener('pointermove', (e) => {
  if (!dragging) return;
  updateJoyPos(e.clientX, e.clientY);
});
function endJoy() {
  if (!dragging) return;
  dragging = false;
  joyX = 0; joyY = 0;
  drawJoystick();
  if (joyTimer) { clearInterval(joyTimer); joyTimer = null; }
  sendDrive(0, 0);
}
canvas.addEventListener('pointerup', endJoy);
canvas.addEventListener('pointercancel', endJoy);
</script>
</body>
</html>
"""


class ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Keep console clean

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _is_connected(self) -> bool:
        try:
            import dbus
            dev_props = dbus.Interface(bot.bus.get_object("org.bluez", bot.dev_path), "org.freedesktop.DBus.Properties")
            return bool(dev_props.Get("org.bluez.Device1", "Connected"))
        except Exception:
            return False

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/status":
            with bot_lock:
                conn = self._is_connected()
                batt = bot.last_telemetry.get("battery")
                if conn and batt is None:
                    try:
                        batt = bot.read_battery()
                    except Exception:
                        pass
                upside_down = check_is_upside_down()
                if upside_down and not cockroach_running:
                    try:
                        bot.stop_motors()
                    except Exception:
                        pass
            self._send_json({
                "connected": conn,
                "battery": batt,
                "upside_down": upside_down,
                "bump_threshold": bump_threshold,
                "telemetry": bot.last_telemetry,
                "cockroach": {"active": cockroach_running, "state": cockroach_state}
            })
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        global cockroach_running, cockroach_thread, bump_threshold
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        payload = json.loads(raw.decode("utf-8") or "{}")
        path = urlparse(self.path).path

        with bot_lock:
            if path == "/api/connect":
                ok = bot.connect(timeout_sec=5.0)
                if ok:
                    ensure_telemetry_stream()
                batt = bot.read_battery() if ok else None
                self._send_json({
                    "connected": ok,
                    "battery": batt,
                    "upside_down": check_is_upside_down(),
                    "bump_threshold": bump_threshold,
                    "telemetry": bot.last_telemetry,
                    "cockroach": {"active": cockroach_running, "state": cockroach_state}
                })
                return

            if not self._is_connected():
                if not bot.connect(timeout_sec=3.0):
                    self._send_json({"connected": False, "error": "Robot not connected"})
                    return
                ensure_telemetry_stream()

            try:
                if path == "/api/cockroach/settings":
                    if "bump_threshold" in payload:
                        bump_threshold = max(0.15, min(1.50, float(payload["bump_threshold"])))
                    self._send_json({
                        "connected": True,
                        "bump_threshold": bump_threshold,
                        "upside_down": check_is_upside_down(),
                        "cockroach": {"active": cockroach_running, "state": cockroach_state}
                    })
                    return

                if path == "/api/cockroach":
                    action = payload.get("action", "toggle")
                    if action == "start" or (action == "toggle" and not cockroach_running):
                        if not cockroach_running:
                            cockroach_running = True
                            cockroach_thread = threading.Thread(target=cockroach_loop, daemon=True)
                            cockroach_thread.start()
                    elif action == "stop" or (action == "toggle" and cockroach_running):
                        cockroach_running = False
                    self._send_json({
                        "connected": True,
                        "bump_threshold": bump_threshold,
                        "upside_down": check_is_upside_down(),
                        "cockroach": {"active": cockroach_running, "state": cockroach_state}
                    })
                    return

                if path == "/api/drive":
                    if cockroach_running:
                        cockroach_running = False
                    if check_is_upside_down():
                        bot.stop_motors()
                        self._send_json({
                            "connected": True,
                            "upside_down": True,
                            "error": "Safety cutoff: Robot is held upside down! Motors stopped.",
                            "telemetry": bot.last_telemetry,
                            "cockroach": {"active": cockroach_running, "state": cockroach_state}
                        })
                        return
                    left = int(payload.get("left", 0))
                    right = int(payload.get("right", 0))
                    bot.drive_direct(left, right)
                elif path == "/api/led":
                    bot.set_led(int(payload.get("r", 0)), int(payload.get("g", 255)), int(payload.get("b", 0)))
                elif path == "/api/ir":
                    bot.send_ir(int(payload.get("id", 1)), int(payload.get("cmd", 42)))
                elif path == "/api/demo":
                    if cockroach_running:
                        cockroach_running = False
                    for r, g, b in [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 255)]:
                        bot.set_led(r, g, b)
                        time.sleep(0.25)
                    for l, r, dur in [(42, 42, 0.7), (-42, -42, 0.6), (-45, 45, 0.6), (45, -45, 0.6)]:
                        t0 = time.time()
                        while time.time() - t0 < dur:
                            bot.drive_direct(l, r)
                            time.sleep(0.08)
                    bot.stop_motors()
                    bot.send_ir(1, 99)
                    bot.set_led(0, 255, 255)

                self._send_json({
                    "connected": True,
                    "battery": bot.last_telemetry.get("battery"),
                    "upside_down": check_is_upside_down(),
                    "bump_threshold": bump_threshold,
                    "telemetry": bot.last_telemetry,
                    "cockroach": {"active": cockroach_running, "state": cockroach_state}
                })
            except Exception as e:
                self._send_json({"connected": self._is_connected(), "error": str(e)})


def main():
    print("[*] Scanning / connecting to Kamigami robot...", flush=True)
    if bot.connect(timeout_sec=4.0):
        ensure_telemetry_stream()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), ControlHandler)
    print(f"[+] Kamigami Control Deck UI running at: http://localhost:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
