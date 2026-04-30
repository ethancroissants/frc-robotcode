# Cold Fusion Sight (Orange Pi 5)

The Pi runs the camera + a styled web UI. The rio runs the robot. They talk
over NetworkTables.

## What's in here

- `server.py` — FastAPI app: hosts the web UI, relays the camera, bridges
  click-to-aim requests to NetworkTables.
- `static/` — HTML/CSS/JS for the operator dashboard.
- `cold-fusion-sight.service` — systemd unit that auto-starts the server.
- `install.sh` — runs on the Pi, sets up venv + apt deps + the service.
- `requirements.txt` — Python deps (FastAPI, uvicorn, pyntcore).

## Setup (from the driver laptop)

Use the Control Panel:

```
python start.py
```

Click **Set up Vision Pi**. It asks for the Pi's user/host (defaults to
`orangepi@orangepi.local`), rsyncs this folder, and runs `install.sh` on
the Pi.

After the install finishes, the panel offers an **Open Sight UI** button —
or visit `http://<pi-host>:8080/` directly.

## Updating

`python start.py` → **Update Vision Pi** rsyncs changes and restarts the
service. No apt/venv churn.

## How click-to-aim works

1. Driver clicks somewhere on the live camera in the browser.
2. Browser POSTs `{x, y}` (normalized 0..1) to `/api/aim`.
3. Pi publishes those to `/SmartDashboard/Sight/Aim/{PixelX,PixelY}` and
   increments `RequestId`.
4. Rio's `AutoAim` command sees the new request id, computes target
   heading + range (LaserCAN if valid, else inverse pinhole projection),
   rotates the drivetrain, and chains into the existing fire sequence.
5. Status flows back via `/SmartDashboard/Sight/Aim/Status` so the UI
   shows `ROTATING / SPINNING_UP / FIRING / DONE`.

## Tweaking the team / camera resolution

`/home/orangepi/cold-fusion-sight/sight.env` is read by the service:

```
TEAM=1279
CAMERA_DEVICE=/dev/video0
CAMERA_WIDTH=1280
CAMERA_HEIGHT=720
CAMERA_FPS=30
HTTP_PORT=8080
```

Edit, then `sudo systemctl restart cold-fusion-sight`.

## Camera passthrough

We use ffmpeg with `-c copy -f mpjpeg` so frames flow USB → HTTP without
ever being decoded. The Pi's CPU stays cold; image quality is whatever
the camera's hardware MJPEG encoder produces. No rio CPU is consumed.
