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

from phoenix6.configs import AudioConfigs
from phoenix6.controls import MusicTone, NeutralOut
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

# Two ascending beeps with short gaps. (frequency Hz, duration s); freq <= 0 is silent.
# Pitched an octave below the obvious A5/E6 choice: motor-coil amplitude is V/(R+jωL),
# so halving the frequency roughly doubles the current swing — much louder mechanical
# sound, still well above any rotational concern and right in the ear's sensitive band.
_BEEP_SEQUENCE: list[tuple[float, float]] = [
    (440.0, 0.15),
    (0.0, 0.05),
    (660.0, 0.20),
    (0.0, 0.05),
]

_last_values: dict[str, float] = {}
_beep_motors: list = []
# Phoenix's control timeout is ~25ms — at the default MusicTone update rate the
# motor will revert to neutral if a robot loop slips. Pin the update rate up so
# a single missed loop doesn't cut the tone short.
_beep_tone = MusicTone(0.0).with_update_freq_hz(200.0)
_beep_silence = NeutralOut()
_beep_start_time: float | None = None

# Phoenix mutes MusicTone while the robot is disabled unless this is True.
# We tune in the pit (disabled), so the audio gate has to be open there.
_beep_audio_configs = AudioConfigs().with_allow_music_dur_disable(True)


def configure_beep_motors(*motors) -> None:
    """Pick the TalonFXs that play change-confirmation tones in unison.

    MusicTone has no software volume — the only way to crank it up is to
    vibrate more coils at once. Pass every TalonFX that's safe to commandeer
    while disabled (idle, no follower obligations the caller hasn't already
    accepted will reset).
    """
    global _beep_motors
    _beep_motors = list(motors)
    apply_beep_audio()


def configure_beep_motor(motor) -> None:
    """Back-compat single-motor wrapper for configure_beep_motors."""
    configure_beep_motors(motor)


def apply_beep_audio() -> None:
    """(Re)apply the audio config that lets beep motors play while disabled.

    Call this any time something does a full configurator.apply() on a beep
    motor — a TalonFXConfiguration apply resets AudioConfigs back to defaults.
    """
    for motor in _beep_motors:
        motor.configurator.apply(_beep_audio_configs)


def _poll_changes() -> bool:
    changed = False
    for key, default_fn in _TUNABLES:
        current = SmartDashboard.getNumber(key, default_fn())
        prev = _last_values.get(key)
        _last_values[key] = current
        if prev is not None and current != prev:
            changed = True
    return changed


def _set_all(control) -> None:
    for motor in _beep_motors:
        motor.set_control(control)


def update(robot_enabled: bool) -> None:
    """Call from robotPeriodic. Plays a beep when a tunable just changed."""
    global _beep_start_time
    changed = _poll_changes()

    if not _beep_motors:
        return

    if robot_enabled:
        # Silence any in-flight chirp so cached MusicTone doesn't ring into the match.
        if _beep_start_time is not None:
            _set_all(_beep_silence)
            _beep_start_time = None
        return

    # Re-trigger from the start on every change, even mid-beep — the user just edited
    # another value and wants confirmation, not the tail of the previous chirp.
    if changed:
        _beep_start_time = time.monotonic()

    if _beep_start_time is None:
        return

    elapsed = time.monotonic() - _beep_start_time
    cumulative = 0.0
    for freq, dur in _BEEP_SEQUENCE:
        cumulative += dur
        if elapsed < cumulative:
            if freq > 0.0:
                _set_all(_beep_tone.with_audio_frequency(freq))
            else:
                # NeutralOut is a hard stop; MusicTone(0) is undefined and on some
                # firmware leaves the coil singing at the previous frequency.
                _set_all(_beep_silence)
            return

    _set_all(_beep_silence)
    _beep_start_time = None
