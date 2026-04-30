"""Cold Fusion Sight — Orange Pi web server.

Replaces the rio-side overlay/streaming entirely. The Pi:
  1. Pulls MJPEG frames from /dev/video0 via ffmpeg in raw passthrough
     mode (no decode, no re-encode — straight USB hardware MJPEG to HTTP).
  2. Hosts a FastAPI web app that serves a styled control UI (camera +
     buttons + click-to-aim + LaserCAN readout + gamepad mirror).
  3. Connects to the roboRIO over NetworkTables (NT4) as a client — same
     protocol Elastic uses — and bridges:
       Pi → rio: click target, calibrate-sight requests, dial bumps.
       rio → Pi: dial/predicted/RPS, LaserCAN distance, gamepad state,
                 aim status.

The rio is on FRC team-numbered IPs (10.TE.AM.2). We default to team 1279,
overridable via TEAM env var.

Run with: uvicorn server:app --host 0.0.0.0 --port 8080
The systemd unit calls exactly that.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import AsyncIterator

import ntcore
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles


# ===== Config (env-overridable) =====
TEAM = int(os.environ.get("TEAM", "1279"))
NT_SERVER = os.environ.get("NT_SERVER", "")  # explicit IP overrides team lookup
CAMERA_DEVICE = os.environ.get("CAMERA_DEVICE", "/dev/video0")
CAMERA_WIDTH = int(os.environ.get("CAMERA_WIDTH", "1280"))
CAMERA_HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "720"))
CAMERA_FPS = int(os.environ.get("CAMERA_FPS", "30"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8080"))

REPO = Path(__file__).resolve().parent
STATIC_DIR = REPO / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("sight")


# ===== NetworkTables bridge =====
# Topic layout — must match what the rio publishes/subscribes to. Anything
# under /Sight is owned by us; /Tune/* is shared with the existing tunables.

class NTBridge:
    """Thin wrapper around ntcore for the values the web UI cares about.

    Reads are cached on a background thread so the FastAPI handlers don't
    have to call into ntcore on the hot path; writes go straight through.
    """

    # rio → Pi (read)
    READ_DOUBLE = {
        "dial_ft": "/SmartDashboard/Tune/Shooter Distance (ft)",
        "predicted_ft": "/SmartDashboard/Tune/Sight Predicted Landing (ft)",
        "rps_setpoint": "/SmartDashboard/Tune/Sight Predicted RPS",
        "lasercan_m": "/SmartDashboard/Sight/LaserCAN/DistanceM",
        "fov_deg": "/SmartDashboard/Tune/Sight Camera FOV (deg)",
        "cam_height_m": "/SmartDashboard/Tune/Sight Camera Height (m)",
        "cam_tilt_rad": "/SmartDashboard/Tune/Sight Camera Tilt (rad)",
    }
    READ_BOOL = {
        "lasercan_valid": "/SmartDashboard/Sight/LaserCAN/Valid",
        # Operator buttons — rio publishes a snapshot of getRawButton state.
        "btn_a": "/SmartDashboard/Sight/Buttons/A",
        "btn_b": "/SmartDashboard/Sight/Buttons/B",
        "btn_x": "/SmartDashboard/Sight/Buttons/X",
        "btn_y": "/SmartDashboard/Sight/Buttons/Y",
        "btn_lb": "/SmartDashboard/Sight/Buttons/LB",
        "btn_rb": "/SmartDashboard/Sight/Buttons/RB",
    }
    READ_INT = {
        "pov": "/SmartDashboard/Sight/Buttons/POV",
        "aim_request_id": "/SmartDashboard/Sight/Aim/RequestId",
    }
    READ_STR = {
        "aim_status": "/SmartDashboard/Sight/Aim/Status",
    }

    # Pi → rio (write)
    WRITE_DOUBLE = {
        "aim_x_norm": "/SmartDashboard/Sight/Aim/PixelX",
        "aim_y_norm": "/SmartDashboard/Sight/Aim/PixelY",
        "shooter_dial_ft": "/SmartDashboard/Tune/Shooter Distance (ft)",
        "calibrate_true_ft": "/SmartDashboard/Tune/Calibrate Sight True Distance (ft)",
    }
    WRITE_INT = {
        "aim_request_id": "/SmartDashboard/Sight/Aim/RequestId",
    }
    WRITE_BOOL = {
        "aim_requested": "/SmartDashboard/Sight/Aim/Requested",
        "calibrate_requested": "/SmartDashboard/Tune/Calibrate Sight",
    }

    def __init__(self) -> None:
        self.inst = ntcore.NetworkTableInstance.getDefault()
        self.inst.startClient4("OrangePi-Sight")
        if NT_SERVER:
            self.inst.setServer(NT_SERVER)
            log.info("NT4: connecting to %s", NT_SERVER)
        else:
            self.inst.setServerTeam(TEAM)
            log.info("NT4: connecting to team %d", TEAM)

        # Cache the NT entries so we're not re-resolving topic handles per call.
        self._d_pubs: dict[str, ntcore.DoublePublisher] = {}
        self._i_pubs: dict[str, ntcore.IntegerPublisher] = {}
        self._b_pubs: dict[str, ntcore.BooleanPublisher] = {}
        self._d_subs: dict[str, ntcore.DoubleSubscriber] = {}
        self._i_subs: dict[str, ntcore.IntegerSubscriber] = {}
        self._b_subs: dict[str, ntcore.BooleanSubscriber] = {}
        self._s_subs: dict[str, ntcore.StringSubscriber] = {}

        for key, path in self.READ_DOUBLE.items():
            self._d_subs[key] = self.inst.getDoubleTopic(path).subscribe(0.0)
        for key, path in self.READ_BOOL.items():
            self._b_subs[key] = self.inst.getBooleanTopic(path).subscribe(False)
        for key, path in self.READ_INT.items():
            self._i_subs[key] = self.inst.getIntegerTopic(path).subscribe(0)
        for key, path in self.READ_STR.items():
            self._s_subs[key] = self.inst.getStringTopic(path).subscribe("idle")

        for key, path in self.WRITE_DOUBLE.items():
            self._d_pubs[key] = self.inst.getDoubleTopic(path).publish()
        for key, path in self.WRITE_INT.items():
            self._i_pubs[key] = self.inst.getIntegerTopic(path).publish()
        for key, path in self.WRITE_BOOL.items():
            self._b_pubs[key] = self.inst.getBooleanTopic(path).publish()

        self._aim_request_id = 0

    def snapshot(self) -> dict:
        """Pull current values from every read entry. Cheap; called per SSE tick."""
        snap: dict[str, object] = {"connected": self.inst.isConnected()}
        for key, sub in self._d_subs.items():
            snap[key] = sub.get()
        for key, sub in self._b_subs.items():
            snap[key] = sub.get()
        for key, sub in self._i_subs.items():
            snap[key] = sub.get()
        for key, sub in self._s_subs.items():
            snap[key] = sub.get()
        return snap

    def request_aim(self, x_norm: float, y_norm: float) -> int:
        """Publish a click target. Returns the new request id."""
        self._aim_request_id += 1
        self._d_pubs["aim_x_norm"].set(float(x_norm))
        self._d_pubs["aim_y_norm"].set(float(y_norm))
        self._b_pubs["aim_requested"].set(True)
        self._i_pubs["aim_request_id"].set(self._aim_request_id)
        return self._aim_request_id

    def cancel_aim(self) -> None:
        self._b_pubs["aim_requested"].set(False)

    def set_dial(self, ft: float) -> None:
        self._d_pubs["shooter_dial_ft"].set(float(ft))

    def request_calibrate(self, true_ft: float) -> None:
        self._d_pubs["calibrate_true_ft"].set(float(true_ft))
        self._b_pubs["calibrate_requested"].set(True)


# ===== Camera relay =====
# ffmpeg with `-c copy -f mpjpeg` reads MJPEG straight off V4L2 (the camera's
# hardware encoder) and writes a multipart/x-mixed-replace stream to stdout —
# no decode, no re-encode. Pi 5 idles at <5% CPU even at 1080p30.
# The first multipart boundary line is configurable; we use the default
# "ffmpeg" boundary so the browser's <img src=mjpg> handler picks it up.

class CameraRelay:
    BOUNDARY = b"ffmpeg"

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._latest: bytes | None = None
        self._cond = threading.Condition()
        self._stop = False

    def start(self) -> None:
        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "ffmpeg not found on PATH — install with `sudo apt install ffmpeg`"
            )
        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-nostdin",
            "-f", "v4l2",
            "-input_format", "mjpeg",
            "-video_size", f"{CAMERA_WIDTH}x{CAMERA_HEIGHT}",
            "-framerate", str(CAMERA_FPS),
            "-i", CAMERA_DEVICE,
            "-c", "copy",
            "-f", "mpjpeg",
            "-boundary_tag", self.BOUNDARY.decode(),
            "pipe:1",
        ]
        log.info("starting camera: %s", " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        threading.Thread(target=self._reader, name="camera-reader", daemon=True).start()
        threading.Thread(target=self._stderr_drain, name="camera-stderr", daemon=True).start()

    def _stderr_drain(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return
        for line in self._proc.stderr:
            log.warning("ffmpeg: %s", line.decode(errors="replace").rstrip())

    def _reader(self) -> None:
        """Parse the multipart stream into discrete JPEG frames.

        The stream looks like:
          --ffmpeg\r\nContent-Type: image/jpeg\r\nContent-Length: NNN\r\n\r\n
          <NNN bytes of JPEG>\r\n
          --ffmpeg\r\n...
        We only need the frame bytes for the SSE/state, but the relay
        forwards the *whole* multipart stream byte-for-byte to the browser
        (handled separately in stream_passthrough).
        """
        if self._proc is None or self._proc.stdout is None:
            return
        buf = b""
        sep = b"--" + self.BOUNDARY + b"\r\n"
        while not self._stop:
            chunk = self._proc.stdout.read(65536)
            if not chunk:
                log.error("camera stream ended; restarting in 1s")
                time.sleep(1.0)
                self.restart()
                return
            buf += chunk
            # Cap buffer; we only keep the most recent frame.
            if len(buf) > 4 * 1024 * 1024:
                buf = buf[-2 * 1024 * 1024:]
            # Push the latest chunk to subscribers waiting on a frame change.
            with self._cond:
                self._latest = chunk
                self._cond.notify_all()

    def restart(self) -> None:
        self.stop()
        self.start()

    def stop(self) -> None:
        self._stop = True
        if self._proc:
            try:
                self._proc.send_signal(signal.SIGINT)
                self._proc.wait(timeout=2.0)
            except Exception:
                self._proc.kill()
        self._proc = None
        self._stop = False

    async def stream_passthrough(self) -> AsyncIterator[bytes]:
        """Forward the multipart MJPEG stream to one HTTP client.

        Each browser tab gets its own iterator; they all subscribe to the
        same shared latest-chunk variable and write it as it arrives.
        """
        loop = asyncio.get_running_loop()
        last_seen = id(self._latest)
        while True:
            chunk = await loop.run_in_executor(None, self._wait_for_chunk, last_seen)
            if chunk is None:
                break
            last_seen, data = chunk
            yield data

    def _wait_for_chunk(self, last_seen: int) -> tuple[int, bytes] | None:
        """Block until a new chunk is available; return (token, bytes)."""
        with self._cond:
            while self._latest is None or id(self._latest) == last_seen:
                self._cond.wait(timeout=2.0)
                if self._stop:
                    return None
            return id(self._latest), self._latest


# ===== FastAPI app =====
app = FastAPI(title="Cold Fusion Sight")
nt = NTBridge()
camera = CameraRelay()


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
    """Pass through the camera's multipart MJPEG to the browser <img>.

    Browsers natively render multipart/x-mixed-replace as a live image
    when used in an <img src> — no JS needed for the basic stream.
    """
    media_type = f"multipart/x-mixed-replace; boundary={CameraRelay.BOUNDARY.decode()}"
    return StreamingResponse(camera.stream_passthrough(), media_type=media_type)


@app.get("/api/state")
async def api_state(request: Request) -> StreamingResponse:
    """Server-Sent Events feed of robot state for the live HUD."""

    async def event_stream() -> AsyncIterator[str]:
        last_payload = ""
        while not await request.is_disconnected():
            snap = nt.snapshot()
            payload = json.dumps(snap, default=float)
            if payload != last_payload:
                last_payload = payload
                yield f"data: {payload}\n\n"
            await asyncio.sleep(0.05)  # 20 Hz max

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/aim")
async def api_aim(payload: dict) -> JSONResponse:
    """Browser POSTs {x: 0..1, y: 0..1} when the user clicks the camera."""
    try:
        x = float(payload["x"])
        y = float(payload["y"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="x and y (0..1) required")
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise HTTPException(status_code=400, detail="x/y must be in [0, 1]")
    rid = nt.request_aim(x, y)
    return JSONResponse({"ok": True, "request_id": rid})


@app.post("/api/aim/cancel")
async def api_aim_cancel() -> JSONResponse:
    nt.cancel_aim()
    return JSONResponse({"ok": True})


@app.post("/api/dial")
async def api_dial(payload: dict) -> JSONResponse:
    """Manual dial setpoint, used by the on-screen +/- buttons."""
    try:
        ft = float(payload["ft"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="ft (number) required")
    nt.set_dial(max(0.0, ft))
    return JSONResponse({"ok": True, "ft": ft})


@app.post("/api/calibrate")
async def api_calibrate(payload: dict) -> JSONResponse:
    try:
        true_ft = float(payload["true_ft"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="true_ft (number) required")
    nt.request_calibrate(true_ft)
    return JSONResponse({"ok": True})


@app.get("/api/healthz")
async def healthz() -> dict:
    return {"ok": True, "nt_connected": nt.inst.isConnected()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="info")
