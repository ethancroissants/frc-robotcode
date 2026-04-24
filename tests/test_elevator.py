# ============================================================
# TESTS FOR ELEVATOR SUBSYSTEM
# ============================================================

import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import constants
from subsystems.elevator import Elevator


def make_elevator(at_top=False, at_bottom=False):
    e = Elevator()
    e.motor = MagicMock()
    e.top_switch = MagicMock()
    e.top_switch.get.return_value = at_top
    e.bottom_switch = MagicMock()
    e.bottom_switch.get.return_value = at_bottom
    return e


class TestSafety:
    """The elevator MUST stop when it hits a limit switch."""

    def test_stops_going_up_when_at_top(self):
        e = make_elevator(at_top=True)
        e.go_up()
        e.motor.stop_motor.assert_called_once()
        e.motor.set.assert_not_called()

    def test_stops_going_down_when_at_bottom(self):
        e = make_elevator(at_bottom=True)
        e.go_down()
        e.motor.stop_motor.assert_called_once()
        e.motor.set.assert_not_called()

    def test_goes_up_when_not_at_top(self):
        e = make_elevator(at_top=False)
        e.go_up()
        e.motor.set.assert_called_once()

    def test_goes_down_when_not_at_bottom(self):
        e = make_elevator(at_bottom=False)
        e.go_down()
        e.motor.set.assert_called_once()


class TestSpeed:
    def test_up_uses_correct_speed(self):
        e = make_elevator()
        e.go_up()
        e.motor.set.assert_called_with(-constants.ELEVATOR_SPEED)

    def test_down_uses_correct_speed(self):
        e = make_elevator()
        e.go_down()
        e.motor.set.assert_called_with(constants.ELEVATOR_SPEED)

    def test_up_and_down_are_opposite(self):
        e1 = make_elevator()
        e1.go_up()
        up_speed = e1.motor.set.call_args[0][0]

        e2 = make_elevator()
        e2.go_down()
        down_speed = e2.motor.set.call_args[0][0]

        assert up_speed == -down_speed


class TestStop:
    def test_stop(self):
        e = make_elevator()
        e.stop()
        e.motor.stop_motor.assert_called_once()


class TestLimitSwitches:
    def test_at_top_true(self):
        assert make_elevator(at_top=True).is_at_top() is True

    def test_at_top_false(self):
        assert make_elevator(at_top=False).is_at_top() is False

    def test_at_bottom_true(self):
        assert make_elevator(at_bottom=True).is_at_bottom() is True

    def test_at_bottom_false(self):
        assert make_elevator(at_bottom=False).is_at_bottom() is False
