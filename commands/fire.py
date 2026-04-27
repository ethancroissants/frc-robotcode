from commands2 import Command
from wpilib import Timer

import tunables
from subsystems.operator_subsystem import OperatorSubsystem


class Fire(Command):
    def __init__(self, operator: OperatorSubsystem):
        super().__init__()
        self.operatorSubsystem = operator
        self.m_timer = Timer()
        self.addRequirements(self.operatorSubsystem)

    def initialize(self):
        self.m_timer.reset()
        self.m_timer.start()

    def execute(self):
        # Spin the flywheel alone first so the underpowered shooter doesn't
        # stall against the first ball fed into it.
        if self.m_timer.get() < tunables.shooter_spin_up_seconds():
            self.operatorSubsystem.shooterOut()
        else:
            self.operatorSubsystem.FIRE()

    def cancel(self):
        self.operatorSubsystem.ceaseFire()

    def end(self, interrupted: bool):
        self.operatorSubsystem.ceaseFire()

    def isFinished(self) -> bool:
        return False
