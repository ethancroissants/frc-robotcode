"""
Cold Fusion 1279 - Robot Web Control Panel
==========================================
Web-based control interface for the FRC robot.
Communicates with the robot via NetworkTables (NT4).

Usage:
    python server.py [--port 5279] [--robot-ip 10.12.79.2]
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from flask import Flask, render_template, jsonify, request, Response

try:
    import ntcore
    NT_AVAILABLE = True
except ImportError:
    NT_AVAILABLE = False
    print("[WARNING] ntcore not installed. Running in demo mode.")
    print("  Install with: pip install pyntcore")

app = Flask(__name__)
app.config["SECRET_KEY"] = "coldfusion1279"

TEAM = "1279"
ROBOT_IP_DEFAULT = "10.12.79.2"

# Debug log buffer (last 200 entries)
debug_log = deque(maxlen=200)
debug_lock = threading.Lock()


def log_debug(direction, key, value):
    """Add an entry to the debug log. direction: 'SEND' or 'RECV'"""
    entry = {
        "time": time.strftime("%H:%M:%S"),
        "ms": int(time.time() * 1000) % 100000,
        "dir": direction,
        "key": key,
        "value": str(value),
    }
    with debug_lock:
        debug_log.append(entry)


class RobotBridge:
    def __init__(self, robot_ip="10.12.79.2"):
        self.robot_ip = robot_ip
        self.connected = False
        self.inst = None
        self.table = None
        self.status_table = None
        self._command_publishers = {}
        self._status_cache = {
            "connected": False,
            "mode": "disabled",
            "match_time": -1,
            "drivetrain": {"vx": 0, "vy": 0, "omega": 0, "slow_mode": False},
            "shooter": {"state": "idle", "velocity": 0},
            "feeder": {"state": "idle"},
            "hood": {"state": "idle"},
            "elevator": {"state": "idle", "position": 0},
        }

        if NT_AVAILABLE:
            self._init_nt()

    def _init_nt(self):
        self.inst = ntcore.NetworkTableInstance.create()
        self.inst.startClient4("ColdFusion1279-WebPanel")
        self.inst.setServer(self.robot_ip)

        self.table = self.inst.getTable("WebPanel")
        self.status_table = self.inst.getTable("RobotStatus")

        for name in ["drive/vx", "drive/vy", "drive/omega", "drive/timestamp"]:
            self._command_publishers[name] = self.table.getDoubleTopic(name).publish()

        action_keys = [
            "drivetrain/slow_mode", "drivetrain/brake", "drivetrain/reset_heading",
            "shooter/fire", "shooter/launch", "shooter/clear",
            "shooter/cease_fire", "shooter/conveyor_fwd", "shooter/conveyor_rev",
            "shooter/stop_conveyor",
            "feeder/intake", "feeder/eject", "feeder/stop",
            "hood/up", "hood/down", "hood/stop",
            "elevator/up", "elevator/down", "elevator/stop",
            "elevator/preset",
        ]
        for cmd_name in action_keys:
            self._command_publishers[cmd_name] = self.table.getDoubleTopic(cmd_name).publish()

        self._drive_counter = 0

        self._mode_pub = self.table.getStringTopic("set_mode").publish()

        self._poll_thread = threading.Thread(target=self._poll_status, daemon=True)
        self._poll_thread.start()

    def set_mode(self, mode):
        if NT_AVAILABLE and hasattr(self, '_mode_pub'):
            self._mode_pub.set(mode)
            log_debug("SEND", "set_mode", mode)

    def _poll_status(self):
        was_connected = False
        while True:
            try:
                if self.inst:
                    self.connected = self.inst.isConnected()
                    self._status_cache["connected"] = self.connected

                    if self.connected and not was_connected:
                        print(f"  [NT] Connected to robot at {self.robot_ip}")
                        log_debug("RECV", "connection", "established")
                    elif not self.connected and was_connected:
                        print(f"  [NT] Lost connection to robot")
                        log_debug("RECV", "connection", "lost")
                    was_connected = self.connected

                    if self.connected and self.status_table:
                        elev_pos = self.status_table.getNumber("elevator/position", 0)
                        shooter_vel = self.status_table.getNumber("shooter/velocity", 0)
                        mode = self.status_table.getString("mode", "disabled")
                        match_time = self.status_table.getNumber("match_time", -1)

                        self._status_cache["elevator"]["position"] = elev_pos
                        self._status_cache["shooter"]["velocity"] = shooter_vel
                        self._status_cache["mode"] = mode
                        self._status_cache["match_time"] = match_time

                        log_debug("RECV", "elevator/position", round(elev_pos, 2))
                        log_debug("RECV", "shooter/velocity", round(shooter_vel, 2))
                        log_debug("RECV", "mode", mode)
            except Exception as e:
                print(f"  [NT] Error: {e}")
            time.sleep(0.1)

    def send_command(self, subsystem, command, value=1.0):
        key = f"{subsystem}/{command}"
        if NT_AVAILABLE and key in self._command_publishers:
            self._command_publishers[key].set(float(value))
            log_debug("SEND", key, value)
            return True
        return not NT_AVAILABLE

    def send_drive(self, vx, vy, omega):
        if not NT_AVAILABLE:
            return
        self._drive_counter += 1
        self._command_publishers["drive/vx"].set(float(vx))
        self._command_publishers["drive/vy"].set(float(vy))
        self._command_publishers["drive/omega"].set(float(omega))
        self._command_publishers["drive/timestamp"].set(float(self._drive_counter))
        if abs(vx) > 0.01 or abs(vy) > 0.01 or abs(omega) > 0.01:
            log_debug("SEND", "drive", f"vx={vx:.2f} vy={vy:.2f} omega={omega:.2f}")

    def get_status(self):
        return self._status_cache


bridge = None
# Track running processes for setup/deploy
_running_processes = {}
_process_output = {}
_process_lock = threading.Lock()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify(bridge.get_status())


@app.route("/api/command", methods=["POST"])
def api_command():
    data = request.json
    subsystem = data.get("subsystem", "")
    command = data.get("command", "")
    value = data.get("value", 1.0)
    success = bridge.send_command(subsystem, command, value)
    return jsonify({"ok": success})


@app.route("/api/drive", methods=["POST"])
def api_drive():
    data = request.json
    bridge.send_drive(data.get("vx", 0), data.get("vy", 0), data.get("omega", 0))
    return jsonify({"ok": True})


@app.route("/api/set_mode", methods=["POST"])
def api_set_mode():
    data = request.json
    mode = data.get("mode", "disabled")
    if mode not in ("disabled", "auto", "teleop", "test"):
        return jsonify({"error": "Invalid mode"}), 400
    bridge.set_mode(mode)
    return jsonify({"ok": True, "mode": mode})


@app.route("/api/debug")
def api_debug():
    with debug_lock:
        entries = list(debug_log)
    return jsonify(entries)


@app.route("/api/network_check")
def api_network_check():
    robot_ip = bridge.robot_ip if bridge else ROBOT_IP_DEFAULT
    reachable = False
    try:
        sock = socket.create_connection((robot_ip, 22), timeout=2)
        sock.close()
        reachable = True
    except Exception:
        try:
            ping_cmd = (["ping", "-n", "1", "-w", "2000", robot_ip]
                        if sys.platform == "win32"
                        else ["ping", "-c", "1", "-W", "2", robot_ip])
            result = subprocess.run(ping_cmd, capture_output=True, timeout=5)
            reachable = result.returncode == 0
        except Exception:
            pass
    return jsonify({"reachable": reachable, "robot_ip": robot_ip, "nt_connected": bridge.connected if bridge else False})


@app.route("/api/run_task", methods=["POST"])
def api_run_task():
    """Run setup or deploy as a background task, streaming output."""
    data = request.json
    task = data.get("task", "")  # "setup" or "deploy"
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if task == "setup":
        cmd = [sys.executable, "-u", os.path.join(project_dir, "setup_headless.py")]
    elif task == "deploy":
        cmd = [sys.executable, "-u", os.path.join(project_dir, "deploy_headless.py")]
    elif task == "test":
        cmd = [sys.executable, "-u", "-m", "pytest", "tests/", "-v", "--tb=short"]
    else:
        return jsonify({"error": "Unknown task"}), 400

    with _process_lock:
        if task in _running_processes and _running_processes[task].poll() is None:
            return jsonify({"error": f"{task} is already running"}), 409
        _process_output[task] = []

    def run_in_bg():
        try:
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True, cwd=project_dir, bufsize=1, env=env,
            )
            if proc.stdin:
                proc.stdin.close()
            with _process_lock:
                _running_processes[task] = proc
            for line in proc.stdout:
                with _process_lock:
                    _process_output[task].append(line.rstrip("\n"))
            proc.wait()
            with _process_lock:
                _process_output[task].append(f"\n--- Finished (exit code {proc.returncode}) ---")
        except Exception as e:
            with _process_lock:
                _process_output[task].append(f"ERROR: {e}")

    t = threading.Thread(target=run_in_bg, daemon=True)
    t.start()
    return jsonify({"ok": True, "task": task})


@app.route("/api/task_output")
def api_task_output():
    task = request.args.get("task", "")
    since = int(request.args.get("since", 0))
    with _process_lock:
        lines = _process_output.get(task, [])
        new_lines = lines[since:]
        running = (task in _running_processes and
                   _running_processes[task].poll() is None)
    return jsonify({"lines": new_lines, "total": len(lines), "running": running})


def main():
    global bridge
    parser = argparse.ArgumentParser(description="Cold Fusion 1279 Web Control Panel")
    parser.add_argument("--port", type=int, default=5279, help="Web server port")
    parser.add_argument("--robot-ip", default=ROBOT_IP_DEFAULT, help="Robot IP address")
    args = parser.parse_args()

    bridge = RobotBridge(robot_ip=args.robot_ip)

    print()
    print("=" * 55)
    print("  COLD FUSION 1279 - Robot Web Control Panel")
    print("=" * 55)
    print(f"  Web UI:    http://localhost:{args.port}")
    print(f"  Robot IP:  {args.robot_ip}")
    print(f"  NT Status: {'Available' if NT_AVAILABLE else 'DEMO MODE'}")
    print("=" * 55)
    print()

    app.run(host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
