"""Cold Fusion Sight — Orange Pi web server.

What the Pi does (and why it's on a Pi rather than the rio)
-----------------------------------------------------------
The rio's Cortex-A9 cannot decode + JPEG-encode + run an AprilTag detector
at 30 fps without blowing the 20 ms loop budget. The Pi 5 has eight A76
cores and idles at <30% load doing all of it. So the Pi owns the entire
vision pipeline; the rio just consumes results over NetworkTables.

End-to-end flow
---------------
1. cv2.VideoCapture grabs MJPEG straight off /dev/video0 (hardware-decoded
   to BGR by libv4l2). One frame, one numpy array, no ffmpeg.
2. cv2.aruco's ArucoDetector runs the AprilTag 36h11 detector on a
   downscaled grey copy of every frame. ~10–20 ms on a Pi 5.
3. We pick the largest tag whose ID is in TARGET_TAG_IDS as the goal.
4. From the tag's pixel location + image size we compute:
     bearing_deg — signed angle of the tag from camera optical axis
                   (negative = left of center, positive = right)
     range_m    — distance from PnP (assumes a known tag side length)
   The LaserCAN range is more accurate (active sensor, not derived from a
   geometry estimate), so the rio prefers LaserCAN; the Pi-PnP range is a
   fallback only.
5. We publish target state continuously to NetworkTables under
   /Sight/Target/*. The rio's AutoAim command reads these every cycle.
6. The browser SHOOT button POSTs /api/shoot, which bumps
   /Sight/Shoot/RequestId. The rio's button-press trigger watches that id
   and schedules AutoAim, which:
     - sets /Sight/DriverLockout=true
     - reads bearing & range each cycle, drives a heading PID off bearing
     - dials shooter RPS from the Pi's calibration lookup
     - fires
     - sets /Sight/DriverLockout=false on end
7. The Pi also serves a calibration-table editor at /api/calibration.
   Operators add (distance, rps) pairs from real shots; the table is
   linearly interpolated and the resulting target RPS is published
   continuously as /Sight/Aim/TargetRps.

The browser stream is the *same* numpy frames after we draw an overlay
(target box, crosshair, range readout) and re-encode to JPEG. Slightly
more CPU than the old ffmpeg passthrough, but worth it for the live
target visualization.

Run with: uvicorn server:app --host 0.0.0.0 --port 8080
The systemd unit calls exactly that.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import AsyncIterator

import cv2
import nt4_client
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles


# ===== Config (env-overridable) =====
TEAM = int(os.environ.get("TEAM", "1279"))
NT_SERVER = os.environ.get("NT_SERVER", "")
CAMERA_DEVICE = os.environ.get("CAMERA_DEVICE", "/dev/video0")
CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "720"))
CAMERA_FPS = int(os.environ.get("CAMERA_FPS", "30"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))

# Camera geometry. Used by the AprilTag PnP fallback to convert a tag's
# pixel size to a metric range. Override via env if your camera has a
# different field-of-view or you've solved a calibrated camera matrix.
CAMERA_HFOV_DEG = float(os.environ.get("CAMERA_HFOV_DEG", "60.0"))
TAG_SIZE_M = float(os.environ.get("TAG_SIZE_M", "0.1651"))  # 6.5"
# JPEG encode quality for the browser stream. 75 is a good speed/quality
# tradeoff on the Pi 5; drop to 60 if CPU pegs.
STREAM_QUALITY = int(os.environ.get("STREAM_QUALITY", "75"))
# Run the detector on every Nth captured frame. 1 = every frame.
DETECT_EVERY = int(os.environ.get("DETECT_EVERY", "1"))
# Downscale factor used only for detection (stream stays full res). Smaller
# = faster detection at the cost of some accuracy on small/distant tags.
DETECT_DOWNSCALE = float(os.environ.get("DETECT_DOWNSCALE", "0.5"))
# Comma-separated list of tag IDs that count as "the goal". Override per
# game/season. Default targets the 2024 Crescendo speaker tags so the
# system is functional out of the box on a typical FRC field.
TARGET_TAG_IDS = {
    int(s.strip())
    for s in os.environ.get("TARGET_TAG_IDS", "3,4,7,8").split(",")
    if s.strip()
}

REPO = Path(__file__).resolve().parent
STATIC_DIR = REPO / "static"
CALIBRATION_PATH = REPO / "sight_calibration.json"

# Default calibration if nothing on disk yet. Keep the floor at 0/0 so
# interpolation is well-defined at any distance >= 0; clamp at the top.
DEFAULT_CALIBRATION = [
    {"distance_ft": 0.0, "rps": 0.0},
    {"distance_ft": 4.0, "rps": 40.0},
    {"distance_ft": 8.0, "rps": 80.0},
    {"distance_ft": 12.0, "rps": 100.0},
    {"distance_ft": 16.0, "rps": 110.0},
]
_FOOT_TO_M = 0.3048

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sight")


# ===== Calibration table =====

class Calibration:
    """Persisted (distance_ft → rps) table with linear interpolation.

    Edits go through replace(); we always write the whole table so it stays
    sorted and validated. Lookups are clamped to the table's range to avoid
    extrapolating into nonsense (sending RPS=300 for a tag that's actually
    a meter away because the table only goes to 16 ft).
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._points: list[dict[str, float]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._points = list(DEFAULT_CALIBRATION)
            self._save()
            return
        try:
            data = json.loads(self.path.read_text())
            pts = data.get("points") or data
            self._points = self._normalize(pts)
        except Exception as e:
            log.warning("calibration load failed (%s); using defaults", e)
            self._points = list(DEFAULT_CALIBRATION)

    @staticmethod
    def _normalize(pts: list) -> list[dict[str, float]]:
        cleaned: list[dict[str, float]] = []
        for p in pts:
            try:
                d = float(p["distance_ft"])
                r = float(p["rps"])
            except (KeyError, TypeError, ValueError):
                continue
            if d < 0 or r < 0:
                continue
            cleaned.append({"distance_ft": d, "rps": r})
        cleaned.sort(key=lambda p: p["distance_ft"])
        # Dedupe identical-distance entries, keep the last (most recent edit).
        deduped: dict[float, float] = {}
        for p in cleaned:
            deduped[p["distance_ft"]] = p["rps"]
        return [{"distance_ft": d, "rps": r} for d, r in sorted(deduped.items())]

    def _save(self) -> None:
        self.path.write_text(json.dumps({"points": self._points}, indent=2) + "\n")

    def points(self) -> list[dict[str, float]]:
        with self._lock:
            return list(self._points)

    def replace(self, pts: list) -> list[dict[str, float]]:
        with self._lock:
            self._points = self._normalize(pts) or list(DEFAULT_CALIBRATION)
            self._save()
            return list(self._points)

    def add(self, distance_ft: float, rps: float) -> list[dict[str, float]]:
        with self._lock:
            new = list(self._points) + [
                {"distance_ft": float(distance_ft), "rps": float(rps)}
            ]
            self._points = self._normalize(new)
            self._save()
            return list(self._points)

    def remove_at(self, distance_ft: float, eps: float = 0.01) -> list[dict[str, float]]:
        with self._lock:
            self._points = [
                p for p in self._points
                if abs(p["distance_ft"] - distance_ft) > eps
            ]
            self._save()
            return list(self._points)

    def lookup_rps(self, distance_ft: float) -> float | None:
        """Linear interpolation; clamps at table edges. None if table empty."""
        with self._lock:
            pts = self._points
        if not pts:
            return None
        if distance_ft <= pts[0]["distance_ft"]:
            return pts[0]["rps"]
        if distance_ft >= pts[-1]["distance_ft"]:
            return pts[-1]["rps"]
        for i in range(1, len(pts)):
            lo, hi = pts[i - 1], pts[i]
            if distance_ft <= hi["distance_ft"]:
                t = (distance_ft - lo["distance_ft"]) / (hi["distance_ft"] - lo["distance_ft"])
                return lo["rps"] + t * (hi["rps"] - lo["rps"])
        return pts[-1]["rps"]


# ===== NetworkTables bridge =====

class NTBridge:
    """All NT topics live in one place so the contract with the rio is
    obvious. Anything under /Sight is owned by us; /Tune/* is shared with
    tunables.py."""

    READ_DOUBLE = {
        "dial_ft": "/SmartDashboard/Tune/Shooter Distance (ft)",
        "lasercan_m": "/SmartDashboard/Sight/LaserCAN/DistanceM",
    }
    READ_BOOL = {
        "lasercan_valid": "/SmartDashboard/Sight/LaserCAN/Valid",
        "driver_lockout": "/SmartDashboard/Sight/DriverLockout",
        # Robot enabled state — rio publishes this from the matching robot
        # code; UI grays out controls when False so we can't fire while the
        # bot is disabled. Defaults True at the subscription so a fresh
        # setup doesn't soft-brick the UI before the rio publishes.
        "robot_enabled": "/SmartDashboard/Sight/RobotEnabled",
        "btn_a": "/SmartDashboard/Sight/Buttons/A",
        "btn_b": "/SmartDashboard/Sight/Buttons/B",
        "btn_x": "/SmartDashboard/Sight/Buttons/X",
        "btn_y": "/SmartDashboard/Sight/Buttons/Y",
        "btn_lb": "/SmartDashboard/Sight/Buttons/LB",
        "btn_rb": "/SmartDashboard/Sight/Buttons/RB",
    }
    READ_INT = {
        "pov": "/SmartDashboard/Sight/Buttons/POV",
    }
    READ_STR = {
        "aim_status": "/SmartDashboard/Sight/Aim/Status",
    }

    WRITE_DOUBLE = {
        # Target geometry — published every frame, even when nothing detected
        # (we publish 0/false so rio can distinguish "stale" from "no tag").
        "target_bearing": "/SmartDashboard/Sight/Target/BearingDeg",
        "target_range_m": "/SmartDashboard/Sight/Target/RangeM",
        "target_cx": "/SmartDashboard/Sight/Target/CenterX",
        "target_cy": "/SmartDashboard/Sight/Target/CenterY",
        # The Pi's calibration-derived RPS recommendation. The rio reads
        # this and applies it during AutoAim.
        "target_rps": "/SmartDashboard/Sight/Aim/TargetRps",
        # Manual dial setpoint, used by the on-screen +/- buttons.
        "shooter_dial_ft": "/SmartDashboard/Tune/Shooter Distance (ft)",
    }
    WRITE_INT = {
        "target_tag_id": "/SmartDashboard/Sight/Target/TagID",
        # Bumped on SHOOT button press; rio's trigger watches this for a
        # rising edge and schedules AutoAim.
        "shoot_request_id": "/SmartDashboard/Sight/Shoot/RequestId",
    }
    WRITE_BOOL = {
        "target_detected": "/SmartDashboard/Sight/Target/Detected",
    }

    def __init__(self) -> None:
        # Pure-Python NT4 client (see nt4_client.py for the why). API is
        # shaped like a slimmed-down ntcore so this code stays familiar.
        self.inst = nt4_client.Client("OrangePi-Sight")
        if NT_SERVER:
            self.inst.set_server(NT_SERVER)
            log.info("NT4: connecting to %s", NT_SERVER)
        else:
            self.inst.set_server_team(TEAM)
            log.info("NT4: connecting to team %d", TEAM)
        self.inst.start()

        self._d_pubs: dict[str, nt4_client.Publisher] = {}
        self._i_pubs: dict[str, nt4_client.Publisher] = {}
        self._b_pubs: dict[str, nt4_client.Publisher] = {}
        self._d_subs: dict[str, nt4_client.Subscriber] = {}
        self._i_subs: dict[str, nt4_client.Subscriber] = {}
        self._b_subs: dict[str, nt4_client.Subscriber] = {}
        self._s_subs: dict[str, nt4_client.Subscriber] = {}

        for key, path in self.READ_DOUBLE.items():
            self._d_subs[key] = self.inst.subscribe(path, "double", 0.0)
        for key, path in self.READ_BOOL.items():
            # robot_enabled defaults True so the UI is usable on a fresh
            # setup before the rio robot code wires up the topic; everything
            # else is False until proven otherwise.
            default = True if key == "robot_enabled" else False
            self._b_subs[key] = self.inst.subscribe(path, "boolean", default)
        for key, path in self.READ_INT.items():
            self._i_subs[key] = self.inst.subscribe(path, "int", 0)
        for key, path in self.READ_STR.items():
            self._s_subs[key] = self.inst.subscribe(path, "string", "idle")

        for key, path in self.WRITE_DOUBLE.items():
            self._d_pubs[key] = self.inst.publish(path, "double")
        for key, path in self.WRITE_INT.items():
            self._i_pubs[key] = self.inst.publish(path, "int")
        for key, path in self.WRITE_BOOL.items():
            self._b_pubs[key] = self.inst.publish(path, "boolean")

        self._shoot_request_id = 0

    def snapshot(self) -> dict:
        snap: dict[str, object] = {"connected": self.inst.is_connected()}
        for key, sub in self._d_subs.items():
            snap[key] = sub.get()
        for key, sub in self._b_subs.items():
            snap[key] = sub.get()
        for key, sub in self._i_subs.items():
            snap[key] = sub.get()
        for key, sub in self._s_subs.items():
            snap[key] = sub.get()
        return snap

    def publish_target(self, det: "Detection | None", rps_hint: float | None) -> None:
        """Push the current detection + RPS recommendation to NT.

        Called from the detection thread every detector tick. Always
        publishes a complete snapshot — when nothing's detected we still
        write detected=False / zeros so the rio can tell live-no-tag from
        stale-link-down (the latter shows up as is_connected=False).
        """
        if det is None:
            self._b_pubs["target_detected"].set(False)
            self._d_pubs["target_bearing"].set(0.0)
            self._d_pubs["target_range_m"].set(0.0)
            self._d_pubs["target_cx"].set(0.0)
            self._d_pubs["target_cy"].set(0.0)
            self._i_pubs["target_tag_id"].set(0)
        else:
            self._b_pubs["target_detected"].set(True)
            self._d_pubs["target_bearing"].set(det.bearing_deg)
            self._d_pubs["target_range_m"].set(det.range_m)
            self._d_pubs["target_cx"].set(det.cx_norm)
            self._d_pubs["target_cy"].set(det.cy_norm)
            self._i_pubs["target_tag_id"].set(det.tag_id)
        if rps_hint is not None:
            self._d_pubs["target_rps"].set(float(rps_hint))

    def request_shoot(self) -> int:
        self._shoot_request_id += 1
        self._i_pubs["shoot_request_id"].set(self._shoot_request_id)
        return self._shoot_request_id

    def set_dial(self, ft: float) -> None:
        self._d_pubs["shooter_dial_ft"].set(float(ft))


# ===== Camera + AprilTag detection =====

class Detection:
    __slots__ = ("tag_id", "bearing_deg", "range_m", "cx_norm", "cy_norm",
                 "corners_px", "ts")

    def __init__(self, tag_id: int, bearing_deg: float, range_m: float,
                 cx_norm: float, cy_norm: float, corners_px: np.ndarray,
                 ts: float):
        self.tag_id = tag_id
        self.bearing_deg = bearing_deg
        self.range_m = range_m
        self.cx_norm = cx_norm
        self.cy_norm = cy_norm
        self.corners_px = corners_px
        self.ts = ts


class CameraEngine:
    """Captures frames, runs detection, draws overlay, encodes for streaming.

    One producer thread does everything in a tight loop:
      capture → detect (every Nth) → overlay → encode → publish to subscribers
    Stream consumers wait on a condition variable for the latest JPEG.

    Separating capture from detection isn't worth the complexity at our
    rate (30 fps × 720p): the V4L2 read is bounded by the camera, and
    detection at half-res fits inside one frame interval on a Pi 5.
    """

    def __init__(self, nt: NTBridge, calibration: Calibration) -> None:
        self.nt = nt
        self.calibration = calibration
        self._stop = threading.Event()
        self._cap: cv2.VideoCapture | None = None
        self._latest_jpeg: bytes = b""
        self._frame_idx = 0
        self._latest_det: Detection | None = None
        # All tag IDs visible in the latest detection tick (targeted or not).
        # Lets the renderer draw non-targeted tags in a different color and
        # the UI surface "we see IDs X, Y" so users debugging "no detection"
        # can immediately see the detector IS working — they just need to
        # update TARGET_TAG_IDS.
        self._latest_all: list[tuple[int, np.ndarray]] = []
        self._cond = threading.Condition()
        self._frame_token = 0  # bumped each new JPEG; used to wake subscribers

        # Detector setup. The 36h11 family is what FRC standardized on in
        # 2023; opencv ships the dictionary built-in, no extra deps.
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
        params = cv2.aruco.DetectorParameters()
        # Refining marker corners with the contour fit helps PnP a lot
        # without much CPU cost.
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self._detector = cv2.aruco.ArucoDetector(dictionary, params)

        # Synthetic camera matrix from FOV. If you want sub-degree bearings,
        # replace this with values from cv2.calibrateCamera; the math here
        # only needs focal_x, optical_center_x, and the equivalents in y.
        focal_x = (CAMERA_WIDTH / 2.0) / math.tan(math.radians(CAMERA_HFOV_DEG) / 2.0)
        focal_y = focal_x  # square pixels assumption
        cx, cy = CAMERA_WIDTH / 2.0, CAMERA_HEIGHT / 2.0
        self._K = np.array([[focal_x, 0, cx], [0, focal_y, cy], [0, 0, 1]], dtype=np.float64)
        self._dist = np.zeros(5, dtype=np.float64)
        # Object points for one tag, centered at origin in the tag's frame.
        # Order matches the corner order ArucoDetector returns
        # (top-left, top-right, bottom-right, bottom-left, looking at the tag).
        s = TAG_SIZE_M / 2.0
        self._tag_obj_points = np.array([
            [-s,  s, 0], [ s,  s, 0], [ s, -s, 0], [-s, -s, 0]
        ], dtype=np.float64)

    # ----- lifecycle -----

    def start(self) -> None:
        threading.Thread(
            target=self._loop, name="camera-engine", daemon=True,
        ).start()

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()

    # ----- main loop -----

    def _open_capture(self) -> bool:
        cap = cv2.VideoCapture(CAMERA_DEVICE, cv2.CAP_V4L2)
        if not cap.isOpened():
            log.error("could not open %s", CAMERA_DEVICE)
            return False
        # Force MJPEG so the V4L2 driver hands us hardware-decoded frames
        # instead of negotiating a slower YUYV path.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        # 1-frame buffer keeps latency low — without this, OpenCV defaults
        # to a few frames of internal queue and we'd aim at where the
        # target was 100 ms ago.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap
        log.info(
            "camera open: %dx%d @ %d fps target_tags=%s",
            CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS, sorted(TARGET_TAG_IDS),
        )
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._cap is None and not self._open_capture():
                time.sleep(2.0)
                continue
            ok, frame = self._cap.read()
            if not ok or frame is None:
                log.error("frame read failed; reopening")
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
                time.sleep(0.5)
                continue

            self._frame_idx += 1
            det = self._latest_det
            if self._frame_idx % max(1, DETECT_EVERY) == 0:
                det = self._detect(frame)
                self._latest_det = det
                # Publish target + recommended RPS to NT every detection
                # tick — the rio sees the freshest values without any
                # request/response.
                rps_hint = self._rps_hint_for(det)
                try:
                    self.nt.publish_target(det, rps_hint)
                except Exception as e:
                    log.warning("nt publish failed: %s", e)

            # Draw overlay + encode. We always re-encode (even if the
            # detection didn't run) so the stream stays smooth.
            jpeg = self._render(frame, det)
            with self._cond:
                self._latest_jpeg = jpeg
                self._frame_token += 1
                self._cond.notify_all()

    def _rps_hint_for(self, det: Detection | None) -> float | None:
        # Prefer LaserCAN for distance — it's an active sensor; tag-PnP
        # range degrades quickly past a few meters because tag pixel size
        # is small and quantized.
        snap_d = self.nt._d_subs["lasercan_m"].get()
        snap_v = self.nt._b_subs["lasercan_valid"].get()
        if snap_v and snap_d > 0.05:
            distance_ft = snap_d / _FOOT_TO_M
        elif det is not None and det.range_m > 0.05:
            distance_ft = det.range_m / _FOOT_TO_M
        else:
            return None
        return self.calibration.lookup_rps(distance_ft)

    # ----- detection -----

    def _detect(self, bgr: np.ndarray) -> Detection | None:
        # Detection runs on a downscaled grey copy — much faster, accuracy
        # loss is small for tags occupying >30 px even after downscale.
        if DETECT_DOWNSCALE != 1.0:
            small = cv2.resize(bgr, None, fx=DETECT_DOWNSCALE, fy=DETECT_DOWNSCALE,
                               interpolation=cv2.INTER_AREA)
        else:
            small = bgr
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        corners_list, ids, _ = self._detector.detectMarkers(gray)
        if ids is None or len(ids) == 0:
            self._latest_all = []
            return None

        # Scale corners back up to full-res pixel coordinates so PnP and
        # bearing math use the camera matrix we built for full-res.
        scale = 1.0 / DETECT_DOWNSCALE if DETECT_DOWNSCALE != 0 else 1.0
        scaled_corners = [c * scale for c in corners_list]

        # Cache every detected tag so the renderer + UI can show non-target
        # detections in a different color. Critical for debugging "tags
        # aren't being detected" — usually they ARE, but TARGET_TAG_IDS
        # doesn't include the IDs the user is testing with.
        self._latest_all = [
            (int(tid), c)
            for tid, c in zip(ids.flatten().tolist(), scaled_corners)
        ]

        candidates: list[tuple[int, np.ndarray]] = []
        for tag_id, corners in zip(ids.flatten().tolist(), scaled_corners):
            if not TARGET_TAG_IDS or int(tag_id) in TARGET_TAG_IDS:
                candidates.append((int(tag_id), corners))
        if not candidates:
            return None

        # "Best" target = largest area in pixels (closest / most reliable).
        def area(c: np.ndarray) -> float:
            return float(cv2.contourArea(c.reshape(-1, 2).astype(np.float32)))
        tag_id, corners = max(candidates, key=lambda c: area(c[1]))

        # Tag center in image-pixel coordinates.
        pts = corners.reshape(-1, 2)
        cx_px = float(pts[:, 0].mean())
        cy_px = float(pts[:, 1].mean())

        # Bearing: signed angle from optical axis. Positive = right of center,
        # which matches CCW-positive yaw if the camera is mounted with +x to
        # the right of the robot (the standard orientation).
        focal_x = self._K[0, 0]
        principal_x = self._K[0, 2]
        bearing_rad = math.atan2(cx_px - principal_x, focal_x)
        bearing_deg = math.degrees(bearing_rad)

        # Range: solvePnP on a single tag with known size. This works at any
        # range but accuracy drops when the tag is small in the frame.
        try:
            ok, rvec, tvec = cv2.solvePnP(
                self._tag_obj_points, pts.astype(np.float64),
                self._K, self._dist, flags=cv2.SOLVEPNP_IPPE_SQUARE,
            )
            range_m = float(np.linalg.norm(tvec)) if ok else 0.0
        except Exception:
            range_m = 0.0

        return Detection(
            tag_id=tag_id,
            bearing_deg=bearing_deg,
            range_m=range_m,
            cx_norm=cx_px / CAMERA_WIDTH,
            cy_norm=cy_px / CAMERA_HEIGHT,
            corners_px=pts,
            ts=time.monotonic(),
        )

    # ----- rendering -----

    def _render(self, frame: np.ndarray, det: Detection | None) -> bytes:
        # Center crosshair (always on).
        h, w = frame.shape[:2]
        cv2.line(frame, (w // 2, 0), (w // 2, h), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(frame, (0, h // 2), (w, h // 2), (255, 255, 255), 1, cv2.LINE_AA)

        # Draw every non-targeted detection first, in a muted orange, so
        # the user can see when the detector is working but their target
        # list doesn't match. The targeted detection then overlays in green.
        target_id = det.tag_id if det is not None else None
        for tid, corners in self._latest_all:
            if tid == target_id:
                continue
            pts_other = corners.astype(np.int32).reshape(-1, 2)
            other_color = (60, 140, 255)  # BGR — soft orange, "seen but not aimed"
            cv2.polylines(frame, [pts_other], isClosed=True, color=other_color,
                          thickness=1, lineType=cv2.LINE_AA)
            cx_o = int(pts_other[:, 0].mean())
            cy_o = int(pts_other[:, 1].mean())
            cv2.putText(frame, f"#{tid}", (cx_o + 6, cy_o - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, other_color, 1, cv2.LINE_AA)

        if det is not None:
            color = (0, 212, 0) if (not TARGET_TAG_IDS or det.tag_id in TARGET_TAG_IDS) else (0, 165, 255)
            pts = det.corners_px.astype(np.int32).reshape(-1, 2)
            cv2.polylines(frame, [pts], isClosed=True, color=color,
                          thickness=2, lineType=cv2.LINE_AA)
            cx, cy = int(det.cx_norm * w), int(det.cy_norm * h)
            cv2.circle(frame, (cx, cy), 4, color, -1, cv2.LINE_AA)
            label = f"#{det.tag_id}  {det.bearing_deg:+.1f}°"
            if det.range_m > 0:
                label += f"  {det.range_m:.2f}m"
            cv2.putText(frame, label, (cx + 12, cy - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_QUALITY])
        return buf.tobytes() if ok else b""

    # ----- streaming to clients -----

    async def stream(self) -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        last_token = -1
        boundary = b"--frame\r\n"
        while not self._stop.is_set():
            data = await loop.run_in_executor(None, self._wait_for_frame, last_token)
            if data is None:
                break
            last_token, jpeg = data
            yield (
                boundary
                + b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(jpeg)}\r\n\r\n".encode()
                + jpeg
                + b"\r\n"
            )

    def _wait_for_frame(self, last_token: int) -> tuple[int, bytes] | None:
        with self._cond:
            while self._frame_token == last_token and not self._stop.is_set():
                self._cond.wait(timeout=2.0)
            if self._stop.is_set():
                return None
            return self._frame_token, self._latest_jpeg


# ===== FastAPI app =====
app = FastAPI(title="Cold Fusion Sight")
nt = NTBridge()
calibration = Calibration(CALIBRATION_PATH)
camera = CameraEngine(nt, calibration)


@app.on_event("startup")
async def on_startup() -> None:
    try:
        camera.start()
    except Exception as e:
        log.error("camera failed to start: %s", e)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    camera.stop()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/stream.mjpg")
async def stream_mjpg() -> StreamingResponse:
    return StreamingResponse(
        camera.stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/state")
async def api_state(request: Request) -> StreamingResponse:
    """Server-Sent Events feed of robot + target state for the live HUD."""
    async def event_stream() -> AsyncIterator[str]:
        last_payload = ""
        # Cap how many times in a row we'll swallow a per-tick exception
        # before bailing out of the loop. A bad NT snapshot shouldn't kill
        # the SSE stream, but a persistent bug shouldn't loop forever
        # either — the client will reconnect via EventSource onerror.
        consecutive_errors = 0
        while not await request.is_disconnected():
            try:
                snap = nt.snapshot()
                det = camera._latest_det
                if det is not None:
                    snap["target"] = {
                        "detected": True,
                        "tag_id": det.tag_id,
                        "bearing_deg": det.bearing_deg,
                        "range_m": det.range_m,
                        "cx_norm": det.cx_norm,
                        "cy_norm": det.cy_norm,
                        "age_ms": int((time.monotonic() - det.ts) * 1000),
                    }
                else:
                    snap["target"] = {"detected": False}
                snap["recommended_rps"] = camera._rps_hint_for(det)
                # Surface every tag ID the detector saw this tick (target
                # or not). Lets the UI show "seen: 14, 22" so users know
                # the detector is working when no targeted tag is in view.
                snap["seen_tags"] = sorted({tid for tid, _ in camera._latest_all})
                payload = json.dumps(snap, default=float)
                if payload != last_payload:
                    last_payload = payload
                    yield f"data: {payload}\n\n"
                consecutive_errors = 0
            except asyncio.CancelledError:
                # Client disconnected mid-yield — let it propagate so
                # uvicorn cleans the response up.
                raise
            except Exception:
                consecutive_errors += 1
                log.exception("SSE tick failed (%d in a row)", consecutive_errors)
                if consecutive_errors >= 20:
                    log.error("too many SSE errors; closing this stream")
                    break
            await asyncio.sleep(0.05)  # 20 Hz max

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/shoot")
async def api_shoot() -> JSONResponse:
    """SHOOT button. Bumps the request id; rio's trigger schedules AutoAim.

    We don't reject "no target" here — the rio can still try to fire on
    the last known bearing, and rejecting up front would block the
    operator from a good-faith fire when the tag briefly drops out. The
    UI shows the target-lock state so they know what they're committing
    to.
    """
    rid = nt.request_shoot()
    return JSONResponse({"ok": True, "request_id": rid})


@app.post("/api/dial")
async def api_dial(payload: dict) -> JSONResponse:
    try:
        ft = float(payload["ft"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="ft (number) required")
    nt.set_dial(max(0.0, ft))
    return JSONResponse({"ok": True, "ft": ft})


@app.get("/api/calibration")
async def api_calibration_get() -> JSONResponse:
    return JSONResponse({"points": calibration.points()})


@app.post("/api/calibration")
async def api_calibration_post(payload: dict) -> JSONResponse:
    """Replace the entire calibration table.

    We accept either {"points": [...]} or a raw list. The Pi sanitizes
    + sorts + dedupes server-side so the UI doesn't need to.
    """
    pts = payload.get("points") if isinstance(payload, dict) else payload
    if not isinstance(pts, list):
        raise HTTPException(status_code=400, detail="points (list) required")
    new = calibration.replace(pts)
    return JSONResponse({"ok": True, "points": new})


@app.post("/api/calibration/add")
async def api_calibration_add(payload: dict) -> JSONResponse:
    """Add or update a single (distance_ft, rps) point.

    Convenience for the in-UI 'capture this shot' button — driver shoots
    a known distance and clicks save; we add the point and snapshot the
    current dialed RPS.
    """
    try:
        d = float(payload["distance_ft"])
        r = float(payload["rps"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="distance_ft and rps required")
    new = calibration.add(d, r)
    return JSONResponse({"ok": True, "points": new})


@app.post("/api/calibration/remove")
async def api_calibration_remove(payload: dict) -> JSONResponse:
    try:
        d = float(payload["distance_ft"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="distance_ft required")
    new = calibration.remove_at(d)
    return JSONResponse({"ok": True, "points": new})


@app.get("/api/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        "nt_connected": nt.inst.isConnected(),
        "target_tag_ids": sorted(TARGET_TAG_IDS),
        "calibration_points": len(calibration.points()),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="info")
