"""Class that contains the driver and operator buttons."""

from commands2.button import CommandXboxController, JoystickButton, POVButton, Trigger
from wpilib import Joystick, XboxController

import constants


# Drive Gamepad/Joystick
driverJoyStick = Joystick(constants.GamePadIDs.DRIVER_GAMEPAD_ID)
# Operator Gamepad/Joystick
operatorJoyStick = Joystick(constants.GamePadIDs.OPERATOR_GAMEPAD_ID)


def getGamepad(stickId):
    if stickId == constants.GamePadIDs.DRIVER_GAMEPAD_ID:
        return driverJoyStick
    if stickId == constants.GamePadIDs.OPERATOR_GAMEPAD_ID:
        return operatorJoyStick
    return driverJoyStick  # failsafe


driverController = XboxController(constants.GamePadIDs.DRIVER_GAMEPAD_ID)
operatorController = CommandXboxController(constants.GamePadIDs.OPERATOR_GAMEPAD_ID)


# OPERATOR BUTTONS
operator_A_Button = operatorController.a()
operator_B_Button = operatorController.b()
operator_X_Button = operatorController.x()
operator_Y_Button = operatorController.y()
operator_leftShoulderButton = operatorController.leftBumper()
operator_rightShoulderButton = operatorController.rightBumper()
operator_backButton = operatorController.back()
operator_startButton = operatorController.start()
operator_leftStickButton = operatorController.leftStick()
operator_rightStickButton = operatorController.rightStick()
operator_leftTrigger = operatorController.leftTrigger()
operator_rightTrigger = operatorController.rightTrigger()

operator_POVButton = POVButton(operatorJoyStick, 0)


# DRIVER BUTTONS
driver_A_Button = JoystickButton(driverController, XboxController.Button.kA)
driver_B_Button = JoystickButton(driverController, XboxController.Button.kB)
driver_X_Button = JoystickButton(driverController, XboxController.Button.kX)
driver_Y_Button = JoystickButton(driverController, XboxController.Button.kY)
driver_leftShoulderButton = JoystickButton(driverController, XboxController.Button.kLeftBumper)
driver_rightShoulderButton = JoystickButton(driverController, XboxController.Button.kRightBumper)
driver_backButton = JoystickButton(driverController, XboxController.Button.kBack)
driver_startButton = JoystickButton(driverController, XboxController.Button.kStart)
driver_leftStickButton = JoystickButton(driverController, XboxController.Button.kLeftStick)
driver_rightStickButton = JoystickButton(driverController, XboxController.Button.kRightStick)

driver_POVButton = POVButton(driverJoyStick, 0)
