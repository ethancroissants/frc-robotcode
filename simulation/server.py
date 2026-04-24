"""
Immaculata Robotics - Team 1279 Cold Fusion
Robot Simulator with full ball physics.

Usage:
    python server.py [--port 5280]
"""

import argparse
import math
import time
import random
import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config["SECRET_KEY"] = "coldfusion1279sim"
socketio = SocketIO(app, cors_allowed_origins="*")


class FieldBall:
    """A ball sitting on the field that can be picked up."""
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.id = random.randint(10000, 99999)

    def to_dict(self):
        return {"id": self.id, "x": round(self.x, 2), "y": round(self.y, 2)}


class Projectile:
    """A ball in flight with 3D physics."""
    def __init__(self, x, y, z, vx, vy, vz):
        self.x = x
        self.y = y
        self.z = z  # height
        self.vx = vx
        self.vy = vy
        self.vz = vz
        self.age = 0
        self.landed = False

    def update(self, dt):
        if self.landed:
            return
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.z += self.vz * dt
        self.vz -= 9.8 * dt  # gravity
        self.age += dt
        if self.z <= 0 and self.age > 0.05:
            self.z = 0
            self.landed = True

    def to_dict(self):
        return {
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "z": round(self.z, 3),
            "landed": self.landed,
        }


class RobotSimulator:
    def __init__(self):
        self.field_width = 16.46
        self.field_height = 8.23

        self.x = self.field_width / 2
        self.y = self.field_height / 2
        self.heading = 0

        self.robot_size = 0.762

        self.vx = 0
        self.vy = 0
        self.omega = 0
        self.slow_mode = False

        self.max_speed = 4.5
        self.max_rot_speed = math.pi * 2

        self.shooter_rpm = 0
        self.shooter_target_rpm = 0
        self.shooter_state = "idle"
        self.kicker_active = False
        self.conveyor_state = "idle"
        self.balls_shot = 0
        self.ball_loaded = False

        self.feeder_state = "idle"

        self.hood_angle = 45
        self.hood_state = "idle"

        self.elevator_position = 0
        self.elevator_target = None
        self.elevator_state = "idle"
        self.elevator_speed = 0.6

        self.ELEVATOR_BOTTOM = 0.0
        self.ELEVATOR_LOADING = 19.0
        self.ELEVATOR_LEVEL_1 = 58.0
        self.ELEVATOR_LEVEL_2 = 86.0
        self.ELEVATOR_LEVEL_3 = 110.0

        self.wheel_angles = [0, 0, 0, 0]

        self.field_balls = []
        self.projectiles = []

        self.pickup_range = 0.6
        self.pickup_cooldown = 0

        self.last_tick = time.time()
        self.running = True

        self._thread = threading.Thread(target=self._physics_loop, daemon=True)
        self._thread.start()

    def _physics_loop(self):
        while self.running:
            now = time.time()
            dt = now - self.last_tick
            self.last_tick = now
            self._tick(dt)
            time.sleep(0.02)

    def _tick(self, dt):
        speed_mult = 0.6 if self.slow_mode else 1.0

        cos_h = math.cos(self.heading)
        sin_h = math.sin(self.heading)

        field_vx = (self.vy * cos_h - self.vx * sin_h) * self.max_speed * speed_mult
        field_vy = (self.vy * sin_h + self.vx * cos_h) * self.max_speed * speed_mult

        self.x += field_vx * dt
        self.y += field_vy * dt
        self.heading += self.omega * self.max_rot_speed * speed_mult * dt
        self.heading = (self.heading + math.pi) % (2 * math.pi) - math.pi

        half = self.robot_size / 2
        self.x = max(half, min(self.field_width - half, self.x))
        self.y = max(half, min(self.field_height - half, self.y))

        if abs(self.vx) > 0.05 or abs(self.vy) > 0.05:
            drive_angle = math.atan2(self.vx, self.vy)
            for i in range(4):
                self.wheel_angles[i] = drive_angle
        if abs(self.omega) > 0.05:
            offsets = [math.pi/4, -math.pi/4, 3*math.pi/4, -3*math.pi/4]
            for i in range(4):
                if abs(self.vx) < 0.05 and abs(self.vy) < 0.05:
                    self.wheel_angles[i] = offsets[i]

        rpm_diff = self.shooter_target_rpm - self.shooter_rpm
        if abs(rpm_diff) > 10:
            self.shooter_rpm += rpm_diff * min(dt * 8, 1)
        else:
            self.shooter_rpm = self.shooter_target_rpm

        if self.elevator_target is not None:
            error = self.elevator_target - self.elevator_position
            if abs(error) < 1.0:
                self.elevator_position = self.elevator_target
                self.elevator_target = None
                self.elevator_state = "idle"
            else:
                direction = 1 if error > 0 else -1
                self.elevator_position += direction * 60 * self.elevator_speed * dt
        elif self.elevator_state == "up":
            self.elevator_position = min(110, self.elevator_position + 60 * self.elevator_speed * dt)
        elif self.elevator_state == "down":
            self.elevator_position = max(0, self.elevator_position - 60 * self.elevator_speed * dt)

        self.elevator_position = max(0, min(110, self.elevator_position))

        if self.hood_state == "up":
            self.hood_angle = min(70, self.hood_angle + 20 * dt)
        elif self.hood_state == "down":
            self.hood_angle = max(30, self.hood_angle - 20 * dt)

        # Auto-fire: when shooter reaches target RPM while in firing state
        if self.shooter_state == "firing" and self.ball_loaded:
            if self.shooter_target_rpm > 3000 and self.shooter_rpm > 2800:
                self._launch_ball()
            elif self.shooter_target_rpm <= 3000 and self.shooter_rpm > 1800:
                self._launch_ball()

        # Ball-robot collision: push balls away when robot drives into them
        robot_radius = self.robot_size / 2 + 0.05
        for ball in self.field_balls:
            dx = ball.x - self.x
            dy = ball.y - self.y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < robot_radius + 0.06:
                if dist < 0.01:
                    dx, dy = 1, 0
                    dist = 1
                push = (robot_radius + 0.06 - dist) + 0.05
                nx = dx / dist
                ny = dy / dist
                ball.x += nx * push * 8 * dt + nx * 4.0 * dt
                ball.y += ny * push * 8 * dt + ny * 4.0 * dt
                ball.x = max(0.1, min(self.field_width - 0.1, ball.x))
                ball.y = max(0.1, min(self.field_height - 0.1, ball.y))

        # Ball pickup: if intake is active and robot is near a field ball, grab it
        if self.pickup_cooldown > 0:
            self.pickup_cooldown -= dt

        if self.feeder_state == "intake" and not self.ball_loaded and self.pickup_cooldown <= 0:
            closest_ball = None
            closest_dist = self.robot_size / 2 + 0.3
            for ball in self.field_balls:
                dx = ball.x - self.x
                dy = ball.y - self.y
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < closest_dist:
                    closest_dist = dist
                    closest_ball = ball
            if closest_ball:
                self.field_balls.remove(closest_ball)
                self.ball_loaded = True
                self.pickup_cooldown = 0.3

        # Update projectiles
        for p in self.projectiles:
            p.update(dt)

        # Convert landed projectiles back to field balls
        landed = [p for p in self.projectiles if p.landed]
        for p in landed:
            if 0 < p.x < self.field_width and 0 < p.y < self.field_height:
                self.field_balls.append(FieldBall(p.x, p.y))
        self.projectiles = [p for p in self.projectiles if not p.landed and p.age < 5.0]

    def set_drive(self, vx, vy, omega):
        self.vx = max(-1, min(1, vx))
        self.vy = max(-1, min(1, vy))
        self.omega = max(-1, min(1, omega))

    def set_slow_mode(self, enabled):
        self.slow_mode = bool(enabled)

    def brake(self):
        self.vx = 0
        self.vy = 0
        self.omega = 0

    def fire(self):
        self.shooter_state = "firing"
        self.shooter_target_rpm = 2400
        self.kicker_active = True
        self.conveyor_state = "forward"
        if self.ball_loaded and self.shooter_rpm > 1800:
            self._launch_ball()

    def launch(self):
        self.shooter_state = "firing"
        self.shooter_target_rpm = 3600
        self.kicker_active = True
        self.conveyor_state = "forward"
        if self.ball_loaded and self.shooter_rpm > 2800:
            self._launch_ball()

    def spin_up(self):
        self.shooter_state = "spinning"
        self.shooter_target_rpm = 2400

    def clear_out(self):
        self.shooter_state = "clearing"
        self.shooter_target_rpm = -1200
        self.conveyor_state = "reverse"
        if self.ball_loaded:
            cos_h = math.cos(self.heading)
            sin_h = math.sin(self.heading)
            bx = self.x - cos_h * 0.5
            by = self.y - sin_h * 0.5
            bx = max(0.1, min(self.field_width - 0.1, bx))
            by = max(0.1, min(self.field_height - 0.1, by))
            self.field_balls.append(FieldBall(bx, by))
            self.ball_loaded = False

    def cease_fire(self):
        self.shooter_state = "idle"
        self.shooter_target_rpm = 0
        self.kicker_active = False
        self.conveyor_state = "idle"

    def conveyor_forward(self):
        self.conveyor_state = "forward"

    def conveyor_reverse(self):
        self.conveyor_state = "reverse"

    def stop_conveyor(self):
        self.conveyor_state = "idle"

    def intake(self):
        self.feeder_state = "intake"

    def stop_feeder(self):
        self.feeder_state = "idle"

    def hood_up(self):
        self.hood_state = "up"

    def hood_down(self):
        self.hood_state = "down"

    def stop_hood(self):
        self.hood_state = "idle"

    def elevator_up(self):
        self.elevator_state = "up"
        self.elevator_target = None

    def elevator_down(self):
        self.elevator_state = "down"
        self.elevator_target = None

    def stop_elevator(self):
        self.elevator_state = "idle"
        self.elevator_target = None

    def elevator_preset(self, position):
        self.elevator_target = max(0, min(110, position))
        self.elevator_state = "preset"

    def emergency_stop(self):
        self.brake()
        self.cease_fire()
        self.stop_feeder()
        self.stop_hood()
        self.stop_elevator()

    def spawn_ball(self):
        x = random.uniform(1.0, self.field_width - 1.0)
        y = random.uniform(1.0, self.field_height - 1.0)
        self.field_balls.append(FieldBall(x, y))

    def spawn_balls_random(self, count=5):
        for _ in range(count):
            self.spawn_ball()

    def clear_balls(self):
        self.field_balls.clear()
        self.projectiles.clear()

    def _launch_ball(self):
        speed = self.shooter_rpm / 400
        angle_rad = math.radians(self.hood_angle)
        cos_h = math.cos(self.heading)
        sin_h = math.sin(self.heading)

        horiz_speed = speed * math.cos(angle_rad)
        vert_speed = speed * math.sin(angle_rad)

        start_x = self.x + cos_h * 0.5
        start_y = self.y + sin_h * 0.5
        start_z = 0.3 + (self.elevator_position / 110.0) * 0.5

        self.projectiles.append(Projectile(
            start_x, start_y, start_z,
            cos_h * horiz_speed,
            sin_h * horiz_speed,
            vert_speed
        ))
        self.balls_shot += 1
        self.ball_loaded = False

    def get_state(self):
        return {
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "heading": round(self.heading, 4),
            "vx": round(self.vx, 2),
            "vy": round(self.vy, 2),
            "omega": round(self.omega, 2),
            "slow_mode": self.slow_mode,
            "wheel_angles": [round(a, 3) for a in self.wheel_angles],
            "shooter_rpm": round(self.shooter_rpm),
            "shooter_state": self.shooter_state,
            "kicker_active": self.kicker_active,
            "conveyor_state": self.conveyor_state,
            "feeder_state": self.feeder_state,
            "hood_angle": round(self.hood_angle, 1),
            "hood_state": self.hood_state,
            "elevator_position": round(self.elevator_position, 1),
            "elevator_state": self.elevator_state,
            "ball_loaded": self.ball_loaded,
            "balls_shot": self.balls_shot,
            "field_balls": [b.to_dict() for b in self.field_balls],
            "projectiles": [p.to_dict() for p in self.projectiles],
        }


sim = RobotSimulator()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    return jsonify(sim.get_state())


@socketio.on("drive")
def handle_drive(data):
    sim.set_drive(
        data.get("vx", 0),
        data.get("vy", 0),
        data.get("omega", 0),
    )


@socketio.on("command")
def handle_command(data):
    cmd = data.get("command", "")
    value = data.get("value", 1.0)

    cmd_map = {
        "fire": sim.fire,
        "launch": sim.launch,
        "spin_up": sim.spin_up,
        "clear": sim.clear_out,
        "cease_fire": sim.cease_fire,
        "conveyor_fwd": sim.conveyor_forward,
        "conveyor_rev": sim.conveyor_reverse,
        "stop_conveyor": sim.stop_conveyor,
        "intake": sim.intake,
        "stop_feeder": sim.stop_feeder,
        "hood_up": sim.hood_up,
        "hood_down": sim.hood_down,
        "stop_hood": sim.stop_hood,
        "elevator_up": sim.elevator_up,
        "elevator_down": sim.elevator_down,
        "stop_elevator": sim.stop_elevator,
        "brake": sim.brake,
        "estop": sim.emergency_stop,
        "spawn_ball": sim.spawn_ball,
        "clear_balls": sim.clear_balls,
    }

    if cmd == "slow_mode":
        sim.set_slow_mode(value)
    elif cmd == "elevator_preset":
        sim.elevator_preset(value)
    elif cmd == "spawn_balls":
        sim.spawn_balls_random(int(value) if value else 5)
    elif cmd in cmd_map:
        cmd_map[cmd]()


@socketio.on("state_request")
def handle_state_request():
    emit("state_update", sim.get_state())


def broadcast_state():
    while True:
        socketio.emit("state_update", sim.get_state())
        socketio.sleep(1 / 30)


def main():
    parser = argparse.ArgumentParser(description="Immaculata Robotics - Robot Simulator")
    parser.add_argument("--port", type=int, default=5280, help="Web server port")
    args = parser.parse_args()

    print()
    print("=" * 55)
    print("  IMMACULATA ROBOTICS - Team 1279 Cold Fusion")
    print("  Robot Simulator")
    print("=" * 55)
    print(f"  Simulator:  http://localhost:{args.port}")
    print(f"  Gamepad:    Connect Xbox/PS controller")
    print(f"  Keyboard:   WASD + mouse for driving")
    print("=" * 55)
    print()

    socketio.start_background_task(broadcast_state)
    socketio.run(app, host="0.0.0.0", port=args.port, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
