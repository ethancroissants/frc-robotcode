"""USB webcam aiming sight with projected trajectory.

Streams the operator camera with a physics-based trajectory arc and a landing
reticle drawn on the frame. Math: simulate projectile from the shooter exit
(rps → m/s × cos/sin of the exit angle, no drag), then project each sampled
world point through a pinhole camera model (FOV → focal length, plus mounted
height and downward tilt) to get pixel coordinates.

Auto-calibration: when the driver presses "Calibrate Sight" in Elastic, we
read the currently-dialed shot distance and assume the visible target sits
where the manual aim line is (i.e. the driver has aligned the dial so the
line covers the target). With camera height known, that single (distance,
pixel) pair determines the camera's downward tilt angle in closed form.

Capture/processing runs in a daemon thread so it can't stall robotPeriodic.
"""

import math
import threading

import cv2
import numpy as np
from cscore import CameraServer, VideoMode

import tunables

_FRAME_WIDTH = 640
_FRAME_HEIGHT = 480
_FRAME_FPS = 30

_FOOT_TO_M = 0.3048
_GRAVITY_MPS2 = 9.81

# Trajectory sampling — enough points for a smooth-looking arc without melting CPU.
_ARC_SAMPLES = 40

_ARC_COLOR = (0, 200, 255)  # amber arc
_ARC_THICKNESS = 2
_TARGET_LINE_COLOR = (0, 255, 0)
_TARGET_LINE_THICKNESS = 2
_RETICLE_COLOR = (0, 0, 255)  # red landing reticle
_RETICLE_RADIUS = 12
_TEXT_COLOR = (0, 255, 0)


def _focal_y_px(fov_deg: float) -> float:
    """Vertical focal length in pixels from horizontal FOV.

    Assuming square pixels, focal_x = focal_y, so we compute from horizontal FOV
    and image width — which is the spec sheet number for most webcams.
    """
    fov_rad = math.radians(fov_deg)
    return (_FRAME_WIDTH / 2.0) / math.tan(fov_rad / 2.0)


def _project_to_pixel(
    x_world_m: float, y_world_m: float, cam_height_m: float, tilt_rad: float, focal_y: float
) -> tuple[int, int] | None:
    """Project a side-view world point onto image pixels.

    Side-view: x is downrange distance, y is height above the target plane (the
    plane where the ball lands — usually the floor). Camera sits at (0, cam_height)
    looking forward and tilted downward by tilt_rad. Returns None if the point
    is behind the camera.
    """
    sin_phi, cos_phi = math.sin(tilt_rad), math.cos(tilt_rad)
    dy = cam_height_m - y_world_m  # positive when point is below camera
    z_forward = x_world_m * cos_phi + dy * sin_phi
    if z_forward <= 0.01:
        return None
    y_image_down = -x_world_m * sin_phi + dy * cos_phi
    px = _FRAME_WIDTH // 2  # side-view: target is on optical axis horizontally
    py = int(_FRAME_HEIGHT / 2 + focal_y * y_image_down / z_forward)
    return px, py


def _simulate_trajectory(
    velocity_mps: float, exit_angle_rad: float, release_height_m: float
) -> tuple[list[tuple[float, float]], float]:
    """Sample (x, y) points along the projectile path and return landing distance.

    No drag — fine at the speeds and distances of an FRC shot. The path is
    sampled uniformly in time from launch to ground contact.
    """
    vx = velocity_mps * math.cos(exit_angle_rad)
    vy = velocity_mps * math.sin(exit_angle_rad)
    # Solve release_height + vy·t - ½g·t² = 0 for t > 0.
    discriminant = vy * vy + 2.0 * _GRAVITY_MPS2 * release_height_m
    t_land = (vy + math.sqrt(discriminant)) / _GRAVITY_MPS2
    points = []
    for i in range(_ARC_SAMPLES + 1):
        t = t_land * i / _ARC_SAMPLES
        x = vx * t
        y = release_height_m + vy * t - 0.5 * _GRAVITY_MPS2 * t * t
        points.append((x, y))
    x_land = vx * t_land
    return points, x_land


def _solve_camera_tilt(
    distance_ft: float, target_pixel_y: int, cam_height_m: float, focal_y: float
) -> float:
    """Closed-form solve: given a target on the ground at known distance and the
    pixel-row where it appears, return the camera's downward tilt angle (rad).

    Derivation: pixel_y - cy = focal_y · (h·cos φ - d·sin φ) / (d·cos φ + h·sin φ).
    Letting r = (pixel_y - cy)/focal_y and rearranging gives
    tan φ = (h - r·d) / (r·h + d). atan2 keeps the right quadrant.
    """
    d_m = distance_ft * _FOOT_TO_M
    r = (target_pixel_y - _FRAME_HEIGHT / 2.0) / focal_y
    return math.atan2(cam_height_m - r * d_m, r * cam_height_m + d_m)


def _draw_overlay(frame: np.ndarray) -> None:
    fov = tunables.sight_fov_deg()
    cam_h = tunables.sight_camera_height_m()
    tilt = tunables.sight_camera_tilt_rad()
    exit_angle = math.radians(tunables.sight_exit_angle_deg())
    release_h = tunables.sight_release_height_m()
    speed_per_rps = tunables.sight_speed_per_rps()

    rps = tunables.shooter_velocity_rps()
    dial_ft = tunables.shooter_distance_feet()
    velocity = max(0.1, rps * speed_per_rps)
    focal_y = _focal_y_px(fov)

    # Trajectory arc + landing reticle from physics.
    traj, x_land_m = _simulate_trajectory(velocity, exit_angle, release_h)
    pts = []
    for x_m, y_m in traj:
        proj = _project_to_pixel(x_m, y_m, cam_h, tilt, focal_y)
        if proj is not None:
            pts.append(proj)
    if len(pts) >= 2:
        cv2.polylines(
            frame, [np.array(pts, dtype=np.int32)], False, _ARC_COLOR, _ARC_THICKNESS
        )
    landing_proj = _project_to_pixel(x_land_m, 0.0, cam_h, tilt, focal_y)
    if landing_proj is not None:
        cv2.circle(frame, landing_proj, _RETICLE_RADIUS, _RETICLE_COLOR, 2)
        cv2.line(
            frame,
            (landing_proj[0] - _RETICLE_RADIUS, landing_proj[1]),
            (landing_proj[0] + _RETICLE_RADIUS, landing_proj[1]),
            _RETICLE_COLOR,
            1,
        )

    # Manual aim line: where the system thinks the target is at the dialed distance.
    # When the driver lines this up with the visible target, the dial matches reality.
    dial_proj = _project_to_pixel(dial_ft * _FOOT_TO_M, 0.0, cam_h, tilt, focal_y)
    if dial_proj is not None:
        y = dial_proj[1]
        if 0 <= y < _FRAME_HEIGHT:
            cv2.line(frame, (0, y), (_FRAME_WIDTH, y), _TARGET_LINE_COLOR, _TARGET_LINE_THICKNESS)

    cv2.putText(
        frame,
        f"dial {dial_ft:.1f}ft  rps {rps:.0f}  predict {x_land_m / _FOOT_TO_M:.1f}ft",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        _TEXT_COLOR,
        2,
    )


def _maybe_calibrate() -> None:
    """One-press calibration: pin the line's current pixel row to the declared true distance.

    Workflow: driver enters the *real* target distance in "Calibrate Sight True
    Distance (ft)", then ramps the dial until the green aim line sits on the
    visible target, then presses Calibrate Sight. The line's current row is
    where the target *actually* is in the image — pair that with the true
    distance and solve for camera tilt.
    """
    if not tunables.sight_calibrate_requested():
        return
    fov = tunables.sight_fov_deg()
    cam_h = tunables.sight_camera_height_m()
    focal_y = _focal_y_px(fov)
    dial_ft = tunables.shooter_distance_feet()
    true_ft = tunables.sight_calibrate_true_distance_ft()
    if dial_ft < 0.5 or true_ft < 0.5:
        tunables.clear_sight_calibrate_request()
        return
    prev_tilt = tunables.sight_camera_tilt_rad()
    line_proj = _project_to_pixel(dial_ft * _FOOT_TO_M, 0.0, cam_h, prev_tilt, focal_y)
    if line_proj is None:
        tunables.clear_sight_calibrate_request()
        return
    new_tilt = _solve_camera_tilt(true_ft, line_proj[1], cam_h, focal_y)
    tunables.set_sight_camera_tilt_rad(new_tilt)
    tunables.clear_sight_calibrate_request()


def _capture_loop(sink, source) -> None:
    frame = np.zeros((_FRAME_HEIGHT, _FRAME_WIDTH, 3), dtype=np.uint8)
    while True:
        timestamp, frame = sink.grabFrame(frame)
        if timestamp == 0:
            source.notifyError(sink.getError())
            continue
        _maybe_calibrate()
        _draw_overlay(frame)
        source.putFrame(frame)


def start() -> None:
    """Open USB camera 0 and start the overlay stream."""
    camera = CameraServer.startAutomaticCapture()
    camera.setResolution(_FRAME_WIDTH, _FRAME_HEIGHT)
    camera.setFPS(_FRAME_FPS)
    camera.setPixelFormat(VideoMode.PixelFormat.kMJPEG)

    sink = CameraServer.getVideo()
    source = CameraServer.putVideo("Shooter Sight", _FRAME_WIDTH, _FRAME_HEIGHT)

    thread = threading.Thread(
        target=_capture_loop, args=(sink, source), name="shooter-sight", daemon=True
    )
    thread.start()
