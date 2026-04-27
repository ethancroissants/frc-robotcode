from commands2 import Command
from wpilib import Timer

import tunables
from subsystems.operator_subsystem import OperatorSubsystem


class FireAndIntake(Command):
    def __init__(self, operator: OperatorSubsystem):
        super().__init__()
        self.operatorSubsystem = operator
        self.m_timer = Timer()
        self.addRequirements(self.operatorSubsystem)

    def initialize(self):
        self.m_timer.reset()
        self.m_timer.start()

    def execute(self):
        # Feeder pulls balls from outside the whole time; kicker/conveyor wait
        # for the flywheel to reach speed so it doesn't stall on the first ball.
        self.operatorSubsystem.feederIn()
        if self.m_timer.get() < tunables.shooter_spin_up_seconds():
            self.operatorSubsystem.shooterOut()
        else:
            self.operatorSubsystem.FIRE()

    def end(self, interrupted: bool):
        self.operatorSubsystem.ceaseFire()
        self.operatorSubsystem.stopFeeder()

    def isFinished(self) -> bool:
        return False
