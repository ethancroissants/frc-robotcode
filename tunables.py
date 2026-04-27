"""Live-tunable values published to SmartDashboard.

publish_defaults() runs once at startup so every key shows up on the dashboard
with its compiled-in default. After that, the getter functions read the
current dashboard value each call — edit it on Shuffleboard/SmartDashboard/
Elastic and the change takes effect on the next loop. The constants.py
defaults are the fallback if NetworkTables doesn't have the key yet.

update() also drives a change-confirmation chirp: when a tunable moves while
the robot is disabled, we play a short two-tone sequence through a TalonFX via
Phoenix's MusicTone (the RoboRIO has no speaker, so the motor coil is the
buzzer). Beeps suppress while enabled to avoid commandeering a motor mid-match.
"""

import time
from typing import Callable

from phoenix6.controls import MusicTone
from wpilib import SmartDashboard

import constants


# Shooter timings / velocities
_SHOOTER_SPIN_UP = "Tune/Shooter Spin-Up (s)"
_SHOOTER_NEAR_VEL = "Tune/Shooter Near Velocity (rps)"
_SHOOTER_FAR_VEL = "Tune/Shooter Far Velocity (rps)"
_AUTO_FIRE_DURATION = "Tune/AutoFire Fire Duration After Spin-Up (s)"

# Open-loop motor speeds
_SHOOTER_OPEN = "Tune/Shooter Open-Loop Speed"
_KICKER_SPEED = "Tune/Kicker Speed"
_CONVEYOR_SPEED = "Tune/Conveyor Speed"
_FEEDER_SPEED = "Tune/Feeder Speed"
_HOOD_SPEED = "Tune/Hood Speed"
_ELEVATOR_SPEED = "Tune/Elevator Speed"


# Defaults that don't live in constants.py yet — keep them here as the single
# source of truth rather than scattering magic numbers.
_DEFAULT_SHOOTER_NEAR_VEL = 95.0
_DEFAULT_SHOOTER_FAR_VEL = 100.0
_DEFAULT_AUTO_FIRE_DURATION = 3.0


def publish_defaults() -> None:
    SmartDashboard.putNumber(
        _SHOOTER_SPIN_UP, constants.MotorSpeeds.SHOOTER_SPIN_UP_SECONDS
    )
    SmartDashboard.putNumber(_SHOOTER_NEAR_VEL, _DEFAULT_SHOOTER_NEAR_VEL)
    SmartDashboard.putNumber(_SHOOTER_FAR_VEL, _DEFAULT_SHOOTER_FAR_VEL)
    SmartDashboard.putNumber(_AUTO_FIRE_DURATION, _DEFAULT_AUTO_FIRE_DURATION)
    SmartDashboard.putNumber(_SHOOTER_OPEN, constants.MotorSpeeds.SHOOTER)
    SmartDashboard.putNumber(_KICKER_SPEED, constants.MotorSpeeds.KICKER)
    SmartDashboard.putNumber(_CONVEYOR_SPEED, constants.MotorSpeeds.CONVEYOR)
    SmartDashboard.putNumber(_FEEDER_SPEED, constants.MotorSpeeds.FEEDER)
    SmartDashboard.putNumber(_HOOD_SPEED, constants.MotorSpeeds.HOOD)
    SmartDashboard.putNumber(_ELEVATOR_SPEED, constants.MotorSpeeds.ELEVATOR)


def shooter_spin_up_seconds() -> float:
    return SmartDashboard.getNumber(
        _SHOOTER_SPIN_UP, constants.MotorSpeeds.SHOOTER_SPIN_UP_SECONDS
    )


def shooter_near_velocity() -> float:
    return SmartDashboard.getNumber(_SHOOTER_NEAR_VEL, _DEFAULT_SHOOTER_NEAR_VEL)


def shooter_far_velocity() -> float:
    return SmartDashboard.getNumber(_SHOOTER_FAR_VEL, _DEFAULT_SHOOTER_FAR_VEL)


def auto_fire_duration() -> float:
    return SmartDashboard.getNumber(_AUTO_FIRE_DURATION, _DEFAULT_AUTO_FIRE_DURATION)


def shooter_open_speed() -> float:
    return SmartDashboard.getNumber(_SHOOTER_OPEN, constants.MotorSpeeds.SHOOTER)


def kicker_speed() -> float:
    return SmartDashboard.getNumber(_KICKER_SPEED, constants.MotorSpeeds.KICKER)


def conveyor_speed() -> float:
    return SmartDashboard.getNumber(_CONVEYOR_SPEED, constants.MotorSpeeds.CONVEYOR)


def feeder_speed() -> float:
    return SmartDashboard.getNumber(_FEEDER_SPEED, constants.MotorSpeeds.FEEDER)


def hood_speed() -> float:
    return SmartDashboard.getNumber(_HOOD_SPEED, constants.MotorSpeeds.HOOD)


def elevator_speed() -> float:
    return SmartDashboard.getNumber(_ELEVATOR_SPEED, constants.MotorSpeeds.ELEVATOR)


# All dashboard keys to watch, with their fallback default for the read-back.
_TUNABLES: list[tuple[str, Callable[[], float]]] = [
    (_SHOOTER_SPIN_UP, lambda: constants.MotorSpeeds.SHOOTER_SPIN_UP_SECONDS),
    (_SHOOTER_NEAR_VEL, lambda: _DEFAULT_SHOOTER_NEAR_VEL),
    (_SHOOTER_FAR_VEL, lambda: _DEFAULT_SHOOTER_FAR_VEL),
    (_AUTO_FIRE_DURATION, lambda: _DEFAULT_AUTO_FIRE_DURATION),
    (_SHOOTER_OPEN, lambda: constants.MotorSpeeds.SHOOTER),
    (_KICKER_SPEED, lambda: constants.MotorSpeeds.KICKER),
    (_CONVEYOR_SPEED, lambda: constants.MotorSpeeds.CONVEYOR),
    (_FEEDER_SPEED, lambda: constants.MotorSpeeds.FEEDER),
    (_HOOD_SPEED, lambda: constants.MotorSpeeds.HOOD),
    (_ELEVATOR_SPEED, lambda: constants.MotorSpeeds.ELEVATOR),
]

# Two ascending beeps with short gaps. (frequency Hz, duration s); 0 Hz = silent.
_BEEP_SEQUENCE: list[tuple[float, float]] = [
    (880.0, 0.08),
    (0.0, 0.04),
    (1319.0, 0.10),
    (0.0, 0.04),
]

_last_values: dict[str, float] = {}
_beep_motor = None
_beep_tone = MusicTone(0.0)
_beep_start_time: float | None = None


def configure_beep_motor(motor) -> None:
    """Pick the TalonFX/FXS that plays change-confirmation tones."""
    global _beep_motor
    _beep_motor = motor


def _poll_changes() -> bool:
    changed = False
    for key, default_fn in _TUNABLES:
        current = SmartDashboard.getNumber(key, default_fn())
        prev = _last_values.get(key)
        _last_values[key] = current
        if prev is not None and current != prev:
            changed = True
    return changed


def update(robot_enabled: bool) -> None:
    """Call from robotPeriodic. Plays a beep when a tunable just changed."""
    global _beep_start_time
    changed = _poll_changes()

    if _beep_motor is None:
        return

    if robot_enabled:
        # Silence any in-flight chirp so cached MusicTone doesn't ring into the match.
        if _beep_start_time is not None:
            _beep_motor.set_control(_beep_tone.with_audio_frequency(0.0))
            _beep_start_time = None
        return

    if changed and _beep_start_time is None:
        _beep_start_time = time.monotonic()

    if _beep_start_time is None:
        return

    elapsed = time.monotonic() - _beep_start_time
    cumulative = 0.0
    for freq, dur in _BEEP_SEQUENCE:
        cumulative += dur
        if elapsed < cumulative:
            _beep_motor.set_control(_beep_tone.with_audio_frequency(freq))
            return

    _beep_motor.set_control(_beep_tone.with_audio_frequency(0.0))
    _beep_start_time = None
