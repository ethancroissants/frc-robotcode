# Setup Guide — Team 1279 Robot Code

This guide walks you through everything from a fresh laptop to driving the robot. No experience needed — just follow each step in order.

---

## Step 1: Install Python

You need Python 3.12 or newer on your computer.

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download the latest Python 3.12+ installer for your system (Windows/Mac/Linux)
3. **Important (Windows):** Check the box that says **"Add Python to PATH"** during install
4. Open a terminal (Command Prompt on Windows, Terminal on Mac) and verify:
   ```
   python --version
   ```
   You should see something like `Python 3.12.x`

---

## Step 2: Install RobotPy and Phoenix6

RobotPy is the Python version of WPILib (the FRC robot framework). Phoenix6 is the library for our CTRE motors.

Open a terminal and run:
```
pip install "robotpy[commands2]" phoenix6
```

This installs everything needed to write and deploy FRC robot code in Python.

---

## Step 3: Set up the project

1. Download or clone this code folder onto your computer
2. Open a terminal and navigate to the `new_code` folder:
   ```
   cd path/to/cold_fusion/robotics_code/new_code
   ```
3. Run the setup checker to make sure everything is ready (see below):
   ```
   python setup.py
   ```

---

## Step 4: Connect the hardware

### The roboRIO (robot brain)
- The **roboRIO** is a small computer that lives on the robot. All our code runs on it.
- It connects to motors over a **CAN bus** — a single wire that daisy-chains through every motor.
- Each motor has a unique **CAN ID** (set in `constants.py`). If a motor isn't responding, check that its ID matches what's in the code.

### Motors on this robot

| Motor | CAN ID | Type | What it does |
|---|---|---|---|
| Front Left Drive | 24 | Kraken | Spins the front-left wheel |
| Front Left Steer | 23 | Falcon | Turns the front-left wheel |
| Front Right Drive | 28 | Kraken | Spins the front-right wheel |
| Front Right Steer | 27 | Falcon | Turns the front-right wheel |
| Rear Left Drive | 22 | Kraken | Spins the rear-left wheel |
| Rear Left Steer | 21 | Falcon | Turns the rear-left wheel |
| Rear Right Drive | 26 | Kraken | Spins the rear-right wheel |
| Rear Right Steer | 25 | Falcon | Turns the rear-right wheel |
| Feeder Left | 4 | Minion | Left intake wheel |
| Feeder Right | 5 | Minion | Right intake wheel |
| Conveyor | 6 | Kraken | Moves balls inside the robot |
| Elevator | 8 | Kraken | Raises/lowers the elevator |
| Kicker | 9 | Minion | Pushes ball into shooter |
| Shooter Left | 10 | Kraken | Left shooter wheel |
| Shooter Right | 11 | Kraken | Right shooter wheel (follows left) |
| Hood | 12 | Minion | Tilts shooter up/down |

### Limit switches
| Switch | DIO Port | Purpose |
|---|---|---|
| Elevator Top | 0 | Stops elevator from going too high |
| Elevator Bottom | 1 | Stops elevator from going too low |

### Wiring checklist
- [ ] All motors are connected to the CAN bus
- [ ] CAN bus is terminated (120Ω resistor at the end of the chain)
- [ ] roboRIO is powered and the green light is on
- [ ] Limit switches are connected to the correct DIO ports
- [ ] Radio is powered and configured for your team number (1279)

---

## Step 5: Connect the controllers

You need **two Xbox controllers** plugged into the **Driver Station laptop** (not the robot).

1. Plug in the **driver controller** first — it becomes **Port 0**
2. Plug in the **operator controller** second — it becomes **Port 1**
3. Open the **FRC Driver Station** software
4. Go to the **USB** tab and confirm:
   - Port 0 = Driver controller
   - Port 1 = Operator controller
5. If they're swapped, drag and drop to reorder them

### Controller layout reminder

**Driver (Port 0):**
| Input | Action |
|---|---|
| Left stick | Drive + strafe |
| Right stick X | Spin |
| Right bumper | Slow mode (hold) |
| X button | Brake (hold) |

**Operator (Port 1):**
| Input | Action |
|---|---|
| Left bumper | FIRE (hold) |
| Left stick click | LAUNCH — long range (hold) |
| Right bumper | Clear jam (hold) |
| X / B | Hood down / up |
| Y / A | Elevator up / down |
| Start / Back | Conveyor fwd / rev |
| Right stick click | Pick up ball |

---

## Step 6: Deploy code to the robot

1. **Make sure you ran `python setup.py` first** — it downloads the Python runtime and packages for the roboRIO so you don't need internet when deploying.
2. Connect your laptop to the robot's network:
   - Plug in via **USB** to the roboRIO, OR
   - Connect to the robot's **WiFi** (named something like `1279_XXXX`)
3. Open a terminal in the `new_code` folder
4. Deploy the code:
   ```
   python deploy.py
   ```
   It will run the tests, upload to the robot, and tell you what to do next.

If it says it can't find the robot:
- Make sure you're on the robot's network
- Try `ping 10.12.79.2` — if it responds, the connection is good
- Try deploying with the USB cable instead of WiFi

---

## Step 7: Run the robot

1. Open the **FRC Driver Station** on your laptop
2. Make sure it says **"Communications"** and **"Robot Code"** are green
3. Select your mode:
   - **TeleOperated** — you drive with controllers
   - **Autonomous** — robot drives itself
4. Press **Enable**
5. Drive!

### If something goes wrong
- **Robot doesn't move:** Check Driver Station — are communications and robot code both green?
- **A motor isn't working:** Check the CAN ID in `constants.py` matches the physical motor. Use Phoenix Tuner to scan the CAN bus.
- **Controller isn't responding:** Check the USB tab in Driver Station. Make sure the right controller is on the right port.
- **Robot drives weird:** Recalibrate the swerve modules. The steer encoders might have wrong offsets.

---

## Step 8: Run the tests

Tests check that the code logic is correct without needing a real robot.

```
python -m pytest tests/ -v
```

All 53 tests should pass. If any fail, something in the code was changed incorrectly.

---

## Step 9: Make changes

Want to adjust something? Here's where to look:

| I want to... | Edit this file |
|---|---|
| Change a motor speed | `constants.py` — look for the speed variables |
| Change a motor's CAN ID | `constants.py` — look for the ID variables |
| Change what a button does | `robotcontainer.py` — find the button in `_setup_operator_buttons` or `_setup_driver_buttons` |
| Change how a mechanism works | The subsystem file in `subsystems/` (e.g., `shooter.py`) |
| Add a new mechanism | Create a new file in `subsystems/`, add it to `robotcontainer.py` |

After making changes, always:
1. Run the tests: `python -m pytest tests/ -v`
2. Deploy to the robot: `python deploy.py`
3. Test on the robot with it up on blocks first!

---

## Web Control Panel

After running `python setup.py`, you can choose to open the **Web Panel** — a browser-based tool that lets you:

- **Control the robot** with on-screen joysticks, buttons, or a USB gamepad
- **Run setup, tests, and deploy** right from the browser (no terminal needed)
- **Debug NetworkTables** — see exactly what data is being sent and received
- **Check network connectivity** to the robot

You can also start the web panel directly:
```
cd web_panel
python server.py
```
Then open http://localhost:5279 in your browser.

---

## Quick reference — useful commands

| Command | What it does |
|---|---|
| `python setup.py` | Checks environment, installs packages, then offers Web Panel or deploy |
| `python deploy.py` | Checks network, runs tests, and deploys to the robot |
| `python -m pytest tests/ -v` | Runs all tests |
| `cd web_panel && python server.py` | Starts the Web Control Panel |
| `python -m robotpy sim` | Runs the robot in simulation (no real robot needed) |
