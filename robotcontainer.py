"""
Copyright (c) FIRST and other WPILib contributors.
Open Source Software; you can modify and/or share it under the terms of
the WPILib BSD license file in the root directory of this project.
"""

import math

from commands2 import DeferredCommand
from commands2.button import CommandXboxController, Trigger
from commands2.sysid import SysIdRoutine
from pathplannerlib.auto import AutoBuilder, NamedCommands
from phoenix6.swerve import SwerveModule, requests as swerve_requests
from wpilib import DriverStation, SendableChooser, SmartDashboard
from wpimath.filter import Debouncer
from wpimath.geometry import Rotation2d

import constants
import gamepads
import motorcontrollers
from commands.auto_fire import AutoFire
from commands.cease_fire import CeaseFire
from commands.clear_out import ClearOut
from commands.clear_shooter import ClearShooter
from commands.conveyor_fwd import ConveyorFwd
from commands.conveyor_rev import ConveyorRev
from commands.drive_normal import DriveNormal
from commands.drive_slow import DriveSlow
from commands.elevator_down import ElevatorDown
from commands.elevator_up import ElevatorUp
from commands.feeder_in import FeederIn
from commands.feeder_out import FeederOut
from commands.fire import Fire
from commands.hood_down import HoodDown
from commands.hood_up import HoodUp
from commands.kicker_in import KickerIn
from commands.kicker_out import KickerOut
from commands.launch import Launch
from commands.run_elevator_to_top_pid import RunElevatorToTopPID
from commands.stop_conveyor import StopConveyor
from commands.stop_elevator import StopElevator
from commands.stop_feeder import StopFeeder
from commands.stop_hood import StopHood
from commands.stop_kicker import StopKicker
from commands.stop_shooter import StopShooter
from generated import tuner_constants
from subsystems.elevator_subsystem import ElevatorSubsystem
from subsystems.operator_subsystem import OperatorSubsystem
from telemetry import Telemetry


class RobotContainer:
    # Static (class-level) subsystems, matching the Java layout
    operator = OperatorSubsystem()
    elevator = ElevatorSubsystem()
    targetingMessage = ""

    def __init__(self):
        self.MaxSpeed = 1.0 * tuner_constants.kSpeedAt12Volts
        self.MaxAngularRate = 0.75 * 2 * math.pi  # 3/4 of a rotation per second

        # Setting up bindings for necessary control of the swerve drive platform
        self.drive = (
            swerve_requests.FieldCentric()
            .with_deadband(self.MaxSpeed * 0.1)
            .with_rotational_deadband(self.MaxAngularRate * 0.1)
            .with_drive_request_type(SwerveModule.DriveRequestType.OPEN_LOOP_VOLTAGE)
        )
        self.brake = swerve_requests.SwerveDriveBrake()
        self.point = swerve_requests.PointWheelsAt()

        self.logger = Telemetry(self.MaxSpeed)

        self.drivetrain = tuner_constants.createDrivetrain()

        self.motors = motorcontrollers

        # Feeder Commands
        self.feederIn = FeederIn(RobotContainer.operator)
        self.feederOut = FeederOut(RobotContainer.operator)
        self.stopFeeder = StopFeeder(RobotContainer.operator)
        # Shooter Commands
        self.fire = Fire(RobotContainer.operator)
        self.autoFire = AutoFire(RobotContainer.operator)
        self.launch = Launch(RobotContainer.operator)
        self.ceaseFire = CeaseFire(RobotContainer.operator)
        self.clearOut = ClearOut(RobotContainer.operator)
        self.stopShooter = StopShooter(RobotContainer.operator)
        self.clearShooter = ClearShooter(RobotContainer.operator)
        # Kicker Commands
        self.kickerIn = KickerIn(RobotContainer.operator)
        self.kickerOut = KickerOut(RobotContainer.operator)
        self.stopKicker = StopKicker(RobotContainer.operator)
        # Conveyor Commands
        self.conveyorFwd = ConveyorFwd(RobotContainer.operator)
        self.conveyorRev = ConveyorRev(RobotContainer.operator)
        self.stopConveyor = StopConveyor(RobotContainer.operator)
        # Hood Commands
        self.hoodUp = HoodUp(RobotContainer.operator)
        self.hoodDown = HoodDown(RobotContainer.operator)
        self.stopHood = StopHood(RobotContainer.operator)
        # Elevator Commands
        self.runElevatorToTopPID = RunElevatorToTopPID(RobotContainer.elevator)
        self.elevatorUp = ElevatorUp(RobotContainer.elevator)
        self.elevatorDown = ElevatorDown(RobotContainer.elevator)
        self.stopElevator = StopElevator(RobotContainer.elevator)

        self.driveSlow = DriveSlow(self.drivetrain)
        self.driveNormal = DriveNormal(self.drivetrain)

        # Register named commands with PathPlanner before AutoBuilder is used.
        NamedCommands.registerCommand(
            "Shoot",
            DeferredCommand(
                lambda: AutoFire(RobotContainer.operator),
                RobotContainer.operator,
            ),
        )
        NamedCommands.registerCommand(
            "FeederIn",
            DeferredCommand(
                lambda: FeederIn(RobotContainer.operator),
                RobotContainer.operator,
            ),
        )

        # Build the auto chooser from all .auto files in deploy/pathplanner/autos/
        self.autoChooser: SendableChooser = AutoBuilder.buildAutoChooser()
        SmartDashboard.putData("Auto Chooser", self.autoChooser)

        self.configureBindings()

    def configureBindings(self):
        # X is defined as forward (WPILib convention), Y is defined to the left.
        self.drivetrain.setDefaultCommand(
            self.drivetrain.applyRequest(
                lambda: self.drive.with_velocity_x(
                    -gamepads.driverController.getLeftY() * self.MaxSpeed
                )
                .with_velocity_y(-gamepads.driverController.getLeftX() * self.MaxSpeed)
                .with_rotational_rate(
                    gamepads.driverController.getRightX() * self.MaxAngularRate
                )
            )
        )

        # Idle while robot is disabled so the configured neutral mode is applied to the drive
        # motors while disabled.
        idle = swerve_requests.Idle()
        Trigger(DriverStation.isDisabled).whileTrue(
            self.drivetrain.applyRequest(lambda: idle).ignoringDisable(True)
        )

        # Apply brake when X button is pressed
        gamepads.driver_X_Button.whileTrue(
            self.drivetrain.applyRequest(lambda: self.brake)
        )
        # Automatically point robot when B button is pressed
        gamepads.driver_B_Button.whileTrue(
            self.drivetrain.applyRequest(
                lambda: self.point.with_module_direction(
                    Rotation2d(
                        -gamepads.driverController.getLeftY(),
                        -gamepads.driverController.getLeftX(),
                    )
                )
            )
        )

        # Run SysId routines when holding back/start and X/Y.
        gamepads.driver_backButton.and_(gamepads.driver_Y_Button).whileTrue(
            self.drivetrain.sysIdDynamic(SysIdRoutine.Direction.kForward)
        )
        gamepads.driver_backButton.and_(gamepads.driver_X_Button).whileTrue(
            self.drivetrain.sysIdDynamic(SysIdRoutine.Direction.kReverse)
        )
        gamepads.driver_startButton.and_(gamepads.driver_Y_Button).whileTrue(
            self.drivetrain.sysIdQuasistatic(SysIdRoutine.Direction.kForward)
        )
        gamepads.driver_startButton.and_(gamepads.driver_X_Button).whileTrue(
            self.drivetrain.sysIdQuasistatic(SysIdRoutine.Direction.kReverse)
        )

        # Reset the field-centric heading on left bumper press
        gamepads.driver_leftShoulderButton.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).onTrue(self.drivetrain.runOnce(lambda: self.drivetrain.seed_field_centric()))

        # ***************************
        # Driver Controller Setup
        # ***************************
        # Drive slow when right bumper is held
        gamepads.driver_rightShoulderButton.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).whileTrue(self.driveSlow).onFalse(self.driveNormal)

        # Reset the field-centric heading on left bumper press
        gamepads.driver_leftShoulderButton.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).onTrue(self.drivetrain.runOnce(lambda: self.drivetrain.seed_field_centric()))

        # *****************************
        # Configure Button Bindings
        # *****************************
        # OPERATOR BUTTONS
        # Hood Buttons
        gamepads.operator_X_Button.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).whileTrue(self.hoodDown).onFalse(self.stopHood)
        gamepads.operator_B_Button.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).whileTrue(self.hoodUp).onFalse(self.stopHood)
        # Elevator Buttons
        gamepads.operator_Y_Button.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).onTrue(self.runElevatorToTopPID).onFalse(self.stopElevator)
        gamepads.operator_A_Button.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).whileTrue(self.elevatorDown).onFalse(self.stopElevator)
        # Shooter Buttons
        # LB: shoot AND intake at the same time (shooter + kicker + conveyor + feeder run together)
        def _fire_and_intake():
            RobotContainer.operator.FIRE()
            RobotContainer.operator.feederIn()

        def _stop_fire_and_intake():
            RobotContainer.operator.ceaseFire()
            RobotContainer.operator.stopFeeder()

        gamepads.operator_leftShoulderButton.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).whileTrue(
            RobotContainer.operator.run(_fire_and_intake)
        ).onFalse(
            RobotContainer.operator.runOnce(_stop_fire_and_intake)
        )
        gamepads.operator_rightShoulderButton.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).whileTrue(self.clearOut).onFalse(self.ceaseFire)
        gamepads.operator_leftStickButton.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).whileTrue(self.launch).onFalse(self.ceaseFire)
        # Conveyor Buttons
        gamepads.operator_startButton.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).whileTrue(self.conveyorFwd).onFalse(self.stopConveyor)
        gamepads.operator_backButton.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).whileTrue(self.conveyorRev).onFalse(self.stopConveyor)
        # Feeder Buttons
        gamepads.operator_rightStickButton.debounce(
            0.1, Debouncer.DebounceType.kBoth
        ).whileTrue(self.feederIn).onFalse(self.stopFeeder)

        self.drivetrain.register_telemetry(self.logger.telemeterize)

    def getAutonomousCommand(self):
        return self.autoChooser.getSelected()
