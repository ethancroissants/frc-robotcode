"""Elevator subsystem."""

from commands2 import SubsystemBase

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


class ElevatorSubsystem(SubsystemBase):
    def __init__(self):
        super().__init__()

    def periodic(self) -> None:
        pass

    def elevatorUp(self):
        if motorcontrollers.TopElevatorLimitSwitch.get():
            motorcontrollers.ElevatorMotor.set(-0.5)
        else:
            self.stopElevator()
            motorcontrollers.ElevatorMotor.set(0.0)

    def elevatorDown(self):
        if motorcontrollers.BottomElevatorLimitSwitch.get():
            motorcontrollers.ElevatorMotor.set(0.5)
        else:
            self.stopElevator()
            motorcontrollers.ElevatorMotor.set(0.0)

    def stopElevator(self):
        motorcontrollers.ElevatorMotor.stopMotor()

    def ElevatorExtend(self):
        motorcontrollers.ElevatorMotor.set(0.5)

    def ElevatorRetract(self):
        motorcontrollers.ElevatorMotor.set(-0.5)

    def zeroElevatorMotor(self):
        motorcontrollers.ElevatorMotor.set_position(0)

    def getElevatorMotorPosition(self) -> float:
        return _round(motorcontrollers.ElevatorMotor.get_position().value_as_double, 1)

    def rotateElevatorMotors(self, rotRate: float):
        motorcontrollers.ElevatorMotor.set(rotRate * -1.0)

    def getTopElevatorLimitSwitch(self) -> bool:
        return motorcontrollers.TopElevatorLimitSwitch.get()

    def getBottomElevatorLimitSwitch(self) -> bool:
        return motorcontrollers.BottomElevatorLimitSwitch.get()
