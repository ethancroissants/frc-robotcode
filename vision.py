"""USB operator-camera HUD: ball-prediction overlay + on-screen UI.

Pipeline: USB → cscore decodes MJPEG to BGR → numpy overlay → cscore re-encodes
MJPEG → dashboard. We re-JPEG once on the way out, so the output MjpegServer's
compression is pinned to a quality that fits the FRC field bandwidth cap (~4
Mbps) — without an explicit setting the dashboard will silently throttle to a
crawl, which is what made the old stream look like 1 fps and pixelated.

Drawing is pure numpy. WPILib's 2026 PyPI mirror has no cv2 wheel for
cp314 linux_roborio, and Pillow isn't in our requires either, so text is
rendered from a 5x7 bitmap font baked into this file (only the glyphs we
actually draw — digits, the letters that show up in the HUD strings, and a
handful of punctuation).

HUD elements (drawn each frame):
- Top header bar: dialed shot distance, predicted landing distance, FPS.
- Trajectory arc + landing reticle, projected through a pinhole camera model
  from the live shooter velocity / exit-angle / camera-tilt tunables.
- Distance ladder: ground-plane ticks at 5/10/15/20/25 ft so the driver can
  eyeball where the dial is pointing without trusting the math alone.
- Green dial line at the dialed distance — the manual-aim reference line that
  the auto-calibrate button locks to.
- Bottom-right gamepad mirror: D-pad cross + LB/RB/A/B/X/Y, lit live from the
  operator stick so the head ref / driver coach can see what's being pressed
  without having to peek at the operator station.

Auto-calibration: when the driver toggles "Calibrate Sight" in Elastic, we
read the currently-dialed shot distance and the *true* target distance the
driver entered, and solve for camera tilt in closed form. Camera height is
known, so a single (distance, pixel) pair determines the downward tilt.

Capture/processing runs in a daemon thread so it can't stall robotPeriodic.
"""

import math
import threading
import time

import numpy as np
from cscore import CameraServer, VideoMode
from wpilib import XboxController

import gamepads
import tunables


# ===== Stream config =====
_FRAME_WIDTH = 1280
_FRAME_HEIGHT = 720
_FRAME_FPS = 20
# 0..100 JPEG quality. ~30 keeps a 720p stream comfortably under the FRC
# field's 4 Mbps cap while still being legible — at -1 (default) cscore lets
# the dashboard request whatever it wants and the field arbitrarily throttles.
_JPEG_QUALITY = 30

_FOOT_TO_M = 0.3048
_GRAVITY_MPS2 = 9.81

_ARC_SAMPLES = 60
_LADDER_TICKS_FT = (5, 10, 15, 20, 25)


# ===== Colors (BGR) =====
_BLACK = np.array([0, 0, 0], dtype=np.uint8)
_WHITE = np.array([240, 240, 240], dtype=np.uint8)
_DIM = np.array([170, 170, 170], dtype=np.uint8)
_HUD_BG = np.array([18, 18, 22], dtype=np.uint8)
_HUD_BORDER = np.array([60, 60, 70], dtype=np.uint8)
_ACCENT = np.array([255, 200, 0], dtype=np.uint8)        # cyan-ish
_ARC_COLOR = np.array([0, 200, 255], dtype=np.uint8)     # amber arc
_RETICLE_COLOR = np.array([0, 0, 255], dtype=np.uint8)   # red reticle
_DIAL_COLOR = np.array([60, 230, 60], dtype=np.uint8)    # green dial line
_LADDER_COLOR = np.array([220, 220, 220], dtype=np.uint8)
_BTN_OFF = np.array([45, 45, 50], dtype=np.uint8)
_BTN_ON = np.array([0, 220, 255], dtype=np.uint8)
_BTN_BORDER = np.array([110, 110, 120], dtype=np.uint8)
_BTN_LABEL = np.array([240, 240, 240], dtype=np.uint8)


# ===== 5x7 bitmap font =====
# Only the glyphs that appear in HUD strings; '#' = on, '.' = off.
# Add to this table when you introduce a new label.
_FONT_5X7: dict[str, list[str]] = {
    " ": [".....", ".....", ".....", ".....", ".....", ".....", "....."],
    "0": [".###.", "#..##", "#.#.#", "##..#", "#...#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": [".###.", "#...#", "....#", ".###.", "....#", "#...#", ".###."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": [".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."],
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".####", "#....", "#....", "#....", "#....", "#....", ".####"],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".####", "#....", "#....", "#..##", "#...#", "#...#", ".####"],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": [".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "##..#", "#.#.#", "#.#.#", "#.#.#", "#..##", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    ".": [".....", ".....", ".....", ".....", ".....", ".....", "..#.."],
    ":": [".....", "..#..", "..#..", ".....", "..#..", "..#..", "....."],
    "-": [".....", ".....", ".....", ".###.", ".....", ".....", "....."],
    "/": ["....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."],
}

_GLYPH_W, _GLYPH_H = 5, 7
_GLYPH_KERN = 1


def _build_glyph_table() -> tuple[dict[str, np.ndarray], np.ndarray]:
    """Pre-bake glyphs into bool arrays so render is just a slice copy."""
    table: dict[str, np.ndarray] = {}
    for ch, rows in _FONT_5X7.items():
        arr = np.zeros((_GLYPH_H, _GLYPH_W), dtype=bool)
        for r, row in enumerate(rows):
            for c, px in enumerate(row):
                arr[r, c] = px == "#"
        table[ch] = arr
    fallback = np.zeros((_GLYPH_H, _GLYPH_W), dtype=bool)
    fallback[1:-1, 1:-1] = True  # solid block for missing chars
    return table, fallback


_GLYPHS, _GLYPH_FALLBACK = _build_glyph_table()


def _measure_text(text: str, scale: int) -> tuple[int, int]:
    n = len(text)
    if n == 0:
        return 0, 0
    width = n * _GLYPH_W * scale + max(0, n - 1) * _GLYPH_KERN * scale
    height = _GLYPH_H * scale
    return width, height


def _draw_text(
    frame: np.ndarray,
    text: str,
    x: int,
    y: int,
    color: np.ndarray,
    scale: int = 2,
) -> None:
    """Stamp `text` at top-left (x, y) using the embedded 5x7 font."""
    h, w = frame.shape[:2]
    cell_w = _GLYPH_W * scale
    cell_h = _GLYPH_H * scale
    cx = x
    for ch in text.upper():
        glyph = _GLYPHS.get(ch, _GLYPH_FALLBACK)
        # Skip work entirely if glyph is offscreen.
        if cx + cell_w > 0 and cx < w and y + cell_h > 0 and y < h:
            # Block-pixel scale via kron, then mask into frame.
            mask = np.kron(glyph, np.ones((scale, scale), dtype=bool))
            mh, mw = mask.shape
            x0 = max(cx, 0)
            y0 = max(y, 0)
            x1 = min(cx + mw, w)
            y1 = min(y + mh, h)
            sub = mask[y0 - y : y1 - y, x0 - cx : x1 - cx]
            if sub.size:
                frame[y0:y1, x0:x1][sub] = color
        cx += cell_w + _GLYPH_KERN * scale


# ===== drawing primitives =====

def _fill_rect(
    frame: np.ndarray, x: int, y: int, w: int, h: int, color: np.ndarray
) -> None:
    fh, fw = frame.shape[:2]
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(fw, x + w)
    y1 = min(fh, y + h)
    if x0 < x1 and y0 < y1:
        frame[y0:y1, x0:x1] = color


def _stroke_rect(
    frame: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    color: np.ndarray,
    thickness: int = 1,
) -> None:
    _fill_rect(frame, x, y, w, thickness, color)
    _fill_rect(frame, x, y + h - thickness, w, thickness, color)
    _fill_rect(frame, x, y, thickness, h, color)
    _fill_rect(frame, x + w - thickness, y, thickness, h, color)


def _draw_segment(
    frame: np.ndarray,
    p0: tuple[int, int],
    p1: tuple[int, int],
    color: np.ndarray,
    thickness: int,
) -> None:
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
    frame: np.ndarray,
    points: list[tuple[int, int]],
    color: np.ndarray,
    thickness: int,
) -> None:
    for i in range(len(points) - 1):
        _draw_segment(frame, points[i], points[i + 1], color, thickness)


def _draw_circle(
    frame: np.ndarray,
    center: tuple[int, int],
    radius: int,
    color: np.ndarray,
    thickness: int,
) -> None:
    """Annulus mask — thickness is the stroke width, not a fill."""
    cx, cy = center
    h, w = frame.shape[:2]
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


def _draw_horizontal_line(
    frame: np.ndarray, y: int, color: np.ndarray, thickness: int,
    x_start: int = 0, x_end: int | None = None,
) -> None:
    h, w = frame.shape[:2]
    if not 0 <= y < h:
        return
    half = thickness // 2
    y0 = max(0, y - half)
    y1 = min(h, y + half + 1)
    x0 = max(0, x_start)
    x1 = w if x_end is None else min(w, x_end)
    if x0 < x1:
        frame[y0:y1, x0:x1] = color


# ===== camera + projectile math =====

def _focal_y_px(fov_deg: float) -> float:
    fov_rad = math.radians(fov_deg)
    return (_FRAME_WIDTH / 2.0) / math.tan(fov_rad / 2.0)


def _project_to_pixel(
    x_world_m: float,
    y_world_m: float,
    cam_height_m: float,
    tilt_rad: float,
    focal_y: float,
) -> tuple[int, int] | None:
    """Side-view pinhole projection: (downrange, height) → pixel."""
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
    vx = velocity_mps * math.cos(exit_angle_rad)
    vy = velocity_mps * math.sin(exit_angle_rad)
    discriminant = vy * vy + 2.0 * _GRAVITY_MPS2 * release_height_m
    t_land = (vy + math.sqrt(discriminant)) / _GRAVITY_MPS2
    points: list[tuple[float, float]] = []
    for i in range(_ARC_SAMPLES + 1):
        t = t_land * i / _ARC_SAMPLES
        x = vx * t
        y = release_height_m + vy * t - 0.5 * _GRAVITY_MPS2 * t * t
        points.append((x, y))
    return points, vx * t_land


def _solve_camera_tilt(
    distance_ft: float, target_pixel_y: int, cam_height_m: float, focal_y: float
) -> float:
    d_m = distance_ft * _FOOT_TO_M
    r = (target_pixel_y - _FRAME_HEIGHT / 2.0) / focal_y
    return math.atan2(cam_height_m - r * d_m, r * cam_height_m + d_m)


# ===== HUD pieces =====

def _draw_distance_ladder(
    frame: np.ndarray, cam_h: float, tilt: float, focal_y: float
) -> None:
    """Short horizontal ticks across the ground plane, labeled in feet.

    Gives the driver an at-a-glance reality check on the projection: if 10
    ft on the ground doesn't fall where the dial says 10 ft, the camera
    parameters need recalibration.
    """
    for ft in _LADDER_TICKS_FT:
        proj = _project_to_pixel(ft * _FOOT_TO_M, 0.0, cam_h, tilt, focal_y)
        if proj is None:
            continue
        cx, cy = proj
        # Tick width shrinks with distance to feel like depth.
        tick_w = max(20, int(120 * 5.0 / max(5.0, ft)))
        _draw_segment(
            frame,
            (cx - tick_w // 2, cy),
            (cx + tick_w // 2, cy),
            _LADDER_COLOR,
            2,
        )
        label = f"{ft}FT"
        tw, th = _measure_text(label, scale=1)
        _draw_text(frame, label, cx - tw // 2, cy - th - 4, _LADDER_COLOR, scale=1)


def _draw_arc_and_reticle(
    frame: np.ndarray,
    cam_h: float,
    tilt: float,
    focal_y: float,
    velocity: float,
    exit_angle: float,
    release_h: float,
) -> float:
    """Returns predicted landing distance (m) for the dashboard readout."""
    traj, x_land_m = _simulate_trajectory(velocity, exit_angle, release_h)
    pts: list[tuple[int, int]] = []
    for x_m, y_m in traj:
        proj = _project_to_pixel(x_m, y_m, cam_h, tilt, focal_y)
        if proj is not None:
            pts.append(proj)
    if len(pts) >= 2:
        # Draw shadow underneath for readability against bright backgrounds.
        _draw_polyline(frame, pts, _BLACK, 5)
        _draw_polyline(frame, pts, _ARC_COLOR, 3)

    landing = _project_to_pixel(x_land_m, 0.0, cam_h, tilt, focal_y)
    if landing is not None:
        cx, cy = landing
        # Crosshair reticle: outer ring + inner cross + small center dot.
        _draw_circle(frame, landing, 18, _BLACK, 4)
        _draw_circle(frame, landing, 18, _RETICLE_COLOR, 2)
        _draw_segment(frame, (cx - 24, cy), (cx - 8, cy), _RETICLE_COLOR, 2)
        _draw_segment(frame, (cx + 8, cy), (cx + 24, cy), _RETICLE_COLOR, 2)
        _draw_segment(frame, (cx, cy - 24), (cx, cy - 8), _RETICLE_COLOR, 2)
        _draw_segment(frame, (cx, cy + 8), (cx, cy + 24), _RETICLE_COLOR, 2)
        _fill_rect(frame, cx - 1, cy - 1, 3, 3, _RETICLE_COLOR)
    return x_land_m


def _draw_dial_line(
    frame: np.ndarray, cam_h: float, tilt: float, focal_y: float, dial_ft: float
) -> None:
    proj = _project_to_pixel(dial_ft * _FOOT_TO_M, 0.0, cam_h, tilt, focal_y)
    if proj is None:
        return
    _, py = proj
    _draw_horizontal_line(frame, py, _BLACK, 5)
    _draw_horizontal_line(frame, py, _DIAL_COLOR, 3)
    label = f"DIAL {dial_ft:.1f}FT".replace(".", ".")
    _draw_text(frame, label, 12, py - 22, _DIAL_COLOR, scale=2)


def _draw_top_hud(
    frame: np.ndarray,
    dial_ft: float,
    predicted_ft: float,
    rps: float,
    fps: float,
) -> None:
    bar_h = 56
    _fill_rect(frame, 0, 0, _FRAME_WIDTH, bar_h, _HUD_BG)
    _fill_rect(frame, 0, bar_h, _FRAME_WIDTH, 2, _HUD_BORDER)

    title = "SHOOTER SIGHT"
    _draw_text(frame, title, 16, 14, _ACCENT, scale=3)

    # Right-aligned cluster of three readouts.
    items = [
        (f"DIAL {dial_ft:5.1f} FT", _DIAL_COLOR),
        (f"PRED {predicted_ft:5.1f} FT", _ARC_COLOR),
        (f"RPS {rps:5.1f}", _WHITE),
        (f"FPS {fps:4.1f}", _DIM),
    ]
    pad = 24
    x = _FRAME_WIDTH - 16
    for text, color in reversed(items):
        tw, th = _measure_text(text, scale=2)
        x -= tw
        _draw_text(frame, text, x, (bar_h - th) // 2, color, scale=2)
        x -= pad


# ===== gamepad-mirror panel =====

# Map our intent to an XboxController-on-Joystick raw button index. WPILib's
# XboxController.Button.kA is 1-based and matches the Joystick button raw IDs
# used by the underlying HAL, so we can just read .getRawButton(int) on the
# operatorJoyStick (which is what the bindings already do via JoystickButton).
_XB = XboxController.Button
# .value isn't available — robotpy 2026 exposes these as plain ints already.
_BUTTON_LAYOUT: list[tuple[str, int]] = [
    ("LB", int(_XB.kLeftBumper)),
    ("RB", int(_XB.kRightBumper)),
    ("A", int(_XB.kA)),
    ("B", int(_XB.kB)),
    ("X", int(_XB.kX)),
    ("Y", int(_XB.kY)),
]


def _read_operator_state() -> tuple[int, dict[str, bool]]:
    """POV (degrees, -1 if released) plus pressed-state for the labeled buttons.

    Reads happen on the capture thread; WPILib's HAL Joystick reads are
    thread-safe.
    """
    js = gamepads.operatorJoyStick
    pov = js.getPOV()
    pressed: dict[str, bool] = {}
    for label, idx in _BUTTON_LAYOUT:
        try:
            pressed[label] = js.getRawButton(idx)
        except Exception:
            # Joystick disconnected — treat everything as released. The DS
            # warning is silenced upstream so this doesn't spam.
            pressed[label] = False
    return pov, pressed


def _pov_active(pov_deg: int, want: str) -> bool:
    """`want` is one of N/NE/E/SE/S/SW/W/NW; True if POV is in that direction."""
    if pov_deg < 0:
        return False
    target = {"N": 0, "NE": 45, "E": 90, "SE": 135,
              "S": 180, "SW": 225, "W": 270, "NW": 315}[want]
    return pov_deg == target


def _draw_gamepad_panel(frame: np.ndarray) -> None:
    """Bottom-right cluster: D-pad cross + LB/RB + ABXY badges."""
    pov, pressed = _read_operator_state()

    panel_w = 280
    panel_h = 200
    panel_x = _FRAME_WIDTH - panel_w - 16
    panel_y = _FRAME_HEIGHT - panel_h - 16

    _fill_rect(frame, panel_x, panel_y, panel_w, panel_h, _HUD_BG)
    _stroke_rect(frame, panel_x, panel_y, panel_w, panel_h, _HUD_BORDER, 2)

    _draw_text(frame, "OPERATOR", panel_x + 12, panel_y + 10, _ACCENT, scale=2)

    # ----- D-pad (3x3) on the left half -----
    cell = 36
    dpad_x = panel_x + 18
    dpad_y = panel_y + 50
    grid = [
        ("NW", "N", "NE"),
        ("W", "C", "E"),
        ("SW", "S", "SE"),
    ]
    for r, row in enumerate(grid):
        for c, name in enumerate(row):
            x = dpad_x + c * (cell + 4)
            y = dpad_y + r * (cell + 4)
            if name == "C":
                # Center: solid dim square, no labels — just a visual anchor.
                _fill_rect(frame, x, y, cell, cell, _BTN_OFF)
                continue
            on = _pov_active(pov, name)
            color = _BTN_ON if on else _BTN_OFF
            _fill_rect(frame, x, y, cell, cell, color)
            _stroke_rect(frame, x, y, cell, cell, _BTN_BORDER, 1)
            # Direction marker — a short bar pointing outward.
            cx = x + cell // 2
            cy = y + cell // 2
            mark_color = _BLACK if on else _BTN_LABEL
            if name == "N":
                _draw_segment(frame, (cx, cy + 6), (cx, cy - 8), mark_color, 3)
            elif name == "S":
                _draw_segment(frame, (cx, cy - 6), (cx, cy + 8), mark_color, 3)
            elif name == "W":
                _draw_segment(frame, (cx + 6, cy), (cx - 8, cy), mark_color, 3)
            elif name == "E":
                _draw_segment(frame, (cx - 6, cy), (cx + 8, cy), mark_color, 3)
            else:
                # Diagonal: short slanted tick.
                if name == "NE":
                    _draw_segment(frame, (cx - 6, cy + 6), (cx + 6, cy - 6), mark_color, 3)
                elif name == "NW":
                    _draw_segment(frame, (cx + 6, cy + 6), (cx - 6, cy - 6), mark_color, 3)
                elif name == "SE":
                    _draw_segment(frame, (cx - 6, cy - 6), (cx + 6, cy + 6), mark_color, 3)
                elif name == "SW":
                    _draw_segment(frame, (cx + 6, cy - 6), (cx - 6, cy + 6), mark_color, 3)

    # ----- Bumper + face buttons on the right half -----
    badge_x = panel_x + 150
    badge_y = panel_y + 50

    # LB / RB across the top of this column.
    for i, label in enumerate(["LB", "RB"]):
        x = badge_x + i * 56
        y = badge_y
        on = pressed.get(label, False)
        color = _BTN_ON if on else _BTN_OFF
        _fill_rect(frame, x, y, 48, 24, color)
        _stroke_rect(frame, x, y, 48, 24, _BTN_BORDER, 1)
        tw, th = _measure_text(label, scale=2)
        _draw_text(
            frame,
            label,
            x + (48 - tw) // 2,
            y + (24 - th) // 2,
            _BLACK if on else _BTN_LABEL,
            scale=2,
        )

    # A/B/X/Y as a 2x2 grid of round-ish square badges.
    grid_x = badge_x
    grid_y = badge_y + 36
    badges = [("Y", 0, 0), ("X", 1, 0), ("B", 0, 1), ("A", 1, 1)]
    badge_size = 40
    spacing = 8
    for label, gx, gy in badges:
        x = grid_x + gx * (badge_size + spacing)
        y = grid_y + gy * (badge_size + spacing)
        on = pressed.get(label, False)
        color = _BTN_ON if on else _BTN_OFF
        _fill_rect(frame, x, y, badge_size, badge_size, color)
        _stroke_rect(frame, x, y, badge_size, badge_size, _BTN_BORDER, 1)
        tw, th = _measure_text(label, scale=3)
        _draw_text(
            frame,
            label,
            x + (badge_size - tw) // 2,
            y + (badge_size - th) // 2,
            _BLACK if on else _BTN_LABEL,
            scale=3,
        )


# ===== orchestrator =====

def _draw_overlay(frame: np.ndarray, fps: float) -> None:
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

    _draw_distance_ladder(frame, cam_h, tilt, focal_y)
    x_land_m = _draw_arc_and_reticle(
        frame, cam_h, tilt, focal_y, velocity, exit_angle, release_h
    )
    _draw_dial_line(frame, cam_h, tilt, focal_y, dial_ft)

    predicted_ft = x_land_m / _FOOT_TO_M
    _draw_top_hud(frame, dial_ft, predicted_ft, rps, fps)
    _draw_gamepad_panel(frame)

    tunables.set_sight_predicted_landing_ft(predicted_ft)


def _maybe_calibrate() -> None:
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
    # EWMA over frame interval — gives a stable HUD readout.
    fps_est = float(_FRAME_FPS)
    last_t = time.monotonic()
    alpha = 0.1
    while True:
        timestamp, frame = sink.grabFrame(frame)
        if timestamp == 0:
            source.notifyError(sink.getError())
            continue
        now = time.monotonic()
        dt = now - last_t
        last_t = now
        if dt > 1e-3:
            fps_est = (1 - alpha) * fps_est + alpha * (1.0 / dt)
        _maybe_calibrate()
        _draw_overlay(frame, fps_est)
        source.putFrame(frame)


def start() -> None:
    """Open USB camera 0 and start the overlay stream."""
    camera = CameraServer.startAutomaticCapture()
    camera.setResolution(_FRAME_WIDTH, _FRAME_HEIGHT)
    camera.setFPS(_FRAME_FPS)
    camera.setPixelFormat(VideoMode.PixelFormat.kMJPEG)

    sink = CameraServer.getVideo()
    source = CameraServer.putVideo("Shooter Sight", _FRAME_WIDTH, _FRAME_HEIGHT)

    # Pin output JPEG quality. Without this, the dashboard's "compression: 0"
    # request lets the field bandwidth limiter drop us to ~1 fps under load.
    try:
        out_server = CameraServer.getServer()
        out_server.setCompression(_JPEG_QUALITY)
        out_server.setDefaultCompression(_JPEG_QUALITY)
    except Exception:
        # Older cscore wheels don't expose getServer(); the stream still works,
        # just at whatever quality the dashboard requests.
        pass

    thread = threading.Thread(
        target=_capture_loop, args=(sink, source), name="shooter-sight", daemon=True
    )
    thread.start()
