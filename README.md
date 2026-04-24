# FRC Robot Code

Python port (RobotPy) of the team's 2026 FRC robot code, originally written in Java.

Built on [RobotPy](https://robotpy.readthedocs.io/) using the command-based framework, CTRE Phoenix 6 for swerve and motor control, and PathPlanner for autonomous routines.

## Project layout

```
robot.py             TimedRobot entry point
robotcontainer.py    Subsystem, command, and controller button bindings
constants.py         Motor speeds, CAN IDs, PID gains, field constants
gamepads.py          Driver / operator controller definitions
motorcontrollers.py  Motor controller instances (Phoenix 6)
telemetry.py         SmartDashboard / NetworkTables logging
commands/            Command classes (shooter, feeder, elevator, drive, ...)
subsystems/          Subsystems (swerve drivetrain, elevator, operator, shooter)
generated/           Phoenix Tuner X output (tuner_constants.py)
deploy/              PathPlanner autos and paths, robot config
ctre_sim/            CTRE simulation support files
```

## Setup

Requires Python 3.10+.

```bash
python setup.py
```

This installs `robotpy`, syncs the dependencies declared in `pyproject.toml` (`robotpy-commands-v2`, `phoenix6`, `robotpy-pathplannerlib`), and runs compile checks.

## Common commands

```bash
python -m robotpy sim              # Run the simulator
python deploy.py                   # Deploy to the roboRIO
python -m robotpy test             # Run unit tests
```

`deploy.py` forwards any extra arguments to `robotpy deploy`.

## Controls

See `robotcontainer.py` for the full binding list. Highlights:

- **Driver** — left stick translates, right stick rotates (field-centric). `X` brakes, `B` points wheels, left bumper reseeds field-centric heading, right bumper engages slow mode.
- **Operator** — face buttons drive the hood and elevator; bumpers fire / clear the shooter; start/back run the conveyor; triggers drive the feeder directly (see `robot.teleopPeriodic`).

## Repo helpers

- `push.py` — stages everything, commits as `"update"`, and pushes. **Contains a hardcoded GitHub token** — rotate it and move to an env var before this repo is ever made public.
- `update.py` — deletes the working copy and re-clones fresh from GitHub. Destructive; it preserves itself via a temp dir but wipes all other local changes.
