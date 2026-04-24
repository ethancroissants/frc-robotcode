from commands2 import Command

from subsystems.command_swerve_drivetrain import CommandSwerveDrivetrain


class DriveNormal(Command):
    def __init__(self, DT: CommandSwerveDrivetrain):
        super().__init__()
        self.driveTrain = DT

    def initialize(self):
        pass

    def execute(self):
        self.driveTrain.normalSpeed()

    def end(self, interrupted: bool):
        self.driveTrain.normalSpeed()

    def isFinished(self) -> bool:
        return False
