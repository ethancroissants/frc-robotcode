# ============================================================
# HOOD - Tilts the shooter up and down to aim
# ============================================================
# The hood is a movable flap on top of the shooter. By tilting
# it up or down, we change the angle that balls fly out at.
#
# Tilted up   = ball goes higher and farther
# Tilted down = ball goes lower and shorter
#
# It's like adjusting the angle of a cannon.
# ============================================================

from commands2 import SubsystemBase
from phoenix6.hardware import TalonFXS
import constants


class Hood(SubsystemBase):
    """Controls the hood that aims the shooter up and down."""

    def __init__(self):
        super().__init__()

        self.motor = TalonFXS(constants.HOOD_ID)

    def tilt_up(self):
        """Tilt the hood upward (shoot farther)."""
        try:
            self.motor.set(constants.HOOD_SPEED)
        except Exception:
            pass

    def tilt_down(self):
        """Tilt the hood downward (shoot shorter)."""
        try:
            self.motor.set(-constants.HOOD_SPEED)
        except Exception:
            pass

    def stop(self):
        """Stop moving the hood."""
        try:
            self.motor.stop_motor()
        except Exception:
            pass

    def get_position(self):
        """Read where the hood is currently pointing."""
        try:
            return round(self.motor.get_position().value_as_double, 1)
        except Exception:
            return 0.0
