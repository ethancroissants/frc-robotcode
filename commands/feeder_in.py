from commands2 import Command

from subsystems.operator_subsystem import OperatorSubsystem


class FeederIn(Command):
    def __init__(self, operator: OperatorSubsystem):
        super().__init__()
        self.operatorSubsystem = operator
        self.addRequirements(self.operatorSubsystem)

    def initialize(self):
        pass

    def execute(self):
        self.operatorSubsystem.feederIn()

    def cancel(self):
        self.operatorSubsystem.stopFeeder()

    def end(self, interrupted: bool):
        self.operatorSubsystem.stopFeeder()

    def isFinished(self) -> bool:
        # PathPlanner zoned event controls start/stop
        return False
