# Vision System Setup

This is the operator-facing guide to the Pi's AprilTag vision pipeline:
how to verify it works, how to calibrate the shooter so SHOOT actually
scores, and how to read the dashboard while you do it. For the full
architecture / NT contract / installation walkthrough see
[`orangepi.md`](orangepi.md).

---

## What the system does (one paragraph)

The Pi's camera runs a 36h11 AprilTag detector at 30 fps. When a target
tag is in view it publishes the live **bearing** (signed angle from
camera optical axis, degrees) and **range** (PnP distance from a known
6.5″ tag side, meters) to NetworkTables. The Pi maintains a small
**calibration table** of `(distance_ft, rps)` pairs; for each frame it
linearly interpolates the table at the live tag range and publishes the
result as the recommended flywheel RPS. When the operator presses
**SHOOT** in the dashboard, the rio's `AutoAim` command picks up the
bearing + the recommended RPS, rotates the swerve onto the tag, spins
the wheel, and fires.

There is no LaserCAN, no separate distance sensor — range is purely
PnP-derived from the tag. That's why the calibration table is what
makes shots actually land.

---

## Pre-flight: is the vision pipeline alive?

Before calibrating, prove the basics work. Open
`http://<pi-host>:8080/` (or whatever your Pi's address is) and confirm:

1. **`RIO LINK UP`** in the topbar — the dashboard is talking to the
   rio. If it says `RIO DISCONNECTED`, no calibration data will reach
   AutoAim until you fix the link.
2. **Camera panel shows a live image** — not a black square. If it's
   black, check `/dev/video0` exists on the Pi (`v4l2-ctl --list-devices`)
   and that the USB camera is seated.
3. **Aim the camera at any AprilTag.** It doesn't have to be a target
   tag — the Pi draws a faint orange box on every detected tag. If
   nothing draws, the detector isn't seeing the tag (focus, lighting,
   distance, or the tag isn't 36h11).
4. **Click the tag in the camera image.** A solid green outline should
   appear; the **Target** panel fills in (`tag #N`, range in meters,
   bearing in degrees). If clicking does nothing, the click isn't
   landing inside the tag's quad — try the center.
5. **Distance panel's `tag range` row should match reality.** Stand at
   a known distance (tape measure) and confirm the readout agrees
   within a few inches at close range, within ~6 inches at long range.

**If the tag range is consistently off by a constant factor** (e.g.
"reads 5 ft when I'm at 10 ft"), one of these is wrong:

- `TAG_SIZE_M` in `sight.env` doesn't match your printed tag (default
  `0.1651` = 6.5″, the FRC standard).
- Camera FOV is wrong (default `CAMERA_HFOV_DEG=60.0`). For maximum
  accuracy, drop a chessboard-calibrated `cam_intrinsics.json` next to
  `server.py` (see [Camera intrinsics](#camera-intrinsics) below).

Fix that *before* calibrating the shooter — calibration data taken
against a wrong tag range will be inconsistent at every distance.

---

## Calibrating the shooter

Different shooting distances need different flywheel RPS. Air drag and
launch arc don't scale linearly. So instead of one "RPS per foot"
constant, the Pi keeps a **table** of `(distance_ft, rps)` rows that
you fill in by actually shooting at known distances. Every frame the
Pi reads the live tag-PnP range, finds the bracketing two rows, and
linearly interpolates an RPS — that's what AutoAim uses when you press
SHOOT.

### Step-by-step (the dedicated calibrate page)

Click **calibrate** in the dashboard topbar to open the calibrate page
in a new tab. It's a focused single-page UI for this exact loop —
manual RPS input, fire button, log-point form, and a live view of the
existing table. It also gives you a **calibrate mode** toggle: while
on, the Pi publishes the manual RPS you've typed to the rio instead of
the table-interpolated value, so your test shot fires at *exactly*
that RPS regardless of what the table says.

The first match you play against a fresh shooter, do this:

1. **Park the bot at a known distance from the goal.** Tape measure or
   field markings — what matters is that you trust the number. A good
   first set of distances: 4 / 8 / 12 / 16 ft (or whatever range you
   actually shoot from).
2. **Click the goal AprilTag in the dashboard's Camera panel.** That
   locks the Pi onto that specific tag. The Target panel shows range
   + bearing; the calibrate page mirrors them in its own readout.
3. **Sanity-check the tag range against your tape.** If it's off,
   stop and fix `TAG_SIZE_M` / camera intrinsics first (see below).
4. **Flip on calibrate mode** (the toggle on the calibrate page).
   The topbar pill on the dashboard reads `calibrate mode` so anyone
   else watching the dashboard knows what's happening.
5. **Type a manual RPS** (or use the `±0.5 / ±1` bumpers) and press
   **FIRE**. Watch where the ball lands. Iterate the RPS up/down
   until shots land cleanly in the goal.
6. **Click "Log this point"** on the calibrate page. The distance
   field defaults to the live tag-PnP range — edit it if your tape
   measure disagrees. The RPS field is the manual RPS you settled on.
   Click the button → row added to the table.
7. **Move to the next distance, repeat** until you have ~5 rows
   spanning your real shooting range.
8. **Flip calibrate mode off** when you're done so SHOOT goes back to
   the table-interpolated RPS for game use.

If you'd rather edit by hand, the dashboard's **Calibration** panel
still has the same `add` form + `snapshot current shot` button — both
write to the same JSON file the calibrate page does.

### How interpolation works

For a tag range `d` (in feet):

- `d` ≤ lowest table row → returns lowest row's RPS (clamped, no
  extrapolation).
- `d` ≥ highest table row → returns highest row's RPS (clamped).
- otherwise → finds the bracketing two rows `(d_lo, rps_lo)` and
  `(d_hi, rps_hi)`, returns `rps_lo + (d - d_lo) / (d_hi - d_lo) * (rps_hi - rps_lo)`.

Two rules of thumb that fall out of this:

- **Cap your table at the maximum distance you'd ever shoot from**, or
  the clamp will silently use the highest row's RPS for any shot beyond
  that — the ball will fall short.
- **More rows in the range you actually shoot from = more accurate
  shots.** Linear interpolation between only two distant points (say
  rows at 0 and 16 ft) is usually wrong in the middle. Five
  well-spaced rows is the sweet spot for most shooters.

### What ships out of the box

| Distance (ft) | RPS |
| ------------- | --- |
| 0             | 0   |
| 4             | 40  |
| 8             | 80  |
| 12            | 100 |
| 16            | 110 |

This is "10 RPS per foot" tapering at the high end. **It is a
placeholder.** It will not score on your goal — every shooter has
different geometry, friction, ball weight, exit angle, etc. Treat the
default rows as data to overwrite on day 1.

The table is stored on the Pi at:

```
/home/orangepi/cold-fusion-sight/sight_calibration.json
```

That path **survives** both reboots and `Set up / Update Vision Pi`
re-pushes from the laptop — the file is deliberately outside the
rsync target so calibration data persists across code updates.

To start over from scratch, SSH to the Pi and `rm` that file; the
service will recreate it from the default rows on next start.

### Editing rows after the fact

The Calibration panel renders one row per table entry, with a `remove`
button on each. To replace a row's RPS, click `remove`, then `add` a
new row at the same distance with the corrected RPS. (Adding a row at
an existing distance also works — the server dedupes and keeps the
most recent.)

---

## Tag range calibration (range-scale)

The PnP range estimate is `(known tag size) / (apparent tag size in
pixels)` projected through the camera matrix. Two things make every
reading off by the same multiplicative factor:

- The synthesized camera matrix from `CAMERA_HFOV_DEG` doesn't match
  the real lens (most common — manufacturer spec is rarely exact).
- `TAG_SIZE_M` doesn't match the printed tag (printed slightly smaller
  or larger than 6.5″).

For both of these, all ranges scale by the same number. So we expose a
single **range-scale multiplier** on the calibrate page that you tune
with one measurement.

### One-shot calibration

1. Park the bot at a **known distance** from a target tag (tape
   measure). Anywhere mid-range works — say 8 ft.
2. On the calibrate page, click the tag in the camera view (or aim at
   it directly so it auto-locks). The "live tag range" row should show
   what the Pi *thinks* the distance is — e.g. it might say `7.20 ft`
   when you're really at 8.
3. Type **8** into the **true distance (ft)** input.
4. Click **calibrate from this**. The Pi solves
   `scale = 8 / 7.20 = 1.111`, applies it immediately, and persists it
   to disk (`range_calibration.json` next to `server.py`).
5. The "live tag range" row should now read close to 8 ft.

The scale survives Pi reboots and `Set up / Update Vision Pi` re-pushes
(rsync without `--delete` leaves files-not-in-source alone).

### What the readout shows

- **live tag range** — the corrected range, after the scale has been
  applied. This is what the rio sees on `/Sight/Target/RangeM`.
- **if uncorrected** — what the raw PnP would have produced (only
  shown when scale ≠ 1.0). Useful for sanity-checking the correction.
- **scale** — the current multiplier; `1.0` = no correction.

### When to recalibrate

- You replaced the camera or changed the lens.
- You started using printed tags of a different size than before
  (with `TAG_SIZE_M` not updated yet — better to fix `TAG_SIZE_M`).
- Range readings drifted noticeably (refocused lens, knocked the camera).

### Reset

Click **reset to 1.0** on the calibrate page if you want raw PnP
readings back (e.g. you swapped in a chessboard-calibrated
`cam_intrinsics.json` and want to start from scratch).

### Why this isn't a per-distance lookup

A single multiplier is the right *shape* for the dominant error
sources here. A per-distance lookup (different correction at 4 / 8 /
12 / 16 ft) would let you fight non-multiplicative errors like lens
distortion — but the right fix for that is a real chessboard
calibration written to `cam_intrinsics.json`, not a polynomial fit on
top of bad intrinsics. Keep this page's calibration simple; if one
scalar isn't enough, calibrate the camera properly.

---

## Spin-up delay (flywheel settle window)

The rio's `AutoAim` command goes through three phases when SHOOT fires:

1. **rotating** — yaw the swerve until bearing is centered.
2. **spinning_up** — command the wheel to the recommended RPS, hold
   heading, and *wait* for the wheel to come up to speed.
3. **firing** — pull the trigger (kicker + conveyor) for
   `auto_fire_duration` seconds.

The wait in step 2 is the **spin-up delay** — how long AutoAim waits
after commanding RPS before pulling the trigger. AutoAim also checks
that the wheel actually reports `isAtRps()` before firing, but the
delay gives the controller time to react and prevents a "command sent
→ trigger pulled in the same loop tick → ball goes flying at half
speed" edge case.

You can tune this from the calibrate page (the **spin-up delay (s)**
input). Range is 0–5 seconds, default 0.4. The Pi publishes it to
`/Sight/Aim/SpinUpDelayS`; AutoAim reads it every cycle, so you can
adjust it without redeploying the rio. Two cases worth thinking about:

- **Shooter takes time to wind up** (heavy flywheel, slow controller
  gains): increase the delay until you stop firing before the wheel
  is at speed.
- **Shooter is already spinning at idle** (e.g. you spin the wheel
  during the rotate phase via some other code path): you can drop the
  delay close to zero so SHOOT fires immediately.

If the NT topic disappears (e.g. rio comes up before the Pi), AutoAim
falls back to the 0.4-second default.

---

## What `SHOOT` actually does with the table

When the operator presses **SHOOT**:

1. Pi sees a tag, e.g. `range_m = 2.40` → `7.87 ft`.
2. Looks up the calibration table → interpolates between the 4 ft and
   8 ft rows → publishes e.g. `78.7 RPS` to `/Sight/Aim/TargetRps`.
3. Increments `/Sight/Shoot/RequestId`.
4. Rio's `AutoAim` command sees the new request, rotates the swerve
   onto the bearing the Pi published (closing a PID loop on
   `/Sight/Target/BearingDeg`), spins the wheel to the recommended
   RPS, fires.
5. Sets `/Sight/DriverLockout=true` for the duration so the
   driver-side display knows the swerve is busy.

If the recommended RPS is wrong for that distance, the table is wrong
— re-shoot at that distance, observe where the ball actually lands,
and overwrite the row.

The dashboard's **Target** panel shows the recommended RPS live (the
`rps` field updates per detection tick) so you can see what AutoAim
*would* fire if you pressed SHOOT right now.

---

## Camera intrinsics

PnP range estimation works from a known tag size + a camera matrix.
By default the Pi synthesizes the matrix from `CAMERA_HFOV_DEG`
(default 60°). For sub-degree bearings + accurate range — especially
at distance — calibrate the camera with a chessboard and drop the
result at `cam_intrinsics.json` next to `server.py` on the Pi:

```json
{
  "K":    [[fx, 0, cx], [0, fy, cy], [0, 0, 1]],
  "dist": [k1, k2, p1, p2, k3]
}
```

The dashboard's **Debug → stats** tab shows which intrinsics path is
in use:

- `synthetic (HFOV=60.0°)` — fallback, fine for short-range work.
- `calibrated (cam_intrinsics.json)` — real intrinsics in use.

Standard chessboard calibration walkthroughs (OpenCV
`cv2.calibrateCamera` with a printed checkerboard) produce K + dist
directly; just write them to the JSON.

---

## Quick troubleshooting

| Symptom                                     | Try                                                                                          |
|---------------------------------------------|----------------------------------------------------------------------------------------------|
| Camera image is black                       | `v4l2-ctl --list-devices` on the Pi; reseat USB camera; verify `CAMERA_DEVICE` in `sight.env`. |
| `seen tags: (none)` on every aim            | Detector isn't finding the tag. Check focus, lighting, that the printed tag is the 36h11 family, and that it's large enough in frame. |
| Tag range is off by ~2× at every distance   | `TAG_SIZE_M` in `sight.env` doesn't match your printed tag. Default `0.1651 m` = 6.5″ FRC tag. |
| Tag bearing is consistently off by a few °  | Camera FOV is wrong. Either fix `CAMERA_HFOV_DEG` or drop a calibrated `cam_intrinsics.json`.  |
| `SHOOT` button stays grey even with target  | Read the sub-label — it names the blocking precondition (`rio offline`, `robot disabled`, `off-bearing`, `no range`, etc.). |
| RPS recommendation looks crazy              | Calibration table has only one row (or rows separated by a huge gap). Add intermediate rows. |
| Shots fall short past your max table row    | Table clamps — anything beyond the highest row uses that row's RPS. Add a row at your max distance. |
| `recommended_rps: null` on the SSE feed     | No tag is in view *or* tag range is below 0.05 m (sanity threshold). Aim at a tag.              |

For everything else, the **Debug → logs** tab tails the live server
log; the **Debug → nt** tab shows current NT topic values + ages.
