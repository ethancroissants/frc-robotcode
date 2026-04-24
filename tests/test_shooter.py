# ============================================================
# TESTS FOR SHOOTER SUBSYSTEM
# ============================================================

import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import constants
from subsystems.shooter import Shooter


def make_shooter():
    s = Shooter()
    s.shooter_left = MagicMock()
    s.shooter_right = MagicMock()
    s.kicker = MagicMock()
    s.conveyor = MagicMock()
    s.velocity_request = MagicMock()
    s.velocity_request.with_velocity.return_value = "velocity_signal"
    s.speed_control = MagicMock()
    return s


class TestFiring:
    def test_fire_starts_all_three(self):
        s = make_shooter()
        s.fire()
        s.shooter_left.set_control.assert_called()  # Shooter spins
        s.kicker.set.assert_called()                 # Kicker pushes
        s.conveyor.set.assert_called()               # Conveyor feeds

    def test_launch_starts_all_three(self):
        s = make_shooter()
        s.launch()
        s.shooter_left.set_control.assert_called()
        s.kicker.set.assert_called()
        s.conveyor.set.assert_called()

    def test_cease_fire_stops_everything(self):
        s = make_shooter()
        s.cease_fire()
        s.shooter_left.set.assert_called_with(0)
        s.kicker.stop_motor.assert_called_once()
        s.conveyor.stop_motor.assert_called_once()


class TestKicker:
    def test_forward_uses_positive_speed(self):
        s = make_shooter()
        s.kicker_forward()
        s.kicker.set.assert_called_with(constants.KICKER_SPEED)

    def test_reverse_uses_negative_speed(self):
        s = make_shooter()
        s.kicker_reverse()
        s.kicker.set.assert_called_with(-constants.KICKER_SPEED)

    def test_stop(self):
        s = make_shooter()
        s.stop_kicker()
        s.kicker.stop_motor.assert_called_once()


class TestConveyor:
    def test_forward(self):
        s = make_shooter()
        s.conveyor_forward()
        s.conveyor.set.assert_called_with(-constants.CONVEYOR_SPEED)

    def test_reverse(self):
        s = make_shooter()
        s.conveyor_reverse()
        s.conveyor.set.assert_called_with(constants.CONVEYOR_SPEED)

    def test_stop(self):
        s = make_shooter()
        s.stop_conveyor()
        s.conveyor.stop_motor.assert_called_once()


class TestClearOut:
    def test_reverses_kicker(self):
        s = make_shooter()
        s.clear_out()
        s.kicker.set.assert_called_with(-constants.KICKER_SPEED)

    def test_reverses_conveyor(self):
        s = make_shooter()
        s.clear_out()
        s.conveyor.set.assert_called_with(constants.CONVEYOR_SPEED)
