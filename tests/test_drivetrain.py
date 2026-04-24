# ============================================================
# TESTS FOR DRIVETRAIN SUBSYSTEM
# ============================================================

import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import constants
from subsystems.drivetrain import Drivetrain


def make_drivetrain():
    dt = Drivetrain()
    # Replace each swerve module's motors with fresh MagicMocks we can inspect
    for module in dt.modules:
        module.drive_motor = MagicMock()
        module.steer_motor = MagicMock()
        module.encoder = MagicMock()
        module.drive_request = MagicMock()
        module.drive_request.with_output.return_value = "drive_signal"
        module.steer_request = MagicMock()
        module.steer_request.with_position.return_value = "steer_signal"
    return dt


class TestSlowMode:
    def test_starts_at_full_speed(self):
        dt = make_drivetrain()
        assert dt.speed_multiplier == constants.DRIVE_FULL_SPEED

    def test_slow_mode_reduces_speed(self):
        dt = make_drivetrain()
        dt.set_slow_mode(True)
        assert dt.speed_multiplier == constants.DRIVE_SLOW_SPEED

    def test_exiting_slow_mode_restores_speed(self):
        dt = make_drivetrain()
        dt.set_slow_mode(True)
        dt.set_slow_mode(False)
        assert dt.speed_multiplier == constants.DRIVE_FULL_SPEED

    def test_slow_is_actually_slower(self):
        dt = make_drivetrain()
        full = dt.speed_multiplier
        dt.set_slow_mode(True)
        assert dt.speed_multiplier < full


class TestDriveStop:
    def test_stop_calls_all_four_drive_motors(self):
        dt = make_drivetrain()
        dt.stop()
        for module in dt.modules:
            assert module.drive_motor.set_control.called


class TestDriveInputs:
    def test_zero_input_no_module_movement(self):
        """With zero input (inside deadzone), modules shouldn't move."""
        dt = make_drivetrain()
        dt.drive(0.0, 0.0, 0.0)
        # All inputs are in the deadzone, so no module should get a command
        for module in dt.modules:
            assert not module.drive_motor.set_control.called


class TestResetHeading:
    def test_reset_heading_calls_gyro(self):
        dt = make_drivetrain()
        dt.gyro = MagicMock()
        dt.reset_heading()
        dt.gyro.set_yaw.assert_called_once_with(0)


class TestSubsystemIsolation:
    def test_no_hood_on_drivetrain(self):
        dt = make_drivetrain()
        assert not hasattr(dt, "hood")

    def test_no_shooter_on_drivetrain(self):
        dt = make_drivetrain()
        assert not hasattr(dt, "shooter")

    def test_has_four_modules(self):
        dt = make_drivetrain()
        assert len(dt.modules) == 4
