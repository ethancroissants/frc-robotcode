# Cold Fusion Sight (Orange Pi 5)

The Pi runs the camera, AprilTag detection, and the operator web UI. The
rio runs robot code. They talk over NetworkTables.

## What's in here

- `server.py` — FastAPI app: camera capture, AprilTag detection, MJPEG
  stream, SSE state feed, calibration table, NT4 bridge.
- `nt4_client.py` — pure-Python NT4 client (we don't ship pyntcore for
  linux_aarch64, so this is enough of NT4 to publish/subscribe).
- `static/` — HTML/CSS/JS for the operator dashboard.
- `cold-fusion-sight.service` — systemd unit that auto-starts the server.
- `install.sh` — runs on the Pi, sets up venv + sight.env + the service.
- `requirements.txt` — Python deps (FastAPI, uvicorn, opencv, numpy, …).

## Setup (from the driver laptop)

Use the Control Panel:

```
python start.py
```

Click **Set up / Update Vision Pi**. It asks for the Pi's user/host
(defaults to `orangepi@orangepi.local`), then:

1. Installs an SSH key so future runs don't ask for the password.
   (If the Pi was reflashed and the host key changed, the script auto-
   clears the stale `known_hosts` entry and retries.)
2. Probes the Pi for Python/arch + missing apt packages.
3. Pushes the latest `orangepi/` folder.
4. **If anything's missing or the wheel cache is stale**: briefly
   connects the Pi's WiFi to a network you supply (apt install + `pip
   download` of the requirements). The Pi's robot ethernet stays put —
   only `wlan0` is used. The bridge is skipped on subsequent re-runs
   when nothing's changed.
5. Runs `install.sh` on the Pi (idempotent — reuses the venv, only
   re-installs pip deps if `requirements.txt` changed, only restarts
   the service if the unit file actually differs).

After install, the panel offers **Open Sight UI** — or visit
`http://<pi-host>:8080/` directly.

> **There is no separate "update" script.** Setup is idempotent. Re-run
> the same button to push code changes; nothing it does is destructive.

## Tweaking the team / camera / target tags

`/home/orangepi/cold-fusion-sight/sight.env` is read by the service:

```
TEAM=1279
CAMERA_DEVICE=/dev/video0
CAMERA_WIDTH=1280
CAMERA_HEIGHT=720
CAMERA_FPS=30
HTTP_PORT=8080

# Comma-separated AprilTag IDs that count as "the goal".
# Default: 2024 Crescendo speaker tags (3,4,7,8).
TARGET_TAG_IDS=3,4,7,8

# Camera horizontal field of view, used for the bearing math.
CAMERA_HFOV_DEG=60.0

# Tag side length (meters). 0.1651 = 6.5 inches (FRC standard).
TAG_SIZE_M=0.1651
```

Edit, then `sudo systemctl restart cold-fusion-sight`.

## Debugging "no detection"

The web UI shows **"Seen X, Y"** under the camera header — those are the
IDs the detector found this tick, regardless of `TARGET_TAG_IDS`.
Non-targeted tags also get drawn on the stream in muted orange. So:

- "Seen (none)": the detector isn't finding tags. Check focus, lighting,
  and that the printed tag is actually the 36h11 family (FRC standard).
- "Seen 14, 22" but UI says "no target": your `TARGET_TAG_IDS` doesn't
  include those IDs. Edit `sight.env` and restart.

## Watching service logs

```
ssh orangepi@orangepi.local
sudo journalctl -u cold-fusion-sight -f
```

The service is `Restart=always` with no rate limit, so it'll keep coming
back if it crashes. If it crashes consistently, the journal has the
traceback.

## How auto-aim works

1. Operator clicks the **SHOOT** button (only red/armed when there's a
   target lock and the robot is enabled).
2. Browser POSTs `/api/shoot`. The Pi increments
   `/SmartDashboard/Sight/Shoot/RequestId`.
3. Rio's button-press trigger sees the rising edge and schedules
   AutoAim.
4. AutoAim sets `DriverLockout=true`, drives heading off
   `/Sight/Target/BearingDeg`, dials shooter RPS off
   `/Sight/Aim/TargetRps` (the Pi's calibration-table interpolation),
   fires, and clears `DriverLockout`.

## Robot enabled state

The Pi reads `/SmartDashboard/Sight/RobotEnabled` and grays out the
SHOOT button + manual dial controls when the robot is disabled. Default
is True (so the UI is usable on a fresh setup that hasn't wired this
up yet); the rio's robot code should publish `false` while disabled and
`true` when enabled.
