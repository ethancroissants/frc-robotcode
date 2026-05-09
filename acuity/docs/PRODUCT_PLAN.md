# Acuity — product plan

A USB-powered compute + camera module that drops onto any FRC robot and
delivers AprilTag detection, target tracking, optional object detection,
and a programmable compute offload — without ethernet, without a
LimeLight-class price tag, and without weeks of integration work per
team.

This document is the working plan for turning our team's in-house
implementation into a product other teams can buy, plug in, and use.

> **Name:** Acuity (locked 2026-05). The product was referred to as
> "the device" while we picked a name; that's done. Internal
> references to `cfsight-*` (our team's codename "Cold Fusion
> Sight") will be renamed to `acuity-*` in a follow-up mechanical
> pass — see [§10 Roadmap](#10-roadmap--milestones).
>
> **Repo layout:** all product source now lives under
> [`acuity/`](../) — firmware, dashboard, libraries, manager app,
> docs.

---

## Table of contents

1. [Product positioning](#1-product-positioning)
2. [What we have today vs. what we need](#2-what-we-have-today-vs-what-we-need)
3. [Branding — name decision](#3-branding--name-decision)
4. [Hardware](#4-hardware)
5. [Software architecture](#5-software-architecture)
6. [User journey — out-of-box to running on the robot](#6-user-journey--out-of-box-to-running-on-the-robot)
7. [Robot-side libraries (Java / Python / C++)](#7-robot-side-libraries-java--python--c)
8. [Driver-station "Device Manager" app](#8-driver-station-device-manager-app)
9. [Production & fulfillment](#9-production--fulfillment)
10. [Roadmap & milestones](#10-roadmap--milestones)
11. [Open questions & risks](#11-open-questions--risks)
12. [Documentation deliverables](#12-documentation-deliverables)
13. [Pricing & business model](#13-pricing--business-model)
14. [Decisions still open](#14-decisions-still-open)

---

## 1. Product positioning

**The pitch:** plug-and-play vision coprocessor for FRC. Plug into the
RoboRIO's USB-A port for power, fill out a captive-portal form once,
and it shows up at a known IP on the team radio with a web dashboard
and a NetworkTables interface.

**Who it's for:** FRC teams who want LimeLight-grade AprilTag tracking
without LimeLight prices, who don't already have a vision coprocessor,
and who'd rather not learn OpenCV from scratch.

**Direct competitors and how we beat them:**

| Product | Price | Power | Ethernet? | Setup |
|---|---|---|---|---|
| LimeLight 3G | ~$400 | 5–12V barrel | required | web UI |
| LimeLight 4 | ~$500 | 5–12V barrel | required | web UI |
| PhotonVision (DIY OPi/RPi) | ~$60–100 | 5V varies | recommended | per-team |
| **The device** | **~$45–60 BOM** | **USB-A from RIO** | **none — WiFi only** | **captive-portal wizard** |

We win on:

* **Price.** ~$50 in parts vs. ~$400+ retail for LimeLight.
* **Setup.** Captive portal first-boot — no ssh, no IP guessing, no
  imager configuration. A team member with a phone is the only
  prerequisite.
* **Form factor.** Pi Zero 2 W is roughly the size of a stick of gum.
  Mounts anywhere.
* **No ethernet required.** One USB cable from the RoboRIO's existing
  USB-A port is the only physical connection.

We lose to LimeLight on:

* **Polish.** They've got an entire integrated calibration UI, deep
  ML target detection, and 5+ years of FRC mindshare.
* **Reliability of the WiFi link.** Ethernet is more deterministic.
  We'll have to publish numbers showing WiFi-only is OK at competition.
* **Documentation.** They have a giant docs site. We will too,
  eventually.

The thesis: the team buying their *first* coprocessor doesn't need
the polish — they need it to work in 20 minutes. We can own the
"first coprocessor" market and earn upgrades from there.

---

## 2. What we have today vs. what we need

Honest inventory of what's already built (CFSight, our team's
implementation) and what blocks shipping to other teams.

### What's already working

* **Repo restructured into `acuity/`** with `firmware/` (the on-Pi
  install scripts and systemd units), `dashboard/` (the on-device
  vision UI), `libraries/{java,python,cpp}/` (robot-side library
  skeletons), `manager/` (Electron Manager app skeleton), and
  `docs/` (this plan + getting-started + NT4 schema).
* **First-boot AP-mode captive-portal wizard.** A fresh Pi boots,
  exposes an open SSID (currently `CFSight-Setup-XXXX`, will rename
  to `Acuity-Setup-XXXX`), dnsmasq wildcards DNS to the gateway, and
  a FastAPI form collects team #, SSID, password, country code. On
  submit, it writes `/boot/firmware/acuity.conf` and reboots into STA
  mode joining the team radio. Light-themed UI matching the dashboard.
* **Static-IP convention.** STA mode pins the device to
  `10.TE.AM.11/24` via NetworkManager, matching FRC's standard
  coprocessor IP slot. mDNS publishes `acuity-NNNN.local` as backup.
* **Vision pipeline.** OpenCV camera capture, MJPEG passthrough (no
  decode/re-encode for the stream), pyapriltags detection (same
  upstream library WPILib + PhotonVision use), SVG overlay rendered
  client-side.
* **Web dashboard.** Windowed/draggable Grafana-style UI on port 8080,
  Aim/Calibrate/Recordings panels, NT4 topic browser, FPS readout.
* **Manufacturer mode.** `firmware/manufacturer-setup.sh` preps an SD
  card for `dd` cloning — forgets bench WiFi, resets machine-id,
  clears shell history, regens SSH host keys via a systemd drop-in.
* **Updater.** Re-running `firmware/install.sh` is idempotent —
  pulls latest code, refreshes the venv, reinstalls systemd units.
* **NT4 schema documented.** [docs/nt4-schema.md](nt4-schema.md)
  locks the contract between device and robot code at version 1.

### What blocks shipping to other teams

1. **Vision code is welded to our team's robot codebase.** The
   dashboard knows about our team-specific NT topics, our shoot/aim
   panel, our calibration table format. Has to be extracted into a
   product that any team can configure.
2. **No installable robot-side library.** Every team would have to
   write their own NT4 client glue. We need vendor libraries for
   Java (vendordep JSON), Python (robotpy package), and C++ (vendor
   library).
3. **No driver-station app.** `start.py` works for our laptop but
   nobody else's. Needs to be a packaged, signed, distributable app
   that any team's drive coach can run.
4. **No name and no branding.** Currently "CFSight" — short for
   "Cold Fusion Sight," our team's name. Has to become a neutral
   product brand.
5. **No physical case.** 3D-printable STL exists internally; needs
   to be polished for production print, durable, and identify the
   product (logo, light pipe for status LED).
6. **No documentation that isn't team-specific.** README assumes
   you're on our team and have our wifi credentials.
7. **No pricing or fulfillment story.** Are we shipping kits? Just
   selling SD images? Selling assembled units? Donation-ware?

The plan in this doc is essentially "fix items 1–7."

---

## 3. Branding — name decision

The name is **Acuity**. "Sharpness of vision" — communicates the
value prop directly, three clean syllables, looks good rendered in
all caps on a tiny case.

Why we picked it:

* Says exactly what the product does without resorting to bird
  metaphors that collide with FRC's existing brand vocabulary
  (Falcon, Kraken, Vortex are all motor brands).
* Pronounceable by a drive coach yelling across a pit.
* Reads as "premium engineering tool" rather than "DIY hobby thing."
* Owns a clear semantic space — when teams talk about "Acuity" in
  Chief Delphi posts, there's no ambiguity about what they mean.

Trademark + domain registration: deferred until we're closer to
shipping. Not blocking development.

### Internal naming map

Used while building:

| Layer | Identifier |
|---|---|
| Product brand | **Acuity** |
| Repo folder | `acuity/` |
| Pi-side service / paths | `acuity-*` (renamed from `cfsight-*` in a follow-up pass) |
| AP SSID | `Acuity-Setup-XXXX` |
| Config file on Pi | `/boot/firmware/acuity.conf` |
| Default static IP | `10.TE.AM.11` (FRC convention) |
| mDNS name | `acuity-NNNN.local` |
| NT4 root table | `/acuity/` |
| Driver-station app | Acuity Manager |
| Java package | `tech.acuity` |
| Python package | `acuity_vision` |
| C++ namespace | `acuity::` |

---

## 4. Hardware

### Bill of materials (target ≤ $60 retail, ≤ $40 in volume)

| Part | Spec | Volume cost | Notes |
|---|---|---|---|
| Compute | Raspberry Pi Zero 2 W | ~$15 | Has WiFi 2.4 GHz, BCM43436 supports concurrent STA+AP. Pi 4/5 supported as upgrade tier. |
| Camera | Raspberry Pi Camera v3 (12 MP, IMX708) | ~$25 | v3 over v1/v2 because of much better autofocus + low-light. v1 (5 MP OV5647) works at lower BOM if we want a budget tier. |
| Camera cable | 22-pin → 22-pin Pi Zero ribbon | ~$3 | Pi Zero uses the smaller connector. |
| SD card | SanDisk Industrial 32 GB A1 | ~$8 | Industrial-grade is worth it — consumer cards die in 6 months on a Pi. |
| Case | 3D-printed PLA, two-piece | ~$2 in filament | TPU lens shroud option for impact protection. |
| Power cable | Micro-USB B → USB-A, 0.3 m | ~$2 | Pi Zero 2 W still uses micro-B. Short cable so it doesn't loop around the RIO. |
| Mounting | M2.5 screws + standoffs OR VHB tape | ~$1 | Two physical mounting options in box. |
| **Total** | | **~$56** | |

Bulk discount targets: **< $40/unit at 100 units, < $30 at 500.**

### Camera comparison — which one ships in the box?

| Sensor | Resolution | FOV (diag) | Autofocus | $ | Notes |
|---|---|---|---|---|---|
| OV5647 (v1) | 5 MP | 75° | no | ~$15 | Original budget option. Decent in good light. |
| IMX219 (v2) | 8 MP | 77° | no | ~$20 | Better dynamic range than v1. |
| **IMX708 (v3)** | **12 MP** | **75°** | **yes** | **~$25** | Best low-light, autofocus is huge for first-time setup. |
| IMX477 (HQ) | 12 MP | depends on lens | manual | ~$50 + lens | Pro option, requires CS-mount lens — separate SKU. |

**Recommendation:** ship v3 in the standard kit. v1 as a "lite" SKU
if we want a sub-$50 bracket.

### Power

The Pi Zero 2 W draws **~250 mA idle, ~600 mA peak** at 5 V. The
RoboRIO 2 USB-A port supplies up to **2.5 A at 5 V** per port. Plenty
of headroom.

What we need to test before claiming "powered from the RIO":

* Brownout behavior when the RIO's CAN bus saturates (~2 A draw
  spikes).
* Whether the RIO chooses to disable USB power during emergency-stop.
* Whether teams running multiple coprocessors saturate the RIO USB
  budget.

If RIO USB turns out to be insufficient: include a USB-A → 2-port
splitter that takes one input and feeds both compute + a 5V/2A wall
wart adapter. Optional accessory, not in base kit.

### Case design priorities

* **Camera-window cutout** sized for v3 lens, with optional TPU shroud.
* **Power LED light pipe** showing AP-mode vs STA-mode (different
  blink patterns), driven by GPIO from `cfsight-firstboot.sh`.
* **Branding cutout** showing the product logo, lit from inside.
* **Mounting tabs** with M2.5 holes and a VHB-tape pad area.
* **Cable strain relief** on the micro-USB side so a yanked cable
  doesn't snap the connector.
* **Thermals.** Pi Zero 2 W gets warm. Vents on the case + a pad of
  thermal tape from the SoC to the case wall.

### Optional v2 hardware

Not in v1, but worth thinking about:

* **Pi 4 / Pi 5 SKU** for teams who want object detection at >15 FPS
  (Pi Zero 2 W tops out around 5 FPS on YOLOv8n at 320×320).
* **Ethernet adapter** as an optional add-on for teams who want
  ethernet reliability without giving up the captive-portal flow.
* **IMU** (BNO055) on the bottom of the case for AprilTag pose
  fusion. Maybe v2.

---

## 5. Software architecture

```
                                          
  ┌─────────────────────────────────────────────────────────────┐
  │  Driver-station laptop                                      │
  │  ┌────────────────────────────────────────────────┐         │
  │  │  Device Manager app (Electron/Tauri or PySide)│         │
  │  │  - Discovers devices on the network (mDNS)     │         │
  │  │  - One-click flash / update / reboot           │         │
  │  │  - Live dashboard window (embeds 8080)         │         │
  │  └─────────────────┬──────────────────────────────┘         │
  └────────────────────┼────────────────────────────────────────┘
                       │ HTTP + WebSocket (NT4 + custom REST)
                       │
        ┌──────────────┴───────────────┐
        │  FRC team radio (Open Mesh)  │
        └──────────────┬───────────────┘
                       │
        ┌──────────────┼──────────────────────────────────────────┐
        │              │              │                          │
  ┌─────┴───────┐  ┌───┴───────┐  ┌───┴────────────────────────┐ │
  │  RoboRIO    │  │  Device   │  │  Other coprocessors        │ │
  │  - User code│  │  10.TE.AM.│  │  (PhotonVision, etc.)      │ │
  │  - Library  │◀─▶  .11      │  └────────────────────────────┘ │
  │    talks NT │  │  - Vision │                                 │
  │  - .11:8080 │  │    pipe   │                                 │
  │    proxied  │  │  - NT4    │                                 │
  │             │  │    server │                                 │
  └─────────────┘  └───────────┘                                 │
                                                                 │
  Boot states:                                                   │
   AP   = no cfsight.conf  → open AP, captive portal             │
   STA  = cfsight.conf set → joins team WiFi at 10.TE.AM.11      │
   STA+AP = bridge mode    → both at once on the same radio      │
                                                                 │
```

### Boot-state machine (already implemented)

```
            ┌──────────────────┐
            │  Pi powers on    │
            └────────┬─────────┘
                     │
                     ▼
            ┌──────────────────┐
            │ cfsight-firstboot│
            │ reads cfsight.conf│
            └────────┬─────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
  cfsight.conf              cfsight.conf
  has SSID                  missing/empty
        │                         │
        ▼                         ▼
  ┌──────────┐              ┌──────────┐
  │ STA mode │              │ AP mode  │
  │ joins    │              │ open AP  │
  │ team     │              │ +captive │
  │ WiFi at  │              │ portal   │
  │.TE.AM.11 │              │.50.1     │
  └────┬─────┘              └────┬─────┘
       │                         │
       │                         ▼
       │                   ┌──────────┐
       │                   │ wizard   │
       │                   │ form on  │
       │                   │ port 80  │
       │                   └────┬─────┘
       │                        │ submit
       │                        ▼
       │                   write conf
       │                   + reboot ──┐
       │                              │
       └──────────────────────────────┘
```

### On-device services

Each one is a systemd unit installed by `pi-image/install.sh`:

| Service | Role | When it runs |
|---|---|---|
| `cfsight-firstboot.service` | Reads `cfsight.conf`, sets hostname, picks AP vs STA, delegates to `cfsight-wifi-mode.sh`. | Every boot, after NetworkManager. |
| `cfsight-setup-wizard.service` | FastAPI captive portal on :80. | Started by `cfsight-wifi-mode.sh ap`, stopped on STA. |
| `cold-fusion-sight.service` | Main vision pipeline + dashboard on :8080. | Boot, after firstboot. |
| `ssh.service` (with our drop-in) | Self-heals host keys via `ExecStartPre=ssh-keygen -A`. | Boot. |
| `avahi-daemon.service` | Publishes `<name>-NNNN.local`. | Boot. |

### Renames needed for product extraction

Everything currently prefixed `cfsight-*` (Cold Fusion Sight, our team
name) becomes `<productname>-*`. Ditto the path `/opt/cfsight/`,
the AP SSID `CFSight-Setup-XXXX`, and the conf file
`/boot/firmware/cfsight.conf`.

This is a mechanical rename pass once the name is locked in. Until
then, treat `cfsight` as a placeholder.

---

## 6. User journey — out-of-box to running on the robot

### Persona: a programming-lead student on a team that has never
used a coprocessor.

#### Step 1 — unbox

Box contains:

* The device (assembled, in case, SD pre-flashed).
* Micro-USB B → USB-A power cable.
* Quick-start card (a single 4×6" card with QR codes).
* Two M2.5 screws + standoffs OR a VHB pad.

#### Step 2 — physical install

1. Mount on the robot near the camera target (intake, shooter, etc.).
2. Plug power into the RoboRIO's USB-A port.
3. Power on the robot.

#### Step 3 — first-boot WiFi setup (captive portal)

1. Wait ~30 seconds. A new SSID appears on phones in the pit:
   `<Brand>-Setup-XXXX`.
2. Connect a phone to it (open network).
3. Phone auto-pops the captive portal *or* the user opens
   `http://192.168.50.1/`.
4. Form: team #, robot WiFi SSID, password, country.
5. Hit save. Pi reboots.

#### Step 4 — first connection from the driver station

1. Connect the driver-station laptop to the team WiFi.
2. Open the Device Manager app.
3. App auto-discovers the device at `10.TE.AM.11` and lights up its
   tile. Click "Open dashboard" — embedded webview opens
   `http://10.TE.AM.11:8080/`.
4. Calibrate: pick the AprilTag layout (loaded from `wpilib`'s
   per-year layout JSON), zero the camera offset.

#### Step 5 — robot code integration

Java team adds the vendordep JSON to their project. Their code:

```java
import org.<brand>.frc.<brand>Vision;

public class Robot extends TimedRobot {
  private final <brand>Vision vision = <brand>Vision.getInstance();

  @Override
  public void robotPeriodic() {
    vision.getBestTag().ifPresent(tag -> {
      SmartDashboard.putNumber("tag/id",         tag.id);
      SmartDashboard.putNumber("tag/distance_m", tag.distanceMeters);
      SmartDashboard.putNumber("tag/yaw_deg",    tag.yawDeg);
    });
  }
}
```

Done. They have AprilTag pose data 30 minutes after opening the box.

---

## 7. Robot-side libraries (Java / Python / C++)

The vision device publishes a deterministic NT4 schema. The libraries
are just typed wrappers around that schema — they don't do anything
clever, they just save every team from re-implementing the same
NT4-topic-name lookups.

### NT4 topic schema (canonical)

All under the `/<brand>/` table. Versioned via a top-level integer
so we can break compat in v2 without taking out v1 deployments.

```
/<brand>/version              int         schema version (start at 1)
/<brand>/heartbeat            int         monotonic counter, +1 / sec
/<brand>/camera/connected     bool
/<brand>/camera/fps           double

/<brand>/tags/best/id         int         -1 = no tag in view
/<brand>/tags/best/distance_m double
/<brand>/tags/best/yaw_deg    double
/<brand>/tags/best/pitch_deg  double
/<brand>/tags/best/tx         double      pixel X offset from center
/<brand>/tags/best/ty         double      pixel Y offset from center
/<brand>/tags/best/area       double      0..1, fraction of frame
/<brand>/tags/best/timestamp  double      seconds since epoch

/<brand>/tags/all             string      JSON array of all detected tags

/<brand>/objects/best/class   string      e.g. "note", "ball"
/<brand>/objects/best/conf    double
/<brand>/objects/best/tx      double
/<brand>/objects/best/ty      double

/<brand>/health/cpu_pct       double
/<brand>/health/temp_c        double
/<brand>/health/uptime_s      int
```

### Java — vendordep

Distribute as a vendordep JSON hosted on GitHub Pages. Team adds the
URL via WPILib VS Code extension.

```java
public class <Brand>Vision {
  public static <Brand>Vision getInstance() { ... }

  public Optional<TagDetection> getBestTag() { ... }
  public List<TagDetection> getAllTags()      { ... }
  public Optional<ObjectDetection> getBestObject() { ... }
  public DeviceHealth getHealth() { ... }

  public boolean isConnected()  { ... }   // heartbeat within 1 s
}
```

### Python — robotpy package

```python
import <brand>vision

vision = <brand>vision.<Brand>Vision()

best = vision.get_best_tag()
if best is not None:
    print(best.id, best.distance_m, best.yaw_deg)
```

Distribute via PyPI. robotpy projects pick it up via
`pyproject.toml`.

### C++ — vendor library

C++ teams add the vendor URL the same way Java teams do. The library
is a thin wrapper around `nt::NetworkTableInstance`.

### Versioning

Every library checks `/<brand>/version` and warns (not errors) if
the device's version is newer than the library expects. Forward
compat where possible — only break on schema rewrites.

---

## 8. Driver-station "Device Manager" app

This is the thing teams open during practice. Replaces our team's
`start.py` for the broader audience.

### Features

* **Auto-discover devices** via mDNS scan for `_<brand>._tcp.local`
  (we'll add a service advertisement to avahi-daemon).
* **Tile UI** showing each discovered device: name, IP, version,
  status dot.
* **Per-device actions:**
  * Open dashboard (embedded webview pointing at :8080)
  * Update firmware (pulls latest install.sh + reruns)
  * Reboot
  * Forget WiFi → re-enters AP-mode setup
  * Download diagnostics bundle (logs, config, screenshots)
* **First-time setup helper:** if no devices found, walks the user
  through "did you connect to the team radio? did the device boot?
  here's how to find the AP SSID."

### Tech choice — Electron (locked)

We use **Electron** for the Manager app. Reasons:

* The on-device dashboard at `:8080` is already a web UI; Electron's
  embedded webview gives us a free "open dashboard inside Manager"
  view without rebuilding any of it.
* We already write the dashboard, captive portal, and main robot
  tooling in JS/Python. Manager being JS means one fewer language
  in the contributor stack.
* `xterm.js` + `node-pty` gives us a real interactive SSH terminal
  in-app, so users never have to open a separate terminal.
* `ssh2` (npm) handles the firmware-update / reboot one-shots
  without shelling out.
* `bonjour-service` (npm) handles mDNS discovery natively.

The downside (~150 MB binary, macOS notarization pain) is
acceptable for a tool teams install once per season.

Skeleton lives at [`acuity/manager/`](../manager/). To run during
development:

```sh
cd acuity/manager
npm install
npm run dev
```

For production builds: `npm run build:mac` / `:win` / `:linux` —
electron-builder handles each platform's packaging.

### Distribution

* macOS: signed `.dmg` from a paid Apple Developer account ($99/yr).
* Windows: signed `.exe` via SignPath (free for OSS) or a code-signing
  cert (~$200/yr). Without signing, SmartScreen yells at the user.
* Linux: AppImage + Flatpak.

Auto-update via Tauri's built-in updater pointing at our GitHub
Releases. Frees us from maintaining update infra.

---

## 9. Production & fulfillment

### Manufacturing flow per unit

1. **Master image build:** the team that ships does a one-time setup
   on their bench Pi (`install.sh`, then `manufacturer-setup.sh`),
   `dd`'s the SD to a master image file. This image is the source of
   truth for that release.
2. **Per-unit clone:** flash the master image to a fresh Industrial
   SD card.
3. **Assembly:** insert SD, mount Pi in case, attach camera ribbon,
   close case. ~3 minutes per unit at first, faster with practice.
4. **Smoke test:** plug into a test bench, watch the AP appear, scan
   the captive portal QR with a phone, confirm form loads. ~30 s.
5. **Pack:** unit + cable + standoffs + quick-start card → small
   crush-resistant box.

### Per-release versioning

Each master image tagged `<brand>-vX.Y.Z`. Image filename includes
the date and git SHA so we know exactly what's in the field.

### Returns / RMA

Treat the SD card as the wear part. Most "broken" units will be
corrupted SD cards. RMA = mail us the device, we replace SD, ship
back. Charge $5 + shipping.

### What if it fails at competition?

We need a **recovery USB stick** SKU — a USB-A flash drive with the
master image. Plug into a laptop, the laptop sees the SD card, an
auto-runner script reflashes the SD to known-good. Costs us $5 in
parts; sells for $15; saves a team's match.

---

## 10. Roadmap & milestones

Calendar-friendly. Adjust as needed.

### Phase 0 — current state (done)

* CFSight running on our team's robot.
* Captive portal wizard, manufacturer-setup, install.sh idempotent.
* Dashboard + AprilTag detection.

### Phase 1 — extract product from team codebase (4–6 weeks)

* [x] **Pick a name.** → Acuity.
* [x] **Restructure repo into `acuity/` folder** with `firmware/`,
      `dashboard/`, `libraries/`, `manager/`, `docs/` subdirs.
* [x] **Update build/install paths** in `install.sh`,
      `manufacturer-setup.sh`, `setup_orangepi.py` to the new layout.
* [x] **Mechanical rename pass:** `cfsight-*` → `acuity-*` across
      the firmware tree — systemd unit filenames + content, helper
      scripts (`acuity-firstboot.sh`, `acuity-wifi-mode.sh`), `/etc/
      acuity/`, `/run/acuity/`, `/var/log/acuity-*`, `/opt/acuity/`,
      `/boot/firmware/acuity.conf`, AP SSID `Acuity-Setup-`,
      NetworkManager profile names (`acuity-team`, `acuity-bridge`),
      log tags. install.sh disables + removes legacy `cfsight-*`
      services so existing dev Pis upgrade cleanly, and migrates
      legacy `cfsight.conf` → `acuity.conf` if found.
* [x] **mDNS service advertisement.** install.sh drops an
      `/etc/avahi/services/acuity.service` so devices announce
      themselves as `_acuity._tcp.local` — Manager discovers them
      with no IP guessing.
* [x] **Strip team-specific dashboard panels.** Moved the team's full
      implementation to [acuity/dashboard-legacy/](../dashboard-legacy/)
      and built a fresh, generic
      [acuity/dashboard/](../dashboard/) — Live / Settings / Network
      / Logs tabs only, no shooter / gamepad / recordings. Same camera
      capture + AprilTag detection backend, but exposes the canonical
      NT4 schema (no `/Sight/...` topics). Dashboard's "Forget WiFi"
      and "Reboot" buttons work via a least-privilege sudoers drop-in
      install.sh installs at `/etc/sudoers.d/acuity-dashboard`.
* [ ] Generic-ize the calibration UI — let teams point at their own
      AprilTag layout JSON. (Open: per-tag distance lookup tables for
      finer PnP than the heuristic-fx default.)
* [ ] Replace hardcoded team 1279 references in dashboard-legacy/
      docs (only matters if we keep that tree around long-term).

### Phase 2 — robot-side libraries (3–4 weeks, parallelizable with Phase 1)

* [x] **Define the canonical NT4 schema** —
      [docs/nt4-schema.md](nt4-schema.md). Locked at version 1.
* [x] **Library skeletons** under `acuity/libraries/{java,python,cpp}/`.
* [x] **Java implementation.** `tech.acuity.AcuityVision` reads the
      schema via `NetworkTableInstance` with typed subscribers,
      heartbeat-based staleness detection, and a hand-rolled JSON
      parser for `getAllTags()`. Gradle build wired up for jar +
      sources + javadoc, with maven-publish set up for GitHub
      Packages. [java/build.gradle](../libraries/java/build.gradle).
* [x] **Vendordep manifest** at
      [libraries/Acuity.json](../libraries/Acuity.json) — the JSON
      teams paste into WPILib VS Code's "Install new library
      (online)" dialog.
* [x] **Python implementation.** `acuity_vision.AcuityVision` against
      `pyntcore`. PyPI-ready via `pyproject.toml` (hatchling).
* [x] **C++ implementation.** `acuity::AcuityVision` against
      `ntcore`, full JSON parsing matching the Java + Python
      bindings.
* [ ] Publish: `mvn deploy` to GitHub Packages, `twine upload` to
      PyPI, push the C++ headers + binaries through the same
      vendordep maven flow.
* [ ] Test plan: each API call against a simulated device (an
      in-repo fake that publishes the schema).

### Phase 3 — Manager app (4 weeks)

* [x] **Electron scaffold** — package.json, main process, preload
      contextBridge, renderer with tabbed UI (Devices / Terminal /
      Libraries / Logs).
* [x] **Light-theme styling** matching the dashboard's design tokens.
* [x] **IPC modules**: `discovery.js` (mDNS via bonjour-service),
      `ssh.js` (one-shot updates / reboots / diagnose via ssh2),
      `pty.js` (interactive terminal via node-pty + xterm.js),
      `libraries.js` (library installer).
* [x] **Library-installer wizard.** Click a language card → folder
      picker → detect project type (build.gradle / pyproject.toml) →
      drop the vendordep JSON or edit pyproject.toml's
      `[tool.robotpy].requires`. Success modal shows a copy-pastable
      sample snippet and a "Show in folder" button.
* [ ] First end-to-end run: `npm install` + `npm run dev`,
      discover a real Acuity, click each action, verify each works.
      *(Can't validate from this environment — needs the user's
      laptop with npm available.)*
* [x] **First-launch onboarding wizard.** Four-step overlay (welcome
      → pick path → per-path instructions → done) with three flow
      branches: setting up a new device, managing an existing one,
      installing the robot library. Re-openable from the topbar **?**
      button. Skips itself once dismissed (`localStorage` flag).
* [x] **Auto-update wired to GitHub Releases.** `electron-updater`
      configured with `provider: github`, signature verification
      disabled (we ship unsigned). Manager checks for new releases
      3 s after launch and surfaces a topbar banner with manual
      Download / Restart-and-install actions — no auto-download.
* [x] **CI release pipeline.**
      [.github/workflows/manager-release.yml](../../.github/workflows/manager-release.yml)
      builds an unsigned NSIS installer + portable EXE on every
      `manager-v*` tag and publishes to GitHub Releases (along with
      the `latest.yml` electron-updater needs). Releasing a new
      version is `git tag manager-vX.Y.Z && git push --tags`.
* [ ] Code signing on macOS + Windows. Deferred — unsigned ships fine
      for the unknown-but-curious-FRC-team beta phase.

### Phase 4 — case + branding (2–3 weeks, parallel)

* [ ] 3D model the production case in Fusion 360.
* [ ] Print → fit-test → revise. Aim for 3 revisions.
* [ ] Logo, color palette, packaging artwork.
* [ ] Quick-start card design.

### Phase 5 — beta with one external team (4 weeks)

* [ ] Recruit a friendly team that's currently LimeLight-less.
* [ ] Ship them 1 unit + the libraries + the Device Manager.
* [ ] Watch them go through unboxing → first match. Take notes.
* [ ] Iterate on whatever broke.

### Phase 6 — public launch

* [ ] Build 100 units for inventory.
* [ ] Public landing page.
* [ ] Chief Delphi launch post + a Reddit r/FRC post.
* [ ] Open-source the firmware (we already use that license).
* [ ] Track support load — keep it under 10 hr/wk or we starve.

### Phase 7 — second-gen hardware (next season)

* Pi 4 / Pi 5 SKU for object detection.
* Optional ethernet adapter.
* Maybe an IMU.

---

## 11. Open questions & risks

### Technical

* **WiFi reliability at competition.** FRC venues are dense with
  competing 2.4 GHz traffic. Our device is on 2.4 GHz too. We need
  field data — measure packet loss between the device and the
  RoboRIO during real matches. If it's bad, we lose the "no ethernet"
  pitch.
* **AprilTag layout updates.** WPILib publishes a new layout JSON
  every year for the new game. Our device should auto-fetch it on
  boot (when it has internet) and cache it. If it has no internet,
  fall back to the bundled one.
* **Power brownout under load.** RIO USB might not always supply
  600 mA. Need bench testing across a full match's worth of CAN
  traffic.
* **Heat.** Pi Zero 2 W's SoC throttles around 80 °C. The case
  needs vents + a thermal pad. Test in a hot pit.

### FRC-specific

* **Inspection rules.** FIRST's robot inspectors check power-budget
  and radio conformity. We need to make sure plugging the device
  into the RIO USB doesn't violate the rules. (Reading the 2026
  manual when it drops.)
* **Field WiFi rules.** We're broadcasting our own AP at home (in
  AP mode), but we're STA-only at competition. Make this explicit
  in docs — *do not* power on a fresh, unconfigured device on the
  field, or you're broadcasting a rogue AP.

### Business

> Legal/business items deferred — we're focused on engineering until
> there's a working beta. Re-visit before the first sale.

* Liability insurance, trademark filing, terms of service, return
  policy: all parked. Will revisit before Phase 6 (public launch).
* **Support load.** Every shipped unit is a potential support
  ticket. Need a Discord / forum + a "is your SSID typed in
  exactly?" troubleshooting flowchart, day one.

---

## 12. Documentation deliverables

Day-one docs:

1. **Quick-start card** (physical, in the box). 4×6", front/back.
   Front: "Plug in. Connect to `<Brand>-Setup-XXXX`. Fill out form.
   Done." Back: a QR to the docs site.
2. **Web docs site:**
   * Getting started
   * Robot-side library reference (Java + Python + C++)
   * NT4 schema reference
   * Captive portal walkthrough
   * Driver-station Device Manager guide
   * Troubleshooting flowchart
   * FAQ
   * Recovery (the USB stick procedure)
3. **GitHub README** for the firmware repo.
4. **Library READMEs** for each language.
5. **YouTube unboxing/setup video.** Five minutes max. Big visual cues.

Tools: MkDocs Material for the docs site, hosted on GitHub Pages
(free).

---

## 13. Pricing & business model

### What we're actually charging for

| Component | Cost | Sell |
|---|---|---|
| Assembled device (in case, SD pre-flashed) | ~$56 | $99 |
| SD card recovery USB | ~$5 | $15 |
| Spare SD card (pre-flashed) | ~$10 | $25 |
| RMA SD-card replacement | ~$10 | $5 + shipping |

Margin on the main unit: **~$43/unit.** Volume discount for teams
buying 4+: 20% off.

### Open-source posture

* **Firmware**: MIT-licensed on GitHub. Community can fork, modify,
  build their own.
* **Robot-side libraries**: MIT.
* **Hardware design files** (case STL, BOM): Creative Commons
  BY-SA. Teams who want to make their own get full schematics.
* **Driver-station app**: MIT.

We sell *convenience* (assembled + flashed + supported). DIY teams
who want to save $50 can do it themselves; we cheer them on.

### Target volume year 1

* 100 units shipped.
* ~$10K gross revenue.
* ~$4K in costs (parts + cards + cases).
* ~$6K to plow back into v2 hardware, signing certs, hosting.

This is not a profit center. It's a way to make the FRC vision
ecosystem cheaper and to get our name in front of teams.

### Stretch year 2

* 500 units.
* Real product liability insurance.
* Hire one summer intern for support + docs.

---

## 14. Decisions

### Locked in

1. ~~**The name.**~~ → **Acuity**.
2. ~~**Driver-station app stack.**~~ → **Electron**.
3. ~~**Repo layout.**~~ → all under `acuity/` with `firmware/`,
   `dashboard/`, `libraries/`, `manager/`, `docs/`.

### Still open

* **Camera tier.** v3 only, or v1+v3 SKUs?
* **Open-source license.** MIT (default), Apache-2.0, or AGPL.
* **Sales channel.** Our own Shopify store, Etsy, or partner with
  AndyMark / REV Robotics?
* **First beta team.** Who breaks it for us before Chief Delphi sees it?
* **Year-zero scope cuts.** Object detection in v1 or v2? IMU in v1
  or v2? Pi 4 SKU in v1 or v2?

None of these block engineering progress on Phase 1 / 2 / 3. They
become real decisions before Phase 5 (beta) and Phase 6 (launch).
