# Acuity

Vision + compute coprocessor for FRC. Plug into the RoboRIO's USB-A
port, fill out a captive-portal form once, and the device shows up at
`10.TE.AM.11` on the team radio with a web dashboard, AprilTag
detection, and a NetworkTables interface.

This is the entire product source — firmware, on-device dashboard,
robot-side libraries, the driver-station Manager app, and docs.

## Layout

```
acuity/
├── firmware/       # Pi-side install (boot, captive portal, services)
│   ├── install.sh
│   ├── manufacturer-setup.sh
│   ├── files/         # systemd units, helper scripts, hostapd templates
│   └── setup-wizard/  # FastAPI captive portal
├── dashboard/      # On-Pi web UI (camera feed, AprilTags, NT4 browser)
├── libraries/      # Robot-side libraries
│   ├── java/          # WPILib vendordep (Java FRC teams)
│   ├── python/        # robotpy package
│   └── cpp/           # WPILib vendordep (C++ FRC teams)
├── manager/        # Electron driver-station app
└── docs/           # Markdown docs (plan, getting started, API reference)
```

## Status

See [docs/PRODUCT_PLAN.md](docs/PRODUCT_PLAN.md) for the full product
plan, milestones, and current progress.

## Quick links

* **First-time setup on a Pi:** [docs/getting-started.md](docs/getting-started.md)
* **NetworkTables schema for robot code:** [docs/nt4-schema.md](docs/nt4-schema.md)
* **Robot library APIs:** [libraries/README.md](libraries/README.md)
* **Manager app:** [manager/README.md](manager/README.md)
* **Dashboard (on-device web UI):** [dashboard/README.md](dashboard/README.md)
* **What still needs human verification:** [docs/next-steps.md](docs/next-steps.md)
