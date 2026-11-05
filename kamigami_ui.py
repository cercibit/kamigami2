#!/usr/bin/env python3
"""
Kamigami Robot (KRB0002 - Firmware 2.0.2) Interactive Web Dashboard & Manual Controller UI
Serves a local web interface at http://localhost:8765 with:
- Virtual 2D Joystick & WASD / Arrow-Key manual driving (Firmware 2.0.2 6-byte MotorDirect)
- Throttle slider (15 - 63)
- RGB Eye LED color picker & quick presets (Firmware 2.0.2 7-byte EyeColor)
- Infrared (IR) battle laser trigger (Firmware 2.0.2 3-byte IR)
- One-click Choreographed Test Run ("Dance / Patrol")
- Live BLE connection status, battery monitor, and 6-axis IMU sensor readout
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from kamigami_cli import DEFAULT_MAC, KamigamiRobot

PORT = 8765
bot_lock = threading.Lock()
bot = KamigamiRobot(DEFAULT_MAC)
notify_initialized = False


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
        bot.set_update_frequencies(imu_hz=5, motor_hz=2)
    except Exception:
        pass


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kamigami Robot (KRB0002) Control Deck</title>
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

  <!-- Right Column: LED, IR, & Choreographed Routines -->
  <div class="card">
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

    <hr style="border:0;border-top:1px solid var(--border);width:100%">

    <h2>🔫 Infrared & Choreographed Routines</h2>
    <div class="row">
      <button class="btn-primary" style="flex:1" onclick="fireIR()">⚡ Fire IR Laser Tag</button>
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
    if (data.connected !== undefined) updateStatusUI(data.connected, data.battery, data.telemetry);
    return data;
  } catch (e) {
    updateStatusUI(false);
  }
}

function updateStatusUI(connected, battery, telemetry) {
  const dot = document.getElementById('connDot');
  const txt = document.getElementById('connText');
  if (connected) {
    dot.classList.add('online');
    txt.textContent = 'Connected';
  } else {
    dot.classList.remove('online');
    txt.textContent = 'Disconnected (Wake Robot)';
  }
  if (battery !== undefined && battery !== null) {
    document.getElementById('battText').textContent = battery + '%';
  }
  if (telemetry && telemetry.imu) {
    const i = telemetry.imu;
    const m = telemetry.motor || {mode: 'DIRECT', left_power: 0, right_power: 0};
    imuBox.textContent =
      `Accel (g) : X=${i.ax_g >= 0 ? '+' : ''}${i.ax_g.toFixed(3)}  Y=${i.ay_g >= 0 ? '+' : ''}${i.ay_g.toFixed(3)}  Z=${i.az_g >= 0 ? '+' : ''}${i.az_g.toFixed(3)}\\n` +
      `Gyro (dps): X=${i.gx_dps >= 0 ? '+' : ''}${i.gx_dps.toFixed(1)}  Y=${i.gy_dps >= 0 ? '+' : ''}${i.gy_dps.toFixed(1)}  Z=${i.gz_dps >= 0 ? '+' : ''}${i.gz_dps.toFixed(1)}\\n` +
      `Motors    : Mode=${m.mode}  Left=${m.left_power}  Right=${m.right_power}`;
  }
}

async function pollStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    updateStatusUI(data.connected, data.battery, data.telemetry);
  } catch (e) {}
}
setInterval(pollStatus, 800);
pollStatus();

async function reconnectRobot() {
  log('Scanning and connecting to KRB0002...');
  const r = await api('/api/connect');
  log(r && r.connected ? 'Connected to KRB0002!' : 'Could not connect — shake/wake robot first.');
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
  log('Firing IR Battle Tag (ID=1, Cmd=42)...');
  await api('/api/ir', {id: 1, cmd: 42});
}

async function runDemo() {
  log('Running choreographed test routine on robot...');
  await api('/api/demo');
  log('Choreographed test routine finished!');
}

let holdTimer = null;
function sendDrive(left, right) {
  api('/api/drive', {left: Math.round(left), right: Math.round(right)});
  log(`MotorDirect -> Left: ${Math.round(left)}, Right: ${Math.round(right)}`);
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
  const normX = joyX / maxR;      // -1 (left) to +1 (right)
  const normY = -joyY / maxR;     // -1 (back) to +1 (fwd)
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
            self._send_json({"connected": conn, "battery": batt, "telemetry": bot.last_telemetry})
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
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
                self._send_json({"connected": ok, "battery": batt, "telemetry": bot.last_telemetry})
                return

            if not self._is_connected():
                if not bot.connect(timeout_sec=3.0):
                    self._send_json({"connected": False, "error": "Robot not connected"})
                    return
                ensure_telemetry_stream()

            try:
                if path == "/api/drive":
                    left = int(payload.get("left", 0))
                    right = int(payload.get("right", 0))
                    bot.drive_direct(left, right)
                elif path == "/api/led":
                    bot.set_led(int(payload.get("r", 0)), int(payload.get("g", 255)), int(payload.get("b", 0)))
                elif path == "/api/ir":
                    bot.send_ir(int(payload.get("id", 1)), int(payload.get("cmd", 42)))
                elif path == "/api/demo":
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
                self._send_json({"connected": True, "battery": bot.last_telemetry.get("battery"), "telemetry": bot.last_telemetry})
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
