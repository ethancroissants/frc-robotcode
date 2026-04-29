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


# Shooter timings / distance
_SHOOTER_SPIN_UP = "Tune/Shooter Spin-Up (s)"
_SHOOTER_DISTANCE = "Tune/Shooter Distance (ft)"
_AUTO_FIRE_DURATION = "Tune/AutoFire Fire Duration After Spin-Up (s)"

# Open-loop motor speeds
_SHOOTER_OPEN = "Tune/Shooter Open-Loop Speed"
_KICKER_SPEED = "Tune/Kicker Speed"
_CONVEYOR_SPEED = "Tune/Conveyor Speed"
_FEEDER_SPEED = "Tune/Feeder Speed"
_HOOD_SPEED = "Tune/Hood Speed"
_ELEVATOR_SPEED = "Tune/Elevator Speed"

# Camera-sight calibration. The trajectory arc and landing reticle are projected
# through a pinhole model with these parameters. FOV / height are measured by hand;
# tilt is solved by the auto-calibrate button (vision.py) so the model matches what
# the driver actually sees through the lens.
_SIGHT_FOV_DEG = "Tune/Sight Camera FOV (deg)"
_SIGHT_CAM_HEIGHT_M = "Tune/Sight Camera Height (m)"
_SIGHT_CAM_TILT_RAD = "Tune/Sight Camera Tilt (rad)"
_SIGHT_EXIT_ANGLE_DEG = "Tune/Sight Shooter Exit Angle (deg)"
_SIGHT_RELEASE_HEIGHT_M = "Tune/Sight Shooter Release Height (m)"
_SIGHT_SPEED_PER_RPS = "Tune/Sight Ball Speed Per RPS (m)"
_SIGHT_CALIBRATE = "Tune/Calibrate Sight"  # boolean trigger
_SIGHT_CALIBRATE_TRUE_FT = "Tune/Calibrate Sight True Distance (ft)"
_SIGHT_PREDICTED_LANDING_FT = "Tune/Sight Predicted Landing (ft)"


# Defaults that don't live in constants.py yet — keep them here as the single
# source of truth rather than scattering magic numbers.
_DEFAULT_SHOOTER_DISTANCE_FEET = 10.0
_DEFAULT_AUTO_FIRE_DURATION = 3.0

# Sight defaults — webcam ~60° H-FOV, mounted ~0.5m up, looking slightly down.
# Exit angle 45° is the textbook max-range; release height ≈ 0.5m approximates
# where the ball leaves the shooter. speed_per_rps assumes a 4" wheel at ~50%
# transfer efficiency (π·0.1016m·0.5 ≈ 0.16 m/rev). Recalibrate when you measure.
_DEFAULT_SIGHT_FOV_DEG = 60.0
_DEFAULT_SIGHT_CAM_HEIGHT_M = 0.5
_DEFAULT_SIGHT_CAM_TILT_RAD = 0.1
_DEFAULT_SIGHT_EXIT_ANGLE_DEG = 45.0
_DEFAULT_SIGHT_RELEASE_HEIGHT_M = 0.5
_DEFAULT_SIGHT_SPEED_PER_RPS = 0.16
_DEFAULT_SIGHT_CALIBRATE_TRUE_FT = 10.0

# Linear distance→velocity mapping for the flywheel. Anchored at 10 ft = 100 rps
# (the previous calibrated "far" setpoint) and 0 ft = 0 rps. The old 60 rps floor
# meant 4 ft launched at 76 rps and overshot wildly — keep this honest until we
# have real shot data across the range.
_SHOOTER_BASE_RPS = 0.0
_SHOOTER_RPS_PER_FOOT = 10.0


def publish_defaults() -> None:
    SmartDashboard.putNumber(
        _SHOOTER_SPIN_UP, constants.MotorSpeeds.SHOOTER_SPIN_UP_SECONDS
    )
    SmartDashboard.putNumber(_SHOOTER_DISTANCE, _DEFAULT_SHOOTER_DISTANCE_FEET)
    SmartDashboard.putNumber(_AUTO_FIRE_DURATION, _DEFAULT_AUTO_FIRE_DURATION)
    SmartDashboard.putNumber(_SHOOTER_OPEN, constants.MotorSpeeds.SHOOTER)
    SmartDashboard.putNumber(_KICKER_SPEED, constants.MotorSpeeds.KICKER)
    SmartDashboard.putNumber(_CONVEYOR_SPEED, constants.MotorSpeeds.CONVEYOR)
    SmartDashboard.putNumber(_FEEDER_SPEED, constants.MotorSpeeds.FEEDER)
    SmartDashboard.putNumber(_HOOD_SPEED, constants.MotorSpeeds.HOOD)
    SmartDashboard.putNumber(_ELEVATOR_SPEED, constants.MotorSpeeds.ELEVATOR)
    SmartDashboard.putNumber(_SIGHT_FOV_DEG, _DEFAULT_SIGHT_FOV_DEG)
    SmartDashboard.putNumber(_SIGHT_CAM_HEIGHT_M, _DEFAULT_SIGHT_CAM_HEIGHT_M)
    SmartDashboard.putNumber(_SIGHT_CAM_TILT_RAD, _DEFAULT_SIGHT_CAM_TILT_RAD)
    SmartDashboard.putNumber(_SIGHT_EXIT_ANGLE_DEG, _DEFAULT_SIGHT_EXIT_ANGLE_DEG)
    SmartDashboard.putNumber(_SIGHT_RELEASE_HEIGHT_M, _DEFAULT_SIGHT_RELEASE_HEIGHT_M)
    SmartDashboard.putNumber(_SIGHT_SPEED_PER_RPS, _DEFAULT_SIGHT_SPEED_PER_RPS)
    SmartDashboard.putBoolean(_SIGHT_CALIBRATE, False)
    SmartDashboard.putNumber(_SIGHT_CALIBRATE_TRUE_FT, _DEFAULT_SIGHT_CALIBRATE_TRUE_FT)
    SmartDashboard.putNumber(_SIGHT_PREDICTED_LANDING_FT, 0.0)


def shooter_spin_up_seconds() -> float:
    return SmartDashboard.getNumber(
        _SHOOTER_SPIN_UP, constants.MotorSpeeds.SHOOTER_SPIN_UP_SECONDS
    )


def shooter_distance_feet() -> float:
    return SmartDashboard.getNumber(_SHOOTER_DISTANCE, _DEFAULT_SHOOTER_DISTANCE_FEET)


def bump_shooter_distance(delta_feet: float) -> None:
    """Nudge the dashboard shot distance. Used by the camera-sight POV bindings."""
    new_value = max(0.0, shooter_distance_feet() + delta_feet)
    SmartDashboard.putNumber(_SHOOTER_DISTANCE, new_value)


def shooter_velocity_rps() -> float:
    """Flywheel rps for the currently dialed-in shot distance.

    One knob (distance, in feet) replaces the old near/far velocity pair —
    drivers tune for "where am I shooting from", not "what rps does that
    need". The mapping is linear; recalibrate the constants above if shots
    consistently undershoot or overshoot.
    """
    return _SHOOTER_BASE_RPS + _SHOOTER_RPS_PER_FOOT * shooter_distance_feet()


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


def sight_fov_deg() -> float:
    return SmartDashboard.getNumber(_SIGHT_FOV_DEG, _DEFAULT_SIGHT_FOV_DEG)


def sight_camera_height_m() -> float:
    return SmartDashboard.getNumber(_SIGHT_CAM_HEIGHT_M, _DEFAULT_SIGHT_CAM_HEIGHT_M)


def sight_camera_tilt_rad() -> float:
    return SmartDashboard.getNumber(_SIGHT_CAM_TILT_RAD, _DEFAULT_SIGHT_CAM_TILT_RAD)


def set_sight_camera_tilt_rad(value: float) -> None:
    SmartDashboard.putNumber(_SIGHT_CAM_TILT_RAD, value)


def sight_exit_angle_deg() -> float:
    return SmartDashboard.getNumber(_SIGHT_EXIT_ANGLE_DEG, _DEFAULT_SIGHT_EXIT_ANGLE_DEG)


def sight_release_height_m() -> float:
    return SmartDashboard.getNumber(_SIGHT_RELEASE_HEIGHT_M, _DEFAULT_SIGHT_RELEASE_HEIGHT_M)


def sight_speed_per_rps() -> float:
    return SmartDashboard.getNumber(_SIGHT_SPEED_PER_RPS, _DEFAULT_SIGHT_SPEED_PER_RPS)


def sight_calibrate_requested() -> bool:
    return SmartDashboard.getBoolean(_SIGHT_CALIBRATE, False)


def clear_sight_calibrate_request() -> None:
    SmartDashboard.putBoolean(_SIGHT_CALIBRATE, False)


def sight_calibrate_true_distance_ft() -> float:
    return SmartDashboard.getNumber(
        _SIGHT_CALIBRATE_TRUE_FT, _DEFAULT_SIGHT_CALIBRATE_TRUE_FT
    )


def set_sight_predicted_landing_ft(value: float) -> None:
    SmartDashboard.putNumber(_SIGHT_PREDICTED_LANDING_FT, value)


# All dashboard keys to watch, with their fallback default for the read-back.
_TUNABLES: list[tuple[str, Callable[[], float]]] = [
    (_SHOOTER_SPIN_UP, lambda: constants.MotorSpeeds.SHOOTER_SPIN_UP_SECONDS),
    (_SHOOTER_DISTANCE, lambda: _DEFAULT_SHOOTER_DISTANCE_FEET),
    (_AUTO_FIRE_DURATION, lambda: _DEFAULT_AUTO_FIRE_DURATION),
    (_SHOOTER_OPEN, lambda: constants.MotorSpeeds.SHOOTER),
    (_KICKER_SPEED, lambda: constants.MotorSpeeds.KICKER),
    (_CONVEYOR_SPEED, lambda: constants.MotorSpeeds.CONVEYOR),
    (_FEEDER_SPEED, lambda: constants.MotorSpeeds.FEEDER),
    (_HOOD_SPEED, lambda: constants.MotorSpeeds.HOOD),
    (_ELEVATOR_SPEED, lambda: constants.MotorSpeeds.ELEVATOR),
    (_SIGHT_FOV_DEG, lambda: _DEFAULT_SIGHT_FOV_DEG),
    (_SIGHT_CAM_HEIGHT_M, lambda: _DEFAULT_SIGHT_CAM_HEIGHT_M),
    (_SIGHT_CAM_TILT_RAD, lambda: _DEFAULT_SIGHT_CAM_TILT_RAD),
    (_SIGHT_EXIT_ANGLE_DEG, lambda: _DEFAULT_SIGHT_EXIT_ANGLE_DEG),
    (_SIGHT_RELEASE_HEIGHT_M, lambda: _DEFAULT_SIGHT_RELEASE_HEIGHT_M),
    (_SIGHT_SPEED_PER_RPS, lambda: _DEFAULT_SIGHT_SPEED_PER_RPS),
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
