from commands2 import Command
from wpilib import Timer

from subsystems.operator_subsystem import OperatorSubsystem


class POVPressed(Command):
    def __init__(self, operator: OperatorSubsystem):
        super().__init__()
        self.m_timer = Timer()

    def initialize(self):
        self.m_timer.reset()
        self.m_timer.start()

    def execute(self):
        # .getPOV() returns an int; -1 if nothing is pressed, otherwise:
        #   up: 0, topRight: 45, right: 90, bottomRight: 135,
        #   bottom: 180, bottomLeft: 225, left: 270, topLeft: 315
        # Get POV value and call command based on value.
        pass

    def cancel(self):
        pass

    def end(self, interrupted: bool):
        pass

    def isFinished(self) -> bool:
        return False
