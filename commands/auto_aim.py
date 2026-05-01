"""AutoAim: Pi SHOOT button → rio rotates onto the AprilTag and fires.

NetworkTables contract (all under /SmartDashboard)
--------------------------------------------------
Pi → rio (read here):
  Sight/Target/Detected      bool   — tag visible right now?
  Sight/Target/BearingDeg    double — signed angle from camera optical axis
                                       (positive = target is right of center)
  Sight/Target/RangeM        double — PnP-derived range (fallback for LaserCAN)
  Sight/Target/TagID         int    — which tag we're tracking
  Sight/Aim/TargetRps        double — Pi's RPS recommendation from its
                                       distance→RPS calibration table
  Sight/Shoot/RequestId      int    — bumped on SHOOT press; rio's trigger
                                       (in robotcontainer) edge-detects this
                                       and schedules this command

rio → Pi (written here):
  Sight/Aim/Status           string — phase: idle | rotating | spinning_up
                                       | firing | done | error
  Sight/DriverLockout        bool   — true while this command is running so
                                       the Pi UI shows "DRIVER LOCKED" and
                                       the operator knows the swerve is busy

Closed-loop strategy
--------------------
We don't compute an absolute target heading — we close the bearing-error
loop directly. Every cycle we read the *fresh* bearing from the Pi and feed
0 as the setpoint to a PIDController. The output is yaw rate (rad/s),
which goes straight into a swerve FieldCentric request with zero translation.

Range comes from LaserCAN preferentially; the AprilTag PnP range is a
fallback for momentary CAN dropouts.

If the tag drops out of view mid-aim we hold the last bearing for up to
HOLD_LAST_BEARING_S; beyond that we abort. That keeps us from spinning
randomly when a robot crosses the line of sight.

The rio's existing requirements system means while this command runs,
the drivetrain's joystick default command is suppressed — the driver
literally cannot drive. The DriverLockout flag is a UI mirror so the
operator sees "yep, I'm locked out for a second" rather than thinking
their controller is broken.
"""

from __future__ import annotations

import math

from commands2 import Command
from phoenix6.swerve import SwerveModule, requests as swerve_requests
from wpilib import SmartDashboard, Timer
from wpimath.controller import PIDController

import tunables
from subsystems.lasercan_subsystem import LaserCanSubsystem
from subsystems.operator_subsystem import OperatorSubsystem


# ----- NT topic names (mirror server.py) -----
_NT_TARGET_DETECTED = "Sight/Target/Detected"
_NT_TARGET_BEARING  = "Sight/Target/BearingDeg"
_NT_TARGET_RANGE_M  = "Sight/Target/RangeM"
_NT_TARGET_TAG_ID   = "Sight/Target/TagID"
_NT_TARGET_RPS      = "Sight/Aim/TargetRps"
_NT_STATUS          = "Sight/Aim/Status"
_NT_LOCKOUT         = "Sight/DriverLockout"

# ----- Tuning -----
# Bearing error → yaw rate. Bearing is in radians; output is rad/s. 4.0 means
# 1° of bearing error commands ~0.07 rad/s of yaw — gentle enough to avoid
# overshoot, fast enough to slew 30° in <1s.
_HEADING_KP = 4.0
_HEADING_KI = 0.0
_HEADING_KD = 0.2
_HEADING_TOLERANCE_RAD = math.radians(1.5)  # within 1.5° of tag center = on target

# Once heading is locked, give the flywheel time to settle (use the velocity
# tolerance check too — whichever is later).
_FLYWHEEL_SETTLE_S = 0.4

# How long to hold the last bearing if the tag temporarily drops out.
_HOLD_LAST_BEARING_S = 0.4

# Hard timeout for the whole sequence.
_OVERALL_TIMEOUT_S = 6.0

# How long to actually feed once at-speed. Reads from the existing tunable
# (auto_fire_duration) so it stays consistent with the manual fire path.
_FOOT_TO_M = 0.3048


def _publish_status(s: str) -> None:
    SmartDashboard.putString(_NT_STATUS, s)


def _publish_lockout(v: bool) -> None:
    SmartDashboard.putBoolean(_NT_LOCKOUT, v)


class AutoAim(Command):
    """Listens for Pi SHOOT requests; rotates onto the tag + fires.

    Constructed once per shoot, by the DeferredCommand wired up in
    robotcontainer.py — that gives us a fresh PIDController state every
    fire so we never carry over integral windup from a prior aim.
    """

    def __init__(self, drivetrain, operator: OperatorSubsystem, lasercan: LaserCanSubsystem):
        super().__init__()
        self.drivetrain = drivetrain
        self.operator = operator
        self.lasercan = lasercan
        # Requirements: holding both means scheduling AutoAim cancels the
        # default joystick-drive command, so the driver physically cannot
        # move the robot until end() runs. That IS the driver lockout —
        # the NT flag is for UI feedback.
        self.addRequirements(operator, drivetrain)

        self._req = (
            swerve_requests.FieldCentric()
            .with_drive_request_type(SwerveModule.DriveRequestType.OPEN_LOOP_VOLTAGE)
        )

        # Bearing PID: setpoint is always 0 (we want the target centered),
        # measurement is the current bearing in radians. Continuous input
        # because bearing wraps if the camera ever sees +/-180° (it
        # shouldn't, but cheap safety).
        self._heading_pid = PIDController(_HEADING_KP, _HEADING_KI, _HEADING_KD)
        self._heading_pid.enableContinuousInput(-math.pi, math.pi)
        self._heading_pid.setTolerance(_HEADING_TOLERANCE_RAD)

        self._timer = Timer()
        self._settle_timer = Timer()
        self._lost_timer = Timer()  # how long since we last saw the tag
        self._target_rps: float = 0.0
        self._last_bearing_rad: float = 0.0
        self._phase = "idle"

    # ----- lifecycle -----

    def initialize(self) -> None:
        self._timer.reset(); self._timer.start()
        self._settle_timer.stop(); self._settle_timer.reset()
        self._lost_timer.stop(); self._lost_timer.reset()
        self._heading_pid.reset()

        # Snapshot what the Pi sees right now. If there's no detection at
        # all we still arm — the tag may show up between init and execute —
        # but we go straight into "rotating" with bearing=0 (no rotation)
        # and rely on the lost-timer to time us out if nothing appears.
        self._target_rps = max(0.0, float(SmartDashboard.getNumber(_NT_TARGET_RPS, 0.0)))
        self._last_bearing_rad = math.radians(
            SmartDashboard.getNumber(_NT_TARGET_BEARING, 0.0)
        )

        # Mirror the Pi-recommended distance into the dial so the driver-side
        # display (Elastic / control panel) stays meaningful.
        range_m = self._best_range_m()
        if range_m is not None:
            tunables.set_shooter_distance_feet(range_m / _FOOT_TO_M)

        self._phase = "rotating"
        _publish_status("rotating")
        _publish_lockout(True)

    def execute(self) -> None:
        if self._phase in ("idle", "error", "done"):
            return

        bearing_rad, fresh = self._read_bearing()
        if fresh:
            self._last_bearing_rad = bearing_rad
            self._lost_timer.stop(); self._lost_timer.reset()
        else:
            if not self._lost_timer.isRunning():
                self._lost_timer.start()
            if self._lost_timer.get() > _HOLD_LAST_BEARING_S:
                # We've lost the tag too long; abort rather than driving on
                # a stale value.
                _publish_status("error")
                self._phase = "error"
                self._stop_drive()
                return
            bearing_rad = self._last_bearing_rad  # hold last known

        # Refresh RPS each tick — distance changes if the bot is moving
        # (it shouldn't be, since we own drivetrain, but the Pi's
        # recommendation reflects the current LaserCAN/PnP reading).
        rps = float(SmartDashboard.getNumber(_NT_TARGET_RPS, 0.0))
        if rps > 0:
            self._target_rps = rps

        if self._phase == "rotating":
            self._rotate_step(bearing_rad)
            if self._heading_pid.atSetpoint() and abs(bearing_rad) < _HEADING_TOLERANCE_RAD:
                self._phase = "spinning_up"
                self._settle_timer.reset(); self._settle_timer.start()
                _publish_status("spinning_up")

        if self._phase == "spinning_up":
            # Keep holding heading + spin the wheel.
            self._rotate_step(bearing_rad)
            if self._target_rps > 0:
                self.operator.shooterAtRps(self._target_rps)
            else:
                self.operator.shooterOut()  # fallback to dial-derived RPS
            settled = self._settle_timer.get() >= _FLYWHEEL_SETTLE_S
            at_speed = self._target_rps > 0 and self.operator.isAtRps(self._target_rps)
            if settled and (at_speed or self._target_rps == 0):
                self._phase = "firing"
                _publish_status("firing")

        if self._phase == "firing":
            # Hold heading + keep flywheel spinning + run kicker/conveyor.
            self._rotate_step(bearing_rad)
            if self._target_rps > 0:
                self.operator.shooterAtRps(self._target_rps)
            self.operator.kickerIn()
            self.operator.conveyorFwd()
            if self._timer.get() >= _FLYWHEEL_SETTLE_S + tunables.auto_fire_duration():
                self._phase = "done"
                _publish_status("done")

    def isFinished(self) -> bool:
        if self._phase in ("done", "error", "idle"):
            return True
        if self._timer.get() >= _OVERALL_TIMEOUT_S:
            _publish_status("error")
            self._phase = "error"
            return True
        return False

    def end(self, interrupted: bool) -> None:
        self.operator.ceaseFire()
        self._stop_drive()
        _publish_lockout(False)
        if self._phase != "done":
            _publish_status("idle" if not interrupted else "error")

    # ----- helpers -----

    def _rotate_step(self, bearing_rad: float) -> None:
        """Drive yaw to zero bearing error; hold translation at zero."""
        omega = self._heading_pid.calculate(bearing_rad, 0.0)
        req = (
            self._req
            .with_velocity_x(0.0)
            .with_velocity_y(0.0)
            .with_rotational_rate(omega)
        )
        self.drivetrain.set_control(req)

    def _stop_drive(self) -> None:
        try:
            self.drivetrain.set_control(
                self._req
                .with_velocity_x(0.0)
                .with_velocity_y(0.0)
                .with_rotational_rate(0.0)
            )
        except Exception:
            pass

    def _read_bearing(self) -> tuple[float, bool]:
        """Returns (bearing_rad, fresh). fresh=False if Pi reports no tag."""
        detected = SmartDashboard.getBoolean(_NT_TARGET_DETECTED, False)
        if not detected:
            return self._last_bearing_rad, False
        return math.radians(SmartDashboard.getNumber(_NT_TARGET_BEARING, 0.0)), True

    def _best_range_m(self) -> float | None:
        """LaserCAN if valid; tag PnP otherwise; None if neither."""
        laser = self.lasercan.distance_m() or self.lasercan.last_known_distance_m()
        if laser is not None and laser > 0.1:
            return laser
        pnp = SmartDashboard.getNumber(_NT_TARGET_RANGE_M, 0.0)
        if pnp > 0.1:
            return pnp
        return None
