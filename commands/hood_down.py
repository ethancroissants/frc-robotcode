from commands2 import Command
from wpilib import Timer

from subsystems.operator_subsystem import OperatorSubsystem


class HoodDown(Command):
    def __init__(self, operator: OperatorSubsystem):
        super().__init__()
        self.operatorSubsystem = operator
        self.m_timer = Timer()
        self.addRequirements(self.operatorSubsystem)

    def initialize(self):
        self.m_timer.reset()
        self.m_timer.start()

    def execute(self):
        self.operatorSubsystem.hoodDown()

    def cancel(self):
        self.operatorSubsystem.stopHood()

    def end(self, interrupted: bool):
        self.operatorSubsystem.stopHood()

    def isFinished(self) -> bool:
        return False
