# Acuity dashboard

Generic on-device web UI for the Acuity vision coprocessor. Serves the
camera feed, AprilTag detections, settings, and network controls at
`http://acuity-NNNN.local:8080/` whenever the firmware is in STA mode.

This is the **product** dashboard. The previous team-specific
implementation (shooter calibration, gamepad mapper, recordings) lives
under [../dashboard-legacy/](../dashboard-legacy/) for reference.

## What's here

```
dashboard/
├── server.py        # FastAPI app: camera capture, AprilTag detection,
│                    # NT4 publisher matching the canonical schema
├── nt4_client.py    # Pure-Python NetworkTables 4 client
├── requirements.txt
└── static/
    ├── index.html   # 4-tab dashboard: Live / Settings / Network / Logs
    ├── style.css    # Light theme, shared tokens with manager + wizard
    └── app.js       # WS client, SVG overlay, settings form
```

## NT4 schema

Every detection cycle, the server writes the full schema documented in
[../docs/nt4-schema.md](../docs/nt4-schema.md) — so robot code using
the [Acuity client libraries](../libraries/) gets typed, versioned data
without ever touching this dashboard.

## Settings

Editable from the **Settings** tab in the dashboard, persisted to
`/var/lib/acuity/settings.json`:

| Setting | Default | Notes |
|---|---|---|
| `resolution`            | 1280×720 | Drop to 800×600 to ease CPU on the Pi Zero. |
| `target_fps`            | 30       | Camera-side FPS cap. |
| `flip_horizontal/vertical` | false | Apply if the case is mounted upside down. |
| `tag_size_m`            | 0.1651   | 6.5 in — 2025 FRC tag size. |
| `min_decision_margin`   | 30       | Filter weak detections. |
| `preferred_tag_ids`     | []       | If non-empty, only these IDs count for "best target." |
| `nt_team`               | 0        | Team number for `roborio-NNNN-frc.local` lookup. |
| `nt_server_host`        | ""       | Override (e.g. `10.12.79.2`) for non-FRC topologies. |

## Run locally (development)

```sh
cd acuity/dashboard
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload --host 0.0.0.0 --port 8080
```

Browse to `http://localhost:8080/`. With no camera attached, the Live
tab renders an empty frame and the WS still connects — useful for
iterating on the UI.

## On a Pi

`acuity/firmware/install.sh` rsyncs this directory to `/opt/acuity/sight/`
and registers the `acuity-dashboard.service` systemd unit. No manual
deploy needed for Pis built from the Acuity image.
