# ============================================================
# CONSTANTS - All the important numbers for our robot
# ============================================================
# This file is like a settings page. Instead of hiding numbers
# deep inside other files, we put them all here so they're
# easy to find and change.
#
# Swerve constants are from Tuner X (the old Java code's
# TunerConstants.java), so they match the actual hardware.
# ============================================================

import math


# --- MOTOR CAN IDS ---
# Every motor on the robot has a unique ID number, like a name tag.
# The robot uses these IDs to talk to the right motor.

# Swerve drive motors (the 4 wheels that let us drive in any direction)
FRONT_LEFT_DRIVE_ID = 24
FRONT_LEFT_STEER_ID = 23
FRONT_RIGHT_DRIVE_ID = 28
FRONT_RIGHT_STEER_ID = 27
REAR_LEFT_DRIVE_ID = 22
REAR_LEFT_STEER_ID = 21
REAR_RIGHT_DRIVE_ID = 26
REAR_RIGHT_STEER_ID = 25

# Game piece motors (the motors that handle balls)
FEEDER_LEFT_ID = 4       # Left feeder wheel  (picks up balls from ground)
FEEDER_RIGHT_ID = 5      # Right feeder wheel
CONVEYOR_ID = 6           # Conveyor belt       (moves balls inside the robot)
ELEVATOR_ID = 8           # Elevator motor      (moves the elevator up/down)
KICKER_ID = 9             # Kicker wheel        (pushes ball into shooter)
SHOOTER_LEFT_ID = 10      # Left shooter wheel  (spins fast to launch balls)
SHOOTER_RIGHT_ID = 11     # Right shooter wheel
HOOD_ID = 12              # Hood motor          (tilts the shooter up/down to aim)

# CANcoder IDs (absolute encoders on each swerve wheel)
FRONT_LEFT_ENCODER_ID = 32
FRONT_RIGHT_ENCODER_ID = 34
REAR_LEFT_ENCODER_ID = 31
REAR_RIGHT_ENCODER_ID = 33

# Pigeon2 IMU (gyroscope -- tells us which way the robot is facing)
PIGEON_ID = 0


# --- SWERVE MODULE POSITIONS ---
# Where each wheel is relative to the center of the robot (in meters).
# These come from TunerConstants.java: 9.875" x 11.75"
SWERVE_FL_X = 0.250825    # 9.875 inches forward
SWERVE_FL_Y = 0.29845     # 11.75 inches left
SWERVE_FR_X = 0.250825
SWERVE_FR_Y = -0.29845    # 11.75 inches right
SWERVE_BL_X = -0.250825   # 9.875 inches backward
SWERVE_BL_Y = 0.29845
SWERVE_BR_X = -0.250825
SWERVE_BR_Y = -0.29845

# --- CANCODER OFFSETS ---
# Each CANcoder has a magnet that might not be perfectly aligned.
# These offsets correct for that (in rotations, from Tuner X).
FL_ENCODER_OFFSET = 0.326904296875
FR_ENCODER_OFFSET = -0.322998046875
BL_ENCODER_OFFSET = 0.18896484375
BR_ENCODER_OFFSET = -0.274169921875

# --- SWERVE GEAR RATIOS ---
# From TunerConstants.java (Tuner X generated values)
DRIVE_GEAR_RATIO = 6.746031746031747    # motor rotations per wheel rotation
STEER_GEAR_RATIO = 21.428571428571427   # motor rotations per wheel rotation
WHEEL_RADIUS_METERS = 0.0508           # 2 inches

# --- SWERVE DRIVE SPEEDS ---
MAX_SPEED_MPS = 4.58                          # meters/sec at 12V (from Tuner X)
MAX_ANGULAR_RATE = 0.75 * 2 * math.pi         # 0.75 rotations/sec in rad/s

# --- SWERVE STEER PID ---
# These control how accurately each wheel points.
# Scaled from Tuner X values (P=100, D=0.5) for motor-position control.
# Original values are for FusedCANcoder (1 rotation = 1 wheel rotation).
# Motor position has gear ratio applied, so we divide by gear ratio.
STEER_P = 4.7      # 100 / 21.43
STEER_I = 0.0
STEER_D = 0.023    # 0.5 / 21.43

# --- DRIVE INVERSION ---
# The right side motors spin the opposite direction to go forward
LEFT_SIDE_INVERTED = False
RIGHT_SIDE_INVERTED = True

# All steer motors are inverted (from Tuner X)
STEER_INVERTED = True

# --- INPUT DEADBAND ---
# Ignore tiny joystick movements (stick drift)
DRIVE_DEADBAND = 0.1   # 10% deadband (matches old code)


# --- GAMEPAD PORTS ---
# We use two Xbox controllers: one for driving, one for operating mechanisms
DRIVER_GAMEPAD_PORT = 0
OPERATOR_GAMEPAD_PORT = 1


# --- MOTOR SPEEDS ---
# These control how fast each motor spins.
# 1.0 = full speed, 0.5 = half speed, 0.0 = stopped
SHOOTER_SPEED = 0.5
KICKER_SPEED = 0.9
CONVEYOR_SPEED = 1.0
HOOD_SPEED = 0.2
FEEDER_SPEED = 0.5
ELEVATOR_SPEED = 0.6
LAUNCH_SPEED = 0.7

# Shooter velocity targets (rotations per second, used for precise speed control)
SHOOTER_CLOSE_VELOCITY = -39   # Speed for shooting nearby targets
SHOOTER_FAR_VELOCITY = -60     # Speed for shooting far away targets


# --- DRIVE SPEED MULTIPLIERS ---
# How fast the whole robot moves around the field
DRIVE_FULL_SPEED = 1.0     # Normal driving speed (multiplier)
DRIVE_SLOW_SPEED = 0.6     # Slow mode for careful driving


# --- ELEVATOR POSITIONS ---
# The elevator can go to specific heights (measured in encoder ticks)
ELEVATOR_BOTTOM = 0.0       # All the way down
ELEVATOR_LOADING = 19.0     # Height for loading game pieces
ELEVATOR_LEVEL_1 = 58.0     # Low scoring position
ELEVATOR_LEVEL_2 = 86.0     # Medium scoring position
ELEVATOR_LEVEL_3 = 110.0    # High scoring position


# --- LIMIT SWITCHES ---
# These are physical switches that tell us when something has
# reached its maximum or minimum position (like a door stopper)
ELEVATOR_TOP_SWITCH = 0
ELEVATOR_BOTTOM_SWITCH = 1


# --- PID TUNING ---
# PID is a math formula that helps motors move to exact positions smoothly.
# P = how aggressively it corrects errors
# I = fixes small lingering errors over time
# D = slows down as it approaches the target (prevents overshooting)
SHOOTER_P = 0.55
SHOOTER_I = 0.05
SHOOTER_D = 0.0
SHOOTER_V = 0.12    # Feedforward: gives the motor a head start

ELEVATOR_P = 0.478
ELEVATOR_I = 0.0
ELEVATOR_D = 0.0
