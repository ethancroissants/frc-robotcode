# ============================================================
# ELEVATOR - Moves a platform up and down
# ============================================================
# The elevator is like a small lift inside the robot. It raises
# and lowers mechanisms to reach different heights -- for example,
# scoring game pieces at different levels on the field.
#
# It has limit switches at the top and bottom that act like
# bumpers: they tell the robot "stop, you've gone far enough!"
# so the elevator doesn't break itself.
# ============================================================

from commands2 import SubsystemBase
from phoenix6.hardware import TalonFX
from wpilib import DigitalInput
import constants


class Elevator(SubsystemBase):
    """Controls the elevator that raises and lowers mechanisms."""

    def __init__(self):
        super().__init__()

        self.motor = TalonFX(constants.ELEVATOR_ID)

        # Limit switches: physical buttons that get pressed at the top and bottom
        self.top_switch = DigitalInput(constants.ELEVATOR_TOP_SWITCH)
        self.bottom_switch = DigitalInput(constants.ELEVATOR_BOTTOM_SWITCH)

    def go_up(self):
        """Move the elevator up (stops automatically if it hits the top)."""
        if self.is_at_top():
            self.stop()
        else:
            try:
                self.motor.set(-constants.ELEVATOR_SPEED)
            except Exception:
                pass

    def go_down(self):
        """Move the elevator down (stops automatically if it hits the bottom)."""
        if self.is_at_bottom():
            self.stop()
        else:
            try:
                self.motor.set(constants.ELEVATOR_SPEED)
            except Exception:
                pass

    def stop(self):
        """Stop the elevator."""
        try:
            self.motor.stop_motor()
        except Exception:
            pass

    def is_at_top(self):
        """Check if the elevator has reached the top limit switch."""
        return self.top_switch.get()

    def is_at_bottom(self):
        """Check if the elevator has reached the bottom limit switch."""
        return self.bottom_switch.get()

    def get_position(self):
        """Read the elevator's current height (in encoder ticks)."""
        try:
            return self.motor.get_position().value_as_double
        except Exception:
            return 0.0

    def go_to_position(self, target):
        """Move the elevator toward a target position (in encoder ticks)."""
        current = self.get_position()
        if abs(current - target) < 2.0:
            self.stop()
        elif current < target:
            self.go_up()
        else:
            self.go_down()
