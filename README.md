# Team 1279 Robot Code (Python)

## What does this robot do?

This is an FRC (FIRST Robotics Competition) robot. It plays a game on a field where it needs to **pick up bals** and **shoot them at targets**. Think of it like a remote-controlled ball-launching machine.

### The robot has 5 main systems:

| System | What it does | Real-world analogy |
| --- | --- | --- |
| **Drivetrain** | Drives the robot around the field | A car's wheels and steering |
| **Feeder** | Picks up balls from the ground | A vacuum cleaner |
| **Shooter** | Launches balls at high speed | A baseball pitching machine |
| **Hood** | Aims the shooter up or down | Tilting a cannon |
| **Elevator** | Raises/lowers a platform | An elevator in a building |

### How the code is organized:

```markdown
robotics_code/
├── robot.py           ← The starting point. Runs when the robot turns on.
├── robotcontainer.py  ← Connects buttons to actions ("press X to do Y").
├── constants.py       ← All the numbers (motor IDs, speeds) in one place.
└── subsystems/        ← One file per robot system:
    ├── drivetrain.py  ← Driving
    ├── shooter.py     ← Shooting (includes kicker + conveyor)
    ├── feeder.py      ← Ball intake
    ├── hood.py        ← Aiming
    └── elevator.py    ← Lifting
```

### How a match works:

1. **Autonomous (15 seconds)** — The robot drives and scores by itself using pre-programmed paths. No humans allowed!
2. **Teleop (2+ minutes)** — Two human drivers control the robot using Xbox controllers.

### Controller layout:

**Driver controller** (left person — drives the robot):

- Left joystick = drive forward/backward and strafe left/right
- Right joystick = spin the robot
- Right bumper = hold for slow mode
- X button = hold to brake

**Operator controller** (right person — runs the mechanisms):

- Left bumper = **FIRE!** (shoot a ball)
- Left stick click = **LAUNCH!** (long-range shot)
- Right bumper = reverse everything (clear a jam)
- X / B = tilt hood down / up
- Y / A = elevator up / down
- Start / Back = conveyor forward / reverse
- Right stick click = pick up a ball

### Key concepts for beginners:

- **Subsystem** = A part of the robot (like the shooter or drivetrain). Each subsystem "owns" its motors and only one command can use a subsystem at a time.
- **Command** = An action the robot performs (like "shoot a ball" or "drive forward"). Commands use subsystems.
- **PID** = A math formula that helps motors go to exact positions or speeds smoothly. The P, I, and D values are tuning knobs.
- **CAN ID** = Every motor has a unique number so the robot's brain can talk to the right motor (like an address).
- **Swerve drive** = A drivetrain where each wheel can independently steer and drive, letting the robot move in any direction.