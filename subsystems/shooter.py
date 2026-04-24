# ============================================================
# SHOOTER - Launches game pieces (balls) at targets
# ============================================================
# The shooter system has three parts that work together:
#   1. Shooter wheels -- spin really fast to launch the ball
#   2. Kicker wheel   -- pushes the ball into the shooter wheels
#   3. Conveyor belt   -- moves balls from storage to the kicker
#
# Think of it like a pitching machine at a batting cage:
# the conveyor feeds balls in, the kicker pushes them forward,
# and the spinning wheels launch them out.
# ============================================================

from commands2 import SubsystemBase
from phoenix6.hardware import TalonFX, TalonFXS
from phoenix6.controls import DutyCycleOut, Follower, VelocityVoltage
from phoenix6.configs import Slot0Configs
from phoenix6.signals import MotorAlignmentValue
import constants


class Shooter(SubsystemBase):
    """Controls the shooter wheels, kicker, and conveyor."""

    def __init__(self):
        super().__init__()

        # --- Shooter wheels (two big wheels that spin to launch balls) ---
        self.shooter_left = TalonFX(constants.SHOOTER_LEFT_ID)
        self.shooter_right = TalonFX(constants.SHOOTER_RIGHT_ID)

        # The right motor follows the left one automatically (they spin together)
        try:
            self.shooter_right.set_control(Follower(constants.SHOOTER_LEFT_ID, MotorAlignmentValue.ALIGNED))
        except Exception:
            pass

        # Set up PID so the shooter spins at a precise speed
        try:
            pid_config = Slot0Configs()
            pid_config.k_p = constants.SHOOTER_P
            pid_config.k_i = constants.SHOOTER_I
            pid_config.k_d = constants.SHOOTER_D
            pid_config.k_v = constants.SHOOTER_V
            self.shooter_left.configurator.apply(pid_config)
        except Exception:
            pass

        # Velocity control: tells the motor to spin at an exact speed
        self.velocity_request = VelocityVoltage(0).with_slot(0)

        # --- Kicker (small wheel that pushes ball into shooter) ---
        self.kicker = TalonFXS(constants.KICKER_ID)

        # --- Conveyor (belt that moves balls toward the shooter) ---
        self.conveyor = TalonFX(constants.CONVEYOR_ID)

        # Simple speed control for kicker and conveyor
        self.speed_control = DutyCycleOut(0)

    # ---- SHOOTER CONTROLS ----

    def spin_up(self):
        """Start the shooter wheels spinning (for close-range shots)."""
        try:
            self.shooter_left.set_control(
                self.velocity_request.with_velocity(constants.SHOOTER_CLOSE_VELOCITY)
            )
        except Exception:
            pass

    def spin_up_far(self):
        """Start the shooter wheels spinning faster (for long-range shots)."""
        try:
            self.shooter_left.set_control(
                self.velocity_request.with_velocity(constants.SHOOTER_FAR_VELOCITY)
            )
        except Exception:
            pass

    def stop_shooter(self):
        """Stop the shooter wheels."""
        try:
            self.shooter_left.set(0)
        except Exception:
            pass

    # ---- KICKER CONTROLS ----

    def kicker_forward(self):
        """Push a ball into the shooter."""
        try:
            self.kicker.set(constants.KICKER_SPEED)
        except Exception:
            pass

    def kicker_reverse(self):
        """Push a ball backward (unjam)."""
        try:
            self.kicker.set(-constants.KICKER_SPEED)
        except Exception:
            pass

    def stop_kicker(self):
        """Stop the kicker."""
        try:
            self.kicker.stop_motor()
        except Exception:
            pass

    # ---- CONVEYOR CONTROLS ----

    def conveyor_forward(self):
        """Move balls toward the shooter."""
        try:
            self.conveyor.set(-constants.CONVEYOR_SPEED)
        except Exception:
            pass

    def conveyor_reverse(self):
        """Move balls away from the shooter (unjam)."""
        try:
            self.conveyor.set(constants.CONVEYOR_SPEED)
        except Exception:
            pass

    def stop_conveyor(self):
        """Stop the conveyor."""
        try:
            self.conveyor.stop_motor()
        except Exception:
            pass

    # ---- COMBINED ACTIONS ----

    def fire(self):
        """Do everything needed to shoot: spin up, kick, and convey."""
        self.spin_up()
        self.kicker_forward()
        self.conveyor_forward()

    def launch(self):
        """Same as fire, but for long-range shots."""
        self.spin_up_far()
        self.kicker_forward()
        self.conveyor_forward()

    def cease_fire(self):
        """Stop everything related to shooting."""
        self.stop_shooter()
        self.stop_kicker()
        self.stop_conveyor()

    def clear_out(self):
        """Reverse everything to clear a jammed ball."""
        try:
            self.shooter_left.set(constants.SHOOTER_SPEED)
        except Exception:
            pass
        self.kicker_reverse()
        self.conveyor_reverse()

    def get_velocity(self):
        """Read the shooter wheel velocity (rotations per second)."""
        try:
            return self.shooter_left.get_velocity().value_as_double
        except Exception:
            return 0.0
