# ============================================================
# DRIVETRAIN - Swerve drive control
# ============================================================
# This robot uses "swerve drive" -- each of the 4 wheels can
# spin AND steer independently, like shopping cart wheels.
#
# Each "swerve module" has:
#   - Drive motor  (TalonFX) -- spins the wheel forward/backward
#   - Steer motor  (TalonFX) -- rotates the wheel to face any direction
#   - CANcoder     -- absolute encoder that knows the wheel's angle
#
# The drivetrain uses WPILib's SwerveDrive4Kinematics to calculate
# what speed and angle each wheel needs to achieve the desired
# robot motion (forward, sideways, and rotation).
#
# Field-centric driving means "forward" is always toward the
# opposite alliance wall, regardless of which way the robot
# is facing. The Pigeon2 gyro tracks the robot's heading.
# ============================================================

import math
from commands2 import SubsystemBase
from phoenix6.hardware import TalonFX, CANcoder, Pigeon2
from phoenix6.controls import DutyCycleOut, PositionVoltage
from phoenix6.configs import Slot0Configs
from wpimath.geometry import Translation2d, Rotation2d
from wpimath.kinematics import (
    SwerveDrive4Kinematics,
    SwerveModuleState,
    ChassisSpeeds,
)
import constants


class SwerveModule:
    """One swerve module: drive motor + steer motor + CANcoder."""

    def __init__(self, drive_id, steer_id, encoder_id, encoder_offset, drive_inverted):
        self.drive_motor = TalonFX(drive_id)
        self.steer_motor = TalonFX(steer_id)
        self.encoder = CANcoder(encoder_id)
        self.encoder_offset = encoder_offset
        self.drive_inverted = drive_inverted

        # Configure steer motor PID (for position control)
        try:
            steer_pid = Slot0Configs()
            steer_pid.k_p = constants.STEER_P
            steer_pid.k_i = constants.STEER_I
            steer_pid.k_d = constants.STEER_D
            self.steer_motor.configurator.apply(steer_pid)
        except Exception:
            pass

        # Seed the steer motor's internal position from the CANcoder.
        # This tells the motor "you're currently at THIS angle" so
        # future position commands are relative to the real world.
        try:
            abs_pos = self.encoder.get_absolute_position().value_as_double
            wheel_angle = abs_pos - self.encoder_offset
            self.steer_motor.set_position(wheel_angle * constants.STEER_GEAR_RATIO)
        except Exception:
            pass

        # Control requests
        self.drive_request = DutyCycleOut(0)
        self.steer_request = PositionVoltage(0).with_slot(0)

    def get_angle(self):
        """Get the wheel's current angle from the CANcoder."""
        try:
            raw = self.encoder.get_absolute_position().value_as_double
            return Rotation2d.fromRotations(raw - self.encoder_offset)
        except Exception:
            # Fallback: estimate from motor position
            try:
                motor_pos = self.steer_motor.get_position().value_as_double
                return Rotation2d.fromRotations(motor_pos / constants.STEER_GEAR_RATIO)
            except Exception:
                return Rotation2d()

    def set_desired_state(self, desired_state):
        """Set the desired speed (m/s) and angle for this module."""
        current_angle = self.get_angle()

        # Optimize: if the desired angle is > 90 degrees away from
        # current, flip the drive direction and turn the shorter way.
        # This prevents the wheel from ever turning more than 90 degrees.
        speed = desired_state.speed
        target_angle = desired_state.angle

        delta_deg = (target_angle - current_angle).degrees()
        # Normalize to [-180, 180]
        while delta_deg > 180:
            delta_deg -= 360
        while delta_deg < -180:
            delta_deg += 360

        if abs(delta_deg) > 90:
            speed = -speed
            delta_deg += 180 if delta_deg < 0 else -180

        # If speed is tiny, STOP the drive motor and hold the current steer angle.
        # (Previously this returned early WITHOUT stopping the motor, so the last
        # non-zero command kept running -- this is what caused the robot to keep
        # moving/spinning after releasing the joystick.)
        if abs(speed) < 0.01:
            try:
                self.drive_motor.set_control(self.drive_request.with_output(0))
            except Exception:
                pass
            return

        # --- Set drive motor ---
        drive_pct = speed / constants.MAX_SPEED_MPS
        if self.drive_inverted:
            drive_pct = -drive_pct
        try:
            self.drive_motor.set_control(self.drive_request.with_output(drive_pct))
        except Exception:
            pass

        # --- Set steer motor ---
        # Convert the angle delta to motor rotations and add to current position
        delta_rotations = delta_deg / 360.0
        try:
            current_motor_pos = self.steer_motor.get_position().value_as_double
            target_motor_pos = current_motor_pos + delta_rotations * constants.STEER_GEAR_RATIO
            self.steer_motor.set_control(self.steer_request.with_position(target_motor_pos))
        except Exception:
            pass

    def stop(self):
        """Stop the drive motor (steer holds position)."""
        try:
            self.drive_motor.set_control(self.drive_request.with_output(0))
        except Exception:
            pass


class Drivetrain(SubsystemBase):
    """Swerve drivetrain with 4 independently steered wheels."""

    def __init__(self):
        super().__init__()

        # --- Create swerve modules ---
        self.front_left = SwerveModule(
            constants.FRONT_LEFT_DRIVE_ID, constants.FRONT_LEFT_STEER_ID,
            constants.FRONT_LEFT_ENCODER_ID, constants.FL_ENCODER_OFFSET,
            drive_inverted=constants.LEFT_SIDE_INVERTED,
        )
        self.front_right = SwerveModule(
            constants.FRONT_RIGHT_DRIVE_ID, constants.FRONT_RIGHT_STEER_ID,
            constants.FRONT_RIGHT_ENCODER_ID, constants.FR_ENCODER_OFFSET,
            drive_inverted=constants.RIGHT_SIDE_INVERTED,
        )
        self.rear_left = SwerveModule(
            constants.REAR_LEFT_DRIVE_ID, constants.REAR_LEFT_STEER_ID,
            constants.REAR_LEFT_ENCODER_ID, constants.BL_ENCODER_OFFSET,
            drive_inverted=constants.LEFT_SIDE_INVERTED,
        )
        self.rear_right = SwerveModule(
            constants.REAR_RIGHT_DRIVE_ID, constants.REAR_RIGHT_STEER_ID,
            constants.REAR_RIGHT_ENCODER_ID, constants.BR_ENCODER_OFFSET,
            drive_inverted=constants.RIGHT_SIDE_INVERTED,
        )

        self.modules = [self.front_left, self.front_right, self.rear_left, self.rear_right]

        # --- Kinematics ---
        # Tells WPILib where each wheel is on the robot so it can
        # calculate what each wheel needs to do for a given motion.
        self.kinematics = SwerveDrive4Kinematics(
            Translation2d(constants.SWERVE_FL_X, constants.SWERVE_FL_Y),
            Translation2d(constants.SWERVE_FR_X, constants.SWERVE_FR_Y),
            Translation2d(constants.SWERVE_BL_X, constants.SWERVE_BL_Y),
            Translation2d(constants.SWERVE_BR_X, constants.SWERVE_BR_Y),
        )

        # --- Gyro (Pigeon2) ---
        # Tracks which direction the robot is facing for field-centric driving
        try:
            self.gyro = Pigeon2(constants.PIGEON_ID)
        except Exception:
            self.gyro = None

        # Speed multiplier (for slow mode)
        self.speed_multiplier = constants.DRIVE_FULL_SPEED

    def drive(self, forward, strafe, rotation):
        """
        Drive the robot with field-centric control.

        forward:   positive = toward opposing alliance wall
        strafe:    positive = left
        rotation:  positive = counter-clockwise

        All values should be between -1.0 and 1.0 (joystick range).
        """
        # Apply deadzone
        forward = self._apply_deadzone(forward)
        strafe = self._apply_deadzone(strafe)
        rotation = self._apply_deadzone(rotation)

        # Apply speed multiplier
        forward *= self.speed_multiplier
        strafe *= self.speed_multiplier
        rotation *= self.speed_multiplier

        # Convert joystick values to real-world speeds
        vx = forward * constants.MAX_SPEED_MPS      # m/s forward
        vy = strafe * constants.MAX_SPEED_MPS        # m/s left
        omega = rotation * constants.MAX_ANGULAR_RATE  # rad/s CCW

        # Get robot heading for field-centric transform
        heading = self._get_heading()

        # Convert from field-relative to robot-relative speeds
        robot_speeds = ChassisSpeeds.fromFieldRelativeSpeeds(vx, vy, omega, heading)

        # Calculate what each module needs to do
        module_states = self.kinematics.toSwerveModuleStates(robot_speeds)

        # Desaturate: if any wheel would exceed max speed, scale all down
        SwerveDrive4Kinematics.desaturateWheelSpeeds(
            module_states, constants.MAX_SPEED_MPS
        )

        # Send commands to each module
        for module, state in zip(self.modules, module_states):
            module.set_desired_state(state)

    def stop(self):
        """Stop all modules."""
        for module in self.modules:
            module.stop()

    def brake(self):
        """Lock wheels in an X pattern to prevent sliding."""
        # Point wheels inward to resist pushing
        brake_states = [
            SwerveModuleState(0, Rotation2d.fromDegrees(45)),
            SwerveModuleState(0, Rotation2d.fromDegrees(-45)),
            SwerveModuleState(0, Rotation2d.fromDegrees(-45)),
            SwerveModuleState(0, Rotation2d.fromDegrees(45)),
        ]
        for module, state in zip(self.modules, brake_states):
            module.set_desired_state(state)

    def set_slow_mode(self, slow):
        """Switch between slow and fast driving."""
        if slow:
            self.speed_multiplier = constants.DRIVE_SLOW_SPEED
        else:
            self.speed_multiplier = constants.DRIVE_FULL_SPEED

    def reset_heading(self):
        """Reset the gyro to 0 (current direction becomes 'forward')."""
        try:
            if self.gyro:
                self.gyro.set_yaw(0)
        except Exception:
            pass

    def _get_heading(self):
        """Get the robot's current heading from the gyro."""
        try:
            if self.gyro:
                yaw_deg = self.gyro.get_yaw().value_as_double
                return Rotation2d.fromDegrees(yaw_deg)
        except Exception:
            pass
        # If no gyro, fall back to robot-centric (heading = 0)
        return Rotation2d()

    def _apply_deadzone(self, value):
        """Ignore small joystick drift."""
        if abs(value) < constants.DRIVE_DEADBAND:
            return 0.0
        return value
