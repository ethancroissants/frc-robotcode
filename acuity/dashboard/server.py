"""Acuity — vision-coprocessor on-device server.

Runs on the Pi, owns the entire vision pipeline, and serves both the
NT4 schema that robot code consumes and the web dashboard a team
opens at `http://acuity-NNNN.local:8080/` to point the camera + watch
detections in real time.

End-to-end flow
---------------
1. cv2.VideoCapture grabs MJPEG straight off /dev/video0.
2. pyapriltags detects 36h11 AprilTags on a downscaled grey copy of
   every frame. Same upstream library WPILib + PhotonVision use.
3. Per detection we compute distance + yaw + pitch + decision margin
   and push them into a thread-safe latest-detections snapshot.
4. NT4 client publishes the snapshot under `/acuity/*` (schema in
   acuity/docs/nt4-schema.md) so robot code reads typed values
   without doing any vision work.
5. The browser hits `/stream.mjpg` (raw MJPEG passthrough — we never
   decode + re-encode just for display) and `/api/detections.ws`
   (WebSocket pushing the same snapshot at frame rate). The dashboard
   draws SVG overlays client-side so the Pi never spends CPU on
   cv2.putText / cv2.line for boxes that the browser is going to
   redraw anyway.

This is the *generic* product dashboard. Team-specific UI (shooter
calibration, gamepad mapper, etc.) lives in their own robot code
or in the dashboard-legacy/ tree we forked from.

Run with: uvicorn server:app --host 0.0.0.0 --port 8080
The acuity-dashboard.service systemd unit calls exactly that.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import math
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

# pyapriltags publishes aarch64 wheels for cp310+ and wraps the same
# upstream C++ AprilTag library WPILib / PhotonVision use. Optional —
# fall back to OpenCV's port if it's not installed (worse range, but
# the dashboard still boots).
try:
    import pyapriltags as _pa  # type: ignore[import]
    _HAVE_PA = True
except Exception:
    _pa = None
    _HAVE_PA = False

import nt4_client  # type: ignore[import]


# ---------------------------------------------------------------------
# Paths + config
# ---------------------------------------------------------------------

HERE         = Path(__file__).resolve().parent
STATIC_DIR   = HERE / "static"
SETTINGS_PATH = Path(os.environ.get("ACUITY_SETTINGS",
                                    "/var/lib/acuity/settings.json"))
ACUITY_CONF  = Path("/boot/firmware/acuity.conf")

# Schema version this server publishes — must match
# /acuity/version. Bump only on breaking changes (see nt4-schema.md).
SCHEMA_VERSION = 1
# Build identifier — overwritten at install time by a CI step or by
# install.sh writing $ACUITY_DIR/dashboard/.build. Defaulted so a
# fresh clone advertises something useful.
BUILD_ID = (HERE / ".build").read_text().strip() if (HERE / ".build").exists() \
           else "acuity-dev"

log = logging.getLogger("acuity.server")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


# ---------------------------------------------------------------------
# Settings — small JSON file users can edit via the dashboard.
#
# Defaults are tuned for "Pi Zero 2 W with the v3 camera" — the
# reference SKU. Teams with a different camera change them here.
# ---------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, Any] = {
    # Capture — full resolution, used for AprilTag detection so distance
    # range stays good. Browser stream is downscaled separately (below).
    "camera_index":     0,
    "resolution":       [1280, 720],   # [w, h]
    "target_fps":       30,
    "flip_horizontal":  False,
    "flip_vertical":    False,

    # Stream — what the browser/Manager actually receives. Defaults
    # tuned for 2.4 GHz WiFi: 640x360 @ q=60 is ~25 KB/frame, ~600
    # KB/s @ 30 fps — comfortable on a team radio. If you have wired
    # ethernet or 5 GHz you can crank both up via the Settings tab.
    # "stream_max_fps": 0 means "match capture FPS"; set lower (e.g.
    # 20) to throttle stream without slowing detection.
    "stream_resolution": [640, 360],
    "stream_quality":    60,           # JPEG q. 55-65 is the AprilTag-decodable floor.
    "stream_max_fps":    0,

    # Detection
    #
    # Defaults match the legacy team-tested configuration that hit
    # ~25 ft range on a 6.5" tag with a Pi Camera + 60° HFOV. Tighter
    # values broke detection in field testing — we tried decimate=2
    # for "speed" and margin_min=30 to "drop weak detections" and
    # both regressed range significantly. Don't tune these without
    # bench-testing against a real tag at distance.
    "tag_family":       "tag36h11",
    "tag_size_m":       0.1651,        # 6.5 in — 2025 FRC standard
    "min_decision_margin": 0.0,        # 0 = no filtering. pyapriltags' own
                                       # gating is already conservative.
    "camera_hfov_deg":  60.0,          # used to synthesize fx/fy when no
                                       # cam_intrinsics.json is present.
    "quad_decimate":    1.0,           # 1.0 = full resolution. Higher is
                                       # faster but loses distant tags.
    "quad_sigma":       0.0,
    "decode_sharpening": 0.25,

    # NT4
    "nt_team":          0,             # 0 → server mode (publish only)
    "nt_server_host":   "",            # blank → use roborio-{team}-frc.local

    # Targeting
    # If the operator clicks a tag in the camera view, that ID lands
    # here and overrides automatic best-target selection. Set to -1
    # to clear. preferred_tag_ids is the next fallback (empty list →
    # "any tag is fair game").
    "selected_tag_id":   -1,
    "preferred_tag_ids": [],

    # Crosshair calibration. The robot may have its launcher / arm
    # mounted off-axis from the camera; teams calibrate by aiming at
    # a tag, marking where the projectile actually lands relative to
    # the image center, and saving those normalized pixel offsets
    # here. Once set, the published yaw_deg / pitch_deg are offsets
    # from the CROSSHAIR, not from the optical center — so robot code
    # can run a heading PID straight off the topic and hit the spot
    # the human calibrated. Range [-1, 1] (full frame). Defaults to
    # the optical center.
    "crosshair_x":        0.0,
    "crosshair_y":        0.0,

    # ----- Color-blob (game-piece) pipeline -----
    #
    # Optional second detector that runs in the same thread, on the
    # same frame, after AprilTag detection finishes. Off by default
    # because most teams just want tags; flip on via the dashboard
    # Settings tab or `POST /api/settings {"enable_objects": true}`.
    #
    # CPU cost on a Pi Zero 2 W at default settings: ~5 ms/frame for
    # a 320x240 mask. Comfortably within budget alongside AprilTag.
    "enable_objects":     False,
    # HSV thresholds (OpenCV ranges: H 0-179, S 0-255, V 0-255). The
    # defaults match a saturated red game piece — tune via the
    # dashboard's Settings tab, watching the live mask preview.
    "hsv_lower":          [0,   100, 100],
    "hsv_upper":          [10,  255, 255],
    # Drop blobs smaller than this (in PIXELS, post-downscale). Stops
    # the detector from latching onto noise.
    "min_object_area_px": 200,
    # Hard cap on results per frame so a noisy mask can't OOM the
    # NT all-objects payload.
    "max_objects":        5,
    # Run the mask at original / N resolution. 2 is a good speed/
    # accuracy trade for a Pi Zero 2 W; bump to 1 if you have CPU
    # headroom and want sub-pixel object centers.
    "object_downscale":   2,
}


def _load_settings() -> dict[str, Any]:
    """Merge on-disk overrides over the defaults. Bad JSON → defaults."""
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        loaded = json.loads(SETTINGS_PATH.read_text())
    except Exception as e:
        log.warning("settings file is malformed (%s) — using defaults", e)
        return dict(DEFAULT_SETTINGS)
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in loaded.items() if k in DEFAULT_SETTINGS})
    return out


def _save_settings(s: dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2))
    os.replace(tmp, SETTINGS_PATH)


# ---------------------------------------------------------------------
# Camera capture
# ---------------------------------------------------------------------

class CameraThread(threading.Thread):
    """Reads frames off /dev/video* in MJPEG mode at full speed and
    keeps the latest one in `self.latest_jpeg` for the streamer.

    We also buffer the last decoded BGR frame for the AprilTag
    detector — but the decode + tag pass run in a *separate* worker
    thread so a slow detector never starves the MJPEG stream. The
    browser sees full camera FPS even if detection drops to 5 Hz.
    """

    def __init__(self, settings_provider):
        super().__init__(daemon=True, name="camera")
        self._settings = settings_provider
        self._stop = threading.Event()

        self.latest_jpeg: Optional[bytes] = None    # raw MJPEG frame
        self.latest_bgr:  Optional[np.ndarray] = None  # decoded for detector
        self.latest_mono = None
        self.latest_ts:   float = 0.0
        self.fps:         float = 0.0
        self.frame_count: int = 0
        self.connected:   bool = False
        self.resolution:  tuple[int, int] = (0, 0)
        self._lock = threading.Lock()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        cap = None
        last_settings = None
        last_fps_t = time.monotonic()
        last_fps_count = 0

        while not self._stop.is_set():
            s = self._settings()
            cam_idx = int(s["camera_index"])
            res = tuple(s["resolution"])
            target_fps = int(s["target_fps"])

            # Re-open if camera index, resolution, or FPS changed.
            cfg_key = (cam_idx, res, target_fps)
            if cap is None or cfg_key != last_settings:
                if cap is not None:
                    cap.release()
                log.info("opening camera %d at %dx%d @ %d fps", cam_idx, *res, target_fps)
                cap = cv2.VideoCapture(cam_idx, cv2.CAP_V4L2)
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH,  res[0])
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, res[1])
                cap.set(cv2.CAP_PROP_FPS,          target_fps)
                self.connected = cap.isOpened()
                if not self.connected:
                    log.warning("camera %d failed to open", cam_idx)
                    time.sleep(1.0)
                    continue
                last_settings = cfg_key

            ok, frame = cap.read()
            if not ok or frame is None:
                self.connected = False
                time.sleep(0.05)
                continue
            self.connected = True

            # Apply CSS-style flips on capture, not on the served stream.
            # The browser doesn't get to flip (it's MJPEG passthrough),
            # so we have to do it here if the user turned it on.
            if s["flip_horizontal"] and s["flip_vertical"]:
                frame = cv2.flip(frame, -1)
            elif s["flip_horizontal"]:
                frame = cv2.flip(frame, 1)
            elif s["flip_vertical"]:
                frame = cv2.flip(frame, 0)

            # Encode once per frame for the MJPEG stream. Two knobs the
            # operator can tweak from the Settings tab to trade image
            # quality for network bandwidth + latency:
            #
            #   stream_resolution: [w, h] — we cv2.resize the frame
            #     down to this size before encoding. Big win on WiFi:
            #     1280x720 → 640x360 cuts the JPEG roughly 4x. Set to
            #     match `resolution` for no downscale.
            #
            #   stream_quality: JPEG quality 5..95. 55-65 is the floor
            #     where AprilTags stay decodable for the operator and
            #     network traffic is minimal.
            #
            #   stream_max_fps: stream-side FPS cap (0 → match capture).
            #     Useful when the camera has to run high FPS for the
            #     detector but the operator only needs a 20 fps preview.
            stream_w, stream_h = (s["stream_resolution"] or [frame.shape[1], frame.shape[0]])
            if stream_w != frame.shape[1] or stream_h != frame.shape[0]:
                stream_frame = cv2.resize(
                    frame, (int(stream_w), int(stream_h)),
                    interpolation=cv2.INTER_AREA,
                )
            else:
                stream_frame = frame
            jpeg_q = max(5, min(95, int(s["stream_quality"])))
            ok, jpg = cv2.imencode(".jpg", stream_frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, jpeg_q])
            if not ok:
                continue

            mono = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            now = time.monotonic()
            with self._lock:
                self.latest_jpeg = jpg.tobytes()
                self.latest_bgr  = frame
                self.latest_mono = mono
                self.latest_ts   = now
                self.frame_count += 1
                self.resolution  = (frame.shape[1], frame.shape[0])

            # FPS, smoothed every second.
            if now - last_fps_t >= 1.0:
                self.fps = (self.frame_count - last_fps_count) / (now - last_fps_t)
                last_fps_t = now
                last_fps_count = self.frame_count

        if cap is not None:
            cap.release()


# ---------------------------------------------------------------------
# AprilTag detection
# ---------------------------------------------------------------------

class Detection(dict):
    """One AprilTag detection. Behaves like a dict so it serializes
    straight to JSON / NT4 for free, but the field names are
    documented and stable — see acuity/docs/nt4-schema.md."""


class TagDetectorThread(threading.Thread):
    """Pulls frames from the camera, runs pyapriltags, computes
    distance/yaw/pitch via PnP using the configured tag size, and
    publishes the latest snapshot to a subscriber callback."""

    def __init__(self, camera: CameraThread, settings_provider, on_snapshot):
        super().__init__(daemon=True, name="detector")
        self._camera = camera
        self._settings = settings_provider
        self._on_snapshot = on_snapshot
        self._stop = threading.Event()
        self._last_processed_ts = 0.0

        # The detector itself is created lazily inside _detect() and
        # re-built when any of its tuning settings change at runtime
        # via /api/settings. pyapriltags doesn't expose runtime
        # parameter setters, so we keep a (settings_signature →
        # Detector) cache and rebuild on miss. Avoids a startup-time
        # baked-in config that the operator can't change.
        self._detector = None
        self._detector_sig = None
        if not _HAVE_PA:
            log.warning("pyapriltags missing; falling back to cv2.aruco "
                        "(reduced range, less precise pose)")

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            ts = self._camera.latest_ts
            if ts == 0 or ts == self._last_processed_ts:
                time.sleep(0.005)
                continue
            self._last_processed_ts = ts

            with self._camera._lock:
                mono = self._camera.latest_mono
                bgr  = self._camera.latest_bgr
                w, h = self._camera.resolution
            if mono is None or bgr is None:
                continue

            s = self._settings()
            tags = self._detect(mono, w, h, s)
            best = self._pick_best(tags, s)

            # Optional color-blob pass on the same BGR frame. Off by
            # default; toggled per-frame via settings so the operator
            # can A/B test without restarting.
            objects: list[dict[str, Any]] = []
            best_object: Optional[dict[str, Any]] = None
            if bool(s.get("enable_objects", False)):
                objects = self._detect_objects(bgr, w, h, s)
                if objects:
                    best_object = max(objects, key=lambda o: o["area"])

            wall_now = time.time()
            self._on_snapshot({
                "tags":         tags,
                "best":         best,
                "objects":      objects,
                "best_object":  best_object,
                "frame_ts":     ts,
                # Latency from frame capture to publication. Robot
                # code subtracts this from FPGA "now" to get the
                # capture instant. Limelight's `tl` field (with their
                # other latency offset folded in).
                "latency_ms":   max(0.0, (wall_now - ts) * 1000.0),
                "width":        w,
                "height":       h,
                "fps":          self._camera.fps,
                "connected":    self._camera.connected,
                "wall_ts":      wall_now,
            })

    def _ensure_detector(self, s: dict[str, Any]):
        """Build (or rebuild) the pyapriltags Detector when any of
        its constructor-time params change. Returns None if
        pyapriltags isn't installed."""
        if not _HAVE_PA:
            return None
        sig = (
            float(s.get("quad_decimate", 1.0)),
            float(s.get("quad_sigma", 0.0)),
            float(s.get("decode_sharpening", 0.25)),
        )
        if self._detector is not None and sig == self._detector_sig:
            return self._detector
        try:
            self._detector = _pa.Detector(
                families="tag36h11",
                nthreads=2,
                quad_decimate=sig[0],
                quad_sigma=sig[1],
                refine_edges=1,
                decode_sharpening=sig[2],
                debug=0,
            )
            self._detector_sig = sig
            log.info("AprilTag detector rebuilt: decimate=%.2f sigma=%.2f sharpen=%.2f",
                     *sig)
            return self._detector
        except Exception:
            log.exception("pyapriltags detector failed to construct")
            self._detector = None
            return None

    def _detect(self, mono: np.ndarray, w: int, h: int,
                s: dict[str, Any]) -> list[Detection]:
        """Detection — ported 1:1 from the team's legacy dashboard,
        which is the configuration that hit ~25 ft on a 6.5" tag.
        Three things matter and they are NOT what pyapriltags'
        defaults give you:

          1. `estimate_tag_pose=False`. pyapriltags' built-in pose
             estimator is less reliable than cv2.solvePnP — its
             accuracy depends on intrinsics being almost perfect,
             and even small mismatches make it flag detections as
             low-confidence and effectively drop them.

          2. **cv2.solvePnP with SOLVEPNP_IPPE_SQUARE** for the
             distance. IPPE_SQUARE is the algorithm the OpenCV docs
             specifically recommend for square fiducial markers.

          3. **Yaw/pitch from corner-center pixel offsets**, not
             from pose_t. `bearing = atan2(cx_px - principal_x, fx)`
             is robust to all the intrinsics-mismatch problems
             above; it's only sensitive to fx (which we synthesize
             from HFOV) and is correct as long as the camera is
             approximately rectilinear.

          4. pyapriltags returns corners in BL, BR, TR, TL order;
             cv2.aruco (and our PnP object points) use TL, TR, BR,
             BL. We reverse on the way out so the rest of the
             pipeline is detector-agnostic.
        """
        det = self._ensure_detector(s)
        if det is None:
            return []

        try:
            results = det.detect(mono, estimate_tag_pose=False)
        except Exception as e:
            log.warning("pyapriltags detect raised: %s", e)
            return []

        if not results:
            return []

        # Synthesize pinhole intrinsics from horizontal FOV. Exact
        # formula the legacy team dashboard uses.
        hfov_deg = float(s.get("camera_hfov_deg", 60.0))
        focal_x = (w / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
        focal_y = focal_x  # square-pixel assumption
        cx_p   = w / 2.0
        cy_p   = h / 2.0
        K = np.array([
            [focal_x, 0.0, cx_p],
            [0.0, focal_y, cy_p],
            [0.0, 0.0, 1.0],
        ], dtype=np.float64)
        dist_coeffs = np.zeros(5, dtype=np.float64)

        # Tag object points centered at origin, TL, TR, BR, BL —
        # matches the post-reverse corner order.
        tag_size = float(s["tag_size_m"])
        half = tag_size / 2.0
        tag_obj_points = np.array([
            [-half,  half, 0],
            [ half,  half, 0],
            [ half, -half, 0],
            [-half, -half, 0],
        ], dtype=np.float64)

        out: list[Detection] = []
        min_dm = float(s["min_decision_margin"])
        frame_area = max(1.0, float(w * h))

        # Crosshair offset, in pixels. Lets robot code treat
        # yaw_deg / pitch_deg as offsets FROM THE CROSSHAIR, not
        # from the optical center, which lets a team calibrate out a
        # camera that's mounted off-axis from their launcher. Default
        # crosshair is (0, 0) → center → no change.
        cx_offset_norm = float(s.get("crosshair_x", 0.0))
        cy_offset_norm = float(s.get("crosshair_y", 0.0))
        cross_px_x = cx_p + cx_offset_norm * cx_p
        cross_px_y = cy_p + cy_offset_norm * cy_p
        cross_yaw_deg   = math.degrees(math.atan2(cross_px_x - cx_p, focal_x))
        cross_pitch_deg = math.degrees(math.atan2(cy_p - cross_px_y, focal_y))

        for r in results:
            if getattr(r, "decision_margin", 0.0) < min_dm:
                continue

            # Reverse pyapriltags' BL, BR, TR, TL → TL, TR, BR, BL.
            corners = np.array(r.corners, dtype=np.float64)[::-1].copy()

            cx_px = float(corners[:, 0].mean())
            cy_px = float(corners[:, 1].mean())

            # Bearing (yaw) from pixel offset, then crosshair-adjusted
            # so 0° means "aim spot is on the calibrated crosshair."
            # Positive = right of the crosshair. CCW-positive when the
            # camera is mounted with +x to the right of the robot.
            yaw_deg   = math.degrees(math.atan2(cx_px - cx_p, focal_x)) - cross_yaw_deg
            # Pitch — same formula on the y axis, sign-flipped so
            # "up" is positive. Crosshair-adjusted to match yaw.
            pitch_deg = math.degrees(math.atan2(cy_p - cy_px, focal_y)) - cross_pitch_deg

            # Distance via cv2.solvePnP. SOLVEPNP_IPPE_SQUARE is the
            # OpenCV-recommended algorithm for square markers.
            distance_m = 0.0
            try:
                ok, _rvec, tvec = cv2.solvePnP(
                    tag_obj_points,
                    corners.astype(np.float64),
                    K,
                    dist_coeffs,
                    flags=cv2.SOLVEPNP_IPPE_SQUARE,
                )
                if ok:
                    distance_m = float(np.linalg.norm(tvec))
            except Exception:
                # solvePnP can raise on degenerate corner geometry;
                # treat as "no range estimate" rather than blowing
                # up the whole detection cycle.
                distance_m = 0.0

            # Normalized pixel offsets from the CROSSHAIR, [-1, 1].
            # Robot code that drives a heading PID reads tx straight
            # off the topic; 0 means "aim is on the calibrated
            # crosshair," not "tag is on the optical axis."
            tx = (cx_px - cross_px_x) / cx_p
            ty = (cy_px - cross_px_y) / cy_p

            area = abs(_polygon_area(corners)) / frame_area

            out.append(Detection(
                id=int(r.tag_id),
                distance_m=distance_m,
                yaw_deg=yaw_deg,
                pitch_deg=pitch_deg,
                tx=tx,
                ty=ty,
                area=area,
                timestamp=self._last_processed_ts,
                decision_margin=float(getattr(r, "decision_margin", 0.0)),
                corners=corners.tolist(),  # TL, TR, BR, BL — for the SVG overlay
            ))
        return out

    @staticmethod
    def _pick_best(tags: list[Detection],
                   s: dict[str, Any]) -> Optional[Detection]:
        if not tags:
            return None

        # Tier 1: an operator-clicked tag wins outright if it's still
        # in view. This is the "lock onto THIS tag" behaviour the
        # legacy team dashboard had — click the tag in the camera
        # frame and the robot keeps aiming at it even if a closer
        # nuisance tag pops into frame later.
        sel = int(s.get("selected_tag_id", -1))
        if sel >= 0:
            for t in tags:
                if t["id"] == sel:
                    return t
            # Fall through — clicked tag isn't visible right now.

        # Tier 2: filter to the preferred-IDs allowlist if set.
        preferred = set(int(x) for x in s.get("preferred_tag_ids", []))
        if preferred:
            filt = [t for t in tags if t["id"] in preferred]
            if filt:
                tags = filt

        # Tier 3: largest visible tag wins — proxies for closest.
        return max(tags, key=lambda t: t["area"])

    def _detect_objects(self, bgr: np.ndarray, w: int, h: int,
                        s: dict[str, Any]) -> list[dict[str, Any]]:
        """Color-blob (game-piece) detector.

        HSV threshold + connected-components on a downscaled copy of
        the BGR frame. Cheap on the Pi Zero 2 W (~5 ms at 320x240,
        the default), opt-in via `enable_objects`. Output schema is
        deliberately the same shape as a tag detection minus the
        AprilTag-specific fields, so robot code can treat the two
        almost interchangeably.

        Returns at most `max_objects` blobs, each:
          { id, cx, cy, area, yaw_deg, pitch_deg, tx, ty,
            width_px, height_px, timestamp }

        `id` is just an index in the per-frame list — colors don't
        have stable identifiers across frames and we don't try to
        track them; that's robot-side state.
        """
        try:
            ds = max(1, int(s.get("object_downscale", 2)))
            lower = np.asarray(s.get("hsv_lower", [0, 100, 100]),
                              dtype=np.uint8)
            upper = np.asarray(s.get("hsv_upper", [10, 255, 255]),
                              dtype=np.uint8)
            min_area = max(1, int(s.get("min_object_area_px", 200)))
            max_n    = max(1, int(s.get("max_objects", 5)))
        except (ValueError, TypeError):
            return []

        # Downscale, convert to HSV, threshold, clean up speckle. The
        # MORPH_OPEN pass costs ~1 ms on the Pi Zero 2 W and saves us
        # from chasing single-pixel noise blobs on the way out.
        if ds > 1:
            small = cv2.resize(bgr, (w // ds, h // ds),
                              interpolation=cv2.INTER_AREA)
        else:
            small = bgr
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower, upper)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return []

        # Scale-back factor so coordinates are reported in the original
        # frame's pixel space — robot code shouldn't have to know about
        # the downscale.
        sf = float(ds)
        hfov_deg = float(s.get("camera_hfov_deg", 60.0))
        focal_x = (w / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
        focal_y = focal_x
        cx_p = w / 2.0
        cy_p = h / 2.0
        cross_px_x = cx_p + float(s.get("crosshair_x", 0.0)) * cx_p
        cross_px_y = cy_p + float(s.get("crosshair_y", 0.0)) * cy_p
        cross_yaw_deg   = math.degrees(math.atan2(cross_px_x - cx_p, focal_x))
        cross_pitch_deg = math.degrees(math.atan2(cy_p - cross_px_y, focal_y))
        frame_area = max(1.0, float(w * h))

        out: list[dict[str, Any]] = []
        for c in contours:
            # Mask area is in downscaled pixels; rescale to original.
            area_px = float(cv2.contourArea(c)) * (sf * sf)
            if area_px < min_area:
                continue
            x, y, ww, hh = cv2.boundingRect(c)
            x   *= sf;   y *= sf
            ww  *= sf;  hh *= sf
            cx_px = x + ww / 2.0
            cy_px = y + hh / 2.0
            yaw_deg   = math.degrees(math.atan2(cx_px - cx_p, focal_x)) - cross_yaw_deg
            pitch_deg = math.degrees(math.atan2(cy_p - cy_px, focal_y)) - cross_pitch_deg
            out.append({
                "id":         len(out),
                "cx":         cx_px,
                "cy":         cy_px,
                "yaw_deg":    yaw_deg,
                "pitch_deg":  pitch_deg,
                "tx":         (cx_px - cross_px_x) / cx_p,
                "ty":         (cy_px - cross_px_y) / cy_p,
                "area":       area_px / frame_area,
                "width_px":   int(ww),
                "height_px":  int(hh),
                "timestamp":  self._last_processed_ts,
            })
            if len(out) >= max_n:
                break
        # Largest first so robot code reading [0] gets "the obvious one".
        out.sort(key=lambda o: o["area"], reverse=True)
        return out


def _polygon_area(pts: np.ndarray) -> float:
    """Shoelace formula for signed polygon area."""
    x = pts[:, 0]
    y = pts[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


# ---------------------------------------------------------------------
# NT4 publisher — writes the canonical schema.
# ---------------------------------------------------------------------

class NTPublisher:
    """Mirrors the latest detection snapshot into NT4 topics under
    `/acuity/*`. Robot code reads from there. See
    acuity/docs/nt4-schema.md.

    The nt4_client we use exposes one Publisher per topic — we cache
    them in `self._pubs` so we publish each path once and just call
    `pub.set(v)` per frame, rather than re-creating publishers in
    the hot loop.
    """

    # path → NT4 type string. Anything not listed defaults to 'string'
    # (we json-encode the value).
    _TOPICS = {
        "acuity/version":               "int",
        "acuity/build":                 "string",
        "acuity/heartbeat":             "int",
        "acuity/latency_ms":            "double",
        "acuity/camera/connected":      "boolean",
        "acuity/camera/fps":            "double",
        "acuity/camera/resolution":     "string",
        "acuity/tags/best/id":          "int",
        "acuity/tags/best/distance_m":  "double",
        "acuity/tags/best/yaw_deg":     "double",
        "acuity/tags/best/pitch_deg":   "double",
        "acuity/tags/best/tx":          "double",
        "acuity/tags/best/ty":          "double",
        "acuity/tags/best/area":        "double",
        "acuity/tags/best/timestamp":   "double",
        "acuity/tags/best/decision_margin": "double",
        "acuity/tags/count":            "int",
        "acuity/tags/all":              "string",
        # Color-blob (game-piece) topics. Only get values when
        # enable_objects is on; subscribers see the defaults
        # otherwise (id=-1, area=0).
        "acuity/objects/best/id":       "int",
        "acuity/objects/best/yaw_deg":  "double",
        "acuity/objects/best/pitch_deg":"double",
        "acuity/objects/best/tx":       "double",
        "acuity/objects/best/ty":       "double",
        "acuity/objects/best/area":     "double",
        "acuity/objects/best/width_px": "int",
        "acuity/objects/best/height_px":"int",
        "acuity/objects/count":         "int",
        "acuity/objects/all":           "string",
        "acuity/health/cpu_pct":        "double",
        "acuity/health/temp_c":         "double",
        "acuity/health/uptime_s":       "int",
    }

    def __init__(self, settings_provider):
        self._settings = settings_provider
        self._client: Optional[nt4_client.Client] = None
        self._pubs: dict[str, Any] = {}
        self._heartbeat = 0
        self._uptime_start = time.monotonic()
        self._last_settings_key: Optional[tuple] = None
        self._lock = threading.Lock()

    def _ensure_client(self) -> Optional[nt4_client.Client]:
        s = self._settings()
        team = int(s.get("nt_team", 0))
        host = (s.get("nt_server_host") or "").strip()
        key  = (team, host)
        with self._lock:
            if key == self._last_settings_key and self._client is not None:
                return self._client

            # Server changed; tear down the old client + publishers.
            if self._client is not None:
                try: self._client.close()
                except Exception: pass
                self._client = None
                self._pubs.clear()

            if not host and team <= 0:
                # Local-only mode. Dashboard works; nothing publishes
                # upstream until the operator sets a team or host.
                self._last_settings_key = key
                return None

            try:
                self._client = nt4_client.connect(
                    name="acuity-dashboard",
                    host=host or None,
                    team=team if team > 0 else None,
                )
                # Publish all known topics up front so publishers exist
                # by the time we want to set values.
                for path, type_str in self._TOPICS.items():
                    self._pubs[path] = self._client.publish(path, type_str)
                log.info("NT4 connected to %s", host or f"team {team}")
            except Exception as e:
                log.warning("NT4 connect failed: %s", e)
                self._client = None
            self._last_settings_key = key
            return self._client

    def publish(self, snapshot: dict[str, Any]) -> None:
        client = self._ensure_client()
        self._heartbeat = (self._heartbeat + 1) & 0x7FFFFFFF

        if client is None or not self._pubs:
            return  # local-only mode; dashboard still works.

        def _set(path: str, value: Any) -> None:
            pub = self._pubs.get(path)
            if pub is not None:
                pub.set(value)

        try:
            _set("acuity/version",            int(SCHEMA_VERSION))
            _set("acuity/build",              str(BUILD_ID))
            _set("acuity/heartbeat",          int(self._heartbeat))
            _set("acuity/latency_ms",         float(snapshot.get("latency_ms", 0.0)))
            _set("acuity/camera/connected",   bool(snapshot["connected"]))
            _set("acuity/camera/fps",         float(snapshot["fps"]))
            _set("acuity/camera/resolution",
                 f"{snapshot['width']}x{snapshot['height']}")

            best = snapshot["best"]
            if best is None:
                _set("acuity/tags/best/id", -1)
            else:
                _set("acuity/tags/best/id",              int(best["id"]))
                _set("acuity/tags/best/distance_m",      float(best["distance_m"]))
                _set("acuity/tags/best/yaw_deg",         float(best["yaw_deg"]))
                _set("acuity/tags/best/pitch_deg",       float(best["pitch_deg"]))
                _set("acuity/tags/best/tx",              float(best["tx"]))
                _set("acuity/tags/best/ty",              float(best["ty"]))
                _set("acuity/tags/best/area",            float(best["area"]))
                _set("acuity/tags/best/timestamp",       float(best["timestamp"]))
                _set("acuity/tags/best/decision_margin", float(best["decision_margin"]))

            _set("acuity/tags/count", len(snapshot["tags"]))
            _set("acuity/tags/all", json.dumps([
                {k: v for k, v in t.items() if k != "corners"}
                for t in snapshot["tags"]
            ]))

            # Color-blob channel.
            best_obj = snapshot.get("best_object")
            if best_obj is None:
                _set("acuity/objects/best/id",        -1)
                _set("acuity/objects/best/area",      0.0)
            else:
                _set("acuity/objects/best/id",        int(best_obj["id"]))
                _set("acuity/objects/best/yaw_deg",   float(best_obj["yaw_deg"]))
                _set("acuity/objects/best/pitch_deg", float(best_obj["pitch_deg"]))
                _set("acuity/objects/best/tx",        float(best_obj["tx"]))
                _set("acuity/objects/best/ty",        float(best_obj["ty"]))
                _set("acuity/objects/best/area",      float(best_obj["area"]))
                _set("acuity/objects/best/width_px",  int(best_obj["width_px"]))
                _set("acuity/objects/best/height_px", int(best_obj["height_px"]))
            objs = snapshot.get("objects") or []
            _set("acuity/objects/count", len(objs))
            _set("acuity/objects/all", json.dumps(objs))

            _set("acuity/health/cpu_pct",  _cpu_pct())
            _set("acuity/health/temp_c",   _temp_c())
            _set("acuity/health/uptime_s", int(time.monotonic() - self._uptime_start))
        except Exception:
            log.exception("NT4 publish failed; will retry next frame")
            # Force reconnect on next iteration.
            with self._lock:
                self._client = None
                self._pubs.clear()
                self._last_settings_key = None


# ---------------------------------------------------------------------
# Health helpers
# ---------------------------------------------------------------------

def _cpu_pct() -> float:
    """Best-effort CPU load. /proc/loadavg avg-1m × 100 / num-cpus."""
    try:
        load1, _, _ = os.getloadavg()
        return min(100.0, load1 / max(1, os.cpu_count() or 1) * 100.0)
    except OSError:
        return 0.0


def _temp_c() -> float:
    """SoC temperature on a Pi. Returns 0 on non-Pi hosts."""
    p = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(p.read_text().strip()) / 1000.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------
# WiFi mode helpers — wrap the same `acuity-wifi-mode.sh` the firmware
# installs. We expose them as POST routes so the dashboard can offer
# "Forget WiFi" / "Reboot" buttons without making the user SSH in.
# ---------------------------------------------------------------------

def _iface_ipv4(name: str) -> str:
    """First IPv4 address bound to <name>, or '' if the iface is down or
    has no v4. Uses iproute2 because nmcli isn't always usable from a
    non-root context."""
    try:
        out = subprocess.check_output(
            ["ip", "-br", "addr", "show", name],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""
    # `wlan0  UP  10.12.79.11/24  fe80::...`
    parts = out.split()
    for p in parts[2:]:
        if "." in p and "/" in p:
            return p.split("/", 1)[0]
    return ""


def _net_state() -> dict[str, Any]:
    """Network state for the status pane / Manager.

    We support three deploy patterns:
      - WiFi only (driven by acuity-firstboot.sh's STA path)
      - wired only (FRC competition: device on the radio over eth0)
      - AP-mode setup (no SSID and no ethernet — open AP up at .50.1)

    The `mode` field collapses those into a single tag the UI can
    branch on. `ip` mirrors whichever interface is currently the
    primary path back to the laptop (preferring ethernet when both
    are up — that's the radio side at competition).
    """
    try:
        host = subprocess.check_output(["hostname"], text=True).strip()
    except Exception:
        host = ""
    eth_ip  = _iface_ipv4("eth0")
    wlan_ip = _iface_ipv4("wlan0")
    in_ap   = wlan_ip == "192.168.50.1"

    if eth_ip:
        primary, mode = eth_ip, "wired"
    elif in_ap:
        primary, mode = wlan_ip, "ap"
    elif wlan_ip:
        primary, mode = wlan_ip, "sta"
    else:
        primary, mode = "", "down"

    return {
        "hostname":   host,
        "ip":         primary,
        "eth_ip":     eth_ip,
        "wlan_ip":    wlan_ip,
        "mode":       mode,
        "conf_set":   ACUITY_CONF.exists(),
    }


# ---------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------

app = FastAPI(title="Acuity dashboard")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Live shared state. The CameraThread + TagDetectorThread feed
# `latest_snapshot`; the WS endpoint and the NT publisher both read
# from it. One source of truth, one lock.
_settings_lock = threading.Lock()
_settings = _load_settings()
def _settings_provider() -> dict[str, Any]:
    with _settings_lock:
        return dict(_settings)

camera   = CameraThread(_settings_provider)
publisher = NTPublisher(_settings_provider)
latest_snapshot: dict[str, Any] = {}
latest_lock = threading.Lock()
ws_event_loop: Optional[asyncio.AbstractEventLoop] = None
ws_clients: set[WebSocket] = set()


def _on_snapshot(snap: dict[str, Any]) -> None:
    with latest_lock:
        latest_snapshot.clear()
        latest_snapshot.update(snap)
    publisher.publish(snap)
    # Push to any browser WebSockets. We schedule the broadcast on
    # the asyncio loop because we're in a worker thread.
    loop = ws_event_loop
    if loop is not None and not loop.is_closed():
        loop.call_soon_threadsafe(_broadcast_snapshot)


detector = TagDetectorThread(camera, _settings_provider, _on_snapshot)


def _broadcast_snapshot() -> None:
    if not ws_clients:
        return
    with latest_lock:
        snap = dict(latest_snapshot)
    # Strip the heavy `corners` array from broadcast — we send a
    # smaller payload to the browser since the SVG only needs the
    # corners for the *currently-rendered* set, which the browser
    # can request separately if it ever wants high-fidelity overlays.
    payload = json.dumps({
        "best":         snap.get("best"),
        "tags":         [{k: v for k, v in t.items() if k != "corners"}
                         for t in snap.get("tags", [])],
        "tags_full":    snap.get("tags", []),
        "best_object":  snap.get("best_object"),
        "objects":      snap.get("objects", []),
        "latency_ms":   snap.get("latency_ms"),
        "fps":          snap.get("fps"),
        "width":        snap.get("width"),
        "height":       snap.get("height"),
        "connected":    snap.get("connected"),
        "wall_ts":      snap.get("wall_ts"),
    })
    dead = []
    for ws in ws_clients:
        try:
            asyncio.create_task(ws.send_text(payload))
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


@app.on_event("startup")
async def _startup() -> None:
    global ws_event_loop
    ws_event_loop = asyncio.get_running_loop()
    camera.start()
    detector.start()
    log.info("acuity dashboard ready")


@app.on_event("shutdown")
async def _shutdown() -> None:
    detector.stop()
    camera.stop()


# ----- HTML / static -----

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


@app.get("/favicon.ico")
async def favicon() -> Any:
    p = STATIC_DIR / "favicon.ico"
    if p.exists():
        return FileResponse(p)
    return PlainTextResponse("", status_code=204)


# ----- MJPEG passthrough -----

# Single-viewer policy. Two MJPEG clients at once (Manager + the web
# dashboard, or two browser tabs) double the JPEG send-rate over one
# Pi WiFi uplink, which is exactly when the user complains "the
# stream is laggy." We let only ONE viewer have the stream at a
# time; the most recent connection wins. The previous viewer's
# generator detects it's no longer the active id and quietly exits.
_stream_lock = threading.Lock()
_stream_id_counter = 0
_active_stream_id = 0


@app.get("/stream.mjpg")
async def stream_mjpg() -> StreamingResponse:
    """Multipart MJPEG. Reuses the JPEG the camera thread already
    encoded — no per-request re-encode. Honors `stream_max_fps`
    (set in /api/settings) to throttle stream FPS independently of
    capture, and is single-viewer: a new connection takes over and
    closes any currently-running stream."""
    global _stream_id_counter, _active_stream_id
    boundary = "acuity-frame"

    with _stream_lock:
        _stream_id_counter += 1
        my_id = _stream_id_counter
        _active_stream_id = my_id
    log.info("stream.mjpg → viewer #%d (took over from previous)", my_id)

    async def generator():
        last_ts = 0.0
        last_yield = 0.0
        while True:
            # Bow out the moment a newer client arrives. They become
            # the active viewer; we stop sending frames into a pipe
            # that's about to be closed.
            if _active_stream_id != my_id:
                log.info("stream.mjpg viewer #%d yielding to a newer one", my_id)
                return
            await asyncio.sleep(0.005)
            s = _settings_provider()
            max_fps = int(s.get("stream_max_fps", 0) or 0)
            min_interval = (1.0 / max_fps) if max_fps > 0 else 0.0

            with camera._lock:
                ts = camera.latest_ts
                jpg = camera.latest_jpeg
            if jpg is None or ts == last_ts:
                continue
            now = time.monotonic()
            if min_interval > 0 and (now - last_yield) < min_interval:
                continue
            last_ts = ts
            last_yield = now
            yield (b"--" + boundary.encode() + b"\r\n"
                   b"Content-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n"
                   + jpg + b"\r\n")

    return StreamingResponse(
        generator(),
        media_type=f"multipart/x-mixed-replace; boundary={boundary}",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.post("/api/target")
async def api_target(req: Request) -> JSONResponse:
    """Operator clicked a tag in the camera view. Latch that tag ID
    so it wins automatic best-target selection until cleared.

    Body:
      {"id": <int>}     # lock to that tag id
      {"id": null}      # clear the lock (auto-pick again)

    The lock survives across reboots because it's stored in the same
    settings JSON as the rest of the config."""
    body = await req.json()
    tag_id = body.get("id") if isinstance(body, dict) else None
    new = -1 if tag_id is None else int(tag_id)
    with _settings_lock:
        _settings["selected_tag_id"] = new
        _save_settings(_settings)
    return JSONResponse({"selected_tag_id": new})


# ----- API: detections (live) -----

@app.websocket("/api/detections.ws")
async def detections_ws(ws: WebSocket) -> None:
    await ws.accept()
    ws_clients.add(ws)
    try:
        # Send initial snapshot so the UI has something to render.
        with latest_lock:
            initial = dict(latest_snapshot)
        if initial:
            await ws.send_text(json.dumps({
                "best":  initial.get("best"),
                "tags":  initial.get("tags", []),
                "fps":   initial.get("fps"),
                "width": initial.get("width"),
                "height": initial.get("height"),
                "connected": initial.get("connected"),
                "wall_ts":   initial.get("wall_ts"),
            }))
        # Then idle — broadcasts come from _broadcast_snapshot.
        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


@app.get("/api/detections")
async def detections() -> JSONResponse:
    """One-shot snapshot. WS is the streaming version."""
    with latest_lock:
        snap = dict(latest_snapshot)
    return JSONResponse({
        "best":         snap.get("best"),
        "tags":         snap.get("tags", []),
        "best_object":  snap.get("best_object"),
        "objects":      snap.get("objects", []),
        "latency_ms":   snap.get("latency_ms", 0.0),
        "fps":          snap.get("fps"),
        "width":        snap.get("width"),
        "height":       snap.get("height"),
        "connected":    snap.get("connected", False),
        "wall_ts":      snap.get("wall_ts", 0),
    })


@app.get("/api/snapshot")
async def api_snapshot() -> Any:
    """Single JPEG of whatever the camera most recently produced.

    Cheap: we hand back the JPEG buffer the MJPEG streamer already
    has cached, so there's no extra encode pass. Good for screenshot
    buttons in robot dashboards / Slack bots / event-triggered
    capture from a script in /api/scripts."""
    with camera._lock:
        jpeg = camera.latest_jpeg
        ts   = camera.latest_ts
    if jpeg is None:
        raise HTTPException(503, "camera has not produced a frame yet")
    headers = {
        "Cache-Control": "no-store",
        "X-Acuity-Frame-Ts": f"{ts:.6f}",
    }
    return Response(content=bytes(jpeg), media_type="image/jpeg",
                    headers=headers)


# ----- API: settings -----

@app.get("/api/settings")
async def get_settings() -> JSONResponse:
    return JSONResponse(_settings_provider())


@app.post("/api/settings")
async def set_settings(req: Request) -> JSONResponse:
    body = await req.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "expected JSON object")
    out: dict[str, Any] = {}
    with _settings_lock:
        for k, v in body.items():
            if k not in DEFAULT_SETTINGS:
                continue
            # Light type-coerce. Lists stay lists, ints stay ints.
            cur = _settings[k]
            try:
                if isinstance(cur, bool):
                    _settings[k] = bool(v)
                elif isinstance(cur, int) and not isinstance(cur, bool):
                    _settings[k] = int(v)
                elif isinstance(cur, float):
                    _settings[k] = float(v)
                elif isinstance(cur, list):
                    _settings[k] = list(v)
                else:
                    _settings[k] = v
                out[k] = _settings[k]
            except (TypeError, ValueError) as e:
                raise HTTPException(400, f"bad value for {k}: {e}")
        _save_settings(_settings)
    return JSONResponse(out)


# ----- API: device control -----

@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "version":     SCHEMA_VERSION,
        "build":       BUILD_ID,
        "fps":         camera.fps,
        "connected":   camera.connected,
        "resolution":  f"{camera.resolution[0]}x{camera.resolution[1]}",
        "cpu_pct":     _cpu_pct(),
        "temp_c":      _temp_c(),
        "uptime_s":    int(time.monotonic()),
        "platform":    platform.platform(),
        "have_pyapriltags": _HAVE_PA,
        "net":         _net_state(),
    })


@app.post("/api/reboot")
async def api_reboot() -> JSONResponse:
    """Schedule a reboot 1s out so the response gets back first."""
    threading.Thread(
        target=lambda: (time.sleep(1.0), subprocess.run(["sudo", "reboot"])),
        daemon=True,
    ).start()
    return JSONResponse({"ok": True, "rebooting_in_seconds": 1})


@app.post("/api/forget-wifi")
async def api_forget_wifi() -> JSONResponse:
    """Delete acuity.conf + reboot — Pi comes back in AP-mode setup."""
    try:
        subprocess.run(["sudo", "rm", "-f", str(ACUITY_CONF)], check=False)
    except Exception as e:
        raise HTTPException(500, f"rm acuity.conf failed: {e}")
    threading.Thread(
        target=lambda: (time.sleep(1.0), subprocess.run(["sudo", "reboot"])),
        daemon=True,
    ).start()
    return JSONResponse({"ok": True})


@app.get("/api/logs")
async def api_logs(lines: int = 200) -> PlainTextResponse:
    """Tail the dashboard's own systemd journal."""
    try:
        out = subprocess.check_output(
            ["journalctl", "-u", "acuity-dashboard.service",
             "-n", str(int(lines)), "--no-pager", "--output=short-iso"],
            text=True, errors="replace",
        )
    except subprocess.CalledProcessError as e:
        out = f"journalctl failed: {e}"
    return PlainTextResponse(out)


@app.get("/api/healthz")
async def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


# ---------------------------------------------------------------------
# Coprocessor endpoints
#
# Acuity is sold as "the vision coprocessor" but a Pi Zero 2 W can do
# more than vision — it sits on the robot's network, runs Linux, has
# CPU + a Python runtime nobody else on the bus has. The endpoints
# below let robot code (or a human via Manager) lean on it as a
# general-purpose helper:
#
#   /api/system               full system snapshot
#   /api/services             list controllable units + their state
#   /api/services/{name}      restart/start/stop a whitelisted unit
#   /api/scripts              list user scripts in ACUITY_SCRIPTS_DIR
#   /api/scripts/{name}/run   start a script in the background
#   /api/scripts/runs/{id}    poll output + exit code of a run
#   /api/scripts/runs/{id}/stop  kill a running script
#   /api/nt/publish           publish a one-off value to NT4
#
# We deliberately do NOT expose arbitrary shell exec — only files
# already on disk in the scripts directory are runnable. A human can
# put scripts there over SSH; the endpoint just runs them.
# ---------------------------------------------------------------------

# Where users drop scripts. /var/lib/acuity already exists for
# settings.json and is writable by the acuity service user — using it
# avoids a second sudoers grant and survives package upgrades.
SCRIPTS_DIR = Path(os.environ.get(
    "ACUITY_SCRIPTS_DIR", "/var/lib/acuity/scripts"))

# Services we expose to the network. Keep tight — anything systemctl
# can reach is a foot-cannon, and we only need a few for normal ops.
# 'acuity-dashboard' restarts THIS process; that one's a useful nuke
# button when you've poked something into a bad state via /api/settings.
_CONTROLLABLE_SERVICES = (
    "acuity-dashboard.service",
    "avahi-daemon.service",
)
_SERVICE_ACTIONS = ("start", "stop", "restart", "status")


def _read_meminfo_pct() -> float:
    """RAM in-use / total, as a 0..100 float. /proc/meminfo lookup
    avoids pulling psutil in just for one number."""
    try:
        info: dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, rest = line.partition(":")
                tok = rest.strip().split()
                if tok:
                    try:
                        info[k.strip()] = int(tok[0])
                    except ValueError:
                        pass
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        if total <= 0:
            return 0.0
        return max(0.0, min(100.0, (1.0 - avail / total) * 100.0))
    except Exception:
        return 0.0


def _read_disk_pct(path: str = "/") -> float:
    """Used / total for the partition holding <path>, 0..100."""
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        free  = st.f_bavail * st.f_frsize
        if total <= 0:
            return 0.0
        return max(0.0, min(100.0, (1.0 - free / total) * 100.0))
    except Exception:
        return 0.0


def _read_uptime_s() -> int:
    """System uptime — independent of when our process started.
    /proc/uptime is two floats: total_secs idle_secs."""
    try:
        with open("/proc/uptime") as f:
            return int(float(f.read().split()[0]))
    except Exception:
        return 0


def _read_pi_model() -> str:
    """Best-effort Pi model string for the UI ("Raspberry Pi Zero 2 W")."""
    p = Path("/sys/firmware/devicetree/base/model")
    try:
        # The DT model string is null-terminated.
        return p.read_text().rstrip("\x00").strip()
    except Exception:
        return platform.machine() or "unknown"


def _systemctl_state(unit: str) -> str:
    """`systemctl is-active` shorthand. Returns 'active', 'inactive',
    'failed', etc., or 'unknown' if systemctl isn't there."""
    try:
        out = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=3,
        )
        # is-active prints state on stdout regardless of exit code
        # ('inactive' is non-zero), so trust the line over rc.
        return (out.stdout or "").strip() or "unknown"
    except Exception:
        return "unknown"


@app.get("/api/system")
async def api_system() -> JSONResponse:
    """Single fat snapshot for Manager's device panel + scripts that
    want to ask 'is this Pi healthy?'. Cheap (<10 ms) — built from
    /proc + /sys reads. Anything that needs sustained polling should
    subscribe to NT4's /acuity/health/* topics instead."""
    return JSONResponse({
        "build":        BUILD_ID,
        "schema":       SCHEMA_VERSION,
        "model":        _read_pi_model(),
        "kernel":       platform.release(),
        "platform":     platform.platform(),
        "cpu_pct":      _cpu_pct(),
        "mem_pct":      _read_meminfo_pct(),
        "disk_pct":     _read_disk_pct("/"),
        "temp_c":       _temp_c(),
        "uptime_s":     _read_uptime_s(),
        "have_pyapriltags": _HAVE_PA,
        "camera": {
            "connected":  camera.connected,
            "fps":        camera.fps,
            "resolution": f"{camera.resolution[0]}x{camera.resolution[1]}",
        },
        "net":          _net_state(),
        "scripts_dir":  str(SCRIPTS_DIR),
    })


@app.get("/api/services")
async def api_services() -> JSONResponse:
    """List controllable services + their current state."""
    return JSONResponse({
        "services": [
            {"name": unit, "state": _systemctl_state(unit)}
            for unit in _CONTROLLABLE_SERVICES
        ],
        "actions": list(_SERVICE_ACTIONS),
    })


@app.post("/api/services/{name}")
async def api_services_action(name: str, req: Request) -> JSONResponse:
    """`{"action": "restart"}` against a whitelisted service.

    'status' just refreshes the cached state; for the others we shell
    out to systemctl. Note: restarting acuity-dashboard kills THIS
    process — the response will not reach the client. That's the
    documented behavior; Manager handles the dropped connection."""
    if name not in _CONTROLLABLE_SERVICES:
        raise HTTPException(404, f"unknown service: {name}")
    body = {}
    try:
        body = await req.json()
    except Exception:
        pass
    action = (body.get("action") or "status").strip()
    if action not in _SERVICE_ACTIONS:
        raise HTTPException(400, f"unknown action: {action}")

    if action == "status":
        return JSONResponse({"name": name, "state": _systemctl_state(name)})

    try:
        subprocess.run(
            ["sudo", "systemctl", action, name],
            check=True, capture_output=True, text=True, timeout=10,
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(500,
            f"systemctl {action} {name} failed: {e.stderr.strip() or e}")
    except Exception as e:
        raise HTTPException(500, f"systemctl {action} {name}: {e}")
    return JSONResponse({
        "name":  name,
        "state": _systemctl_state(name),
        "action": action,
    })


# ----- Script runner -----
#
# Lets users drop arbitrary Python (or any executable) into
# /var/lib/acuity/scripts/ and run it from the dashboard / Manager.
# Each run is a Popen with stdout+stderr merged into a bounded
# in-memory ring buffer keyed by run_id. State machine:
#
#   created → running → exited(code) | killed
#
# Runs persist for the lifetime of the dashboard process so users can
# poll /api/scripts/runs/<id> after the script finishes. We cap the
# in-memory transcript at MAX_RUN_BYTES per run so a runaway script
# can't OOM the Pi; older bytes get truncated.

MAX_RUN_BYTES = 256 * 1024  # 256 KB per run — plenty for status output

_runs_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}
_run_seq = 0


def _list_scripts() -> list[dict[str, Any]]:
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    for p in sorted(SCRIPTS_DIR.iterdir()):
        if p.is_file() and not p.name.startswith("."):
            try:
                st = p.stat()
                out.append({
                    "name":         p.name,
                    "size":         st.st_size,
                    "modified":     int(st.st_mtime),
                    "executable":   bool(st.st_mode & 0o111),
                })
            except Exception:
                continue
    return out


def _start_run(name: str, args: list[str]) -> dict[str, Any]:
    """Spawn the script with stdout/stderr merged into our buffer."""
    global _run_seq
    script_path = (SCRIPTS_DIR / name).resolve()
    # Confine to SCRIPTS_DIR — `..` traversal would otherwise let
    # POST /api/scripts/..%2F..%2Fbin%2Fsh/run smuggle execution.
    try:
        script_path.relative_to(SCRIPTS_DIR.resolve())
    except ValueError:
        raise HTTPException(400, "script must live inside the scripts dir")
    if not script_path.is_file():
        raise HTTPException(404, f"no such script: {name}")

    # Pick how to launch: Python by extension, otherwise exec the file
    # directly (it must be chmod +x'd by the user). We don't auto-chmod
    # — that hides "I forgot to mark it runnable" failures.
    if script_path.suffix == ".py":
        argv = ["python3", str(script_path), *args]
    else:
        if not os.access(script_path, os.X_OK):
            raise HTTPException(400,
                f"{name} is not executable. `chmod +x` it first or rename to .py.")
        argv = [str(script_path), *args]

    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=str(SCRIPTS_DIR),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except Exception as e:
        raise HTTPException(500, f"could not start {name}: {e}")

    with _runs_lock:
        _run_seq += 1
        run_id = f"r{_run_seq}"
        run = {
            "id":         run_id,
            "name":       name,
            "argv":       argv,
            "pid":        proc.pid,
            "started":    time.time(),
            "ended":      None,
            "exit_code":  None,
            "state":      "running",
            "buf":        bytearray(),
            "truncated":  False,
            "_proc":      proc,
        }
        _runs[run_id] = run

    def _drain():
        # Read stdout in small chunks. Cap at MAX_RUN_BYTES — drop the
        # tail (we'd rather lose the end of a chatty script than the
        # start, which is where the useful "starting up…" lines are).
        try:
            assert proc.stdout is not None
            for chunk in iter(lambda: proc.stdout.read(4096), b""):
                with _runs_lock:
                    if len(run["buf"]) + len(chunk) > MAX_RUN_BYTES:
                        room = max(0, MAX_RUN_BYTES - len(run["buf"]))
                        if room:
                            run["buf"].extend(chunk[:room])
                        run["truncated"] = True
                    else:
                        run["buf"].extend(chunk)
        except Exception:
            pass
        finally:
            try: proc.stdout.close()
            except Exception: pass
            code = proc.wait()
            with _runs_lock:
                run["exit_code"] = code
                run["ended"]     = time.time()
                run["state"]     = (
                    "killed" if code is not None and code < 0 else "exited"
                )

    threading.Thread(target=_drain, daemon=True).start()
    return run


def _run_view(run: dict[str, Any]) -> dict[str, Any]:
    """Public projection — strips the internal Popen handle."""
    return {
        "id":         run["id"],
        "name":       run["name"],
        "pid":        run["pid"],
        "started":    run["started"],
        "ended":      run["ended"],
        "exit_code":  run["exit_code"],
        "state":      run["state"],
        "truncated":  run["truncated"],
        "output":     bytes(run["buf"]).decode("utf-8", errors="replace"),
    }


@app.get("/api/scripts")
async def api_scripts_list() -> JSONResponse:
    return JSONResponse({
        "dir":     str(SCRIPTS_DIR),
        "scripts": _list_scripts(),
    })


@app.post("/api/scripts/{name}/run")
async def api_scripts_run(name: str, req: Request) -> JSONResponse:
    body = {}
    try:
        body = await req.json()
    except Exception:
        pass
    args = body.get("args") or []
    if not isinstance(args, list) or not all(isinstance(a, (str, int, float)) for a in args):
        raise HTTPException(400, "args must be a list of strings/numbers")
    args = [str(a) for a in args]
    run = _start_run(name, args)
    return JSONResponse(_run_view(run))


@app.get("/api/scripts/runs")
async def api_scripts_runs() -> JSONResponse:
    """List all known runs from this dashboard process. Resets when
    the dashboard restarts — runs aren't persisted to disk."""
    with _runs_lock:
        return JSONResponse({"runs": [_run_view(r) for r in _runs.values()]})


@app.get("/api/scripts/runs/{run_id}")
async def api_scripts_run_state(run_id: str) -> JSONResponse:
    with _runs_lock:
        run = _runs.get(run_id)
    if run is None:
        raise HTTPException(404, f"no such run: {run_id}")
    return JSONResponse(_run_view(run))


@app.post("/api/scripts/runs/{run_id}/stop")
async def api_scripts_run_stop(run_id: str) -> JSONResponse:
    with _runs_lock:
        run = _runs.get(run_id)
    if run is None:
        raise HTTPException(404, f"no such run: {run_id}")
    proc = run.get("_proc")
    if proc is not None and proc.poll() is None:
        try: proc.terminate()
        except Exception: pass
    return JSONResponse(_run_view(run))


# ----- NT4 publish passthrough -----
#
# Robot code can subscribe to arbitrary topics under /acuity/user/...
# and have the dashboard publish to them. Useful for testing or for
# robot code that wants to hand a value off to a debug tool quickly
# without standing up its own NT4 publisher.
#
# We sandbox to the /acuity/user/ subtree so this can't stomp on the
# canonical /acuity/tags/* topics the camera thread owns.
_user_pubs: dict[str, Any] = {}
_user_pubs_lock = threading.Lock()


@app.post("/api/nt/publish")
async def api_nt_publish(req: Request) -> JSONResponse:
    body = await req.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "expected JSON object")
    path  = str(body.get("path") or "").strip()
    type_ = str(body.get("type") or "string").strip()
    value = body.get("value")
    if not path or path.startswith("/"):
        raise HTTPException(400, "path must be relative (e.g. 'user/foo')")
    if not path.startswith("acuity/user/") and not path.startswith("user/"):
        # Be tolerant of missing 'acuity/' — auto-prepend.
        path = "acuity/user/" + path.lstrip("/").removeprefix("user/")
    if type_ not in ("int", "double", "boolean", "string"):
        raise HTTPException(400, "type must be int|double|boolean|string")

    client = publisher._ensure_client()  # lean on the existing one
    if client is None:
        raise HTTPException(503,
            "NT4 client not connected — set nt_team or nt_server_host first")

    with _user_pubs_lock:
        pub = _user_pubs.get(path)
        if pub is None:
            pub = client.publish(path, type_)
            _user_pubs[path] = pub
    try:
        if type_ == "int":     pub.set(int(value))
        elif type_ == "double": pub.set(float(value))
        elif type_ == "boolean": pub.set(bool(value))
        else:                   pub.set(str(value))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"value didn't fit type {type_}: {e}")
    return JSONResponse({"ok": True, "path": path, "type": type_})


# ---------------------------------------------------------------------
# Pipelines — named settings snapshots
#
# The classic Limelight idiom: a robot wants different vision configs
# for different jobs (long-range AprilTags, near-field game pieces,
# off-during-driving), and switching them is a single call from robot
# code. We model a "pipeline" as a partial settings dict you save under
# a name; applying it merges those overrides on top of whatever's
# currently active. Snapshots live in their own JSON file so the active
# `settings.json` is still the single source of truth for the running
# camera + detector threads.
#
# Robot code switches via `POST /api/pipelines/<name>/apply`. Cheap (a
# settings update is a dict swap; the camera thread re-reads on its
# next loop iteration, ~30 Hz). Common pattern: bind it to a button on
# the operator controller so the human can flip modes mid-match.
# ---------------------------------------------------------------------

PIPELINES_PATH = Path(os.environ.get(
    "ACUITY_PIPELINES", "/var/lib/acuity/pipelines.json"))


def _load_pipelines() -> dict[str, dict[str, Any]]:
    if not PIPELINES_PATH.exists():
        return {}
    try:
        data = json.loads(PIPELINES_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_pipelines(p: dict[str, Any]) -> None:
    PIPELINES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PIPELINES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, indent=2))
    os.replace(tmp, PIPELINES_PATH)


_pipelines_lock = threading.Lock()
_pipelines = _load_pipelines()
# Track active pipeline so robot code / dashboard can reflect it. We
# store this OUTSIDE settings.json because it's a status field, not a
# user-tunable knob.
_active_pipeline: str = _pipelines.get("_current", "")


def _list_pipelines() -> list[str]:
    return sorted(k for k in _pipelines.keys() if not k.startswith("_"))


@app.get("/api/pipelines")
async def api_pipelines_list() -> JSONResponse:
    with _pipelines_lock:
        return JSONResponse({
            "current":   _active_pipeline,
            "pipelines": _list_pipelines(),
        })


@app.post("/api/pipelines/{name}/save")
async def api_pipelines_save(name: str) -> JSONResponse:
    """Snapshot the current settings under <name>. Overwrites if it
    already exists. Pipeline name must be a single component — no
    slashes — so URLs stay sensible."""
    if "/" in name or name.startswith("_") or not name:
        raise HTTPException(400, "bad pipeline name")
    with _pipelines_lock, _settings_lock:
        # Take a copy of the live settings sans meta keys (we don't
        # serialize the pipelines list inside a pipeline).
        snapshot = {k: v for k, v in _settings.items()
                    if k in DEFAULT_SETTINGS}
        _pipelines[name] = snapshot
        _save_pipelines(_pipelines)
    return JSONResponse({"ok": True, "name": name, "saved_keys": len(snapshot)})


@app.post("/api/pipelines/{name}/apply")
async def api_pipelines_apply(name: str) -> JSONResponse:
    """Merge <name>'s saved overrides into the live settings. Robot
    code calls this to switch modes."""
    global _active_pipeline
    with _pipelines_lock:
        if name not in _pipelines:
            raise HTTPException(404, f"unknown pipeline: {name}")
        overrides = _pipelines[name]
    applied: dict[str, Any] = {}
    with _settings_lock:
        for k, v in overrides.items():
            if k in DEFAULT_SETTINGS:
                _settings[k] = v
                applied[k] = v
        _save_settings(_settings)
    with _pipelines_lock:
        _active_pipeline = name
        _pipelines["_current"] = name
        _save_pipelines(_pipelines)
    return JSONResponse({"ok": True, "name": name, "applied": applied})


@app.delete("/api/pipelines/{name}")
async def api_pipelines_delete(name: str) -> JSONResponse:
    global _active_pipeline
    with _pipelines_lock:
        if name not in _pipelines or name.startswith("_"):
            raise HTTPException(404, f"unknown pipeline: {name}")
        del _pipelines[name]
        if _active_pipeline == name:
            _active_pipeline = ""
            _pipelines["_current"] = ""
        _save_pipelines(_pipelines)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------
# Telemetry log — append-only JSONL data sink
#
# Robot code POSTs structured records (any subsystem can log: shooter
# RPM, intake current, pose estimate, command name). Acuity stamps
# them with wall-clock + monotonic time and appends to a single
# rotating JSONL file on disk. Designed to be cheap enough to call
# at 50 Hz from every subsystem on the bus — each write is a single
# `f.write(json.dumps(...) + "\n")`.
#
# Why JSONL not WPILog: WPILog is the canonical FRC format but parsing
# / writing it from a Python dashboard adds dependencies we don't have
# headroom for on a Pi Zero. JSONL is greppable from a laptop, easy to
# parse with `pandas.read_json(lines=True)`, and survives partial
# writes (each record is its own line).
# ---------------------------------------------------------------------

LOGS_DIR = Path(os.environ.get("ACUITY_LOGS_DIR", "/var/lib/acuity/logs"))
LOG_FILE = LOGS_DIR / "data.jsonl"
LOG_ROTATE_BYTES = 10 * 1024 * 1024     # 10 MB before we rotate
LOG_KEEP = 4                            # data.jsonl + 4 archives = ~50 MB cap

_log_lock = threading.Lock()
_log_fh: Optional[Any] = None


def _ensure_log_fh():
    """Open the log file lazily. Cheaper than re-opening per record,
    safe across rotations because we always reopen after rename."""
    global _log_fh
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if _log_fh is None:
        _log_fh = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
    return _log_fh


def _maybe_rotate_log():
    """Rotate when the live file crosses LOG_ROTATE_BYTES. Keeps
    LOG_KEEP archives, dropping the oldest."""
    global _log_fh
    try:
        size = LOG_FILE.stat().st_size
    except FileNotFoundError:
        return
    if size < LOG_ROTATE_BYTES:
        return
    if _log_fh is not None:
        try: _log_fh.close()
        except Exception: pass
        _log_fh = None
    # Shift archives: data.jsonl.3 → .4 → discarded
    for i in range(LOG_KEEP, 0, -1):
        src = LOGS_DIR / f"data.jsonl.{i}"
        dst = LOGS_DIR / f"data.jsonl.{i + 1}"
        if i == LOG_KEEP and src.exists():
            try: src.unlink()
            except Exception: pass
        elif src.exists():
            try: src.replace(dst)
            except Exception: pass
    try: LOG_FILE.replace(LOGS_DIR / "data.jsonl.1")
    except Exception: pass


@app.post("/api/log")
async def api_log_write(req: Request) -> JSONResponse:
    """Append one record. Body shape:
       { "key": "shooter_rpm", "value": 4350, "tags": { "match": "Q12" } }
    All three fields are optional except `key`."""
    body = await req.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "expected JSON object")
    key = body.get("key")
    if not isinstance(key, str) or not key:
        raise HTTPException(400, "'key' (string) is required")
    record = {
        "ts":    time.time(),
        "mono":  round(time.monotonic(), 6),
        "key":   key,
        "value": body.get("value"),
        "tags":  body.get("tags") or {},
    }
    line = json.dumps(record, separators=(",", ":")) + "\n"
    with _log_lock:
        _maybe_rotate_log()
        fh = _ensure_log_fh()
        fh.write(line)
    return JSONResponse({"ok": True, "ts": record["ts"]})


@app.get("/api/log")
async def api_log_tail(lines: int = 200) -> PlainTextResponse:
    """Tail the live log. Cheap because we only seek to a position
    near the end — no full read."""
    n = max(1, min(int(lines), 5000))
    if not LOG_FILE.exists():
        return PlainTextResponse("")
    # Read backwards in small chunks until we have N newlines or hit BOF.
    chunks: list[bytes] = []
    found = 0
    try:
        with open(LOG_FILE, "rb") as f:
            f.seek(0, 2)
            pos = f.tell()
            block = 8192
            while pos > 0 and found <= n:
                size = min(block, pos)
                pos -= size
                f.seek(pos)
                buf = f.read(size)
                chunks.append(buf)
                found += buf.count(b"\n")
    except Exception as e:
        return PlainTextResponse(f"# read error: {e}", status_code=500)
    chunks.reverse()
    text = b"".join(chunks).decode("utf-8", errors="replace")
    tail = "\n".join(text.splitlines()[-n:])
    return PlainTextResponse(tail)


@app.get("/api/log/download")
async def api_log_download() -> FileResponse:
    if not LOG_FILE.exists():
        raise HTTPException(404, "no log file yet")
    return FileResponse(LOG_FILE, media_type="application/x-ndjson",
                        filename="acuity-data.jsonl")


@app.post("/api/log/clear")
async def api_log_clear() -> JSONResponse:
    """Truncate the live log. Keeps existing archives."""
    global _log_fh
    with _log_lock:
        if _log_fh is not None:
            try: _log_fh.close()
            except Exception: pass
            _log_fh = None
        if LOG_FILE.exists():
            LOG_FILE.unlink()
    return JSONResponse({"ok": True})
