"""Motor controller definitions for the robot."""

from phoenix6.controls import DutyCycleOut
from phoenix6.hardware import TalonFX, TalonFXS
from wpilib import DigitalInput

import constants


# Competition drive train w/ Falcon 500's
frontLeftSteer = TalonFX(constants.ControllerIDs.FALCON_FRONT_LEFT_STEER_ID)
rearLeftSteer = TalonFX(constants.ControllerIDs.FALCON_REAR_LEFT_STEER_ID)
frontRightSteer = TalonFX(constants.ControllerIDs.FALCON_FRONT_RIGHT_STEER_ID)
rearRightSteer = TalonFX(constants.ControllerIDs.FALCON_REAR_RIGHT_STEER_ID)
frontLeftDrive = TalonFX(constants.ControllerIDs.KRAKEN_FRONT_LEFT_DRIVE_ID)
rearLeftDrive = TalonFX(constants.ControllerIDs.KRAKEN_REAR_LEFT_DRIVE_ID)
frontRightDrive = TalonFX(constants.ControllerIDs.KRAKEN_FRONT_RIGHT_DRIVE_ID)
rearRightDrive = TalonFX(constants.ControllerIDs.KRAKEN_REAR_RIGHT_DRIVE_ID)

# Game component controllers
# Feeder - Minion
Feeder1Motor = TalonFXS(constants.ControllerIDs.FEEDER1_DRIVE_ID)
Feeder2Motor = TalonFXS(constants.ControllerIDs.FEEDER2_DRIVE_ID)
# Shooter - Kraken
Shooter1Motor = TalonFX(constants.ControllerIDs.SHOOTER1_DRIVE_ID)
Shooter2Motor = TalonFX(constants.ControllerIDs.SHOOTER2_DRIVE_ID)

# Kicker - Minion
KickerMotor = TalonFXS(constants.ControllerIDs.KICKER_DRIVE_ID)
# Carousel - Kraken
ConveyorMotor = TalonFX(constants.ControllerIDs.CONVEYOR_DRIVE_ID)
# Hood - Minion
HoodMotor = TalonFXS(constants.ControllerIDs.HOOD_DRIVE_ID)
# Climber - Kraken
ElevatorMotor = TalonFX(constants.ControllerIDs.ELEVATOR_DRIVE_ID)
# Wrist - Kraken
WristMotor = TalonFX(constants.ControllerIDs.WRIST_DRIVE_ID)
# Test Motor
TestMotor = TalonFXS(constants.ControllerIDs.MINION_DRIVE_ID)
m_dutyCycleOut = DutyCycleOut(0)

# Limit switches
TopElevatorLimitSwitch = DigitalInput(constants.Switches.elevatorTopLimitSwitch)
BottomElevatorLimitSwitch = DigitalInput(constants.Switches.elevatorBottomLimitSwitch)
WristTopLimitSwitch = DigitalInput(constants.Switches.wristTopLimitSwitch)
WristBottomLimitSwitch = DigitalInput(constants.Switches.wristBottomLimitSwitch)
