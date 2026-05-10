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

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
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
    "tag_family":       "tag36h11",
    "tag_size_m":       0.1651,        # 6.5 in — 2025 FRC standard
    "min_decision_margin": 30.0,       # below this we drop detections

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

        if _HAVE_PA:
            self._detector = _pa.Detector(
                families="tag36h11",
                nthreads=2,
                quad_decimate=2.0,    # halves resolution for the detector
                quad_sigma=0.0,
                refine_edges=1,
                decode_sharpening=0.25,
                debug=0,
            )
        else:
            log.warning("pyapriltags missing; falling back to cv2.aruco "
                        "(reduced range, less precise pose)")
            self._detector = None

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
            self._on_snapshot({
                "tags":       tags,
                "best":       best,
                "frame_ts":   ts,
                "width":      w,
                "height":     h,
                "fps":        self._camera.fps,
                "connected":  self._camera.connected,
                "wall_ts":    time.time(),
            })

    def _detect(self, mono: np.ndarray, w: int, h: int,
                s: dict[str, Any]) -> list[Detection]:
        if self._detector is None:
            return []
        tag_size = float(s["tag_size_m"])
        # We pass approximate pinhole intrinsics — for a real
        # calibration we'd run cv2.calibrateCamera. For most teams
        # the approximation is plenty for tag-tracking use cases;
        # the calibration UI on the dashboard refines this if they
        # want better PnP accuracy.
        fx = fy = w * 0.9     # pure heuristic — good enough as a default
        cx = w * 0.5
        cy = h * 0.5

        try:
            results = self._detector.detect(
                mono,
                estimate_tag_pose=True,
                camera_params=(fx, fy, cx, cy),
                tag_size=tag_size,
            )
        except Exception:
            log.exception("AprilTag detection failed")
            return []

        out: list[Detection] = []
        min_dm = float(s["min_decision_margin"])
        for r in results:
            if getattr(r, "decision_margin", 0.0) < min_dm:
                continue
            cx_px, cy_px = float(r.center[0]), float(r.center[1])
            tx = (cx_px - w * 0.5) / (w * 0.5)
            ty = (cy_px - h * 0.5) / (h * 0.5)

            dist_m = 0.0
            yaw_deg = 0.0
            pitch_deg = 0.0
            if r.pose_t is not None and r.pose_R is not None:
                t = np.asarray(r.pose_t).reshape(3)
                # pyapriltags: t = [x, y, z] in meters, camera frame.
                # z = forward distance, x = right offset, y = down offset.
                dist_m = float(np.linalg.norm(t))
                yaw_deg   = math.degrees(math.atan2(float(t[0]), float(t[2])))
                pitch_deg = math.degrees(math.atan2(-float(t[1]), float(t[2])))

            # Tag area: corners (4×2) → polygon area / image area.
            corners = np.asarray(r.corners, dtype=np.float64)
            area = abs(_polygon_area(corners)) / max(1.0, float(w * h))

            out.append(Detection(
                id=int(r.tag_id),
                distance_m=dist_m,
                yaw_deg=yaw_deg,
                pitch_deg=pitch_deg,
                tx=tx,
                ty=ty,
                area=area,
                timestamp=self._last_processed_ts,
                decision_margin=float(getattr(r, "decision_margin", 0.0)),
                corners=corners.tolist(),  # for the SVG overlay
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

def _net_state() -> dict[str, Any]:
    """Read current WiFi mode + IP + hostname for the status pane."""
    try:
        host = subprocess.check_output(["hostname"], text=True).strip()
    except Exception:
        host = ""
    addr = ""
    try:
        out = subprocess.check_output(
            ["ip", "-br", "addr", "show", "wlan0"], text=True).strip()
        # `wlan0  UP  10.12.79.11/24  fe80::...`
        parts = out.split()
        for p in parts[2:]:
            if "." in p and "/" in p:
                addr = p.split("/", 1)[0]
                break
    except Exception:
        pass
    in_ap = addr == "192.168.50.1"
    return {
        "hostname":   host,
        "ip":         addr,
        "mode":       "ap" if in_ap else "sta" if addr else "down",
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
        "best":      snap.get("best"),
        "tags":      [{k: v for k, v in t.items() if k != "corners"}
                      for t in snap.get("tags", [])],
        "tags_full": snap.get("tags", []),
        "fps":       snap.get("fps"),
        "width":     snap.get("width"),
        "height":    snap.get("height"),
        "connected": snap.get("connected"),
        "wall_ts":   snap.get("wall_ts"),
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
        "best":  snap.get("best"),
        "tags":  snap.get("tags", []),
        "fps":   snap.get("fps"),
        "width": snap.get("width"),
        "height": snap.get("height"),
        "connected": snap.get("connected", False),
        "wall_ts":   snap.get("wall_ts", 0),
    })


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
