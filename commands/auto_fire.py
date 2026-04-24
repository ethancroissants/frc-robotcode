from commands2 import Command
from wpilib import Timer

from subsystems.operator_subsystem import OperatorSubsystem


class AutoFire(Command):
    def __init__(self, operator: OperatorSubsystem):
        super().__init__()
        self.operatorSubsystem = operator
        self.m_timer = Timer()
        self.addRequirements(self.operatorSubsystem)

    def initialize(self):
        self.m_timer.reset()
        self.m_timer.start()

    def execute(self):
        if self.m_timer.get() < 0.7:
            # Spin up the shooter before running the kicker and conveyor
            self.operatorSubsystem.shooterOut()
        else:
            self.operatorSubsystem.FIRE()

    def cancel(self):
        self.operatorSubsystem.ceaseFire()

    def end(self, interrupted: bool):
        self.operatorSubsystem.ceaseFire()

    def isFinished(self) -> bool:
        return self.m_timer.get() > 4.0
