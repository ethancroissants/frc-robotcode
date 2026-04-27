"""Live-tunable values published to SmartDashboard.

publish_defaults() runs once at startup so every key shows up on the dashboard
with its compiled-in default. After that, the getter functions read the
current dashboard value each call — edit it on Shuffleboard/SmartDashboard/
Elastic and the change takes effect on the next loop. The constants.py
defaults are the fallback if NetworkTables doesn't have the key yet.
"""

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
