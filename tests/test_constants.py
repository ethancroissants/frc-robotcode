# ============================================================
# TESTS FOR CONSTANTS
# ============================================================
# Makes sure all our robot numbers are set correctly.
# If someone accidentally changes a motor ID, these tests catch it.
# ============================================================

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import constants


class TestMotorIDs:
    """Every motor ID should be unique -- two motors can't share an ID."""

    def test_all_motor_ids_are_unique(self):
        motor_ids = [
            constants.FRONT_LEFT_DRIVE_ID,
            constants.FRONT_LEFT_STEER_ID,
            constants.FRONT_RIGHT_DRIVE_ID,
            constants.FRONT_RIGHT_STEER_ID,
            constants.REAR_LEFT_DRIVE_ID,
            constants.REAR_LEFT_STEER_ID,
            constants.REAR_RIGHT_DRIVE_ID,
            constants.REAR_RIGHT_STEER_ID,
            constants.FEEDER_LEFT_ID,
            constants.FEEDER_RIGHT_ID,
            constants.CONVEYOR_ID,
            constants.ELEVATOR_ID,
            constants.KICKER_ID,
            constants.SHOOTER_LEFT_ID,
            constants.SHOOTER_RIGHT_ID,
            constants.HOOD_ID,
        ]
        assert len(motor_ids) == len(set(motor_ids)), "Duplicate motor ID found!"

    def test_all_encoder_ids_are_unique(self):
        encoder_ids = [
            constants.FRONT_LEFT_ENCODER_ID,
            constants.FRONT_RIGHT_ENCODER_ID,
            constants.REAR_LEFT_ENCODER_ID,
            constants.REAR_RIGHT_ENCODER_ID,
        ]
        assert len(encoder_ids) == len(set(encoder_ids)), "Duplicate encoder ID found!"

    def test_motor_ids_dont_overlap_encoder_ids(self):
        motor_ids = {
            constants.FRONT_LEFT_DRIVE_ID, constants.FRONT_LEFT_STEER_ID,
            constants.FRONT_RIGHT_DRIVE_ID, constants.FRONT_RIGHT_STEER_ID,
            constants.REAR_LEFT_DRIVE_ID, constants.REAR_LEFT_STEER_ID,
            constants.REAR_RIGHT_DRIVE_ID, constants.REAR_RIGHT_STEER_ID,
        }
        encoder_ids = {
            constants.FRONT_LEFT_ENCODER_ID, constants.FRONT_RIGHT_ENCODER_ID,
            constants.REAR_LEFT_ENCODER_ID, constants.REAR_RIGHT_ENCODER_ID,
        }
        overlap = motor_ids & encoder_ids
        assert len(overlap) == 0, f"Motor and encoder IDs overlap: {overlap}"


class TestMotorSpeeds:
    """Motor speeds should be between 0 and 1 (valid range)."""

    def test_speeds_are_in_valid_range(self):
        speeds = [
            constants.SHOOTER_SPEED,
            constants.KICKER_SPEED,
            constants.CONVEYOR_SPEED,
            constants.HOOD_SPEED,
            constants.FEEDER_SPEED,
            constants.ELEVATOR_SPEED,
            constants.LAUNCH_SPEED,
        ]
        for speed in speeds:
            assert 0.0 < speed <= 1.0, f"Speed {speed} is out of range (0, 1]"

    def test_slow_speed_is_less_than_full_speed(self):
        assert constants.DRIVE_SLOW_SPEED < constants.DRIVE_FULL_SPEED


class TestElevatorPositions:
    """Elevator positions should be in ascending order."""

    def test_positions_go_up(self):
        positions = [
            constants.ELEVATOR_BOTTOM,
            constants.ELEVATOR_LOADING,
            constants.ELEVATOR_LEVEL_1,
            constants.ELEVATOR_LEVEL_2,
            constants.ELEVATOR_LEVEL_3,
        ]
        for i in range(len(positions) - 1):
            assert positions[i] < positions[i + 1], (
                f"Elevator positions are out of order: {positions[i]} >= {positions[i+1]}"
            )


class TestGamepadPorts:
    """Gamepad ports must be different (can't use the same controller for both)."""

    def test_gamepads_are_different(self):
        assert constants.DRIVER_GAMEPAD_PORT != constants.OPERATOR_GAMEPAD_PORT


class TestPIDValues:
    """PID values should be non-negative."""

    def test_shooter_pid_non_negative(self):
        assert constants.SHOOTER_P >= 0
        assert constants.SHOOTER_I >= 0
        assert constants.SHOOTER_D >= 0

    def test_elevator_pid_non_negative(self):
        assert constants.ELEVATOR_P >= 0
        assert constants.ELEVATOR_I >= 0
        assert constants.ELEVATOR_D >= 0
