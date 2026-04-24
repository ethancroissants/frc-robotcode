from commands2 import Command

from subsystems.elevator_subsystem import ElevatorSubsystem


class RunElevatorToTopPID(Command):
    def __init__(self, elevator: ElevatorSubsystem):
        super().__init__()
        self.elevatorSubsystem = elevator

        self.startPosition = 0.0
        self.position0 = 55.0  # The position we want the elevator motor to stop at for climbing
        self.rotationRate = 0.5  # Speed at which the elevator motor will rotate
        self.rotationdir = 0.0

        self.addRequirements(self.elevatorSubsystem)

    def initialize(self):
        self.startPosition = self.elevatorSubsystem.getElevatorMotorPosition()
        if self.startPosition < self.position0:
            self.rotationdir = 1
        elif self.startPosition > self.position0:
            self.rotationdir = -1
        else:
            self.rotationdir = 0.0

        self.elevatorSubsystem.rotateElevatorMotors(self.rotationdir * self.rotationRate)

    def execute(self):
        currPosition = self.elevatorSubsystem.getElevatorMotorPosition()
        print(f"{currPosition}--{self.position0}")
        if self.rotationdir > 0 and self.elevatorSubsystem.getElevatorMotorPosition() >= self.position0:
            self.elevatorSubsystem.stopElevator()
        elif self.rotationdir < 0 and self.elevatorSubsystem.getElevatorMotorPosition() <= self.position0:
            self.elevatorSubsystem.stopElevator()

    def cancel(self):
        self.elevatorSubsystem.stopElevator()
        print("Elevator CANCELED")

    def end(self, interrupted: bool):
        self.elevatorSubsystem.stopElevator()
        print("================================")
        print(f"Finishing Position: {self.elevatorSubsystem.getElevatorMotorPosition()}")
        print("================================")

    def isFinished(self) -> bool:
        return False
