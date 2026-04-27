"""Operator subsystem: shooter, kicker, conveyor, feeder, hood, wrist and test motor."""

import math

from commands2 import SubsystemBase
from phoenix6.controls import DutyCycleOut, Follower, PositionVoltage, VelocityVoltage
from phoenix6.signals import MotorAlignmentValue

import motorcontrollers
import tunables


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
        self.m_request = VelocityVoltage(0).with_slot(0)

        # Switch which control request to use based on a button press
        self.m_positionVoltage = PositionVoltage(0)
        self.feederStatus = False

        # Open-loop control request (percent output)
        self.dutyCycle = DutyCycleOut(0)

        # Slot0 gains are baked into tuner_constants.kShooterInitialConfigs so they survive
        # the full-config apply in Robot.teleopInit().
        motorcontrollers.Shooter2Motor.set_control(
            Follower(10, MotorAlignmentValue.ALIGNED)
        )

    def periodic(self) -> None:
        # This method will be called once per scheduler run
        pass

    # START Feeder methods
    def feederIn(self):
        speed = tunables.feeder_speed()
        motorcontrollers.Feeder1Motor.set(speed)  # CCW
        motorcontrollers.Feeder2Motor.set(-speed)  # CW

    def feederOut(self):
        speed = tunables.feeder_speed()
        motorcontrollers.Feeder1Motor.set(-speed)  # CW
        motorcontrollers.Feeder2Motor.set(speed)  # CCW

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
        motorcontrollers.Shooter1Motor.set(tunables.shooter_open_speed())  # CCW

    def shooterOut(self):
        motorcontrollers.Shooter1Motor.set_control(
            self.m_request.with_velocity(-tunables.shooter_near_velocity())
        )  # CW

    def farShooterOut(self):
        motorcontrollers.Shooter1Motor.set_control(
            self.m_request.with_velocity(-tunables.shooter_far_velocity())
        )  # CW

    def stopShooter(self):
        # Drive the velocity PID to 0 rps so the wheel actively brakes instead of coasting
        # down from ~5700 rpm.
        motorcontrollers.Shooter1Motor.set_control(self.m_request.with_velocity(0))

    def isAtSpeed(self) -> bool:
        # Simplified: Assume instant readiness or check velocity sensor
        return True

    # END Shooter methods

    # START Kicker methods
    def kickerIn(self):
        motorcontrollers.KickerMotor.set(tunables.kicker_speed())  # CCW

    def kickerOut(self):
        motorcontrollers.KickerMotor.set(-tunables.kicker_speed())  # CW

    def stopKicker(self):
        motorcontrollers.KickerMotor.stopMotor()

    # END Kicker methods

    # START Carousel methods
    def conveyorFwd(self):
        motorcontrollers.ConveyorMotor.set(-tunables.conveyor_speed())  # CW

    def conveyorRev(self):
        motorcontrollers.ConveyorMotor.set(tunables.conveyor_speed())  # CCW

    def stopConveyor(self):
        motorcontrollers.ConveyorMotor.stopMotor()

    # END Carousel methods

    # START Climber methods
    def elevatorUp(self):
        motorcontrollers.ElevatorMotor.set(-tunables.elevator_speed())

    def elevatorDown(self):
        motorcontrollers.ElevatorMotor.set(tunables.elevator_speed())

    def stopElevator(self):
        motorcontrollers.ElevatorMotor.stopMotor()

    # END Climber methods

    # START Hood methods
    def hoodUp(self):
        motorcontrollers.HoodMotor.set(tunables.hood_speed())  # CCW

    def hoodDown(self):
        motorcontrollers.HoodMotor.set(-tunables.hood_speed())  # CW

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
