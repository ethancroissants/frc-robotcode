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
3. Target selection:
     - If the operator clicked a tag in the UI (selected_tag_id is set)
       and that tag is visible, that tag wins.
     - Otherwise we pick the largest tag whose ID is in TARGET_TAG_IDS.
     - Otherwise no target.
4. From the tag's pixel location + image size we compute:
     bearing_deg — signed angle of the tag from camera optical axis
                   (negative = left of center, positive = right)
     range_m    — distance from PnP (assumes a known tag side length)
5. We publish target state continuously to NetworkTables under
   /Sight/Target/* (plus /Sight/Aim/Ready when the bot is on-target). The
   rio's AutoAim command reads these every cycle.
6. The browser SHOOT button POSTs /api/shoot, which bumps
   /Sight/Shoot/RequestId. The rio's button-press trigger watches that id
   and schedules AutoAim, which:
     - sets /Sight/DriverLockout=true
     - reads bearing & range each cycle, drives a heading PID off bearing
     - dials shooter RPS from the Pi's calibration lookup
     - fires
     - sets /Sight/DriverLockout=false on end
7. The Pi serves a calibration-table editor at /api/calibration, plus a
   live debug-log feed at /api/logs and a click-to-target endpoint at
   /api/target. The browser dashboard owns the windowing/UX; this file
   only exposes data.

The browser stream is the *same* numpy frames after we draw an overlay
(target box, crosshair, range readout) and re-encode to JPEG.

Run with: uvicorn server:app --host 0.0.0.0 --port 8080
The systemd unit calls exactly that.
"""

from __future__ import annotations

import asyncio
import collections
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


# ===== Version =====
# Bumped on every meaningful change so the UI footer can prove the right
# code is running. Kept in lockstep with start.py's version for the
# Vision-Pi Setup wizard, but the Pi can be ahead/behind during a push.
VERSION = "2.3.0"


# ===== Config (env-overridable) =====
TEAM = int(os.environ.get("TEAM", "1279"))
NT_SERVER = os.environ.get("NT_SERVER", "")
CAMERA_DEVICE = os.environ.get("CAMERA_DEVICE", "/dev/video0")
# 640x480 is the universal hardware-MJPEG mode on USB cameras and gives the
# detector 2-3x more headroom than 720p — at 480p we comfortably hit 30 fps
# end-to-end on the Pi 5 with cycles to spare. Bump if you're sure your
# camera + Pi can hold it.
CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", "640"))
CAMERA_HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.environ.get("CAMERA_FPS", "30"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))

# Camera geometry. Overridden by cam_intrinsics.json if present (preferred —
# real chessboard-calibrated K + dist coeffs give sub-degree bearings and
# accurate range). The synthetic FOV path is a sane default for a fresh
# install where no one has calibrated yet.
CAMERA_HFOV_DEG = float(os.environ.get("CAMERA_HFOV_DEG", "60.0"))
TAG_SIZE_M = float(os.environ.get("TAG_SIZE_M", "0.1651"))  # 6.5"

# Bearing band that counts as "ready to fire". The flywheel is forgiving
# in distance (calibration interpolates) but unforgiving in heading — so
# we publish ready=True only when we're inside this many degrees of
# centered. AutoAim has its own (tighter) tolerance for the actual fire,
# but the operator UI uses this looser one for the "armed" indicator.
READY_BEARING_DEG = float(os.environ.get("READY_BEARING_DEG", "2.5"))

# JPEG encode quality for the browser stream. 75 is a good speed/quality
# tradeoff on the Pi 5; drop to 60 if CPU pegs.
STREAM_QUALITY = int(os.environ.get("STREAM_QUALITY", "75"))
# Run the detector on every Nth captured frame. 1 = every frame.
DETECT_EVERY = int(os.environ.get("DETECT_EVERY", "1"))
# Downscale factor used only for detection (stream stays full res). Smaller
# = faster detection at the cost of some accuracy on small/distant tags.
# At 640x480 we run detection full-res by default — there's no headroom
# pressure and corner refinement is more accurate without the resize.
DETECT_DOWNSCALE = float(os.environ.get("DETECT_DOWNSCALE", "1.0"))
# Comma-separated list of tag IDs that count as "the goal" by default.
# Operator can override per-shot by clicking a tag in the UI; if no tag is
# selected and none of the visible tags match this list, target=None.
TARGET_TAG_IDS = {
    int(s.strip())
    for s in os.environ.get("TARGET_TAG_IDS", "3,4,7,8").split(",")
    if s.strip()
}

REPO = Path(__file__).resolve().parent
STATIC_DIR = REPO / "static"
CALIBRATION_PATH = REPO / "sight_calibration.json"
INTRINSICS_PATH = REPO / "cam_intrinsics.json"
# Range-scale multiplier — corrects systematic PnP-range error caused by
# slightly-wrong camera intrinsics or tag size, as a single scalar.
# Persists across restarts so the calibration survives reboots/re-pushes
# (rsync without --delete leaves files not in source alone).
RANGE_CAL_PATH = REPO / "range_calibration.json"

# Recordings live OUTSIDE the install dir on purpose: the laptop's
# "Set up / Update Vision Pi" wizard rsync's `orangepi/` over the
# install dir on every push, so anything inside it would be wiped.
# $HOME/cold-fusion-sight-recordings survives reinstalls.
RECORDINGS_DIR = Path(
    os.environ.get("CFS_RECORDINGS_DIR")
    or (Path.home() / "cold-fusion-sight-recordings")
)
try:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    # Fall back to a tmp path if HOME isn't writable. The endpoint will
    # surface the failure rather than silently dropping recordings.
    RECORDINGS_DIR = Path("/tmp/cold-fusion-sight-recordings")
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

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


# ===== In-memory log buffer =====
# The debug-console panel in the UI tails this. Cap at a few hundred lines
# so a runaway log loop can't OOM the Pi. Each entry is a dict ready to be
# JSON-dumped — building it in the handler is cheaper than building it in
# the SSE loop on every fetch.

_LOG_RING: collections.deque = collections.deque(maxlen=500)
_log_seq = 0
_log_lock = threading.Lock()
_log_cv = threading.Condition(_log_lock)


class _RingHandler(logging.Handler):
    """Tee log records into _LOG_RING. SSE consumers wake on _log_cv."""

    def emit(self, record: logging.LogRecord) -> None:
        global _log_seq
        try:
            text = self.format(record)
        except Exception:
            text = record.getMessage()
        with _log_cv:
            _log_seq += 1
            _LOG_RING.append({
                "seq": _log_seq,
                "ts": record.created,
                "level": record.levelname,
                "name": record.name,
                "msg": text,
            })
            _log_cv.notify_all()


_ring_handler = _RingHandler()
_ring_handler.setFormatter(logging.Formatter("%(message)s"))

# `force=True` resets root's existing handlers — needed because uvicorn sets
# up logging *before* importing this module. Without force, basicConfig is a
# silent no-op, root stays at whatever level uvicorn picked (typically WARNING
# for non-uvicorn loggers), and every `NT4: connecting …` line gets dropped
# before the ring handler ever sees it. Operators saw "no rio logs" and
# couldn't tell whether the Pi was even attempting to dial the rio.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    force=True,
)
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(_ring_handler)
# nt4_client uses its own named logger; make sure INFO from it propagates
# even if some downstream code muted root-level INFO again.
logging.getLogger("nt4").setLevel(logging.INFO)
log = logging.getLogger("sight")


# ===== Camera intrinsics =====

def _load_intrinsics() -> tuple[np.ndarray, np.ndarray, str]:
    """Returns (K, dist_coeffs, source_label).

    cam_intrinsics.json (preferred):
      {"K": [[fx,0,cx],[0,fy,cy],[0,0,1]], "dist": [k1,k2,p1,p2,k3]}
      OR flat: {"fx": ..., "fy": ..., "cx": ..., "cy": ..., "dist": [...]}

    Synthesizes from CAMERA_HFOV_DEG if no file. Returns float64 arrays so
    cv2.solvePnP doesn't have to upcast every frame.
    """
    if INTRINSICS_PATH.exists():
        try:
            data = json.loads(INTRINSICS_PATH.read_text())
            if "K" in data:
                K = np.array(data["K"], dtype=np.float64)
            else:
                K = np.array([
                    [float(data["fx"]), 0.0, float(data["cx"])],
                    [0.0, float(data["fy"]), float(data["cy"])],
                    [0.0, 0.0, 1.0],
                ], dtype=np.float64)
            dist = np.array(data.get("dist", [0, 0, 0, 0, 0]), dtype=np.float64).flatten()
            if dist.size < 5:
                dist = np.concatenate([dist, np.zeros(5 - dist.size)])
            return K, dist, f"calibrated ({INTRINSICS_PATH.name})"
        except Exception as e:
            log.warning("intrinsics load failed (%s); using FOV synthesis", e)
    focal_x = (CAMERA_WIDTH / 2.0) / math.tan(math.radians(CAMERA_HFOV_DEG) / 2.0)
    focal_y = focal_x  # square pixels assumption
    cx, cy = CAMERA_WIDTH / 2.0, CAMERA_HEIGHT / 2.0
    K = np.array([[focal_x, 0, cx], [0, focal_y, cy], [0, 0, 1]], dtype=np.float64)
    return K, np.zeros(5, dtype=np.float64), f"synthetic (HFOV={CAMERA_HFOV_DEG:.1f}°)"


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
    }
    READ_BOOL = {
        "driver_lockout": "/SmartDashboard/Sight/DriverLockout",
        # Robot enabled state — rio publishes this from the matching robot
        # code; UI grays out controls when False so we can't fire while the
        # bot is disabled. Defaults True at the subscription so a fresh
        # setup doesn't soft-brick the UI before the rio publishes.
        "robot_enabled": "/SmartDashboard/Sight/RobotEnabled",
        # Operator stick (kept at the original /Sight/Buttons/* path for
        # back-compat with older Pi/rio code).
        "op_btn_a": "/SmartDashboard/Sight/Buttons/A",
        "op_btn_b": "/SmartDashboard/Sight/Buttons/B",
        "op_btn_x": "/SmartDashboard/Sight/Buttons/X",
        "op_btn_y": "/SmartDashboard/Sight/Buttons/Y",
        "op_btn_lb": "/SmartDashboard/Sight/Buttons/LB",
        "op_btn_rb": "/SmartDashboard/Sight/Buttons/RB",
        # Driver stick (new — rio publishes under /Sight/Buttons/Driver/*).
        "dr_btn_a": "/SmartDashboard/Sight/Buttons/Driver/A",
        "dr_btn_b": "/SmartDashboard/Sight/Buttons/Driver/B",
        "dr_btn_x": "/SmartDashboard/Sight/Buttons/Driver/X",
        "dr_btn_y": "/SmartDashboard/Sight/Buttons/Driver/Y",
        "dr_btn_lb": "/SmartDashboard/Sight/Buttons/Driver/LB",
        "dr_btn_rb": "/SmartDashboard/Sight/Buttons/Driver/RB",
    }
    READ_INT = {
        "op_pov": "/SmartDashboard/Sight/Buttons/POV",
        "dr_pov": "/SmartDashboard/Sight/Buttons/Driver/POV",
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
        # Flywheel spin-up delay (seconds): how long AutoAim waits after
        # commanding the wheel to spin up before pulling the trigger.
        # Tunable from the calibrate page so we don't have to redeploy
        # the rio to lengthen the settle window.
        "spin_up_delay_s": "/SmartDashboard/Sight/Aim/SpinUpDelayS",
    }
    WRITE_INT = {
        "target_tag_id": "/SmartDashboard/Sight/Target/TagID",
        # Bumped on SHOOT button press; rio's trigger watches this for a
        # rising edge and schedules AutoAim.
        "shoot_request_id": "/SmartDashboard/Sight/Shoot/RequestId",
        # Mirrors the operator's clicked-tag selection so other consumers
        # (e.g. dashboards on other clients) can see what we're locked to.
        "selected_tag_id": "/SmartDashboard/Sight/Target/SelectedID",
    }
    WRITE_BOOL = {
        "target_detected": "/SmartDashboard/Sight/Target/Detected",
        # True when target is detected, bearing is inside READY_BEARING_DEG,
        # robot is enabled, and AutoAim isn't already running. Rio can wire
        # this to e.g. a controller rumble or a pre-fire indicator.
        "target_ready": "/SmartDashboard/Sight/Aim/Ready",
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

    def _sub_age_ms(self, sub: nt4_client.Subscriber) -> int | None:
        """Time since this subscription's last update, in ms.

        None means we've never received a value (so the rio-side publisher
        is missing — distinct from "value is fresh and is False/0").
        """
        last_us = getattr(sub._state, "last_update_us", 0)
        if not last_us:
            return None
        now_us = int(time.time() * 1_000_000)
        return max(0, (now_us - last_us) // 1000)

    def snapshot(self) -> dict:
        snap: dict[str, object] = {"connected": self.inst.is_connected()}
        ages: dict[str, int | None] = {}
        for key, sub in self._d_subs.items():
            snap[key] = sub.get()
            ages[key] = self._sub_age_ms(sub)
        for key, sub in self._b_subs.items():
            snap[key] = sub.get()
            ages[key] = self._sub_age_ms(sub)
        for key, sub in self._i_subs.items():
            snap[key] = sub.get()
            ages[key] = self._sub_age_ms(sub)
        for key, sub in self._s_subs.items():
            snap[key] = sub.get()
            ages[key] = self._sub_age_ms(sub)
        snap["_ages_ms"] = ages
        return snap

    def publish_spin_up_delay(self, seconds: float) -> None:
        self._d_pubs["spin_up_delay_s"].set(float(seconds))

    def publish_target(
        self, det: "Detection | None", rps_hint: float | None,
        ready: bool, selected_id: int | None,
    ) -> None:
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
        self._b_pubs["target_ready"].set(bool(ready))
        self._i_pubs["selected_tag_id"].set(int(selected_id) if selected_id is not None else 0)
        if rps_hint is not None:
            self._d_pubs["target_rps"].set(float(rps_hint))

    def request_shoot(self) -> int:
        self._shoot_request_id += 1
        self._i_pubs["shoot_request_id"].set(self._shoot_request_id)
        return self._shoot_request_id

    def set_dial(self, ft: float) -> None:
        self._d_pubs["shooter_dial_ft"].set(float(ft))


# ===== Recording =====

# Filename-safe identifier matcher. Recording filenames are returned as-is
# in URLs, so we stamp them ourselves and reject anything else (no path
# traversal, no shell metachars).
import re as _re
_FILENAME_RE = _re.compile(r"^[A-Za-z0-9._-]+$")


class Recording:
    """One open MP4 writer fed by the CameraEngine.

    Recording is intentionally a sink the engine pushes BGR frames to,
    not a separate consumer thread — that way we record the *rendered*
    frame (with overlay/crosshair/box drawn) and avoid a second copy.
    Recording at the camera's frame rate; the writer is opened at the
    actual capture size.

    The first start() call may pick `mp4v`, `avc1`, or `MJPG` depending
    on what the local OpenCV's ffmpeg backend supports — we fall through
    until VideoWriter.isOpened() succeeds. MJPG-AVI is the universal
    fallback (no external codec).
    """

    _CODECS = (
        ("mp4", "mp4v"),  # MPEG-4 Part 2 — usually available
        ("mp4", "avc1"),  # H.264 — sometimes available depending on build
        ("avi", "MJPG"),  # always available
    )

    def __init__(self, dirpath: Path, fps: float, size: tuple[int, int]) -> None:
        self.dirpath = dirpath
        self.fps = max(1.0, float(fps))
        self.size = (int(size[0]), int(size[1]))
        self.path: Path | None = None
        self.codec: str | None = None
        self.started_at: float = 0.0
        self.frames: int = 0
        self._writer: cv2.VideoWriter | None = None
        self._lock = threading.Lock()

    def start(self) -> Path:
        ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        for ext, fourcc in self._CODECS:
            path = self.dirpath / f"sight-{ts}.{ext}"
            fcc = cv2.VideoWriter_fourcc(*fourcc)
            writer = cv2.VideoWriter(str(path), fcc, self.fps, self.size)
            if writer.isOpened():
                self._writer = writer
                self.path = path
                self.codec = fourcc
                self.started_at = time.time()
                log.info("recording → %s (%s @ %.1f fps)", path.name, fourcc, self.fps)
                return path
            try: writer.release()
            except Exception: pass
        raise RuntimeError("no working VideoWriter codec — recording disabled")

    def write(self, bgr: np.ndarray) -> None:
        # Called from the camera thread; guard with a lock so a concurrent
        # stop() can't release mid-write.
        with self._lock:
            if self._writer is None:
                return
            try:
                self._writer.write(bgr)
                self.frames += 1
            except Exception as e:
                log.warning("recording write failed: %s", e)

    def stop(self) -> Path | None:
        with self._lock:
            if self._writer is None:
                return None
            try:
                self._writer.release()
            except Exception:
                pass
            self._writer = None
            log.info(
                "recording stopped: %s (%d frames, %.1fs)",
                self.path.name if self.path else "?",
                self.frames,
                time.time() - self.started_at,
            )
            return self.path

    def status(self) -> dict:
        return {
            "active": self._writer is not None,
            "path": self.path.name if self.path else None,
            "codec": self.codec,
            "frames": self.frames,
            "elapsed_s": (time.time() - self.started_at) if self.started_at else 0.0,
            "size": list(self.size),
            "fps": self.fps,
        }


# ===== Camera + AprilTag detection =====

class Detection:
    __slots__ = ("tag_id", "bearing_deg", "range_m", "cx_norm", "cy_norm",
                 "corners_px", "ts", "selected_locked")

    def __init__(self, tag_id: int, bearing_deg: float, range_m: float,
                 cx_norm: float, cy_norm: float, corners_px: np.ndarray,
                 ts: float, selected_locked: bool):
        self.tag_id = tag_id
        self.bearing_deg = bearing_deg
        self.range_m = range_m
        self.cx_norm = cx_norm
        self.cy_norm = cy_norm
        self.corners_px = corners_px  # shape (4, 2), float pixels
        self.ts = ts
        self.selected_locked = selected_locked  # operator clicked this tag


class CameraEngine:
    """Captures frames, runs detection, draws overlay, encodes for streaming.

    One producer thread does everything in a tight loop:
      capture → detect (every Nth) → overlay → encode → publish to subscribers
    Stream consumers wait on a condition variable for the latest JPEG.

    Separating capture from detection isn't worth the complexity at our
    rate (30 fps × 480p): the V4L2 read is bounded by the camera, and
    detection at full-res fits inside one frame interval on a Pi 5.
    """

    def __init__(self, nt: NTBridge, calibration: Calibration) -> None:
        self.nt = nt
        self.calibration = calibration
        self._stop = threading.Event()
        self._cap: cv2.VideoCapture | None = None
        self._latest_jpeg: bytes = b""
        self._frame_idx = 0
        self._latest_det: Detection | None = None
        # All tag IDs visible in the latest detection tick (targeted or not),
        # in image-pixel coords. Lets the renderer draw non-targeted tags in
        # a different color, the UI surface "we see IDs X, Y" so users
        # debugging "no detection" can immediately see the detector IS
        # working, and the click-to-target hit-test work without re-running
        # detection on the browser side.
        self._latest_all: list[tuple[int, np.ndarray]] = []
        self._cond = threading.Condition()
        self._frame_token = 0  # bumped each new JPEG; used to wake subscribers

        # Operator's click-locked target (or None). When set, the tag with
        # this ID becomes the chosen target whenever it's visible. If it
        # drops out, target_detected goes False (the operator decides
        # whether to clear or wait for it to come back) — we don't
        # auto-fall-back to TARGET_TAG_IDS because that'd silently aim at a
        # different tag than what the operator clicked.
        self._selected_tag_id: int | None = None

        # Active recording (or None). Owned by the camera thread; the API
        # endpoints flip this on/off via start_recording/stop_recording
        # which serialize through the engine lock.
        self._recording: Recording | None = None
        self._rec_lock = threading.Lock()

        # Calibration mode. When `_calibrate_active` is True, _rps_hint_for
        # returns `_manual_rps` instead of doing the table interpolation —
        # so the operator can iterate RPS by hand on the calibrate page,
        # fire, observe, log the row that worked, and move on.
        # `_spin_up_delay_s` mirrors `/Sight/Aim/SpinUpDelayS` to NT every
        # detection tick; AutoAim reads it for its flywheel-settle window.
        self._calibrate_active = False
        self._manual_rps: float = float(
            os.environ.get("CFS_DEFAULT_MANUAL_RPS", "60.0")
        )
        self._spin_up_delay_s: float = float(
            os.environ.get("CFS_DEFAULT_SPIN_UP_DELAY_S", "0.4")
        )
        # Multiplier applied to PnP-derived range. 1.0 = no correction.
        # Loaded from RANGE_CAL_PATH on init (so it survives reboots);
        # a single-shot calibration (true distance entered on the
        # calibrate page) updates it via solve scale = true / measured.
        self._range_scale: float = self._load_range_scale()

        # Rolling FPS estimates for the debug panel.
        self._fps_capture = 0.0
        self._fps_detect = 0.0
        self._last_capture_t = 0.0
        self._last_detect_t = 0.0

        # Detector setup. The 36h11 family is what FRC standardized on in
        # 2023; opencv ships the dictionary built-in, no extra deps.
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
        params = cv2.aruco.DetectorParameters()
        # Refining marker corners with the contour fit helps PnP a lot
        # without much CPU cost.
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self._detector = cv2.aruco.ArucoDetector(dictionary, params)

        # Real intrinsics if available; otherwise FOV synthesis. Logged at
        # startup so the debug panel can show which path is in use.
        self._K, self._dist, self.intrinsics_source = _load_intrinsics()
        log.info("intrinsics: %s", self.intrinsics_source)
        # Object points for one tag, centered at origin in the tag's frame.
        # Order matches the corner order ArucoDetector returns
        # (top-left, top-right, bottom-right, bottom-left, looking at the tag).
        s = TAG_SIZE_M / 2.0
        self._tag_obj_points = np.array([
            [-s,  s, 0], [ s,  s, 0], [ s, -s, 0], [-s, -s, 0]
        ], dtype=np.float64)

    # ----- selection (click-to-target) -----

    def set_selected_tag(self, tag_id: int | None) -> None:
        if tag_id is None:
            if self._selected_tag_id is not None:
                log.info("selected tag cleared")
            self._selected_tag_id = None
            return
        if self._selected_tag_id != tag_id:
            log.info("selected tag → #%d", tag_id)
        self._selected_tag_id = int(tag_id)

    def selected_tag_id(self) -> int | None:
        return self._selected_tag_id

    # ----- calibrate mode (manual RPS override + spin-up delay) -----

    def set_calibrate_mode(self, active: bool) -> dict:
        prev = self._calibrate_active
        self._calibrate_active = bool(active)
        if prev != self._calibrate_active:
            log.info("calibrate mode → %s", "ON" if self._calibrate_active else "OFF")
        return self.calibrate_status()

    def set_manual_rps(self, rps: float) -> dict:
        # Clamp to a sane envelope. 0..500 covers any FRC shooter; we want
        # to refuse NaN / huge values that'd be a UI typo.
        try:
            v = float(rps)
        except (TypeError, ValueError):
            raise ValueError("rps must be a number")
        if not math.isfinite(v):
            raise ValueError("rps must be finite")
        self._manual_rps = max(0.0, min(500.0, v))
        return self.calibrate_status()

    def set_spin_up_delay(self, seconds: float) -> dict:
        try:
            v = float(seconds)
        except (TypeError, ValueError):
            raise ValueError("seconds must be a number")
        if not math.isfinite(v):
            raise ValueError("seconds must be finite")
        # Cap at 5s — anything longer is almost certainly a typo and
        # blocks the entire firing pipeline. Floor at 0.
        self._spin_up_delay_s = max(0.0, min(5.0, v))
        return self.calibrate_status()

    def calibrate_status(self) -> dict:
        det = self._latest_det
        # `last_range_m` is what _detect() produced this tick (already
        # scale-applied). Surface the *unscaled* value too so the
        # calibrate page can compute "you'd get X if scale were 1" if
        # it ever wants to.
        last_range_m = float(det.range_m) if det is not None else None
        last_unscaled_range_m = (
            (last_range_m / self._range_scale)
            if (last_range_m is not None and self._range_scale > 0)
            else None
        )
        return {
            "active": self._calibrate_active,
            "manual_rps": self._manual_rps,
            "spin_up_delay_s": self._spin_up_delay_s,
            "range_scale": self._range_scale,
            "last_range_m": last_range_m,
            "last_unscaled_range_m": last_unscaled_range_m,
            "tag_id": int(det.tag_id) if det is not None else None,
        }

    # ----- range-scale persistence -----

    def _load_range_scale(self) -> float:
        try:
            if RANGE_CAL_PATH.exists():
                data = json.loads(RANGE_CAL_PATH.read_text())
                v = float(data.get("scale", 1.0))
                if math.isfinite(v) and 0.1 <= v <= 10.0:
                    log.info("range_scale loaded from disk: %.4f", v)
                    return v
                log.warning("range_scale on disk out of range (%s); using 1.0", v)
        except Exception as e:
            log.warning("range_scale load failed (%s); using 1.0", e)
        return 1.0

    def _save_range_scale(self) -> None:
        try:
            RANGE_CAL_PATH.write_text(
                json.dumps({"scale": self._range_scale}, indent=2) + "\n"
            )
        except Exception as e:
            log.warning("range_scale save failed: %s", e)

    def set_range_scale(self, scale: float) -> dict:
        try:
            v = float(scale)
        except (TypeError, ValueError):
            raise ValueError("scale must be a number")
        if not math.isfinite(v) or v <= 0:
            raise ValueError("scale must be positive and finite")
        # Clamp to a sane envelope. 0.1..10 covers any plausible
        # intrinsics / tag-size error; outside that range the user
        # should fix `cam_intrinsics.json` or `TAG_SIZE_M` instead.
        v = max(0.1, min(10.0, v))
        if abs(v - self._range_scale) > 1e-6:
            log.info("range_scale: %.4f → %.4f", self._range_scale, v)
            self._range_scale = v
            self._save_range_scale()
        return self.calibrate_status()

    def calibrate_range_from_measurement(self, true_ft: float) -> dict:
        """Solve a new range_scale from the current detection.

        scale = (true distance) / (currently-reported, scale-applied distance)
              = (true distance) / (measured-PnP * old-scale)

        We compute against the live `range_m` (which has the previous
        scale already baked in), so the new scale supersedes the old
        one cleanly: applying it to the *unscaled* PnP value gives the
        true distance.
        """
        try:
            true_ft_v = float(true_ft)
        except (TypeError, ValueError):
            raise ValueError("true_ft must be a number")
        if not math.isfinite(true_ft_v) or true_ft_v <= 0:
            raise ValueError("true_ft must be positive")
        det = self._latest_det
        if det is None or det.range_m <= 0.05:
            raise ValueError("no tag in view — aim at the target first")
        true_m = true_ft_v * _FOOT_TO_M
        # det.range_m is already scale-applied. We want:
        #   new_scale * unscaled_pnp = true_m
        #   unscaled_pnp = det.range_m / old_scale
        #   ⇒ new_scale = true_m * old_scale / det.range_m
        new_scale = true_m * self._range_scale / det.range_m
        return self.set_range_scale(new_scale)

    def reset_range_scale(self) -> dict:
        return self.set_range_scale(1.0)

    # ----- recording -----

    def start_recording(self) -> dict:
        with self._rec_lock:
            if self._recording is not None:
                return self._recording.status()
            # Use the actual capture FPS we're achieving (clamped) — better
            # than hard-coding CAMERA_FPS, which is the *requested* fps.
            fps = self._fps_capture if self._fps_capture > 1 else float(CAMERA_FPS)
            rec = Recording(RECORDINGS_DIR, fps=fps, size=(CAMERA_WIDTH, CAMERA_HEIGHT))
            rec.start()
            self._recording = rec
            return rec.status()

    def stop_recording(self) -> dict:
        with self._rec_lock:
            rec = self._recording
            if rec is None:
                return {"active": False}
            path = rec.stop()
            self._recording = None
            return {"active": False, "path": path.name if path else None}

    def recording_status(self) -> dict:
        with self._rec_lock:
            return self._recording.status() if self._recording else {"active": False}

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
            "camera open: %dx%d @ %d fps target_tags=%s intrinsics=%s",
            CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS, sorted(TARGET_TAG_IDS),
            self.intrinsics_source,
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

            now = time.monotonic()
            if self._last_capture_t > 0:
                dt = now - self._last_capture_t
                if dt > 1e-3:
                    # EWMA — stable enough for a debug readout.
                    self._fps_capture = 0.85 * self._fps_capture + 0.15 * (1.0 / dt)
            self._last_capture_t = now

            self._frame_idx += 1
            det = self._latest_det
            if self._frame_idx % max(1, DETECT_EVERY) == 0:
                t0 = time.monotonic()
                det = self._detect(frame)
                self._latest_det = det
                if self._last_detect_t > 0:
                    dt = t0 - self._last_detect_t
                    if dt > 1e-3:
                        self._fps_detect = 0.85 * self._fps_detect + 0.15 * (1.0 / dt)
                self._last_detect_t = t0
                # Publish target + recommended RPS to NT every detection
                # tick — the rio sees the freshest values without any
                # request/response.
                rps_hint = self._rps_hint_for(det)
                ready = self._compute_ready(det)
                try:
                    self.nt.publish_target(
                        det, rps_hint, ready, self._selected_tag_id,
                    )
                    self.nt.publish_spin_up_delay(self._spin_up_delay_s)
                except Exception as e:
                    log.warning("nt publish failed: %s", e)

            # Draw overlay + encode. We always re-encode (even if the
            # detection didn't run) so the stream stays smooth.
            jpeg = self._render(frame, det)
            # If recording, capture the *rendered* frame (overlay + box +
            # crosshair drawn). Reading after _render means the writer
            # gets the same image the operator saw.
            rec = self._recording
            if rec is not None:
                rec.write(frame)
            with self._cond:
                self._latest_jpeg = jpeg
                self._frame_token += 1
                self._cond.notify_all()

    def _compute_ready(self, det: "Detection | None") -> bool:
        if det is None:
            return False
        if abs(det.bearing_deg) > READY_BEARING_DEG:
            return False
        # Don't claim ready while AutoAim is already running (it owns the
        # heading PID; a "ready" indicator would be misleading).
        if self.nt._b_subs["driver_lockout"].get():
            return False
        if not self.nt._b_subs["robot_enabled"].get():
            return False
        return True

    def _rps_hint_for(self, det: Detection | None) -> float | None:
        # Calibrate-mode override: publish the operator's hand-set RPS
        # instead of the table lookup. When calibrating, the dashboard
        # is iterating manual RPS values — we want SHOOT to fire at the
        # value the operator picked, not at whatever the table says.
        if self._calibrate_active:
            return float(self._manual_rps)
        # Distance comes from PnP on the visible tag. Accuracy drops past
        # a few meters because tag pixel size shrinks; calibrate the
        # camera (cam_intrinsics.json) for sub-degree bearings + better
        # range at distance.
        if det is None or det.range_m <= 0.05:
            return None
        return self.calibration.lookup_rps(det.range_m / _FOOT_TO_M)

    # ----- detection -----

    def _detect(self, bgr: np.ndarray) -> Detection | None:
        # Detection runs on a downscaled grey copy when DETECT_DOWNSCALE<1.
        # At 480p we run full-res by default — corner refinement is more
        # accurate without the resize and we have CPU to spare.
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
        # detections in a different color and so the click-to-target hit
        # test on the browser side works against authoritative pixel coords.
        self._latest_all = [
            (int(tid), c.reshape(-1, 2).astype(np.float32))
            for tid, c in zip(ids.flatten().tolist(), scaled_corners)
        ]

        # Target selection:
        # - If the operator clicked a tag (selected_tag_id is set), only
        #   that tag can be the target. If it's not visible right now we
        #   return None — DON'T silently fall back to TARGET_TAG_IDS or
        #   we'd auto-aim at a different tag than what the operator
        #   picked. The selection ID stays so the UI can show
        #   "tag #7 — searching".
        # - Otherwise (no manual lock), pick the largest tag whose ID is
        #   in TARGET_TAG_IDS.
        selected = self._selected_tag_id
        chosen_corners: np.ndarray | None = None
        chosen_id: int | None = None
        chosen_locked = False

        if selected is not None:
            for tag_id, corners in self._latest_all:
                if tag_id == selected:
                    chosen_id = tag_id
                    chosen_corners = corners
                    chosen_locked = True
                    break
            if chosen_corners is None:
                return None
        else:
            candidates = [
                (tid, c) for tid, c in self._latest_all
                if not TARGET_TAG_IDS or tid in TARGET_TAG_IDS
            ]
            if not candidates:
                return None
            def area(c: np.ndarray) -> float:
                return float(cv2.contourArea(c.astype(np.float32)))
            chosen_id, chosen_corners = max(candidates, key=lambda c: area(c[1]))

        pts = chosen_corners.reshape(-1, 2)
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
        # Apply the user's range-scale correction. PnP-range error is
        # multiplicative (caused by intrinsics or tag-size mis-spec, both
        # of which scale linearly), so a single scalar fixes it. Default
        # scale is 1.0 (no correction).
        range_m *= self._range_scale

        return Detection(
            tag_id=int(chosen_id) if chosen_id is not None else 0,
            bearing_deg=bearing_deg,
            range_m=range_m,
            cx_norm=cx_px / CAMERA_WIDTH,
            cy_norm=cy_px / CAMERA_HEIGHT,
            corners_px=pts,
            ts=time.monotonic(),
            selected_locked=chosen_locked,
        )

    # ----- rendering -----

    def _render(self, frame: np.ndarray, det: Detection | None) -> bytes:
        # Center crosshair (always on). Color by ready-state so the operator
        # gets a "good to fire" signal without taking eyes off the camera.
        h, w = frame.shape[:2]
        if det is not None and abs(det.bearing_deg) <= READY_BEARING_DEG:
            crosshair = (0, 255, 0)  # green = ready
        else:
            crosshair = (255, 255, 255)
        cv2.line(frame, (w // 2, 0), (w // 2, h), crosshair, 1, cv2.LINE_AA)
        cv2.line(frame, (0, h // 2), (w, h // 2), crosshair, 1, cv2.LINE_AA)

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
            thickness = 3 if det.selected_locked else 2
            cv2.polylines(frame, [pts], isClosed=True, color=color,
                          thickness=thickness, lineType=cv2.LINE_AA)
            # Draw a dotted-style outline for operator-locked targets so it
            # reads as "you picked this one" vs "auto-picked by ID list".
            if det.selected_locked:
                for i, p in enumerate(pts):
                    cv2.circle(frame, tuple(p), 4, color, -1, cv2.LINE_AA)
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
    """Server-Sent Events feed of robot + target state for the live HUD.

    Includes:
      - rio-side NT topics (with per-topic age in ms so the UI can dim
        stale values rather than confidently displaying defaults)
      - the chosen target detection (with image-pixel corners for the UI
        to draw an overlay box that doesn't depend on the MJPEG arriving)
      - every detected tag with image-pixel corners (for the click-to-
        target hit-test on the browser)
      - selected_tag_id (operator's locked tag, if any)
      - image_size, recommended_rps, fps counters, version
    """
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
                # Ready-to-fire is computed by the engine each detect tick;
                # recompute here too so the SSE always has the latest
                # value even when detection lags by one tick.
                ready = camera._compute_ready(det)
                if det is not None:
                    snap["target"] = {
                        "detected": True,
                        "tag_id": det.tag_id,
                        "bearing_deg": det.bearing_deg,
                        "range_m": det.range_m,
                        "cx_norm": det.cx_norm,
                        "cy_norm": det.cy_norm,
                        "corners_px": det.corners_px.tolist(),
                        "selected_locked": det.selected_locked,
                        "ready": ready,
                        "age_ms": int((time.monotonic() - det.ts) * 1000),
                    }
                else:
                    snap["target"] = {"detected": False, "ready": False}
                snap["recommended_rps"] = camera._rps_hint_for(det)
                # Every tag the detector saw this tick. Browser uses this
                # to hit-test clicks against authoritative pixel coords.
                snap["all_tags"] = [
                    {"tag_id": int(tid), "corners_px": c.tolist()}
                    for tid, c in camera._latest_all
                ]
                snap["seen_tags"] = sorted({tid for tid, _ in camera._latest_all})
                snap["selected_tag_id"] = camera.selected_tag_id()
                snap["image_size"] = {"w": CAMERA_WIDTH, "h": CAMERA_HEIGHT}
                snap["fps"] = {
                    "capture": round(camera._fps_capture, 1),
                    "detect": round(camera._fps_detect, 1),
                }
                snap["version"] = VERSION
                snap["intrinsics_source"] = camera.intrinsics_source
                # Surface the rio NT host so the dashboard can show
                # *which* address we're dialing — without this, "rio
                # disconnected" gives the operator no information about
                # whether it's a wrong-team / wrong-IP / unreachable issue.
                snap["nt_host"] = nt.inst.server_host()
                snap["target_tag_ids"] = sorted(TARGET_TAG_IDS)
                snap["ready_bearing_deg"] = READY_BEARING_DEG
                # Reshape the flat op_*/dr_* button keys into per-stick
                # blocks so the UI can render two panels with one loop.
                # Older flat keys are dropped from the SSE shape — the UI
                # was already going to be rewritten.
                snap["operator"] = {
                    "pov": snap.pop("op_pov", -1),
                    "btn_a": snap.pop("op_btn_a", False),
                    "btn_b": snap.pop("op_btn_b", False),
                    "btn_x": snap.pop("op_btn_x", False),
                    "btn_y": snap.pop("op_btn_y", False),
                    "btn_lb": snap.pop("op_btn_lb", False),
                    "btn_rb": snap.pop("op_btn_rb", False),
                }
                snap["driver"] = {
                    "pov": snap.pop("dr_pov", -1),
                    "btn_a": snap.pop("dr_btn_a", False),
                    "btn_b": snap.pop("dr_btn_b", False),
                    "btn_x": snap.pop("dr_btn_x", False),
                    "btn_y": snap.pop("dr_btn_y", False),
                    "btn_lb": snap.pop("dr_btn_lb", False),
                    "btn_rb": snap.pop("dr_btn_rb", False),
                }
                snap["recording"] = camera.recording_status()
                snap["calibrate"] = camera.calibrate_status()
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


@app.get("/api/logs")
async def api_logs(request: Request) -> StreamingResponse:
    """Server-Sent Events feed of recent server log lines.

    Sends the current ring buffer immediately on connect (so the panel
    isn't blank), then waits on _log_cv for new entries. Each event is a
    JSON object — see _RingHandler for the shape.
    """
    async def event_stream() -> AsyncIterator[str]:
        # Snapshot the existing ring so we can deliver it before any new
        # writes arrive. Using sequence numbers means we never resend the
        # same line twice, even if the buffer wraps.
        with _log_lock:
            initial = list(_LOG_RING)
            last_seq = initial[-1]["seq"] if initial else 0
        for entry in initial:
            if await request.is_disconnected():
                return
            yield f"data: {json.dumps(entry)}\n\n"

        # Then poll for new entries. We can't use threading.Condition.wait
        # directly from async code; run it in a thread executor.
        loop = asyncio.get_running_loop()

        def _wait_for_new(prev_seq: int, timeout: float) -> list[dict]:
            with _log_cv:
                _log_cv.wait_for(
                    lambda: (_LOG_RING and _LOG_RING[-1]["seq"] > prev_seq),
                    timeout=timeout,
                )
                return [e for e in _LOG_RING if e["seq"] > prev_seq]

        while not await request.is_disconnected():
            new_entries = await loop.run_in_executor(None, _wait_for_new, last_seq, 1.0)
            for entry in new_entries:
                yield f"data: {json.dumps(entry)}\n\n"
                last_seq = entry["seq"]

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/target")
async def api_target(payload: dict) -> JSONResponse:
    """Set or clear the operator's locked target.

    Body: {"tag_id": <int>} to lock onto a tag, or {"tag_id": null} to
    fall back to TARGET_TAG_IDS-based selection.
    """
    raw = payload.get("tag_id") if isinstance(payload, dict) else None
    if raw is None or raw == "" or (isinstance(raw, str) and raw.lower() == "null"):
        camera.set_selected_tag(None)
        return JSONResponse({"ok": True, "selected_tag_id": None})
    try:
        tag_id = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="tag_id must be int or null")
    camera.set_selected_tag(tag_id)
    return JSONResponse({"ok": True, "selected_tag_id": tag_id})


@app.post("/api/record/start")
async def api_record_start() -> JSONResponse:
    """Start a new recording. No-op if already recording."""
    try:
        status = camera.start_recording()
        return JSONResponse({"ok": True, **status})
    except Exception as e:
        log.exception("recording start failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/record/stop")
async def api_record_stop() -> JSONResponse:
    """Stop the active recording. No-op if nothing's recording."""
    status = camera.stop_recording()
    return JSONResponse({"ok": True, **status})


@app.get("/api/record/status")
async def api_record_status() -> JSONResponse:
    return JSONResponse(camera.recording_status())


@app.get("/api/recordings")
async def api_recordings_list() -> JSONResponse:
    """List recordings under RECORDINGS_DIR with size + mtime."""
    out = []
    try:
        for p in sorted(RECORDINGS_DIR.iterdir(), key=lambda x: x.name, reverse=True):
            if not p.is_file():
                continue
            try:
                st = p.stat()
            except Exception:
                continue
            out.append({
                "name": p.name,
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
    except FileNotFoundError:
        pass
    return JSONResponse({"dir": str(RECORDINGS_DIR), "items": out})


@app.get("/recordings/{name}")
async def api_recording_download(name: str) -> FileResponse:
    """Download one recording. The filename is restricted to the safe
    charset we generate ourselves — no slashes, no traversal."""
    if not _FILENAME_RE.match(name):
        raise HTTPException(status_code=400, detail="bad filename")
    path = RECORDINGS_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    # Resolve and re-check parent — defense in depth against symlink races.
    try:
        path = path.resolve()
        if RECORDINGS_DIR.resolve() not in path.parents:
            raise HTTPException(status_code=400, detail="bad path")
    except Exception:
        raise HTTPException(status_code=400, detail="bad path")
    # MP4 first; fall back on AVI.
    media = "video/mp4" if path.suffix.lower() == ".mp4" else "video/x-msvideo"
    return FileResponse(path, media_type=media, filename=name)


@app.delete("/api/recordings/{name}")
async def api_recording_delete(name: str) -> JSONResponse:
    if not _FILENAME_RE.match(name):
        raise HTTPException(status_code=400, detail="bad filename")
    path = RECORDINGS_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    try:
        path.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse({"ok": True})


@app.get("/recordings.html")
async def recordings_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "recordings.html")


@app.get("/api/calibrate/status")
async def api_calibrate_status() -> JSONResponse:
    return JSONResponse(camera.calibrate_status())


@app.post("/api/calibrate/mode")
async def api_calibrate_mode(payload: dict) -> JSONResponse:
    """Toggle calibrate mode. Body: {"active": true|false}.

    When active, the Pi publishes the operator's `manual_rps` to
    /Sight/Aim/TargetRps instead of the calibration-table interpolation.
    SHOOT then fires at exactly that RPS — letting the operator iterate
    by hand and log the row that worked.
    """
    active = bool(payload.get("active", False)) if isinstance(payload, dict) else False
    return JSONResponse({"ok": True, **camera.set_calibrate_mode(active)})


@app.post("/api/calibrate/rps")
async def api_calibrate_rps(payload: dict) -> JSONResponse:
    """Set the manual RPS override used while calibrate mode is active.

    Body: {"rps": <number>}. Range is clamped to [0, 500].
    """
    if not isinstance(payload, dict) or "rps" not in payload:
        raise HTTPException(status_code=400, detail="rps (number) required")
    try:
        return JSONResponse({"ok": True, **camera.set_manual_rps(payload["rps"])})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/calibrate/spin_up_delay")
async def api_calibrate_spin_up_delay(payload: dict) -> JSONResponse:
    """Set the flywheel spin-up delay AutoAim uses (seconds).

    Body: {"seconds": <number>}. Range is clamped to [0, 5].
    """
    if not isinstance(payload, dict) or "seconds" not in payload:
        raise HTTPException(status_code=400, detail="seconds (number) required")
    try:
        return JSONResponse({"ok": True, **camera.set_spin_up_delay(payload["seconds"])})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/calibrate/range/scale")
async def api_calibrate_range_scale(payload: dict) -> JSONResponse:
    """Set the PnP range-scale multiplier directly.

    Body: {"scale": <number>}. Range is clamped to [0.1, 10]. Scale is
    persisted to RANGE_CAL_PATH so it survives Pi restarts.
    """
    if not isinstance(payload, dict) or "scale" not in payload:
        raise HTTPException(status_code=400, detail="scale (number) required")
    try:
        return JSONResponse({"ok": True, **camera.set_range_scale(payload["scale"])})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/calibrate/range/calibrate")
async def api_calibrate_range_from_measurement(payload: dict) -> JSONResponse:
    """Solve range_scale from one measurement.

    Body: {"true_ft": <number>}. Operator stands at a known distance,
    aims the camera at the goal tag, types in the actual distance — the
    server uses the current (scale-applied) PnP range to compute
    scale = true / measured and applies it. Persisted on success.

    Errors with 400 if no tag is currently visible.
    """
    if not isinstance(payload, dict) or "true_ft" not in payload:
        raise HTTPException(status_code=400, detail="true_ft (number) required")
    try:
        return JSONResponse({"ok": True, **camera.calibrate_range_from_measurement(payload["true_ft"])})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/calibrate/range/reset")
async def api_calibrate_range_reset() -> JSONResponse:
    """Reset range_scale to 1.0 (no correction). Persists."""
    return JSONResponse({"ok": True, **camera.reset_range_scale()})


@app.get("/calibrate.html")
async def calibrate_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "calibrate.html")


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
        "version": VERSION,
        "nt_connected": nt.inst.is_connected(),
        "target_tag_ids": sorted(TARGET_TAG_IDS),
        "calibration_points": len(calibration.points()),
        "intrinsics_source": camera.intrinsics_source,
        "image_size": {"w": CAMERA_WIDTH, "h": CAMERA_HEIGHT},
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="info")
