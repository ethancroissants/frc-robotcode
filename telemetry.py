"""Swerve drive telemetry publisher."""

from ntcore import NetworkTableInstance
from phoenix6 import SignalLogger
from wpilib import Color, Color8Bit, Mechanism2d, SmartDashboard
from wpimath.geometry import Pose2d
from wpimath.kinematics import ChassisSpeeds, SwerveModulePosition, SwerveModuleState


class Telemetry:
    """
    Construct a telemetry object, with the specified max speed of the robot.
    """

    def __init__(self, maxSpeed: float):
        self.MaxSpeed = maxSpeed
        SignalLogger.start()

        self.inst = NetworkTableInstance.getDefault()

        # Robot swerve drive state
        self.driveStateTable = self.inst.getTable("DriveState")
        self.drivePose = self.driveStateTable.getStructTopic("Pose", Pose2d).publish()
        self.driveSpeeds = self.driveStateTable.getStructTopic("Speeds", ChassisSpeeds).publish()
        self.driveModuleStates = self.driveStateTable.getStructArrayTopic(
            "ModuleStates", SwerveModuleState
        ).publish()
        self.driveModuleTargets = self.driveStateTable.getStructArrayTopic(
            "ModuleTargets", SwerveModuleState
        ).publish()
        self.driveModulePositions = self.driveStateTable.getStructArrayTopic(
            "ModulePositions", SwerveModulePosition
        ).publish()
        self.driveTimestamp = self.driveStateTable.getDoubleTopic("Timestamp").publish()
        self.driveOdometryFrequency = self.driveStateTable.getDoubleTopic(
            "OdometryFrequency"
        ).publish()

        # Robot pose for field positioning
        self.table = self.inst.getTable("Pose")
        self.fieldPub = self.table.getDoubleArrayTopic("robotPose").publish()
        self.fieldTypePub = self.table.getStringTopic(".type").publish()

        # Mechanisms to represent the swerve module states
        self.m_moduleMechanisms = [
            Mechanism2d(1, 1),
            Mechanism2d(1, 1),
            Mechanism2d(1, 1),
            Mechanism2d(1, 1),
        ]
        self.m_moduleSpeeds = [
            mech.getRoot("RootSpeed", 0.5, 0.5).appendLigament("Speed", 0.5, 0)
            for mech in self.m_moduleMechanisms
        ]
        self.m_moduleDirections = [
            mech.getRoot("RootDirection", 0.5, 0.5).appendLigament(
                "Direction", 0.1, 0, 0, Color8Bit(Color.kWhite)
            )
            for mech in self.m_moduleMechanisms
        ]

        for i, mech in enumerate(self.m_moduleMechanisms):
            SmartDashboard.putData(f"Module {i}", mech)

        self.m_poseArray = [0.0, 0.0, 0.0]

    def telemeterize(self, state) -> None:
        """Accept the swerve drive state and telemeterize it to SmartDashboard and SignalLogger."""
        self.drivePose.set(state.pose)
        self.driveSpeeds.set(state.speeds)
        self.driveModuleStates.set(state.module_states)
        self.driveModuleTargets.set(state.module_targets)
        self.driveModulePositions.set(state.module_positions)
        self.driveTimestamp.set(state.timestamp)
        self.driveOdometryFrequency.set(1.0 / state.odometry_period)

        SignalLogger.write_struct("DriveState/Pose", Pose2d, state.pose)
        SignalLogger.write_struct("DriveState/Speeds", ChassisSpeeds, state.speeds)
        SignalLogger.write_struct_array(
            "DriveState/ModuleStates", SwerveModuleState, state.module_states
        )
        SignalLogger.write_struct_array(
            "DriveState/ModuleTargets", SwerveModuleState, state.module_targets
        )
        SignalLogger.write_struct_array(
            "DriveState/ModulePositions", SwerveModulePosition, state.module_positions
        )
        SignalLogger.write_double("DriveState/OdometryPeriod", state.odometry_period, "seconds")

        self.fieldTypePub.set("Field2d")

        self.m_poseArray[0] = state.pose.X()
        self.m_poseArray[1] = state.pose.Y()
        self.m_poseArray[2] = state.pose.rotation().degrees()
        self.fieldPub.set(self.m_poseArray)

        for i in range(4):
            angle_deg = state.module_states[i].angle.degrees()
            self.m_moduleSpeeds[i].setAngle(angle_deg)
            self.m_moduleDirections[i].setAngle(angle_deg)
            self.m_moduleSpeeds[i].setLength(
                state.module_states[i].speed / (2 * self.MaxSpeed)
            )
