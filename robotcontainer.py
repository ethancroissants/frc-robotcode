# ============================================================
# ROBOT CONTAINER - Wires everything together
# ============================================================
# This file connects the controllers (Xbox gamepads) to the
# robot's subsystems. It's like a switchboard:
#   "When the driver presses THIS button, do THAT action."
#
# We use TWO controllers:
#   Driver   -- controls driving around the field
#   Operator -- controls the shooter, feeder, hood, and elevator
# ============================================================

from commands2 import cmd
from commands2.button import CommandXboxController, Trigger
import constants
from subsystems.drivetrain import Drivetrain
from subsystems.shooter import Shooter
from subsystems.feeder import Feeder
from subsystems.hood import Hood
from subsystems.elevator import Elevator
from subsystems.web_control import WebControl


class RobotContainer:
    """Sets up all subsystems and maps controller buttons to actions."""

    def __init__(self):
        # --- Create the two Xbox controllers ---
        self.driver = CommandXboxController(constants.DRIVER_GAMEPAD_PORT)
        self.operator = CommandXboxController(constants.OPERATOR_GAMEPAD_PORT)

        # --- Create all subsystems ---
        self.drivetrain = Drivetrain()
        self.shooter = Shooter()
        self.feeder = Feeder()
        self.hood = Hood()
        self.elevator = Elevator()

        # --- Web Control Panel (receives commands via NetworkTables) ---
        self.web_control = WebControl(
            self.drivetrain, self.shooter, self.feeder, self.hood, self.elevator
        )

        # --- Set up default behaviors ---
        # The drivetrain always listens to the driver's joysticks
        # using field-centric driving (forward is always downfield).
        # Deadzone is applied inside drivetrain.drive().
        self.drivetrain.setDefaultCommand(
            cmd.run(
                lambda: self.drivetrain.drive(
                    -self.driver.getLeftY(),    # Forward/backward (Y axis is inverted)
                    -self.driver.getLeftX(),    # Left/right strafe
                    -self.driver.getRightX(),   # Spin left/right
                ),
                self.drivetrain,
            )
        )

        # --- Map all the buttons ---
        self._setup_driver_buttons()
        self._setup_operator_buttons()

    def _setup_driver_buttons(self):
        """Set up the DRIVER controller buttons (driving-related)."""

        # Right bumper: hold to drive slowly (for precise alignment)
        self.driver.rightBumper().onTrue(
            cmd.runOnce(lambda: self.drivetrain.set_slow_mode(True), self.drivetrain)
        )
        self.driver.rightBumper().onFalse(
            cmd.runOnce(lambda: self.drivetrain.set_slow_mode(False), self.drivetrain)
        )

        # X button: hold to brake (lock wheels in X pattern)
        self.driver.x().whileTrue(
            cmd.run(lambda: self.drivetrain.brake(), self.drivetrain)
        )

        # Left bumper: reset field-centric heading
        # (makes the current facing direction the new "forward")
        self.driver.leftBumper().onTrue(
            cmd.runOnce(lambda: self.drivetrain.reset_heading(), self.drivetrain)
        )

    def _setup_operator_buttons(self):
        """Set up the OPERATOR controller buttons (mechanisms)."""

        # --- HOOD (aiming up/down) ---
        # X = tilt hood down, B = tilt hood up
        self.operator.x().whileTrue(
            cmd.run(lambda: self.hood.tilt_down(), self.hood)
        ).onFalse(
            cmd.runOnce(lambda: self.hood.stop(), self.hood)
        )

        self.operator.b().whileTrue(
            cmd.run(lambda: self.hood.tilt_up(), self.hood)
        ).onFalse(
            cmd.runOnce(lambda: self.hood.stop(), self.hood)
        )

        # --- ELEVATOR ---
        # Y = elevator to top position (like old RunElevatorToTopPID)
        # A = elevator down
        self.operator.y().whileTrue(
            cmd.run(
                lambda: self.elevator.go_to_position(constants.ELEVATOR_LEVEL_3),
                self.elevator,
            )
        ).onFalse(
            cmd.runOnce(lambda: self.elevator.stop(), self.elevator)
        )

        self.operator.a().whileTrue(
            cmd.run(lambda: self.elevator.go_down(), self.elevator)
        ).onFalse(
            cmd.runOnce(lambda: self.elevator.stop(), self.elevator)
        )

        # --- SHOOTER ---
        # Left bumper: FIRE! (spins up shooter, then kicks ball in)
        # The sequence: spin up for 0.7 seconds, then fire everything
        self.operator.leftBumper().whileTrue(
            cmd.run(lambda: self.shooter.spin_up(), self.shooter)
                .withTimeout(0.7)
                .andThen(cmd.run(lambda: self.shooter.fire(), self.shooter))
        ).onFalse(
            cmd.runOnce(lambda: self.shooter.cease_fire(), self.shooter)
        )

        # Right bumper: reverse everything (clear a jam)
        self.operator.rightBumper().whileTrue(
            cmd.run(lambda: self.shooter.clear_out(), self.shooter)
        ).onFalse(
            cmd.runOnce(lambda: self.shooter.cease_fire(), self.shooter)
        )

        # Left stick button: LAUNCH (long-range shot)
        self.operator.leftStick().whileTrue(
            cmd.run(lambda: self.shooter.launch(), self.shooter)
        ).onFalse(
            cmd.runOnce(lambda: self.shooter.cease_fire(), self.shooter)
        )

        # --- CONVEYOR ---
        # Start = conveyor forward, Back = conveyor reverse
        self.operator.start().whileTrue(
            cmd.run(lambda: self.shooter.conveyor_forward(), self.shooter)
        ).onFalse(
            cmd.runOnce(lambda: self.shooter.stop_conveyor(), self.shooter)
        )

        self.operator.back().whileTrue(
            cmd.run(lambda: self.shooter.conveyor_reverse(), self.shooter)
        ).onFalse(
            cmd.runOnce(lambda: self.shooter.stop_conveyor(), self.shooter)
        )

        # --- FEEDER (ball intake) ---
        # Right stick button: pick up balls from the ground
        self.operator.rightStick().whileTrue(
            cmd.run(lambda: self.feeder.intake(), self.feeder)
        ).onFalse(
            cmd.runOnce(lambda: self.feeder.stop(), self.feeder)
        )

    def get_autonomous_command(self):
        """Return the command to run during the autonomous period."""
        # For now, just do nothing. Teams add PathPlanner autos here later.
        return cmd.none()
