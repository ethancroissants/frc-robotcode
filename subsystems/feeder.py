# ============================================================
# FEEDER - Picks up game pieces (balls) from the ground
# ============================================================
# The feeder is a pair of spinning wheels at the front of the
# robot that grab balls off the floor and pull them inside.
# Think of it like a vacuum cleaner -- it sucks things in.
#
# There are two wheels that spin in OPPOSITE directions so
# they both pull the ball inward at the same time.
# ============================================================

from commands2 import SubsystemBase
from phoenix6.hardware import TalonFXS
from phoenix6.controls import DutyCycleOut
import constants


class Feeder(SubsystemBase):
    """Controls the intake wheels that pick up balls from the ground."""

    def __init__(self):
        super().__init__()

        self.left_wheel = TalonFXS(constants.FEEDER_LEFT_ID)
        self.right_wheel = TalonFXS(constants.FEEDER_RIGHT_ID)
        self.speed_control = DutyCycleOut(0)

    def intake(self):
        """Spin the wheels inward to pick up a ball."""
        try:
            self.left_wheel.set(constants.FEEDER_SPEED)
        except Exception:
            pass
        try:
            self.right_wheel.set(-constants.FEEDER_SPEED)  # Opposite direction!
        except Exception:
            pass

    def eject(self):
        """Spin the wheels outward to spit a ball out."""
        try:
            self.left_wheel.set(-constants.FEEDER_SPEED)
        except Exception:
            pass
        try:
            self.right_wheel.set(constants.FEEDER_SPEED)
        except Exception:
            pass

    def stop(self):
        """Stop the feeder wheels."""
        try:
            self.left_wheel.stop_motor()
        except Exception:
            pass
        try:
            self.right_wheel.stop_motor()
        except Exception:
            pass
