# ============================================================
# ROBOT.PY - The main entry point for the robot
# ============================================================
# This is where it all starts! When the robot turns on, this
# file runs first. It creates the RobotContainer (which sets
# up everything else) and then handles the different phases
# of an FRC match:
#
#   1. Autonomous (15 sec) -- Robot drives itself, no human input
#   2. Teleop (2+ min)     -- Drivers control the robot
#   3. Disabled             -- Robot is off, waiting
#
# The "periodic" methods run over and over (50 times per second!)
# while the robot is in that mode. That's how the robot stays
# responsive to controller inputs.
# ============================================================

import wpilib
from wpilib import DriverStation
from commands2 import CommandScheduler
from ntcore import NetworkTableInstance
from robotcontainer import RobotContainer


class Robot(wpilib.TimedRobot):
    """The main robot class. This runs the whole show."""

    def __init__(self):
        # Use a 50ms loop instead of the default 20ms.
        # CAN bus timeouts on missing/disconnected motors add ~5ms each,
        # which causes loop overruns at 20ms. 50ms gives plenty of headroom.
        super().__init__(period=0.05)

    def robotInit(self):
        """Runs once when the robot first turns on."""
        DriverStation.silenceJoystickConnectionWarning(True)
        self.container = RobotContainer()
        self.auto_command = None

        # Publish robot mode so the web panel can display it
        status_table = NetworkTableInstance.getDefault().getTable("RobotStatus")
        self._mode_pub = status_table.getStringTopic("mode").publish()
        self._match_time_pub = status_table.getDoubleTopic("match_time").publish()

    def robotPeriodic(self):
        """Runs 50 times per second, no matter what mode we're in.
        This keeps the command system running."""
        try:
            CommandScheduler.getInstance().run()
        except Exception:
            pass

        # Publish current mode and match time for the web panel
        try:
            if self.isDisabled():
                self._mode_pub.set("disabled")
            elif self.isAutonomous():
                self._mode_pub.set("auto")
            elif self.isTeleop():
                self._mode_pub.set("teleop")
            elif self.isTest():
                self._mode_pub.set("test")
            self._match_time_pub.set(DriverStation.getMatchTime())
        except Exception:
            pass

    # --- AUTONOMOUS MODE ---
    # The robot drives itself using pre-programmed routines

    def autonomousInit(self):
        """Runs once when autonomous mode starts."""
        self.auto_command = self.container.get_autonomous_command()
        if self.auto_command is not None:
            self.auto_command.schedule()

    def autonomousExit(self):
        """Runs once when autonomous mode ends."""
        if self.auto_command is not None:
            self.auto_command.cancel()

    # --- TELEOP MODE ---
    # Human drivers control the robot with Xbox controllers

    def teleopInit(self):
        """Runs once when teleop (driver control) mode starts."""
        # If autonomous was running, stop it so the driver takes over
        if self.auto_command is not None:
            self.auto_command.cancel()

    # --- DISABLED MODE ---
    # Robot is powered on but not moving (between matches, etc.)

    def disabledPeriodic(self):
        """Runs while the robot is disabled. We don't do anything here."""
        pass


# ============================================================
# To run this robot code, use one of these commands:
#   Simulate:  python -m robotpy sim
#   Deploy:    python -m robotpy deploy
# ============================================================
