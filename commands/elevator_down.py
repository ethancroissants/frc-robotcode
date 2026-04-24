from commands2 import Command
from wpilib import Timer

from subsystems.elevator_subsystem import ElevatorSubsystem


class ElevatorDown(Command):
    def __init__(self, elevator: ElevatorSubsystem):
        super().__init__()
        self.elevatorSubsystem = elevator
        self.m_timer = Timer()
        self.addRequirements(self.elevatorSubsystem)

    def initialize(self):
        self.m_timer.reset()
        self.m_timer.start()

    def execute(self):
        self.elevatorSubsystem.elevatorDown()

    def cancel(self):
        self.elevatorSubsystem.stopElevator()

    def end(self, interrupted: bool):
        self.elevatorSubsystem.stopElevator()

    def isFinished(self) -> bool:
        return False
