"""AutoAim: Pi click → rio rotates + dials in shot distance + fires.

Pi publishes the target as a normalized image-frame click on
/SmartDashboard/Sight/Aim/{PixelX,PixelY,RequestId,Requested}. We treat the
request id as a fresh-shot trigger: every time it increments, we re-arm.

Math:
  - x_norm in [0, 1] is left-to-right across the image. Center is 0.5.
  - Translate to a yaw offset using the camera's horizontal FOV:
      yaw_off_rad = (x_norm - 0.5) * fov_rad
    The camera is fixed to the robot, so target_heading = current_heading +
    yaw_off (assuming "forward" of the camera matches "forward" of the bot;
    if you mount sideways, add the offset in tunables).
  - For range, prefer the LaserCAN measurement (it points down-bore of the
    camera). If the laser is invalid, fall back to projecting y_norm onto
    the ground plane through the existing pinhole tunables — the same math
    `vision.py` uses, just inverted.

Drive: PID on heading error using the swerve drivetrain's setpoint API.
Once heading is within tolerance and shooter has spun up, hand off to the
existing AutoFire by calling shooterOut/FIRE on the operator subsystem.

Status is published back to /Sight/Aim/Status as one of:
  idle | rotating | spinning_up | firing | done | error
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


_NT_REQ_ID = "Sight/Aim/RequestId"
_NT_REQUESTED = "Sight/Aim/Requested"
_NT_X = "Sight/Aim/PixelX"
_NT_Y = "Sight/Aim/PixelY"
_NT_STATUS = "Sight/Aim/Status"

# Heading-loop gains. Conservative defaults — tune after first practice.
_HEADING_KP = 4.0  # rad/s per rad of error
_HEADING_KI = 0.0
_HEADING_KD = 0.2
_HEADING_TOLERANCE_RAD = math.radians(2.0)  # within 2° = "on target"

# Once heading is locked, give the flywheel this long to settle before firing.
_SETTLE_S = 0.25
# Hard timeout for the whole sequence, in case something goes wrong.
_OVERALL_TIMEOUT_S = 6.0

_FOOT_TO_M = 0.3048


def _publish_status(s: str) -> None:
    SmartDashboard.putString(_NT_STATUS, s)


class AutoAim(Command):
    """Listens for Pi aim requests; rotates + sets dial + fires."""

    def __init__(self, drivetrain, operator: OperatorSubsystem, lasercan: LaserCanSubsystem):
        super().__init__()
        self.drivetrain = drivetrain
        self.operator = operator
        self.lasercan = lasercan
        self.addRequirements(operator, drivetrain)

        # Heading control happens via a swerve FieldCentric request that we
        # rebuild each tick. The drivetrain's existing default command runs
        # joystick drive, which we override while AutoAim is scheduled.
        self._req = (
            swerve_requests.FieldCentric()
            .with_drive_request_type(SwerveModule.DriveRequestType.OPEN_LOOP_VOLTAGE)
        )

        self._heading_pid = PIDController(_HEADING_KP, _HEADING_KI, _HEADING_KD)
        self._heading_pid.enableContinuousInput(-math.pi, math.pi)
        self._heading_pid.setTolerance(_HEADING_TOLERANCE_RAD)

        self._timer = Timer()
        self._settle_timer = Timer()
        self._target_heading: float | None = None
        self._target_distance_m: float | None = None
        self._phase = "idle"
        self._last_seen_request_id: int = 0

    # ----- lifecycle -----

    def initialize(self) -> None:
        rid = int(SmartDashboard.getNumber(_NT_REQ_ID, 0))
        if rid <= self._last_seen_request_id or not SmartDashboard.getBoolean(_NT_REQUESTED, False):
            # Nothing new — finish immediately so the scheduler stops nagging.
            self._phase = "idle"
            _publish_status("idle")
            return
        self._last_seen_request_id = rid

        x_norm = SmartDashboard.getNumber(_NT_X, 0.5)
        y_norm = SmartDashboard.getNumber(_NT_Y, 0.5)
        self._timer.reset(); self._timer.start()

        try:
            self._target_heading = self._compute_target_heading(x_norm)
            self._target_distance_m = self._compute_target_distance_m(y_norm)
        except Exception as e:
            print(f"AutoAim init failed: {e}")
            _publish_status("error")
            self._phase = "error"
            return

        # Push the dialed distance straight to the SmartDashboard tunable so
        # the existing shooter-distance → rps mapping picks it up. The driver
        # can still see and override it via the slider.
        if self._target_distance_m is not None:
            tunables.set_shooter_distance_feet(self._target_distance_m / _FOOT_TO_M)

        self._phase = "rotating"
        _publish_status("rotating")
        self._heading_pid.reset()

    def execute(self) -> None:
        if self._phase in ("idle", "error", "done"):
            return

        if self._phase == "rotating":
            self._rotate_step()
            if self._heading_pid.atSetpoint():
                # Begin spin-up; keep holding heading.
                self._phase = "spinning_up"
                self._settle_timer.reset(); self._settle_timer.start()
                _publish_status("spinning_up")

        if self._phase == "spinning_up":
            self._rotate_step()                    # keep holding heading
            self.operator.shooterOut()             # flywheel only, no feed
            if self._settle_timer.get() >= _SETTLE_S:
                self._phase = "firing"
                _publish_status("firing")

        if self._phase == "firing":
            self._rotate_step()
            # Run the full FIRE sequence (kicker + conveyor + flywheel),
            # matching what AutoFire does in its post-spin-up phase.
            self.operator.FIRE()
            if self._timer.get() >= tunables.shooter_spin_up_seconds() + tunables.auto_fire_duration():
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
        SmartDashboard.putBoolean(_NT_REQUESTED, False)
        if self._phase != "done":
            _publish_status("idle" if not interrupted else "error")
        # Stop driving — drivetrain's default command resumes joystick drive.

    # ----- math -----

    def _rotate_step(self) -> None:
        """Drive the swerve toward `_target_heading` with a heading PID."""
        if self._target_heading is None:
            return
        cur = self._current_heading_rad()
        omega = self._heading_pid.calculate(cur, self._target_heading)
        req = (
            self._req
            .with_velocity_x(0.0)
            .with_velocity_y(0.0)
            .with_rotational_rate(omega)
        )
        # CTRE's swerve drivetrain exposes set_control(request) directly; the
        # subsystem's applyRequest() helper just wraps that in a runnable.
        self.drivetrain.set_control(req)

    def _current_heading_rad(self) -> float:
        """Robot pose heading in radians, normalized [-pi, pi]."""
        try:
            pose = self.drivetrain.get_state().pose
            return pose.rotation().radians()
        except Exception:
            try:
                return self.drivetrain.getRotation3d().z
            except Exception:
                return 0.0

    def _compute_target_heading(self, x_norm: float) -> float:
        """Map normalized x click to absolute target heading.

        Camera FOV is in tunables; (x_norm - 0.5) * FOV is the angular offset
        of the click from camera center. Camera and robot share heading.
        """
        fov_rad = math.radians(tunables.sight_fov_deg())
        yaw_off = (x_norm - 0.5) * fov_rad
        return self._current_heading_rad() + yaw_off

    def _compute_target_distance_m(self, y_norm: float) -> float | None:
        """Prefer LaserCAN; fall back to projecting y_norm onto ground plane."""
        laser = self.lasercan.distance_m() or self.lasercan.last_known_distance_m()
        if laser is not None and laser > 0.1:
            return laser
        # Inverse pinhole on the ground plane: solve for downrange given pixel.
        cam_h = tunables.sight_camera_height_m()
        tilt = tunables.sight_camera_tilt_rad()
        fov = math.radians(tunables.sight_fov_deg())
        # Normalize y to "pixels from optical center" using the 4:3 frame
        # assumption baked into the pi camera. The pi sends y_norm in [0, 1];
        # any aspect ratio works because we pre-divide by image height.
        # focal_y in same units as h_image: focal/(0.5 * H) = 1/tan(fov/2).
        if y_norm <= 0.5:
            return None  # click was above horizon — can't compute ground hit
        r = math.tan((y_norm - 0.5) * fov)
        # Same closed form as vision._project_to_pixel inverted:
        #   tan(angle below horizon) = (h - r·d_horizon) / (...)
        # Easier path: ray pitch = tilt + (y_norm-0.5)*fov, intersect with y=0.
        ray_pitch = tilt + (y_norm - 0.5) * fov
        if ray_pitch <= 1e-3:
            return None
        return cam_h / math.tan(ray_pitch)
