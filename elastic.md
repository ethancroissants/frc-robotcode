# Elastic Dashboard — Team 1279

[Elastic](https://github.com/Gold872/elastic-dashboard) is the dashboard we use
to watch the robot and tweak values at the pit / in the stands without
redeploying code. It speaks NetworkTables, so anything the robot publishes
(`SmartDashboard.putNumber`, `putBoolean`, `putData`, …) shows up in Elastic
and can be edited live.

---

## 1. Install

Grab the latest release from the [Elastic releases page](https://github.com/Gold872/elastic-dashboard/releases)
(Windows `.exe`, macOS `.dmg`, or Linux `.AppImage` / `.deb`). Install it on
the driver laptop alongside the Driver Station.

---

## 2. Connect to the robot

1. Launch Elastic.
2. Open **Settings** (gear icon, top-right).
3. Set **IP Address Mode** to **Driver Station** — Elastic will follow whatever
   robot the DS is talking to.
   - Or set it manually: team number **1279** → `10.12.79.2` (roboRIO).
   - For the simulator, use `127.0.0.1` / **localhost** mode.
4. The connection light (top bar) turns green when NT connects.

---

## 3. Laying out widgets

- Drag a key from the **NetworkTables tree** (left panel) onto the grid to
  create a widget.
- Right-click a widget → **Show Settings** to change the type (number field,
  slider, text display, graph, etc.), min/max, and precision.
- **File → Save Layout** writes the layout to disk so it persists across
  restarts. Use **Save Layout As…** if you want separate pit-vs-match layouts.

### Widget types at a glance

When you drop a number key on the grid, Elastic picks **Text Display** by
default. Right-click → **Show type** (or the dropdown in the settings panel)
to switch. The common choices for our tunables:

| Widget              | Good for                                  | Editable? | Notes                                           |
|---------------------|-------------------------------------------|-----------|-------------------------------------------------|
| **Text Display**    | Any number — just type a new value        | Yes       | Fastest for precise entry (e.g. `94.5 rps`).    |
| **Number Slider**   | Values with a natural min/max             | Yes       | You set **Min / Max / Divisions** in settings. Great for duty-cycle (−1…1) and spin-up seconds. |
| **Number Bar**      | Read-only "how full / how fast"           | No        | Use for live sensor readouts, not tunables.     |
| **Graph**           | Trending a value over time                | No        | Handy while tuning — drop a second copy of the key as a Graph next to the editable one. |
| **Voltage View**    | Battery voltage, bus voltage              | No        | Only use on voltage keys. Our tunables aren't voltages — leave this one for `PDP/Voltage`, etc. |
| **Boolean Box**     | On/off indicator                          | No        | Not used by our tunables (all numeric).         |
| **Toggle Switch**   | Editable boolean                          | Yes       | Not used by our tunables (all numeric).         |
| **ComboBox Chooser**| `SendableChooser` (e.g. the Auto Chooser) | Yes       | Required for `SmartDashboard/Auto Chooser`.     |

**Rule of thumb for our tunables:**

- If the value is a **duty-cycle** (−1.0 … 1.0) → **Number Slider**, min `-1`,
  max `1`, divisions `20` (gives 0.1 steps). Flip the sign if your mechanism
  runs backwards instead of memorizing which ones are negative.
- If the value is a **time** (seconds) → **Number Slider**, min `0`, reasonable
  max (e.g. `5` for spin-up, `10` for fire duration). Or just a **Text Display**
  if you want to type exact values like `2.25`.
- If the value is a **velocity** (rps) → **Text Display** for fine tuning, or
  a **Number Slider** with min `0`, max ~`120` (above shooter free-speed) for
  coarse sweeps. Pair with a **Graph** widget on the measured velocity so you
  can see the flywheel settle.

---

## 4. Editing tunables live

Values published under the `Tune/` table are meant to be edited from the
dashboard. The flow is:

1. Robot code boots → `tunables.publish_defaults()` seeds every key with its
   compiled-in default (`constants.py` or the default in `tunables.py`).
2. You edit the value in Elastic → the new value lives in NetworkTables.
3. The next loop, `tunables.*()` getters read the fresh value and the robot
   uses it immediately — **no redeploy needed**.
4. Power-cycling the robot resets values to the compiled defaults. If you like
   a tuned value, copy it back into `constants.py` / `tunables.py` and deploy.

> ⚠️ Elastic does **not** persist the NT values themselves — it only persists
> your widget layout. Tuned numbers are lost on robot reboot unless you bake
> them into code.

---

## 5. Tunable NetworkTables keys

All of these live under the `SmartDashboard/Tune/…` table (Elastic shows them
under **SmartDashboard → Tune**). Source: `tunables.py`.

### Shooter timings / velocities

| NT key                                          | Default | Units | Recommended widget | Slider Min / Max | Used by                         |
|-------------------------------------------------|--------:|-------|--------------------|------------------|---------------------------------|
| `Tune/Shooter Spin-Up (s)`                      | `2.0`   | sec   | **Number Slider**  | `0` / `5`        | `commands/auto_fire.py`, `commands/fire.py` |
| `Tune/Shooter Near Velocity (rps)`              | `95.0`  | rps   | **Text Display** (fine) or **Number Slider** (coarse) | `0` / `120` | closed-loop shooter (near shot) |
| `Tune/Shooter Far Velocity (rps)`               | `100.0` | rps   | **Text Display** (fine) or **Number Slider** (coarse) | `0` / `120` | closed-loop shooter (far shot)  |
| `Tune/AutoFire Fire Duration After Spin-Up (s)` | `3.0`   | sec   | **Number Slider**  | `0` / `10`       | `commands/auto_fire.py`         |

Why these ranges:

- **Spin-up seconds** — anything above ~4 s just wastes match time; `0` lets
  you test instant-fire.
- **Shooter velocity (rps)** — Kraken free speed is ~100 rps at the motor,
  geared shooter wheels typically top out near that. `120` gives a little
  headroom; stay above ~60 rps or balls won't clear.
- **Fire duration** — needs to cover spin-down + clearing stuck balls. More
  than ~6 s usually means something else is wrong.

### Open-loop motor speeds (duty-cycle, −1.0 … 1.0)

These are raw throttle values. **All of them want a Number Slider with min
`-1`, max `1`, divisions `20`** (0.1 steps).

| NT key                         | Default (from `constants.MotorSpeeds`) | Direction note                  | Subsystem                    |
|--------------------------------|---------------------------------------:|---------------------------------|------------------------------|
| `Tune/Shooter Open-Loop Speed` | `0.5`                                  | positive = shoot outward        | shooter (open-loop fallback) |
| `Tune/Kicker Speed`            | `0.9`                                  | positive = kick into flywheel   | kicker                       |
| `Tune/Conveyor Speed`          | `1.0`                                  | positive = feed upward          | conveyor                     |
| `Tune/Feeder Speed`            | `0.5`                                  | positive = intake               | feeder                       |
| `Tune/Hood Speed`              | `0.2`                                  | tune **small** — hood is geared low | hood                     |
| `Tune/Elevator Speed`          | `0.6`                                  | positive = up                   | elevator                     |

> 🛑 **Safety:** setting a duty-cycle to `1.0` means full voltage. For the
> hood especially, crank it up **in small steps** (0.05) — it's easy to snap
> a linkage. Current limits in `constants.ModuleConstants` (e.g.
> `kShooterMotorCurrentLimit = 60 A`) are the only thing keeping a runaway
> command from cooking a motor.

### Getter-to-key mapping

If you're reading the code and wondering which dashboard key a call reads:

| `tunables.*()` function          | NT key                                          |
|----------------------------------|-------------------------------------------------|
| `shooter_spin_up_seconds()`      | `Tune/Shooter Spin-Up (s)`                      |
| `shooter_near_velocity()`        | `Tune/Shooter Near Velocity (rps)`              |
| `shooter_far_velocity()`         | `Tune/Shooter Far Velocity (rps)`               |
| `auto_fire_duration()`           | `Tune/AutoFire Fire Duration After Spin-Up (s)` |
| `shooter_open_speed()`           | `Tune/Shooter Open-Loop Speed`                  |
| `kicker_speed()`                 | `Tune/Kicker Speed`                             |
| `conveyor_speed()`               | `Tune/Conveyor Speed`                           |
| `feeder_speed()`                 | `Tune/Feeder Speed`                             |
| `hood_speed()`                   | `Tune/Hood Speed`                               |
| `elevator_speed()`               | `Tune/Elevator Speed`                           |

---

## 6. Other keys worth watching (not tunable)

These are published by the robot for telemetry — look, don't edit:

- `SmartDashboard/Auto Chooser` — the autonomous routine selector
  (`robotcontainer.py`). Use a **ComboBox Chooser** widget.
- `SmartDashboard/Module 0…3` — swerve module state diagrams
  (`telemetry.py`). Use the **Mechanism2d** widget.
- Any `Swerve/…` or `DriveState/…` entries the CTRE telemetry publishes.

---

## 7. Adding a new tunable

1. Add a private key constant + default in `tunables.py`.
2. Publish it in `publish_defaults()` with `SmartDashboard.putNumber(...)`.
3. Add a getter that reads with `SmartDashboard.getNumber(key, default)`.
4. Call the getter from the command/subsystem that needs it.
5. Add a row to the table above so the next person knows it exists.

Deploy once, and the new key appears in Elastic under `SmartDashboard → Tune`.
