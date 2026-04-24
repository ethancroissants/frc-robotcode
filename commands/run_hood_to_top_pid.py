from commands2 import Command

from subsystems.operator_subsystem import OperatorSubsystem


class RunHoodToTopPID(Command):
    def __init__(self, operator: OperatorSubsystem):
        super().__init__()
        self.operatorSubsystem = operator

        self.startPosition = 0.0
        self.position0 = 55.0  # The position we want the hood motor to stop at for shooting
        self.rotationRate = 0.5  # Speed at which the hood motor will rotate
        self.rotationdir = 0.0

        self.addRequirements(self.operatorSubsystem)

    def initialize(self):
        self.startPosition = self.operatorSubsystem.getHoodMotorPosition()
        if self.startPosition < self.position0:
            self.rotationdir = 1
        elif self.startPosition > self.position0:
            self.rotationdir = -1
        else:
            self.rotationdir = 0.0

        self.operatorSubsystem.rotateHoodMotor(self.rotationdir * self.rotationRate)

    def execute(self):
        currPosition = self.operatorSubsystem.getHoodMotorPosition()
        print(f"{currPosition}--{self.position0}")
        if self.rotationdir > 0 and self.operatorSubsystem.getHoodMotorPosition() >= self.position0:
            self.operatorSubsystem.stopElevator()
        elif self.rotationdir < 0 and self.operatorSubsystem.getHoodMotorPosition() <= self.position0:
            self.operatorSubsystem.stopElevator()

    def cancel(self):
        self.operatorSubsystem.stopElevator()
        print("Elevator CANCELED")

    def end(self, interrupted: bool):
        self.operatorSubsystem.stopElevator()
        print("================================")
        print(f"Finishing Position: {self.operatorSubsystem.getHoodMotorPosition()}")
        print("================================")

    def isFinished(self) -> bool:
        return False
