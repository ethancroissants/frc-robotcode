# NetworkTables 4 schema

Acuity publishes vision data to NetworkTables 4 (NT4) under the
`/acuity/` table. Robot code reads from these topics.

The schema is **versioned** via `/acuity/version`. Robot-side
libraries check that and warn if they're talking to a newer device
than they were built against. We add fields freely, only bump the
version on a breaking rename or removal.

> If you're using one of the official robot-side libraries (Java
> vendordep, robotpy, C++ vendordep) you don't need to read this — the
> library wraps the schema. This page is for teams writing custom NT4
> clients or doing dashboard work.

## Conventions

* **Units:** SI everywhere. Meters, radians (and degrees as a
  convenience copy), seconds, Hz.
* **Pixels:** `tx` / `ty` are the offset from frame center, normalized
  to `[-1, +1]` (so they don't depend on resolution).
* **Stale data:** every timestamped topic also has a sibling
  `_timestamp` topic. Compare against `Timer.getFPGATimestamp()` —
  if the gap is >100 ms, the value is stale. The libraries hide
  this; raw NT4 clients should check.
* **No data:** "no tag in view" is encoded as `id = -1` (not "absent").
  Easier to consume from robot code than `Optional`-style absence.

## Topics

### Identity / health

| Topic | Type | Notes |
|---|---|---|
| `/acuity/version` | int | Schema version. Currently `1`. |
| `/acuity/build` | string | Build identifier (`acuity-v0.1.0+abc1234`). |
| `/acuity/heartbeat` | int | Monotonic counter, +1/sec. Robot code uses this to detect "device offline." |
| `/acuity/health/cpu_pct` | double | 0..100. |
| `/acuity/health/temp_c` | double | SoC temperature. |
| `/acuity/health/uptime_s` | int | Seconds since last boot. |

### Camera

| Topic | Type | Notes |
|---|---|---|
| `/acuity/camera/connected` | bool | False if `/dev/video*` failed to open. |
| `/acuity/camera/fps` | double | Smoothed over the last 30 frames. |
| `/acuity/camera/resolution` | string | `"1280x720"`. |

### AprilTags — best target

The "best" target is whichever tag is largest in frame, with optional
filtering for "expected tag IDs" set in the dashboard.

| Topic | Type | Notes |
|---|---|---|
| `/acuity/tags/best/id` | int | Tag ID, or `-1` if no tag. |
| `/acuity/tags/best/distance_m` | double | Meters from camera to tag center. |
| `/acuity/tags/best/yaw_deg` | double | Camera's yaw to the tag, signed. |
| `/acuity/tags/best/pitch_deg` | double | Camera's pitch to the tag, signed. |
| `/acuity/tags/best/tx` | double | Pixel-X offset, normalized `[-1, +1]`. |
| `/acuity/tags/best/ty` | double | Pixel-Y offset, normalized `[-1, +1]`. |
| `/acuity/tags/best/area` | double | Fraction of frame occupied, `0..1`. |
| `/acuity/tags/best/timestamp` | double | FPGA-timestamp seconds when the frame was captured. |
| `/acuity/tags/best/decision_margin` | double | pyapriltags confidence score. |

### AprilTags — all in view

| Topic | Type | Notes |
|---|---|---|
| `/acuity/tags/count` | int | How many tags this frame. |
| `/acuity/tags/all` | string | JSON array of every tag. Format below. |

JSON format for `/acuity/tags/all`:

```json
[
  {
    "id": 7,
    "distance_m": 1.42,
    "yaw_deg": -3.2,
    "pitch_deg": 0.5,
    "tx": -0.12,
    "ty": 0.04,
    "area": 0.018,
    "decision_margin": 38.4
  },
  { "id": 8, "...": "..." }
]
```

### Object detection (optional, off by default)

Only published if object detection is enabled in the dashboard. Off in
v1 because Pi Zero 2 W can't run a useful YOLO model in real time.
Reserved for the Pi 4/5 SKU.

| Topic | Type | Notes |
|---|---|---|
| `/acuity/objects/best/class` | string | e.g. `"note"`, `"ball"`. |
| `/acuity/objects/best/conf` | double | 0..1 confidence. |
| `/acuity/objects/best/tx` | double | Center, normalized. |
| `/acuity/objects/best/ty` | double | Center, normalized. |

## Versioning policy

* **Add a field** = no version bump.
* **Rename or remove a field** = `version` += 1. Libraries pinned to
  the old version emit a warning and degrade gracefully.
* **Restructure the table layout** (e.g., move `tags/` somewhere
  else) = `version` += 1, ship a migration note.

We try hard to never break compat. The only *intentional* break we
have on the roadmap is encoding tag pose as a 3D `Pose3d` instead of
flat distance/yaw/pitch — that'd be schema v2.
