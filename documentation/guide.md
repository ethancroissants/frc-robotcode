# Team 1279 — Build, Deploy & Driver Station Guide (Python / RobotPy)

This is the RobotPy port of the 2026 FRC robot code. The controls and bindings are
**identical** to the Java version in `../old_code/` — same USB slots, same buttons,
same motor directions. Only the language and the build/deploy commands differ.

Team number: **1279**
RobotPy version: **2026.2.2** (see `pyproject.toml`)

---

## 1. One-time setup (new laptop / fresh install)

You need these installed:

1. **Python 3.10+** — from [python.org](https://www.python.org/downloads/) or your
   package manager. Verify with `python --version`.
2. **RobotPy + project deps** — run once from the project root:
   ```bash
   python setup.py
   ```
   That installs `robotpy` and syncs `robotpy-commands-v2`, `phoenix6`, and
   `robotpy-pathplannerlib` (declared in `pyproject.toml`).
3. **FRC Game Tools 2026** (Windows only, from NI) — installs the **Driver Station**
   and **roboRIO Imaging Tool**. This is what the driver laptop uses to enable /
   disable the robot. Get it from
   [https://www.ni.com/en/support/downloads/drivers/download.frc-game-tools.html](https://www.ni.com/en/support/downloads/drivers/download.frc-game-tools.html).
4. **PathPlanner** (optional but used here) — from the Microsoft Store or
   [https://github.com/mjansen4857/pathplanner/releases](https://github.com/mjansen4857/pathplanner/releases).
   Autos live in `deploy/pathplanner/`.

---

## 2. Building / compile check

RobotPy is interpreted, so there's no real "build" step — just a syntax check:

```bash
python -m py_compile robot.py robotcontainer.py gamepads.py constants.py
```

Or compile the whole tree:

```bash
python -m compileall .
```

---

## 3. Deploying to the robot

**Use the helper script (recommended):**

```bash
python deploy.py
```

This wraps `robotpy deploy` with a connectivity pre-check and nicer output. Extra
args are forwarded:

```bash
python deploy.py --skip-tests     # skip the test step
python deploy.py --nc             # stream console output while deploying
```

**Raw equivalent:**

```bash
python -m robotpy deploy
```

The roboRIO must be reachable — on the robot WiFi, USB-tethered, or Ethernet to the
radio's LAN port. `deploy.py` will ping `roborio-1279-FRC.local`, the team-static
IP, and the USB tether address before it even tries to deploy.

---

## 4. Running the simulator (no robot needed)

```bash
python -m robotpy sim
```

Opens the RobotPy Sim GUI with a simulated Driver Station. Map keys to axes /
buttons in the GUI — the defaults are in `ctre_sim/` / the saved sim layout.

---

## 5. Driver Station setup (this is where the shooter-not-working issue comes from)

**This section is identical to the Java project — the Python code reads from the
same USB slots.** If the operator controller is not in **USB slot 1**, every
operator binding — including the entire shooter — silently does nothing.

Defined in `constants.py`:

| Role     | USB slot | Constant                                            |
|----------|----------|-----------------------------------------------------|
| Driver   | 0        | `constants.GamePadIDs.DRIVER_GAMEPAD_ID   = 0`      |
| Operator | 1        | `constants.GamePadIDs.OPERATOR_GAMEPAD_ID = 1`      |

### Steps — every time the DS is freshly installed (or a USB cable moves)

1. Plug both Xbox controllers into the driver laptop.
2. Open the **FRC Driver Station**.
3. Click the **USB tab** (gamepad icon on the left-hand column). You'll see four
   slots, 0 through 3, in whatever order Windows enumerated them — which is almost
   never the order we want.
4. **Drag and drop** each controller onto the slot it should be in:
   - **Slot 0** → driver controller (swerve drive)
   - **Slot 1** → operator controller (shooter / elevator / hood / feeder / conveyor)
5. Confirm each slot shows the controller as active (row turns green, not greyed
   out).
6. **Wiggle the sticks** on each controller and watch the axis bars in the USB tab
   move. Press each face button and watch the button LEDs light up. A button that
   doesn't light up means the controller itself is dead — swap it before you waste
   an hour on "the code is broken."
7. Enable the robot in **Teleop** and re-test.

The DS remembers the slot assignment as long as you keep plugging the same
controller into the same physical USB port on the laptop. Save the DS config
(top-right gear → **Save**) after setting slots so it survives a reboot.

---

## 6. Controller map

Source of truth: `robotcontainer.py` → `configureBindings()`. These match the Java
bindings 1:1.

### Driver controller (USB slot 0)

| Input                          | Action                                              |
|--------------------------------|-----------------------------------------------------|
| Left stick Y                   | Drive forward / back (field-centric)                |
| Left stick X                   | Strafe left / right (field-centric)                 |
| Right stick X                  | Rotate                                              |
| **Left bumper**                | Reset field-centric heading (press once)            |
| **Right bumper (hold)**        | Slow drive mode                                     |
| **X button (hold)**            | Swerve X-brake (wheels form an X)                   |
| **B button (hold)**            | Point wheels toward left-stick direction            |
| Back + Y                       | SysId dynamic forward (tuning only)                 |
| Back + X                       | SysId dynamic reverse (tuning only)                 |
| Start + Y                      | SysId quasistatic forward (tuning only)             |
| Start + X                      | SysId quasistatic reverse (tuning only)             |

### Operator controller (USB slot 1)

| Input                          | Action                                              |
|--------------------------------|-----------------------------------------------------|
| **Left bumper (hold)**         | **FIRE** — spin up shooter 0.7 s, then kicker + conveyor |
| **Right bumper (hold)**        | Clear out — shooter/kicker/conveyor reversed        |
| **Left stick click (hold)**    | LAUNCH — same shooter velocity as FIRE; both read `Tune/Shooter Distance (ft)` |
| **Right stick click (hold)**   | Feeder in (pickup)                                  |
| **Y button (press)**           | Elevator up to top (PID)                            |
| **A button (hold)**            | Elevator down                                       |
| **X button (hold)**            | Hood down                                           |
| **B button (hold)**            | Hood up                                             |
| **Start button (hold)**        | Conveyor forward                                    |
| **Back button (hold)**         | Conveyor reverse                                    |

All operator buttons release to a stop command (`ceaseFire` / `stopElevator` /
`stopHood` / `stopConveyor` / `stopFeeder`), so letting go always kills the motor.

---

## 7. Autonomous

PathPlanner autos and paths live under:

```
deploy/pathplanner/paths/
deploy/pathplanner/autos/
```

The selected auto comes from the **SmartDashboard** `Auto Chooser` widget — built
in `RobotContainer.__init__` with `AutoBuilder.buildAutoChooser()`.

Named commands already wired (see `RobotContainer.__init__`):

- `Shoot`    → `AutoFire`
- `FeederIn` → `FeederIn`

If you add a new named command to a `.auto` file, you **must** also register it
with `NamedCommands.registerCommand(...)` in `RobotContainer.__init__` or the auto
will silently skip that step.

---

## 8. Troubleshooting

**"I press the operator buttons and nothing happens."**
→ 99% of the time this is §5 — operator controller isn't in USB slot 1. Open the DS
USB tab and check.

**"Driver works, operator does nothing."**
→ Same as above. One controller is in slot 0, the other is not in slot 1. Drag it.

**"Shooter spins but the ball doesn't launch."**
→ Hold longer. `AutoFire` (`commands/auto_fire.py` line 19) waits 0.7 s for the
shooter to spin up before the kicker + conveyor engage. Short taps never make it
past spin-up.

**"Shooter runs backwards."**
→ `OperatorSubsystem.shooterOut()` uses
`m_request.with_velocity(-tunables.shooter_velocity_rps())` — the negative
sign is intentional (CW). Flipping it reverses the wheel.

**"Ball goes too short / too far at every distance."**
→ Tune `Tune/Shooter Distance (ft)` to whatever you actually shot from. If
the *whole* mapping is off, edit `_SHOOTER_BASE_RPS` and
`_SHOOTER_RPS_PER_FOOT` in `tunables.py` and redeploy.

**"Deploy fails: can't reach the roboRIO."**
→ `deploy.py` pings the robot first. If that fails, you're not actually on the
robot network. Check the Driver Station comms light, or plug in USB-B to the
roboRIO.

**"Deploy succeeds but robot doesn't move."**
→ Check the DS communications + robot code lights. If comms is green and robot
code is red, the Python program crashed on startup. Run
`python -m robotpy deploy --nc` to stream the roboRIO console and read the
traceback.

**"CAN bus error / motor not responding."**
→ Verify CAN IDs in `constants.ControllerIDs` using Phoenix Tuner X. Every motor ID
there must match a physical controller on the CAN bus.

**"The DS keeps forgetting my controller slots."**
→ Plug the same controller into the same USB port each time. Save the DS config
after setting slots (top-right gear → **Save**).

---

## 9. Parity with the Java version

This code is a direct port of `../old_code/`. Confirmed identical as of the
current commit:

- USB slot assignments (driver=0, operator=1)
- Every button binding in `configureBindings()` (hood / elevator / shooter / kicker
  / conveyor / feeder)
- Debounce of 0.1 s with `kBoth` on every button
- Motor-speed constants: SHOOTER 0.5, KICKER 0.9, CONVEYOR 1.0, HOOD 0.2, FEEDER
  0.5, ELEVATOR 0.6, LAUNCH 0.7
- Sign conventions on every `xxxFwd` / `xxxRev` / `xxxIn` / `xxxOut` helper

**Diverged from Java:** the shooter no longer has separate near/far velocity
setpoints. Both `Fire` and `Launch` now read a single `Tune/Shooter Distance
(ft)` knob (default `10 ft`) which maps to flywheel rps via a linear model in
`tunables.py` (`rps = 60 + 4 × ft`). See `elastic.md` §5 for the dashboard
table.

**Terminology:** "elevator" in this codebase is the **climbing** elevator
(limit switches, climb positions) — the *ball* elevator is the **conveyor**.
See `elastic.md` for the conveyor direction convention.

If you change a binding or motor sign in one project, change it in the other and
re-check this parity list.
