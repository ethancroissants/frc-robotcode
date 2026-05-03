# Cold Fusion Sight (Orange Pi 5)

The Pi runs the camera, AprilTag detection, and the operator web UI. The
rio runs robot code. They talk over NetworkTables.

## What's in here

- `server.py` — FastAPI app: camera capture, AprilTag detection, MJPEG
  stream, SSE state feed, debug-log feed, calibration table, NT4 bridge.
- `nt4_client.py` — pure-Python NT4 client (we don't ship pyntcore for
  linux_aarch64, so this is enough of NT4 to publish/subscribe).
- `static/` — windowed dashboard (HTML/CSS/JS).
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

## Pis without WiFi (Orange Pi 5 base, etc.)

The wizard uses the Pi's `wlan0` to briefly bridge to the internet for
the apt + pip download step. If your Pi has no built-in WiFi (the base
**Orange Pi 5 v1.x** is ethernet-only), the bridge can't run.

Workaround: plug the Pi into a network that already has internet (your
home router, a hotspot, etc.), SSH in, and run:

```bash
curl -sSL https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master/orangepi/manual_net_install.sh | bash
```

That installs the apt packages and downloads the pip wheels into the
same `~/cold-fusion-sight/vendor/wheels/` location the wizard uses, then
stamps the cache. Once it finishes, unplug the Pi from internet, move
it back to the robot network, and run **Set up / Update Vision Pi** —
the wizard will see the stamp and skip the bridge entirely.

## The dashboard

The web UI is a windowed dashboard. Each panel:

- **drag** by its title bar
- **resize** by the bottom-right corner
- **minimize** with the `−` button (collapses to header only)

Layout (positions, sizes, minimized state) persists in the browser's
`localStorage`. **Reset layout** in the top bar restores the defaults.

### Panels

- **Camera** — live MJPEG stream at 640×480 with crosshair, target box,
  range/bearing readout. Crosshair turns green when bearing is within
  the ready band (default ±2.5°). **Click any visible AprilTag to lock
  onto it** — the locked tag wins regardless of the configured
  `TARGET_TAG_IDS`. Click the letterbox / empty area, or the `clear
  lock` button, to release the lock.
- **Target** — tag id, range, bearing, recommended RPS. Status line
  reads `locked #N`, `searching for #N…`, or `no target`.
- **Fire** — the SHOOT button. Only turns red and becomes clickable when
  every precondition holds: rio connected, robot enabled, target
  detected with a known range, bearing inside the ready band, AutoAim
  not already running. The sub-label tells you which precondition is
  blocking. Below it, the live AutoAim status from the rio.
- **Distance** — manual dial (`±1`, `±½` ft) and the live tag-PnP range
  (in feet) for whatever tag is currently the target. `use as dial`
  copies the live tag range into the manual dial in one click. Stale
  values render as `—`.
- **Calibration** — distance (ft) → flywheel RPS table. The Pi reads
  the live tag-PnP range every frame, looks up + interpolates this
  table, and publishes the result as the auto-aim RPS. See **How to
  use calibration** below for the workflow.
- **Operator** — mirror of the operator-stick D-pad, bumpers, ABXY,
  driven from NT topics the rio publishes.
- **Debug** — three tabs:
  - `logs` — live tail of the server log (in-memory ring of the last
    500 lines, streamed over SSE). Exactly the same lines as
    `journalctl -u cold-fusion-sight`, no shell needed.
  - `nt` — NT topics with current value + age. Stale topics (no update
    in >2 s) render dim with the age in red.
  - `stats` — capture/detect/stream FPS, image size, intrinsics source,
    configured target tag IDs, currently-seen tag IDs, version.

## Click-to-target

The detector reports every visible AprilTag's pixel-space corners on
the SSE feed. When you click anywhere on the camera, the browser hit-
tests the click against those quads and POSTs the chosen `tag_id` to
`/api/target`. The server holds the selection until you change it:

- selection set + tag visible → that tag is the target (drawn with a
  thicker outline + corner dots so it reads as "operator-locked")
- selection set + tag *not* currently visible → no target
  (`searching for #N…`); the lock survives the dropout
- no selection → fall back to the largest tag whose ID is in
  `TARGET_TAG_IDS` (the original behavior)

The `/SmartDashboard/Sight/Target/SelectedID` topic mirrors the
selection so other dashboards / the rio can see what's locked.

## How to use calibration

Different shooting distances need different flywheel RPS. Air drag and
launch arc don't scale linearly. So instead of one "RPS per foot"
constant, the Pi keeps a **table** of `(distance_ft, rps)` rows that
you fill in by actually shooting at known distances. Every frame the
Pi reads the live tag-PnP range, finds the bracketing two rows, and
linearly interpolates an RPS — that's what AutoAim uses when you press
SHOOT.

### Step-by-step workflow

Open the **calibrate** link in the dashboard topbar (or go directly to
`/calibrate.html`). It's a focused page for this loop — manual RPS
input, FIRE button, log-point form. It also has a **calibrate mode**
toggle: while on, the Pi publishes your manual RPS to the rio instead
of the table value, so each test shot fires at exactly the RPS you
typed.

The first match you play against a fresh shooter, do this:

1. **Park the bot at a known distance from the goal.** A good first
   set: 4, 8, 12, 16 ft (or whatever range you actually shoot from).
2. **Click the goal AprilTag in the Camera panel** (on the dashboard).
   That locks the Pi onto that specific tag.
3. **Verify the tag range matches your tape measure** (visible on the
   calibrate page's target readout). If it's way off, fix
   `TAG_SIZE_M` / camera intrinsics first (see
   [`Camera intrinsics`](#camera-intrinsics) below).
4. **Flip on calibrate mode**, type a starting RPS, press FIRE.
   Iterate the RPS up/down until shots land in the goal.
5. **Click "Log this point"** — distance defaults to the live tag
   range, RPS defaults to your manual setting. Edit either if you
   want, then save → the row's added to the table.
6. **Move to the next distance, repeat** until you have ~5 rows
   spanning your real shooting range.
7. **Flip calibrate mode off** when you're done so SHOOT goes back to
   the table-interpolated RPS for game use.

If you'd rather edit by hand, the **Calibration** panel on the main
dashboard still has the same `add` form + `snapshot current shot`
button.

### Spin-up delay

The calibrate page also exposes a **spin-up delay** input — how long
AutoAim waits after commanding the wheel to spin up before firing.
Default 0.4 s, range 0–5 s. The Pi publishes it to
`/Sight/Aim/SpinUpDelayS`; AutoAim reads it every cycle, so you can
tune it from the dashboard without redeploying the rio. Increase it
if you're firing before the wheel is at speed, drop it toward zero if
the wheel is already spinning when SHOOT happens.

### How interpolation works

For a tag range of `d` (in feet):

- `d` ≤ lowest table row → returns lowest row's RPS (clamped).
- `d` ≥ highest table row → returns highest row's RPS (clamped).
- otherwise → finds the bracketing rows, linearly interpolates.

**Cap your table at the maximum distance you'd ever shoot from**, or
the clamp will silently use the highest row's RPS for any shot beyond
that — the ball will fall short.

**More rows in the range you actually shoot from = more accurate
shots.** Linear interpolation between two distant points (say only
rows at 0 and 16 ft) is usually wrong in the middle. Five rows is the
sweet spot for most shooters.

### What ships out of the box

| Distance (ft) | RPS |
| ------------- | --- |
| 0             | 0   |
| 4             | 40  |
| 8             | 80  |
| 12            | 100 |
| 16            | 110 |

This is "10 RPS/ft" tapering at the high end. **It will not score on
your goal.** Treat it as a placeholder — replace the rows on day 1.

The table lives at
`/home/orangepi/cold-fusion-sight/sight_calibration.json` and survives
both reboots and `Set up / Update Vision Pi` re-pushes (the path is
deliberately outside the rsync target).

### What SHOOT actually does with this

When the operator presses SHOOT:

1. Pi sees a tag, e.g. `range_m = 2.40` → `7.87 ft`.
2. Looks up the calibration table → interpolates between the 4 and 8
   ft rows → publishes e.g. `78.7 RPS` to `/Sight/Aim/TargetRps`.
3. Increments `/Sight/Shoot/RequestId`.
4. Rio's AutoAim sees the new request, rotates onto the bearing the
   Pi published, spins the wheel to 78.7 RPS, fires.

If the recommended RPS is wrong, the table is wrong — re-shoot at
that distance and overwrite the row.

## Camera intrinsics

The PnP range estimate works from a known tag size + camera intrinsics.
By default we synthesize a camera matrix from `CAMERA_HFOV_DEG` (a sane
fallback). For sub-degree bearings + accurate range, calibrate the
camera and drop the result at `cam_intrinsics.json` next to
`server.py`:

```json
{
  "K":    [[fx, 0, cx], [0, fy, cy], [0, 0, 1]],
  "dist": [k1, k2, p1, p2, k3]
}
```

The debug `stats` tab shows which path is in use (`synthetic …` vs
`calibrated (cam_intrinsics.json)`).

## Tweaking the team / camera / target tags

`/home/orangepi/cold-fusion-sight/sight.env` is read by the service:

```
TEAM=1279
CAMERA_DEVICE=/dev/video0
CAMERA_WIDTH=640
CAMERA_HEIGHT=480
CAMERA_FPS=30
HTTP_PORT=8080

# Comma-separated AprilTag IDs that count as "the goal" by default.
# Operator can override per-shot with click-to-target in the UI.
TARGET_TAG_IDS=3,4,7,8

# Ready-to-fire bearing band — SHOOT only arms when |bearing| ≤ this.
READY_BEARING_DEG=2.5

# Tag side length (meters). 0.1651 = 6.5 inches (FRC standard).
TAG_SIZE_M=0.1651
```

Edit, then `sudo systemctl restart cold-fusion-sight`.

## Debugging "no detection"

Open the **Debug → stats** tab — the `seen tags` row lists every tag the
detector found this tick, regardless of `TARGET_TAG_IDS`. Non-targeted
tags also draw on the camera stream in muted orange, so:

- "seen (none)": the detector isn't finding anything. Check focus,
  lighting, that the printed tag is the 36h11 family (FRC standard),
  and that the tag is large enough in frame.
- "seen 14, 22" but no target: your `TARGET_TAG_IDS` doesn't include
  those IDs. Either click the tag in the UI to lock onto it, or edit
  `sight.env` and restart.

## Watching service logs

The **Debug → logs** tab in the UI tails the same log stream. If you
need to look from a shell:

```
ssh orangepi@orangepi.local
sudo journalctl -u cold-fusion-sight -f
```

The service is `Restart=always` with no rate limit, so it'll keep coming
back if it crashes.

## How auto-aim works

1. Operator clicks a tag in the camera (locks the target) — or relies
   on the default `TARGET_TAG_IDS` pick — and presses **SHOOT** when the
   button arms (red).
2. Browser POSTs `/api/shoot`. The Pi increments
   `/SmartDashboard/Sight/Shoot/RequestId`.
3. Rio's button-press trigger sees the rising edge and schedules
   AutoAim.
4. AutoAim sets `DriverLockout=true`, drives heading off
   `/Sight/Target/BearingDeg`, dials shooter RPS off
   `/Sight/Aim/TargetRps` (the Pi's calibration-table interpolation),
   fires, and clears `DriverLockout`.

The Pi also publishes `/Sight/Aim/Ready` (true when bearing is inside
`READY_BEARING_DEG`, the robot is enabled, and AutoAim isn't already
running). Wire that to a controller rumble or a pre-fire indicator if
you want.

## Robot enabled state

The Pi reads `/SmartDashboard/Sight/RobotEnabled` and grays out the
SHOOT button + manual dial controls when the robot is disabled. Default
is True (so the UI is usable on a fresh setup that hasn't wired this
up yet); the rio's robot code should publish `false` while disabled and
`true` when enabled.
