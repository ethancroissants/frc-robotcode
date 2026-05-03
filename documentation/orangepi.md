# Vision Pi (Orange Pi 5) — Setup Guide

The Pi runs the camera, AprilTag detector, and the SHOOT web page. The
rio runs the robot. They share the robot's network and talk over
NetworkTables.

If you're new to this — **read the next section first.** It's the part
that's confusing the first time, and the rest of the doc assumes you've
seen it.

---

## How firing actually works (the new way)

The old "click anywhere on the camera and the bot fires there" is gone.
Replaced with: **the Pi tracks an AprilTag with the camera, the operator
presses SHOOT, the rio rotates onto the tag and fires using the
calibrated RPS for that distance.** No clicking required.

**Step by step, when you press SHOOT:**

1. The Pi has been running an AprilTag detector on every camera frame
   the whole time. It already knows: which tag, what angle off the
   robot's nose (bearing, in degrees), and approximately how far away
   (range, in meters — derived from solvePnP on the known tag size +
   the camera intrinsics).
2. The Pi looks up the right flywheel RPS from its **calibration
   table** (a list of distance → RPS pairs you fill in by shooting at
   known distances; see "Shooter calibration" below).
3. The Pi POSTs to its own `/api/shoot`, which bumps an NT counter
   `/Sight/Shoot/RequestId`.
4. The rio's command scheduler sees the counter tick and schedules
   `AutoAim`. AutoAim:
   a. Sets `/Sight/DriverLockout = true` so the Pi UI shows
      **DRIVER LOCKED** and the operator knows.
   b. Reads the *fresh* bearing from the Pi every 20 ms loop, runs a
      PID that drives bearing to zero by yawing the swerve. The
      driver controller is *physically powerless* during this — the
      AutoAim command requires the drivetrain, which cancels the
      joystick default command.
   c. Spins the flywheel at the Pi-recommended RPS (not the rio's
      old "10 rps per foot" linear mapping — the calibration table
      is the source of truth now).
   d. When bearing is locked AND the flywheel is at speed, runs the
      kicker + conveyor for `auto_fire_duration` seconds.
   e. Releases the lockout, returns control to the driver.

**This means:** the only inputs that matter to firing are (a) what
AprilTag the Pi sees and (b) the calibration table. Everything else
is automatic.

---

## TL;DR — what do I press in the control panel?

Open `python start.py`. The **Vision Pi** section has four buttons.
They're numbered for the order you press them the *first* time:

| #   | Button                       | When to press                                                                                                       |
| --- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| 1   | **Set up / Update Vision Pi**| Once per Pi for first install; re-run any time to push code changes (idempotent — only does what's actually needed). |
| 2   | **Open Sight UI**            | Any time after #1 finishes. Opens the camera page in your browser.                                                  |
| —   | **SSH to Vision Pi**         | Debugging only — opens a terminal on the Pi.                                                                        |

After step #1 succeeds, **you do not press anything else day-to-day.**
The "Deploy to Robot" button in the Robot Code section ships your code
to the rio, and the rio automatically forwards Pi files to the Pi on
its next boot. (See "How this actually works" below.)

**If a button is greyed out**, the panel is telling you why in its
subtitle — usually one of:

- *"Run 'Set up Vision Pi' first."* — `.orangepi_cfg` doesn't exist yet.
- *"Pi offline — power it and connect to the robot network."* — the Pi
  isn't responding to ping. Check power, ethernet, and that you're on
  the same network as the Pi.

The control panel polls every 5 seconds, so cards re-enable on their
own once the Pi comes back.

---

## TL;DR — what do I press in the control panel?

Open `python start.py`. The **Vision Pi** section has four buttons.
They're numbered for the order you press them the *first* time:

| #   | Button                       | When to press                                                                                                       |
| --- | ---------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| 1   | **Set up / Update Vision Pi**| Once per Pi for first install; re-run any time to push code changes (idempotent — only does what's actually needed). |
| 2   | **Open Sight UI**            | Any time after #1 finishes. Opens the camera page in your browser.                                                  |
| —   | **SSH to Vision Pi**         | Debugging only — opens a terminal on the Pi.                                                                        |

After step #1 succeeds, **you do not press anything else day-to-day.**
The "Deploy to Robot" button in the Robot Code section ships your code
to the rio, and the rio automatically forwards Pi files to the Pi on
its next boot. (See "How this actually works" below.)

**If a button is greyed out**, the panel is telling you why in its
subtitle — usually one of:

- *"Run 'Set up Vision Pi' first."* — `.orangepi_cfg` doesn't exist yet.
- *"Pi offline — power it and connect to the robot network."* — the Pi
  isn't responding to ping. Check power, ethernet, and that you're on
  the same network as the Pi.

The control panel polls every 5 seconds, so cards re-enable on their
own once the Pi comes back.

---

## How this actually works (read this)

### The network

Every FRC robot has the same network shape:

```
                Driver laptop (DHCP)
                       │
                   robot WiFi
                       │
                ┌──────┴──────┐
                │   Radio     │   10.TE.AM.1     ← always
                └──┬────────┬─┘
                   │        │
                Ethernet  Ethernet
                   │        │
              ┌────▼──┐  ┌──▼──────────┐
              │ rio   │  │ Orange Pi 5 │
              │ .2    │  │ .11         │   ← we pin this
              └───────┘  └─────────────┘
```

For team **1279**, that means:

| Device              | IP          | Notes                              |
|---------------------|-------------|------------------------------------|
| Radio               | 10.12.79.1  | Set by the radio image             |
| **roboRIO**         | 10.12.79.2  | Set by the FRC NI image, hardcoded |
| Driver laptop       | 10.12.79.5+ | DHCP, varies                       |
| **Vision Pi**       | 10.12.79.11 | Pinned by `install.sh` (this repo) |

You don't pick these. The radio + rio + image all assume them. We just
pick `.11` for the Pi because that's the standard "first coprocessor"
slot in FRC, and we *pin* it during Pi setup so it never moves.

> "What if I'm not on team 1279?" Edit `pyproject.toml` /
> `.wpilib/wpilib_preferences.json` to set your team. The setup script
> will read it and pin the Pi to `10.<TE>.<AM>.11` automatically.

### The boot sequence

Power flows on. From there, with **zero buttons pressed:**

1. Radio comes up (`10.TE.AM.1`).
2. Pi boots Armbian → `cold-fusion-sight.service` autostarts → web
   server listens on `:8080` → tries to reach the rio over NT.
3. rio boots → robot code starts → `orangepi_pusher.py` runs in a
   daemon thread. It looks at `pi_target.json` (which got deployed
   along with `robot.py`), finds the Pi at `10.TE.AM.11`, and:
   - hashes the deployed `orangepi/` files
   - SSHes the Pi as `orangepi` (using a key set up at provisioning time)
   - if the hash differs from what's on the Pi, tar-pipes the new
     files, writes the hash, and `systemctl restart cold-fusion-sight`
   - if the hashes match, does nothing.
4. Pi's web server is now showing the latest UI; rio's robot code is
   running. They've found each other over NT and the dashboard pill
   says **CONNECTED**.

That's it. **You never need to deploy the Pi separately.** Press the
single **Deploy to Robot** button on the laptop → rio gets the code →
on next robot boot the rio pushes the relevant files to the Pi. Done.

### How they talk

Two channels:

- **NetworkTables (live state).** Same protocol Elastic and Shuffleboard
  use. The Pi runs as an NT4 client and the rio is the server. Topic map:

  *Pi → rio*:
  - `/Sight/Target/Detected` (bool) — tag visible right now?
  - `/Sight/Target/BearingDeg` — signed angle of tag from camera axis
  - `/Sight/Target/RangeM` — PnP-derived range (meters)
  - `/Sight/Target/TagID` — which tag is locked
  - `/Sight/Target/SelectedID` — operator's clicked-tag selection
  - `/Sight/Aim/TargetRps` — calibrated flywheel RPS for current distance
  - `/Sight/Aim/Ready` — bearing aligned + enabled + AutoAim idle
  - `/Sight/Shoot/RequestId` — bumped on SHOOT button press

  *rio → Pi*:
  - `/Sight/RobotEnabled` — DS enabled state mirror
  - `/Sight/Aim/Status` — `idle` / `rotating` / `spinning_up` / `firing` / `done` / `error`
  - `/Sight/DriverLockout` — true while AutoAim is running
  - `/Sight/Buttons/{A,B,X,Y,LB,RB,POV}` — operator gamepad mirror
  - `/Sight/Buttons/Driver/{A,B,X,Y,LB,RB,POV}` — driver gamepad mirror
  - `/Tune/Shooter Distance (ft)` — manual dial value

- **SSH (file pushes).** Used only for `orangepi_pusher.py` (rio →
  Pi) shipping new files when you redeploy. Not used at runtime — all
  match-time chatter is NT.

### Where you open the UI

Three URLs, all show the same page:

- `http://10.12.79.11:8080/` — the static IP, always works on the
  robot's network.
- `http://orangepi.local:8080/` — convenience, mDNS hostname.
- The **Open Sight UI** button in the control panel.

Bookmark the first one. It's rock-solid because the Pi's IP is pinned.

---

## First-time hardware setup

You only do this once per Pi, when you first build it.

### What you need

- Orange Pi 5 (or 5B) — 4 GB RAM is plenty
- microSD card, 32 GB or larger (Class 10 / A2)
- USB-C 5 V / 3 A power supply (Pi 5 won't reliably boot at 2 A)
- USB webcam (any UVC camera that supports MJPEG — most do)
- Ethernet cable (Pi → robot radio's spare LAN port)
- microSD reader for your laptop

You don't need a monitor or keyboard for the Pi after first boot.
Setup is "headless" — flash the SD, plug it in, then drive it from
the laptop over SSH.

### What needs to be powered on, and what network you need

This trips people up the first time. Quick reference:

| Step                     | Pi          | rio         | Radio       | Laptop network              |
| ------------------------ | ----------- | ----------- | ----------- | --------------------------- |
| 1. Flash SD card         | OFF         | —           | —           | any (download only)         |
| 2. First boot of Pi      | ON (powered) | —          | —           | same network as the Pi¹     |
| 3. Find Pi from laptop   | ON          | —           | —           | same network as the Pi¹     |
| 4. Set up Vision Pi      | ON          | **ON**²     | ON          | **robot WiFi (FRC-1279)**   |
| 5. Deploy to Robot       | ON³         | **ON**      | ON          | **robot WiFi (FRC-1279)**   |
| Daily use                | ON          | ON          | ON          | robot WiFi                  |

¹ For Steps 2–3 you can use any network as long as the Pi and your
laptop are on the same one — your home WiFi, school network, or the
robot radio all work. The robot's radio is recommended because it's
where the Pi will live permanently anyway.

² **rio should be on for Step 4** so the wizard can install SSH keys
in both directions (Pi → rio for `orangepi_pusher.py`'s reverse path,
rio → Pi so the rio can push files automatically). If the rio is off
when you run setup, the wizard will say "rio not reachable — skipping
cross-host SSH for now" and finish the rest. Re-run setup later with
the rio on, or run the **Set up Vision Pi** button again — it's
idempotent.

³ The Pi doesn't actually need to be on for Step 5 — the rio just
caches the new files and pushes them next time the Pi boots. But if
both are on, the new code lands within seconds of the deploy.

### Connecting your laptop to the robot WiFi

The control panel's **Connect** button (Connection section) does this
for you on Windows: it joins `FRC-1279`, drops the Windows firewall,
and pings the rio. If you're on macOS / Linux, join the WiFi by hand
and verify with `ping 10.12.79.2` (rio) and `ping 10.12.79.11` (Pi).

### Step 1 — flash the SD card

> **Powered on:** nothing.  **Network:** any (just need to download).

1. Download **Armbian** for Orange Pi 5 (Bookworm minimal):
   <https://www.armbian.com/orange-pi-5/>
2. Download **balenaEtcher**: <https://etcher.balena.io/>
3. Open Etcher → pick the Armbian `.img.xz` → pick the SD card → **Flash**.
4. Eject the card.

### Step 2 — first boot (one-time, with monitor)

> **Powered on:** Pi (with monitor + keyboard temporarily).
> **Network:** plug the Pi's ethernet into any network that has DHCP +
> internet — the robot radio is fine, your house/school WiFi router is
> fine. The rio does not need to be on yet.

For first boot you'll want a USB keyboard and HDMI monitor on the Pi
just for ~5 minutes:

1. Insert SD card. Plug in keyboard, monitor, USB camera, ethernet
   (to a regular network — your house, school, or the robot's radio).
   Plug in USB-C power.
2. Wait for the login prompt. First Armbian login is `root` / `1234`;
   it'll force you to change the password and create a regular user.
   **Use the username `orangepi`** — the rest of this guide assumes it.
3. Once logged in as `orangepi`, run:
   ```bash
   sudo systemctl enable --now ssh
   ip a
   ```
   Note the IP address. On the robot's radio it's whatever DHCP gave
   you at first; we'll pin it to `.11` during setup.
4. Unplug monitor + keyboard. The rest is from your laptop.

### Step 3 — find the Pi from your laptop

> **Powered on:** Pi.  **Network:** your laptop must be on the same
> network as the Pi (same WiFi router or plugged into the same radio).
> The rio still doesn't need to be on.

```bash
ping orangepi.local
# or use the IP you noted from Step 2
```

If `orangepi.local` doesn't resolve, your network blocks mDNS — use
the IP. Either works for the rest of the setup.

### Step 4 — provision from the laptop

> **Powered on:** Pi, **rio**, radio.
> **Network:** your laptop on the robot WiFi (`FRC-1279`). The Connect
> button in the control panel does this for you on Windows.
>
> Why the rio needs to be on: the wizard installs SSH keys both
> directions (rio's `lvuser` → Pi for the auto-push, Pi → rio admin for
> debugging). If the rio is off, the wizard finishes everything else
> and prints "rio not reachable — skipping cross-host SSH for now";
> re-run setup later with the rio on. It's idempotent.

```bash
python start.py
```

Click **Set up Vision Pi**. The wizard will:

1. Ask for the Pi's host (`orangepi.local` or its IP) and user (`orangepi`).
2. Ask for the Pi user's password (the one you set on first boot)
   **only on the first run**. On every re-run after that, key auth
   already works — no prompt, no nag.
   - If the Pi was reflashed and its host key changed, the wizard
     auto-clears the stale `known_hosts` entry so it doesn't get
     stuck on a "REMOTE HOST IDENTIFICATION HAS CHANGED" warning.
3. rsync this whole `orangepi/` folder onto the Pi.
4. **If anything's missing or the wheel cache is stale**, briefly
   connect the Pi's `wlan0` to a WiFi you supply (the wizard will
   prompt for SSID + password). Inside that bridge it apt-installs
   any missing packages and `pip download`s wheels. Disconnects when
   done. The Pi's robot ethernet is left alone the whole time.
   - On re-runs where everything is already installed, the bridge is
     skipped entirely and no WiFi prompt appears.
5. Run `install.sh` on the Pi, which:
   - creates the venv if it doesn't exist
   - installs pip deps from the local wheel cache (only if
     `requirements.txt` changed since last run — stamped in `.venv/.pip-stamp`)
   - **pins the Pi's IP to `10.TE.AM.11`** on `eth0`
   - drops a sudoers rule so the rio can `systemctl restart` later
   - installs the `cold-fusion-sight` systemd unit (and only restarts
     the service if the unit file actually differs from what's installed)
6. Set up SSH keys both directions (Pi ↔ admin@rio, Pi ↔ lvuser@rio).
7. Write `pi_target.json` at the repo root so the rio knows where the
   Pi lives once you deploy.

When done, click **Open Sight UI**. Your browser lands on
`http://10.TE.AM.11:8080/`. You should see CONNECTED in green and a
live camera feed.

### Step 5 — the very next deploy

> **Powered on:** **rio** (and Pi if you want changes to land
> immediately — the rio caches them either way).  **Network:** laptop
> on `FRC-1279`.

Press **Deploy to Robot**. The rio gets the new code (including
`pi_target.json`); on its next boot, `orangepi_pusher` will SSH the
Pi and verify the orangepi/ files match. From then on, every Deploy
keeps both in sync automatically. **You never touch the Pi directly
again unless you want to.**

---

## AprilTag tracking — what the Pi looks for

The Pi runs OpenCV's `cv2.aruco` detector on every camera frame, looking
for AprilTags from the **36h11** family (the standard FRC field uses
this family — every season's field-element tags are 36h11).

By default the Pi tracks tag IDs **3, 4, 7, 8** (2024 Crescendo speaker
tags). To track different tags, edit one line in
`orangepi/sight.env` on the Pi (or in the install.sh defaults if you're
re-provisioning):

```
TARGET_TAG_IDS=3,4,7,8
```

Comma-separated list. Empty list means "track any tag in the family",
which is fine for testing but you really want to constrain it to the
tags that mark *your* shooting target so the Pi doesn't lock onto a
random partner-bot's tag mid-match.

If you change `TARGET_TAG_IDS`, restart the Pi service (or just the
robot — the rio re-pushes the Pi files on boot if they changed):

```bash
ssh orangepi@10.12.79.11 'sudo systemctl restart cold-fusion-sight'
```

### Camera FOV

The bearing computation needs the camera's horizontal field-of-view in
degrees. The default is **60°**, which fits most USB webcams and the
ELP/Logitech cameras typically used for FRC vision. If you're using a
narrower or wider lens, set `CAMERA_HFOV_DEG` in `sight.env`.

The Pi will work with the wrong FOV — it'll just point a degree or two
off, since bearing scales linearly with the FOV value. To check: pick a
spot 5 m away with a tag, and verify the Pi's bearing readout agrees
with where the tag actually is in the frame (center = 0°, edge of frame
= ±FOV/2).

### Tag size

PnP range estimation assumes a **6.5 inch (0.1651 m)** tag side length,
which is the FRC standard. If you're testing with printed tags of a
different size, set `TAG_SIZE_M` in `sight.env`. Range readings are
linearly proportional to the assumed tag size, so a 2× error here gives
a 2× error in the range — set this to match the tag you actually print.

---

## Shooter calibration — making it accurate

> **Operator-facing walkthrough:** see [`vision_setup.md`](vision_setup.md)
> for the step-by-step "click tag → measure → save row" workflow plus
> a quick troubleshooting table. The section below is the architecture
> view of what's happening underneath.

Different shooting distances need different flywheel RPS — air drag and
launch arc don't scale linearly with distance. So the Pi keeps an
**interpolation table** of (distance_ft, rps) pairs that you fill in by
shooting at known distances. The Pi reads the live tag-PnP range every
frame, looks up the bracketing two table rows, linearly interpolates
the RPS, and publishes the result to NT for AutoAim to consume.

### How to calibrate (the actual workflow)

In the Sight dashboard there's a **CALIBRATION** panel showing the
current table, an **add** form, and a **snapshot current shot** button.

The fast loop:

1. **Park the bot at a known distance from the goal.** Tape measure or
   field markings — what matters is that you trust the number.
2. **Aim and shoot.** Click the goal AprilTag in the Camera panel so the
   target is locked, then dial flywheel RPS up/down (the **Distance**
   panel's `±1 / ±½` buttons step the dial in feet, which the rio's
   shooter command turns into RPS). Fire manually.
3. **Iterate the RPS** until shots actually land cleanly. This is the
   hard part — it's calibrating to your shooter's geometry, not to math.
4. **Save the row.** Either:
   - Type the distance + final RPS into the **add** form and click
     **add** — explicit, precise.
   - Or click **snapshot current shot** — captures the live tag range
     (in ft) + the dialed RPS automatically. Faster but only as accurate
     as the tag-PnP range.
5. **Move to a new distance, repeat.** Aim for ~5 evenly-spaced points
   spanning your real shooting range (e.g. 4, 8, 12, 16 ft).

The table is stored on the Pi at
`/home/orangepi/cold-fusion-sight/sight_calibration.json` and survives
reboots and re-pushes. Edit rows by deleting (the **remove** button per
row) and re-adding.

### How interpolation works

For a given distance `d` (in ft):
- If `d` is at or below the lowest table row: returns that row's RPS.
- If `d` is at or above the highest table row: returns that row's RPS.
- Otherwise: finds the two bracketing rows and linearly interpolates.

**Cap your table at the maximum distance you'd ever shoot from**,
otherwise the clamp will silently use the highest row's RPS for any
shot beyond that — under-throwing the ball.

### Sensible starting table

The default table the Pi ships with:

| Distance (ft) | RPS |
| ------------- | --- |
| 0             | 0   |
| 4             | 40  |
| 8             | 80  |
| 12            | 100 |
| 16            | 110 |

This matches "10 RPS per foot" at the low end and diminishes at the
high end (air resistance). **It is a starting point.** It will not
score on your goal. Replace it with real shot data on day 1.

### What's the SHOOT button doing with this?

When the operator clicks **SHOOT**:
1. Pi sees a tag at e.g. `range_m = 2.40 m → 7.87 ft`.
2. Looks up the calibration table → interpolates between the 4 ft and
   8 ft rows → gets e.g. `78.7 RPS`.
3. Publishes that to `/Sight/Aim/TargetRps`.
4. Increments `/Sight/Shoot/RequestId`.
5. Rio's AutoAim sees the new request, rotates onto the bearing the
   Pi published, spins the wheel to 78.7 RPS, fires.

If the table only has rows 0/4/8/12/16, a shot at 7.87 ft uses the
4→8 ft slope. If you only have rows at 0 and 16, the Pi linearly
interpolates across the entire range — usually wrong. **More rows in
the range you actually shoot from = more accurate shots.**

---

## How do I know the whole system is working?

After Set up Vision Pi finishes successfully, do this once to verify
end-to-end:

> **Powered on:** radio, rio, Pi (everything).
> **Network:** laptop on `FRC-1279` (use the **Connect** button).

1. **Power cycle the robot** (radio + rio + Pi all booting fresh).
2. Wait ~60 seconds for everything to come up.
3. From the laptop, click **Connect** in the control panel. Header
   should turn green and say `Connected (10.12.79.2)` (your team's IP).
4. Click **Open Sight UI**. Browser should load
   `http://10.12.79.11:8080/` and show:
   - A live camera image (not a black square).
   - A green **CONNECTED** pill in the top bar (NT4 link to rio is up).
   - Live RPS / dial / tag-range readouts in the Distance + Target panels.
   - Operator gamepad mirror lighting up when you press buttons on the
     paired controller.
5. Aim the camera at one of your target AprilTags. The
   **NO TARGET → LOCK #N** pill in the top bar should flip to LOCK
   within a frame or two; range/bearing readouts come alive.
6. Press the big red **SHOOT** button (bottom-right) — it turns green
   when armed (target visible + range known + lockout off). With the
   robot enabled in DriverStation, it should rotate onto the tag,
   spin up the shooter, fire. The DRIVER LOCKED pill appears for the
   duration; the aim status walks through `rotating → spinning_up →
   firing → done`.

If any step fails, work through the **Troubleshooting** table below.

---

## Day-to-day use

- **Drive the robot:** control panel → **Connect** → DriverStation.
- **Push code:** **Deploy to Robot**. Sends rio code, and the rio
  passes any orangepi/ changes to the Pi on next boot.
- **Open the UI:** **Open Sight UI** (or bookmark `http://10.12.79.11:8080/`).
- **Aim & shoot:** click the goal AprilTag in the Camera panel to lock
  onto it, then press SHOOT. rio rotates, dials in the calibrated RPS
  for the live tag-PnP range, fires.
- **Force-push the Pi without rebooting the rio:** re-run **Set up / Update Vision Pi**. It rsyncs the latest code, restarts the service if anything changed, and skips the parts that are already done.
  Useful when iterating on HTML/CSS/JS — push from laptop, no rio reboot.

## Cross-host SSH

After provisioning, both directions are passwordless:

```bash
# Laptop:
ssh admin@10.12.79.2          # rio
ssh orangepi@10.12.79.11      # Pi

# From the Pi:
ssh admin@10.12.79.2          # rio (Pi's key trusted)

# From the rio (login first as admin):
ssh orangepi@10.12.79.11      # Pi (admin's key trusted)

# Robot code on the rio runs as `lvuser` and uses *its own* key, also
# trusted on the Pi — that's how `orangepi_pusher.py` works without
# anyone typing a password.
```

## Troubleshooting

| Symptom                                 | Try                                                                |
|-----------------------------------------|--------------------------------------------------------------------|
| Can't `ping 10.12.79.11`                | Check Pi power, eth cable, the radio is the DHCP server, NOT a switch |
| **Set up Vision Pi** "Permission denied"| Re-enter Pi password; or run `ssh-copy-id orangepi@<host>` once    |
| Web UI loads but says **DISCONNECTED**  | rio's down, or Pi can't reach `10.TE.AM.2`; ssh to Pi and ping it  |
| New code didn't reach the Pi            | Check `journalctl -u cold-fusion-sight` and `/tmp/robot-log` on rio for `[orangepi-pusher]` lines |
| Camera frame is black                   | `v4l2-ctl --list-devices` on the Pi; reseat USB                    |
| Pi UI laggy                             | Lower `CAMERA_FPS` in `sight.env` and `sudo systemctl restart cold-fusion-sight` |
| Tag range looks wrong (off by 2×)       | Check `TAG_SIZE_M` in `sight.env` matches your printed tag (default 0.1651 m = 6.5"). For better accuracy, drop a chessboard-calibrated `cam_intrinsics.json` next to `server.py`. |
| Pi works at home, fails on the robot    | Static IP needs `eth0`; if your Pi labels it `enP4p65s0` or similar, edit `/etc/NetworkManager/system-connections/cold-fusion-eth0.nmconnection` |

## When to re-run "Set up Vision Pi"

- You re-flashed the SD card.
- You changed team numbers (the static IP needs to change).
- You replaced the Pi with another one.
- The rio's lvuser key got deleted somehow (e.g. you wiped the rio).

Re-running is safe and idempotent — it just refreshes everything.

## What lives where

```
your repo/
├── orangepi/              ← Pi-side code (server.py, static/, install.sh)
├── orangepi_pusher.py     ← rio module: ships orangepi/ to the Pi at boot
├── pi_target.json         ← {"host": "10.12.79.11", ...} written by setup
├── setup_orangepi.py      ← provisioning + update wizard (idempotent re-runs)
└── documentation/orangepi.md  ← (you are here)
```

On the Pi:

```
/home/orangepi/cold-fusion-sight/
├── server.py
├── static/
├── .venv/
├── sight.env              ← TEAM=1279, CAMERA_*, HTTP_PORT
└── .deploy_hash           ← what version of orangepi/ is currently installed
```

On the rio (after `robotpy deploy`):

```
/home/lvuser/py/
├── robot.py
├── orangepi/              ← ships every deploy; pusher reads from here
├── orangepi_pusher.py
└── pi_target.json
```
