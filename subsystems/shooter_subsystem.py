"""Shooter subsystem (mostly stubbed in the Java version)."""

from commands2 import SubsystemBase
from phoenix6.configs import Slot0Configs, TalonFXConfiguration


class ShooterSubsystem(SubsystemBase):
    SHOOTER_SPEED = 1.0

    def __init__(self):
        super().__init__()
        self.shooterMotorConfig = TalonFXConfiguration()
        self.slot0Configs = Slot0Configs()

    def isAtSpeed(self) -> bool:
        # Simplified: Assume instant readiness or check velocity sensor
        return True

    def fire(self):
        print("Firing!")

    def stopShooter(self):
        pass
