"""
Copyright (c) 2018-2019 FIRST. All Rights Reserved.
Open Source Software - may be modified and shared by FRC teams. The code
must be accompanied by the FIRST BSD license file in the root directory of
the project.

The Constants module provides a convenient place for teams to hold robot-wide
numerical or boolean constants.
"""

import math

from wpimath.controller import PIDController
from wpimath.geometry import Translation2d
from wpimath.kinematics import DifferentialDriveKinematics, SwerveDrive4Kinematics
from wpimath.trajectory import TrapezoidProfile
from wpimath.units import inchesToMeters


class MotorSpeeds:
    SHOOTER = 0.5
    KICKER = 0.9
    CONVEYOR = 1.0
    HOOD = 0.2
    FEEDER = 0.5
    ELEVATOR = 0.6
    LAUNCH = 0.7

    # Seconds the flywheel spins alone before the kicker/conveyor feed a ball.
    SHOOTER_SPIN_UP_SECONDS = 2.0


class ControllerIDs:
    FALCON_FRONT_RIGHT_STEER_ID = 27
    FALCON_REAR_RIGHT_STEER_ID = 25
    FALCON_FRONT_LEFT_STEER_ID = 23
    FALCON_REAR_LEFT_STEER_ID = 21
    KRAKEN_FRONT_RIGHT_DRIVE_ID = 28
    KRAKEN_REAR_RIGHT_DRIVE_ID = 26
    KRAKEN_FRONT_LEFT_DRIVE_ID = 24
    KRAKEN_REAR_LEFT_DRIVE_ID = 22

    MINION_DRIVE_ID = 3

    FEEDER1_DRIVE_ID = 4
    FEEDER2_DRIVE_ID = 5
    CONVEYOR_DRIVE_ID = 6
    WRIST_DRIVE_ID = 7
    ELEVATOR_DRIVE_ID = 8
    KICKER_DRIVE_ID = 9
    SHOOTER1_DRIVE_ID = 10
    SHOOTER2_DRIVE_ID = 11
    HOOD_DRIVE_ID = 12

    TEST_DRIVE_ID = 40


class CancoderIDs:
    FRONT_LEFT_CANCODER_ID = 32
    FRONT_RIGHT_CANCODER_ID = 34
    REAR_LEFT_CANCODER_ID = 31
    REAR_RIGHT_CANCODER_ID = 33


class GamePadIDs:
    DRIVER_GAMEPAD_ID = 0
    OPERATOR_GAMEPAD_ID = 1


class PneumaticIDs:
    ARM_EXTEND_ID = 6
    ARM_RETRACT_ID = 7
    CONE_GRAB_ID = 4
    CONE_RELEASE_ID = 5
    CUBE_GRAB_ID = 2
    CUBE_RELEASE_ID = 3


class ButtonIDs:
    A_BUTTON_ID = 1
    B_BUTTON_ID = 2
    X_BUTTON_ID = 3
    Y_BUTTON_ID = 4
    LEFT_SHOULDER_BUTTON_ID = 5
    RIGHT_SHOULDER_BUTTON_ID = 6
    BACK_BUTTON_ID = 7
    START_BUTTON_ID = 8
    LEFT_STICK_BUTTON_ID = 9
    RIGHT_STICK_BUTTON_ID = 10


class JoystickAxisIDs:
    LEFT_X_AXIS = 0
    LEFT_Y_AXIS = 1
    RIGHT_X_AXIS = 4
    RIGHT_Y_AXIS = 5

    LEFT_TRIGGER_ID = 2
    RIGHT_TRIGGER_ID = 3


class Cameras:
    AprilTagIP = "10.12.79.2"
    AprilTagPort = 5810
    AprilTagURL = f"http://{AprilTagIP}:{AprilTagPort}/?action=stream"


class Switches:
    elevatorTopLimitSwitch = 0
    elevatorBottomLimitSwitch = 1
    wristTopLimitSwitch = 2
    wristBottomLimitSwitch = 3


class ElevatorPositions:
    bottom = 0.0
    loading = 19.0
    level1 = 58.0
    level2 = 86.0
    level3 = 110.0


class DriveConstants:
    fullSpeed = 1.0
    slowSpeed = 0.6

    kMaxSpeedMetersPerSecond = 1.0
    kMaxAngularSpeed = 2 * math.pi

    kDirectionSlewRate = 1.2
    kMagnitudeSlewRate = 1.8
    kRotationalSlewRate = 2.0

    kTrackWidth = inchesToMeters(21.5)
    kWheelBase = inchesToMeters(21.5)
    kDriveKinematics = SwerveDrive4Kinematics(
        Translation2d(kWheelBase / 2, kTrackWidth / 2),
        Translation2d(kWheelBase / 2, -kTrackWidth / 2),
        Translation2d(-kWheelBase / 2, kTrackWidth / 2),
        Translation2d(-kWheelBase / 2, -kTrackWidth / 2),
    )

    kFrontLeftChassisAngularOffset = -math.pi / 2
    kFrontRightChassisAngularOffset = 0
    kBackLeftChassisAngularOffset = math.pi
    kBackRightChassisAngularOffset = math.pi / 2

    kFrontLeftDrivingCanId = 4
    kRearLeftDrivingCanId = 2
    kFrontRightDrivingCanId = 6
    kRearRightDrivingCanId = 8

    kFrontLeftTurningCanId = 3
    kRearLeftTurningCanId = 1
    kFrontRightTurningCanId = 5
    kRearRightTurningCanId = 7

    kGyroReversed = True


class NeoMotorConstants:
    kFreeSpeedRpm = 5676


class ModuleConstants:
    kDrivingMotorPinionTeeth = 13

    kTurningEncoderInverted = True

    kDrivingMotorFreeSpeedRps = NeoMotorConstants.kFreeSpeedRpm / 60
    kWheelDiameterMeters = 0.0762
    kWheelCircumferenceMeters = kWheelDiameterMeters * math.pi
    kDrivingMotorReduction = (45.0 * 22) / (kDrivingMotorPinionTeeth * 15)
    kDriveWheelFreeSpeedRps = (
        kDrivingMotorFreeSpeedRps * kWheelCircumferenceMeters
    ) / kDrivingMotorReduction

    kDrivingEncoderPositionFactor = (kWheelDiameterMeters * math.pi) / kDrivingMotorReduction
    kDrivingEncoderVelocityFactor = (
        (kWheelDiameterMeters * math.pi) / kDrivingMotorReduction
    ) / 60.0

    kTurningEncoderPositionFactor = 2 * math.pi
    kTurningEncoderVelocityFactor = (2 * math.pi) / 60.0

    kTurningEncoderPositionPIDMinInput = 0
    kTurningEncoderPositionPIDMaxInput = kTurningEncoderPositionFactor

    kDrivingP = 0.04
    kDrivingI = 0
    kDrivingD = 0
    kDrivingFF = 1 / kDriveWheelFreeSpeedRps

    kDrivingMinOutput = -0.4
    kDrivingMaxOutput = 0.4

    kTurningP = 1
    kTurningI = 0
    kTurningD = 0
    kTurningFF = 0
    kTurningMinOutput = -1
    kTurningMaxOutput = 1

    kDrivingMotorCurrentLimit = 50
    kSteerMotorCurrentLimit = 30
    kDrivingMotorCurrentThreshold = 55
    kSteerMotorCurrentThreshold = 30
    kDrivingMotorCurrentThresholdTime = 0.1
    kSteerMotorCurrentThresholdTime = 0.1

    kShooterMotorCurrentLimit = 60.0


class OIConstants:
    kDriverControllerPort = 0
    kDriveDeadband = 0.05
    kDeadband = 0.09


class AutoConstants:
    kMaxSpeedMetersPerSecond = 1
    kMaxAccelerationMetersPerSecondSquared = 1
    kMaxAngularSpeedRadiansPerSecond = math.pi
    kMaxAngularSpeedRadiansPerSecondSquared = math.pi

    kPXController = 1
    kPYController = 1
    kPThetaController = 1

    kThetaControllerConstraints = TrapezoidProfile.Constraints(
        kMaxAngularSpeedRadiansPerSecond, kMaxAngularSpeedRadiansPerSecondSquared
    )


class RobotLimits:
    kHoldDistance = 12.0
    kValueToInches = 0.125
    kP = 0.05
    kUltrasonicPort = 0


class DriveTrain:
    driveSpeed = 0.8

    kWheelRadiusInches = 2

    kDriveReduction = 1.0

    class Encoders:
        LEFT_ENCODER_SLOT = 1
        RIGHT_ENCODER_SLOT = 1

        LEFT_SENSOR_PHASE = True
        RIGHT_SENSOR_PHASE = False

        PULSES_PER_REVOLUTION = 5760

    class Measurements:
        WHEEL_DIAMETER = inchesToMeters(6.0)
        WHEEL_CIRCUMFERENCE = math.pi * WHEEL_DIAMETER

        DRIVEBASE_WIDTH = inchesToMeters(28.0)
        DRIVEBASE_LENGTH = inchesToMeters(28.0)

        GEAR_RATIO = 8.45

        MOTOR_MAX_RPM = 5330

    ALIGNMENT_EPSILON = 3


class Operator:
    OPERATOR_ACTUATOR_TALON = 13
    OPERATOR_ROLLER_TALON = 14

    OPERATOR_ACTUATOR_TALON_INVERTED = False
    OPERATOR_ROLLER_TALON_INVERTED = True

    OPERATOR_LIMIT_BOTTOM = 0
    OPERATOR_LIMIT_TOP = 1

    kPArm = 0.011111111111
    kIArm = 0.0
    kDArm = 0.0

    ARM_TICKS_PER_DEGREE = 1000

    ARM_UP_SPEED = -0.85
    ARM_DOWN_SPEED = 0.35

    ROLLER_SPEED = 0.4


class ControlGains:
    ksVolts = 1.02
    kvVoltsSecondsPerMeter = 7.01
    kaVoltsSecondsSquaredPerMeter = 2.64

    kPDriveVel = 0.478
    kIDriveVel = 0.0
    kDDriveVel = 0.008

    kPTurnVel = 0.0088
    kITurnVel = 0.01
    kDTurnVel = 0.0106

    kRP = 0.05

    kPElevatorVel = 0.478
    kIElevatorVel = 0.0
    kDElevatorVel = 0.0

    turningPIDController = PIDController(kPTurnVel, kITurnVel, kDTurnVel)
    drivePidController = PIDController(kPTurnVel, kITurnVel, kDTurnVel)
    elevatorPidController = PIDController(kPElevatorVel, kIElevatorVel, kDElevatorVel)

    kTrackWidthMeters = 0.1524
    kDriveKinematics = DifferentialDriveKinematics(kTrackWidthMeters)

    kMaxSpeedMetersPerSecond = 3
    kMaxAccelerationMetersPerSecondSquared = 1.5

    kRamseteB = 2
    kRamseteZeta = 0.7


class Autonomous:
    SCORE_LATE_DELAY = 5.0
    VISION_DISTANCE_KP = -0.1
    AUTO_TARGET_DISTANCE_EPSILON = 5.0


DRIVETRAIN_TRACKWIDTH_METERS = 1.0
DRIVETRAIN_WHEELBASE_METERS = 1.0

DRIVETRAIN_PIGEON_ID = 0

FRONT_LEFT_MODULE_DRIVE_MOTOR = ControllerIDs.KRAKEN_FRONT_LEFT_DRIVE_ID
FRONT_LEFT_MODULE_STEER_MOTOR = ControllerIDs.FALCON_FRONT_LEFT_STEER_ID
FRONT_LEFT_MODULE_STEER_ENCODER = CancoderIDs.FRONT_LEFT_CANCODER_ID
FRONT_LEFT_MODULE_STEER_OFFSET = -math.radians(0.0)

FRONT_RIGHT_MODULE_DRIVE_MOTOR = ControllerIDs.KRAKEN_FRONT_RIGHT_DRIVE_ID
FRONT_RIGHT_MODULE_STEER_MOTOR = ControllerIDs.FALCON_FRONT_RIGHT_STEER_ID
FRONT_RIGHT_MODULE_STEER_ENCODER = CancoderIDs.FRONT_RIGHT_CANCODER_ID
FRONT_RIGHT_MODULE_STEER_OFFSET = -math.radians(0.0)

BACK_LEFT_MODULE_DRIVE_MOTOR = ControllerIDs.KRAKEN_REAR_LEFT_DRIVE_ID
BACK_LEFT_MODULE_STEER_MOTOR = ControllerIDs.FALCON_REAR_LEFT_STEER_ID
BACK_LEFT_MODULE_STEER_ENCODER = CancoderIDs.REAR_LEFT_CANCODER_ID
BACK_LEFT_MODULE_STEER_OFFSET = -math.radians(0.0)

BACK_RIGHT_MODULE_DRIVE_MOTOR = ControllerIDs.KRAKEN_REAR_RIGHT_DRIVE_ID
BACK_RIGHT_MODULE_STEER_MOTOR = ControllerIDs.FALCON_REAR_RIGHT_STEER_ID
BACK_RIGHT_MODULE_STEER_ENCODER = CancoderIDs.REAR_RIGHT_CANCODER_ID
BACK_RIGHT_MODULE_STEER_OFFSET = -math.radians(0.0)
