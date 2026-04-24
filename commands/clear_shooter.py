from commands2 import Command
from wpilib import Timer

from subsystems.operator_subsystem import OperatorSubsystem


class ClearShooter(Command):
    def __init__(self, operator: OperatorSubsystem):
        super().__init__()
        self.operatorSubsystem = operator
        self.m_timer = Timer()
        self.addRequirements(self.operatorSubsystem)

    def initialize(self):
        self.m_timer.reset()
        self.m_timer.start()
        self.operatorSubsystem.feederStatus = False

    def execute(self):
        self.operatorSubsystem.shooterIn()
        self.operatorSubsystem.feederIn()
        self.operatorSubsystem.conveyorRev()

    def cancel(self):
        self.operatorSubsystem.stopShooter()
        self.operatorSubsystem.stopFeeder()
        self.operatorSubsystem.stopConveyor()

    def end(self, interrupted: bool):
        self.operatorSubsystem.stopShooter()
        self.operatorSubsystem.stopFeeder()
        self.operatorSubsystem.stopConveyor()

    def isFinished(self) -> bool:
        return False
