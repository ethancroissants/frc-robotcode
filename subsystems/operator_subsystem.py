"""Operator subsystem: shooter, kicker, conveyor, feeder, hood, wrist and test motor."""

import math

from commands2 import SubsystemBase
from phoenix6.configs import Slot0Configs, TalonFXConfiguration
from phoenix6.controls import DutyCycleOut, Follower, PositionVoltage, VelocityVoltage
from phoenix6.signals import MotorAlignmentValue

import constants
import motorcontrollers


def _round(value: float, decimal_places: int) -> float:
    if decimal_places < 0 or decimal_places > 9:
        raise ValueError("The specified decimalPlaces must be between 0 and 9 (inclusive).")
    scale = 10 ** decimal_places
    scaled_up = value * scale
    dec = scaled_up % 1.0
    fixed_dec = round(dec * 10) / 10.0
    new_value = scaled_up + fixed_dec
    return round(new_value) / scale


class OperatorSubsystem(SubsystemBase):
    # Shooter Max speed
    SHOOTER_SPEED = 1.0

    def __init__(self):
        super().__init__()
        self.slot0Configs = Slot0Configs()
        self.m_request = VelocityVoltage(0).with_slot(0)
        self.configs = TalonFXConfiguration()

        # Switch which control request to use based on a button press
        self.m_positionVoltage = PositionVoltage(0)
        self.feederStatus = False

        # Open-loop control request (percent output)
        self.dutyCycle = DutyCycleOut(0)

        motorcontrollers.Shooter2Motor.set_control(
            Follower(10, MotorAlignmentValue.ALIGNED)
        )

        self.slot0Configs.k_p = 0.55
        self.slot0Configs.k_i = 0.05
        self.slot0Configs.k_d = 0.0
        self.slot0Configs.k_v = 0.12

        motorcontrollers.Shooter1Motor.configurator.apply(self.slot0Configs)

    def periodic(self) -> None:
        # This method will be called once per scheduler run
        pass

    # START Feeder methods
    def feederIn(self):
        motorcontrollers.Feeder1Motor.set(constants.MotorSpeeds.FEEDER)  # CCW
        motorcontrollers.Feeder2Motor.set(-1 * constants.MotorSpeeds.FEEDER)  # CW

    def feederOut(self):
        motorcontrollers.Feeder1Motor.set(-1 * constants.MotorSpeeds.FEEDER)  # CW
        motorcontrollers.Feeder2Motor.set(constants.MotorSpeeds.FEEDER)  # CCW

    def stopFeeder(self):
        motorcontrollers.Feeder1Motor.stopMotor()
        motorcontrollers.Feeder2Motor.stopMotor()

    # END Feeder methods

    # START Shooter methods
    def FIRE(self):
        self.shooterOut()
        self.kickerIn()
        self.conveyorFwd()

    def LAUNCH(self):
        self.farShooterOut()
        self.kickerIn()
        self.conveyorFwd()

    def ceaseFire(self):
        self.stopKicker()
        self.stopConveyor()
        self.stopShooter()

    def shooterIn(self):
        motorcontrollers.Shooter1Motor.set(constants.MotorSpeeds.SHOOTER)  # CCW

    def shooterOut(self):
        motorcontrollers.Shooter1Motor.set_control(self.m_request.with_velocity(-39))  # CW

    def farShooterOut(self):
        motorcontrollers.Shooter1Motor.set_control(self.m_request.with_velocity(-60))  # CW

    def stopShooter(self):
        motorcontrollers.Shooter1Motor.set(0)

    def isAtSpeed(self) -> bool:
        # Simplified: Assume instant readiness or check velocity sensor
        return True

    # END Shooter methods

    # START Kicker methods
    def kickerIn(self):
        motorcontrollers.KickerMotor.set(constants.MotorSpeeds.KICKER)  # CCW

    def kickerOut(self):
        motorcontrollers.KickerMotor.set(-1 * constants.MotorSpeeds.KICKER)  # CW

    def stopKicker(self):
        motorcontrollers.KickerMotor.stopMotor()

    # END Kicker methods

    # START Carousel methods
    def conveyorFwd(self):
        motorcontrollers.ConveyorMotor.set(-1 * constants.MotorSpeeds.CONVEYOR)  # CW

    def conveyorRev(self):
        motorcontrollers.ConveyorMotor.set(constants.MotorSpeeds.CONVEYOR)  # CCW

    def stopConveyor(self):
        motorcontrollers.ConveyorMotor.stopMotor()

    # END Carousel methods

    # START Climber methods
    def elevatorUp(self):
        motorcontrollers.ElevatorMotor.set(-1 * constants.MotorSpeeds.ELEVATOR)

    def elevatorDown(self):
        motorcontrollers.ElevatorMotor.set(constants.MotorSpeeds.ELEVATOR)

    def stopElevator(self):
        motorcontrollers.ElevatorMotor.stopMotor()

    # END Climber methods

    # START Hood methods
    def hoodUp(self):
        motorcontrollers.HoodMotor.set(constants.MotorSpeeds.HOOD)  # CCW

    def hoodDown(self):
        motorcontrollers.HoodMotor.set(-1 * constants.MotorSpeeds.HOOD)  # CW

    def stopHood(self):
        motorcontrollers.HoodMotor.stopMotor()

    def getHoodMotorPosition(self) -> float:
        return _round(motorcontrollers.HoodMotor.get_position().value_as_double, 1)

    def rotateHoodMotor(self, rotRate: float):
        motorcontrollers.HoodMotor.set(rotRate * -1.0)

    # END Hood methods

    # START Wrist methods
    def wristUp(self):
        if self.limitSwitchForWristTop():
            motorcontrollers.WristMotor.stopMotor()
        else:
            motorcontrollers.WristMotor.set(-1.0)

    def wristDown(self):
        if self.limitSwitchForWristBottom():
            motorcontrollers.WristMotor.stopMotor()
        else:
            motorcontrollers.WristMotor.set(1.0)

    def stopWrist(self):
        motorcontrollers.WristMotor.stopMotor()

    # END Wrist methods

    # Test motor
    def runTestMotorFwd(self):
        motorcontrollers.TestMotor.set_control(self.dutyCycle.with_output(0.5))

    def runTestMotorRev(self):
        motorcontrollers.TestMotor.set_control(self.dutyCycle.with_output(-0.5))

    def stopTestMotor(self):
        motorcontrollers.TestMotor.stopMotor()
        motorcontrollers.TestMotor.set_control(self.dutyCycle.with_output(0.0))

    def configTestMotor(self):
        # Make sure we start at 0
        motorcontrollers.TestMotor.set_position(0)

    def getTestMotorPosition(self) -> float:
        return _round(motorcontrollers.TestMotor.get_position().value_as_double, 1)

    def rotateTestMotor(self, rotRate: float):
        motorcontrollers.TestMotor.set(rotRate)

    def limitSwitchForWristTop(self) -> bool:
        return motorcontrollers.WristTopLimitSwitch.get()

    def limitSwitchForWristBottom(self) -> bool:
        return motorcontrollers.WristBottomLimitSwitch.get()
