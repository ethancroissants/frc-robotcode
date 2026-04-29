"""USB webcam aiming sight with projected trajectory.

Streams the operator camera with a physics-based trajectory arc and a landing
reticle overlaid on the frame. Math: simulate projectile from the shooter exit
(rps → m/s × cos/sin of the exit angle, no drag), then project each sampled
world point through a pinhole camera model (FOV → focal length, plus mounted
height and downward tilt) to get pixel coordinates.

Drawing is done in pure numpy — WPILib's 2026 PyPI mirror has no OpenCV wheel
for cp314 linux_roborio, so we can't rely on cv2 on the rio. cscore's putFrame
accepts the raw numpy BGR array directly. The numerical readouts (dial, rps,
predicted landing) live on SmartDashboard text widgets instead of overlaid
on the frame, since rendering text without cv2 would mean shipping a bitmap
font that we'd have to maintain ourselves.

Auto-calibration: when the driver presses "Calibrate Sight" in Elastic, we
read the currently-dialed shot distance and the *true* target distance the
driver entered, and solve for camera tilt in closed form. With camera height
known, that single (distance, pixel) pair determines the downward tilt.

Capture/processing runs in a daemon thread so it can't stall robotPeriodic.
"""

import math
import threading

import numpy as np
from cscore import CameraServer, VideoMode

import tunables

_FRAME_WIDTH = 640
_FRAME_HEIGHT = 480
_FRAME_FPS = 30

_FOOT_TO_M = 0.3048
_GRAVITY_MPS2 = 9.81

_ARC_SAMPLES = 40

_ARC_COLOR = np.array([0, 200, 255], dtype=np.uint8)  # amber (BGR)
_ARC_THICKNESS = 2
_TARGET_LINE_COLOR = np.array([0, 255, 0], dtype=np.uint8)  # green
_TARGET_LINE_THICKNESS = 2
_RETICLE_COLOR = np.array([0, 0, 255], dtype=np.uint8)  # red
_RETICLE_RADIUS = 12
_RETICLE_THICKNESS = 2


# ---------- pure-numpy drawing primitives ----------

def _draw_horizontal_line(frame: np.ndarray, y: int, color: np.ndarray, thickness: int) -> None:
    h = frame.shape[0]
    if not 0 <= y < h:
        return
    half = thickness // 2
    y0 = max(0, y - half)
    y1 = min(h, y + half + 1)
    frame[y0:y1, :] = color


def _draw_segment(
    frame: np.ndarray, p0: tuple[int, int], p1: tuple[int, int], color: np.ndarray, thickness: int
) -> None:
    """Bresenham-ish line via linspace; thickens by stamping a small square at each sample."""
    h, w = frame.shape[:2]
    x0, y0 = p0
    x1, y1 = p1
    n = max(abs(x1 - x0), abs(y1 - y0)) + 1
    if n <= 1:
        return
    xs = np.linspace(x0, x1, n).round().astype(np.int32)
    ys = np.linspace(y0, y1, n).round().astype(np.int32)
    half = thickness // 2
    for dy in range(-half, half + 1):
        yy = np.clip(ys + dy, 0, h - 1)
        for dx in range(-half, half + 1):
            xx = np.clip(xs + dx, 0, w - 1)
            frame[yy, xx] = color


def _draw_polyline(
    frame: np.ndarray, points: list[tuple[int, int]], color: np.ndarray, thickness: int
) -> None:
    for i in range(len(points) - 1):
        _draw_segment(frame, points[i], points[i + 1], color, thickness)


def _draw_circle(
    frame: np.ndarray, center: tuple[int, int], radius: int, color: np.ndarray, thickness: int
) -> None:
    """Annulus mask: pixels whose distance from center falls within thickness of radius."""
    cx, cy = center
    h, w = frame.shape[:2]
    # Bound the work area to the circle's bounding box plus thickness slack.
    pad = radius + thickness
    x0, x1 = max(0, cx - pad), min(w, cx + pad + 1)
    y0, y1 = max(0, cy - pad), min(h, cy + pad + 1)
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.ogrid[y0:y1, x0:x1]
    dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
    inner = max(0, radius - thickness) ** 2
    outer = radius ** 2
    mask = (dist2 >= inner) & (dist2 <= outer)
    frame[y0:y1, x0:x1][mask] = color


# ---------- camera + projectile math ----------

def _focal_y_px(fov_deg: float) -> float:
    """Vertical focal length in pixels from horizontal FOV.

    Assumes square pixels, so focal_x == focal_y; computed from horizontal FOV
    and image width, which is the spec-sheet number for most webcams.
    """
    fov_rad = math.radians(fov_deg)
    return (_FRAME_WIDTH / 2.0) / math.tan(fov_rad / 2.0)


def _project_to_pixel(
    x_world_m: float, y_world_m: float, cam_height_m: float, tilt_rad: float, focal_y: float
) -> tuple[int, int] | None:
    """Project a side-view world point onto image pixels.

    x is downrange, y is height above the target plane; camera at (0, cam_height)
    looking forward and tilted downward by tilt_rad. Returns None if the point
    is at/behind the camera focal plane.
    """
    sin_phi, cos_phi = math.sin(tilt_rad), math.cos(tilt_rad)
    dy = cam_height_m - y_world_m
    z_forward = x_world_m * cos_phi + dy * sin_phi
    if z_forward <= 0.01:
        return None
    y_image_down = -x_world_m * sin_phi + dy * cos_phi
    px = _FRAME_WIDTH // 2
    py = int(_FRAME_HEIGHT / 2 + focal_y * y_image_down / z_forward)
    return px, py


def _simulate_trajectory(
    velocity_mps: float, exit_angle_rad: float, release_height_m: float
) -> tuple[list[tuple[float, float]], float]:
    """Sample (x, y) points along the projectile path and return landing distance."""
    vx = velocity_mps * math.cos(exit_angle_rad)
    vy = velocity_mps * math.sin(exit_angle_rad)
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
    """Closed-form: target on ground at known distance, observed at given pixel row → camera tilt.

    pixel_y - cy = focal_y · (h·cosφ - d·sinφ) / (d·cosφ + h·sinφ)
    Let r = (pixel_y - cy)/focal_y; rearrange to tan φ = (h - r·d) / (r·h + d).
    """
    d_m = distance_ft * _FOOT_TO_M
    r = (target_pixel_y - _FRAME_HEIGHT / 2.0) / focal_y
    return math.atan2(cam_height_m - r * d_m, r * cam_height_m + d_m)


# ---------- frame loop ----------

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

    traj, x_land_m = _simulate_trajectory(velocity, exit_angle, release_h)
    pts: list[tuple[int, int]] = []
    for x_m, y_m in traj:
        proj = _project_to_pixel(x_m, y_m, cam_h, tilt, focal_y)
        if proj is not None:
            pts.append(proj)
    if len(pts) >= 2:
        _draw_polyline(frame, pts, _ARC_COLOR, _ARC_THICKNESS)

    landing_proj = _project_to_pixel(x_land_m, 0.0, cam_h, tilt, focal_y)
    if landing_proj is not None:
        _draw_circle(frame, landing_proj, _RETICLE_RADIUS, _RETICLE_COLOR, _RETICLE_THICKNESS)
        # Crosshair tick across the reticle for visual centerline.
        _draw_segment(
            frame,
            (landing_proj[0] - _RETICLE_RADIUS, landing_proj[1]),
            (landing_proj[0] + _RETICLE_RADIUS, landing_proj[1]),
            _RETICLE_COLOR,
            1,
        )

    # Manual aim line at where the system thinks the dialed distance lies.
    dial_proj = _project_to_pixel(dial_ft * _FOOT_TO_M, 0.0, cam_h, tilt, focal_y)
    if dial_proj is not None:
        _draw_horizontal_line(frame, dial_proj[1], _TARGET_LINE_COLOR, _TARGET_LINE_THICKNESS)

    # Numerical readout to dashboard so Elastic can show it next to the camera.
    tunables.set_sight_predicted_landing_ft(x_land_m / _FOOT_TO_M)


def _maybe_calibrate() -> None:
    """One-press calibration: pin the line's current pixel row to the declared true distance.

    Driver enters real target distance in "Calibrate Sight True Distance (ft)",
    ramps the dial until the green line covers the visible target, presses the
    button. The line's current row is where the target actually is — pair with
    the true distance and solve for camera tilt.
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
