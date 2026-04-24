# ============================================================
# WEB CONTROL - Receives commands from the web control panel
# ============================================================
# This subsystem reads commands from NetworkTables that are
# sent by the web control panel, and translates them into
# actions on the robot's subsystems.
#
# Commands use a TIMESTAMP approach: the web panel writes an
# incrementing counter each time a button is pressed/released.
# The robot detects the change and executes the action once.
#
# It also publishes robot status (elevator position, shooter
# velocity, etc.) so the web panel can display live data.
# ============================================================

import time
from commands2 import SubsystemBase
from ntcore import NetworkTableInstance


class WebControl(SubsystemBase):
    """Reads web panel commands from NetworkTables and drives subsystems."""

    def __init__(self, drivetrain, shooter, feeder, hood, elevator):
        super().__init__()
        self.drivetrain = drivetrain
        self.shooter = shooter
        self.feeder = feeder
        self.hood = hood
        self.elevator = elevator

        # Get NetworkTables
        nt = NetworkTableInstance.getDefault()
        self.cmd_table = nt.getTable("WebPanel")
        self.status_table = nt.getTable("RobotStatus")

        # --- Drive values (continuous, read every cycle) ---
        self._drive_vx_sub = self.cmd_table.getDoubleTopic("drive/vx").subscribe(0.0)
        self._drive_vy_sub = self.cmd_table.getDoubleTopic("drive/vy").subscribe(0.0)
        self._drive_omega_sub = self.cmd_table.getDoubleTopic("drive/omega").subscribe(0.0)

        # Track when the web panel last sent a drive update
        self._drive_ts_sub = self.cmd_table.getDoubleTopic("drive/timestamp").subscribe(0.0)
        self._last_drive_ts = 0.0
        self._last_drive_time = 0.0
        self._drive_active = False
        self.DRIVE_TIMEOUT = 0.25

        # --- Action commands (edge-triggered via counter) ---
        # Each action has a counter that increments on press/release.
        # We detect the change and run the action once.
        self._action_keys = [
            "shooter/fire", "shooter/launch", "shooter/clear",
            "shooter/cease_fire", "shooter/conveyor_fwd", "shooter/conveyor_rev",
            "shooter/stop_conveyor",
            "feeder/intake", "feeder/eject", "feeder/stop",
            "hood/up", "hood/down", "hood/stop",
            "elevator/up", "elevator/down", "elevator/stop",
            "elevator/preset",
            "drivetrain/slow_mode", "drivetrain/brake",
            "drivetrain/reset_heading",
        ]
        self._action_subs = {}
        self._last_action = {}
        for key in self._action_keys:
            self._action_subs[key] = self.cmd_table.getDoubleTopic(key).subscribe(0.0)
            self._last_action[key] = 0.0

        # Status publishers
        self._elev_pos_pub = self.status_table.getDoubleTopic(
            "elevator/position"
        ).publish()
        self._shooter_vel_pub = self.status_table.getDoubleTopic(
            "shooter/velocity"
        ).publish()
        self._connected_pub = self.status_table.getDoubleTopic(
            "web/connected"
        ).publish()

        # Only publish status every 10th cycle (~500ms) to reduce
        # CAN traffic from sensor reads on potentially missing motors
        self._status_counter = 0

    def periodic(self):
        """Called every loop cycle. Check for web commands and publish status."""
        try:
            self._process_drive()
            self._process_actions()
        except Exception:
            pass

        # Publish status less frequently to avoid CAN timeout delays
        self._status_counter += 1
        if self._status_counter >= 10:
            self._status_counter = 0
            self._publish_status()

    def _process_drive(self):
        """Read drive joystick values from the web panel."""
        ts = self._drive_ts_sub.get()
        now = time.monotonic()

        if ts != self._last_drive_ts:
            self._last_drive_ts = ts
            self._last_drive_time = now
            self._drive_active = True

            vx = self._drive_vx_sub.get()
            vy = self._drive_vy_sub.get()
            omega = self._drive_omega_sub.get()
            self.drivetrain.drive(vx, vy, omega)
        elif self._drive_active and (now - self._last_drive_time) > self.DRIVE_TIMEOUT:
            self.drivetrain.drive(0, 0, 0)
            self._drive_active = False

    def _process_actions(self):
        """Read action commands and fire on change."""
        for key in self._action_keys:
            val = self._action_subs[key].get()
            if val == self._last_action[key]:
                continue
            self._last_action[key] = val
            self._run_action(key, val)

    def _run_action(self, key, value):
        """Execute a single action command."""
        actions = {
            "shooter/fire": lambda v: self.shooter.fire() if v > 0 else None,
            "shooter/launch": lambda v: self.shooter.launch() if v > 0 else None,
            "shooter/clear": lambda v: self.shooter.clear_out() if v > 0 else None,
            "shooter/cease_fire": lambda v: self.shooter.cease_fire(),
            "shooter/conveyor_fwd": lambda v: self.shooter.conveyor_forward() if v > 0 else None,
            "shooter/conveyor_rev": lambda v: self.shooter.conveyor_reverse() if v > 0 else None,
            "shooter/stop_conveyor": lambda v: self.shooter.stop_conveyor(),
            "feeder/intake": lambda v: self.feeder.intake() if v > 0 else None,
            "feeder/eject": lambda v: self.feeder.eject() if v > 0 else None,
            "feeder/stop": lambda v: self.feeder.stop(),
            "hood/up": lambda v: self.hood.tilt_up() if v > 0 else None,
            "hood/down": lambda v: self.hood.tilt_down() if v > 0 else None,
            "hood/stop": lambda v: self.hood.stop(),
            "elevator/up": lambda v: self.elevator.go_up() if v > 0 else None,
            "elevator/down": lambda v: self.elevator.go_down() if v > 0 else None,
            "elevator/stop": lambda v: self.elevator.stop(),
            "elevator/preset": lambda v: self.elevator.go_to_position(v) if v > 0 else None,
            "drivetrain/slow_mode": lambda v: self.drivetrain.set_slow_mode(v > 0.5),
            "drivetrain/brake": lambda v: self.drivetrain.stop() if v > 0 else None,
            "drivetrain/reset_heading": lambda v: self.drivetrain.reset_heading() if v > 0 else None,
        }
        fn = actions.get(key)
        if fn:
            try:
                fn(value)
            except Exception:
                pass

    def _publish_status(self):
        """Publish robot status to NetworkTables for the web panel."""
        try:
            self._elev_pos_pub.set(self.elevator.get_position())
        except Exception:
            pass

        try:
            self._shooter_vel_pub.set(self.shooter.get_velocity())
        except Exception:
            pass

        try:
            self._connected_pub.set(1.0)
        except Exception:
            pass
