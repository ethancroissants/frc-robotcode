# ============================================================
# TESTS FOR HOOD SUBSYSTEM
# ============================================================

import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import constants
from subsystems.hood import Hood


def make_hood():
    h = Hood()
    h.motor = MagicMock()
    return h


class TestDirections:
    def test_tilt_up_positive(self):
        h = make_hood()
        h.tilt_up()
        h.motor.set.assert_called_with(constants.HOOD_SPEED)

    def test_tilt_down_negative(self):
        h = make_hood()
        h.tilt_down()
        h.motor.set.assert_called_with(-constants.HOOD_SPEED)

    def test_up_and_down_are_opposite(self):
        h1 = make_hood()
        h1.tilt_up()
        up = h1.motor.set.call_args[0][0]

        h2 = make_hood()
        h2.tilt_down()
        down = h2.motor.set.call_args[0][0]

        assert up == -down


class TestStop:
    def test_stop(self):
        h = make_hood()
        h.stop()
        h.motor.stop_motor.assert_called_once()


class TestHoodSpeed:
    def test_hood_speed_is_slow(self):
        assert constants.HOOD_SPEED <= 0.5, "Hood should move slowly for precise aiming"
