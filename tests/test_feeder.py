# ============================================================
# TESTS FOR FEEDER SUBSYSTEM
# ============================================================

import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import constants
from subsystems.feeder import Feeder


def make_feeder():
    f = Feeder()
    f.left_wheel = MagicMock()
    f.right_wheel = MagicMock()
    return f


class TestIntake:
    def test_left_wheel_spins_forward(self):
        f = make_feeder()
        f.intake()
        f.left_wheel.set.assert_called_with(constants.FEEDER_SPEED)

    def test_right_wheel_spins_backward(self):
        f = make_feeder()
        f.intake()
        f.right_wheel.set.assert_called_with(-constants.FEEDER_SPEED)

    def test_wheels_spin_opposite_directions(self):
        f = make_feeder()
        f.intake()
        left = f.left_wheel.set.call_args[0][0]
        right = f.right_wheel.set.call_args[0][0]
        assert left == -right, "Wheels should spin in opposite directions!"


class TestEject:
    def test_reverses_left_wheel(self):
        f = make_feeder()
        f.eject()
        f.left_wheel.set.assert_called_with(-constants.FEEDER_SPEED)

    def test_reverses_right_wheel(self):
        f = make_feeder()
        f.eject()
        f.right_wheel.set.assert_called_with(constants.FEEDER_SPEED)

    def test_eject_is_opposite_of_intake(self):
        f = make_feeder()
        f.intake()
        intake_left = f.left_wheel.set.call_args[0][0]
        f.eject()
        eject_left = f.left_wheel.set.call_args[0][0]
        assert intake_left == -eject_left


class TestStop:
    def test_stops_both_wheels(self):
        f = make_feeder()
        f.stop()
        f.left_wheel.stop_motor.assert_called_once()
        f.right_wheel.stop_motor.assert_called_once()
