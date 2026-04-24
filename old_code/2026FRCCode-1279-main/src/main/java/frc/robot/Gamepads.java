package frc.robot;

import edu.wpi.first.wpilibj.Joystick;
import edu.wpi.first.wpilibj.XboxController;
//import edu.wpi.first.wpilibj2.command.button.;
import edu.wpi.first.wpilibj2.command.button.JoystickButton;
import edu.wpi.first.wpilibj2.command.button.Trigger;
//import edu.wpi.first.wpilibj2.command.button.CommandPS4Controller;
import edu.wpi.first.wpilibj2.command.button.CommandXboxController;
import edu.wpi.first.wpilibj2.command.button.POVButton;

/**
* Class that contains the driver and operator buttons
*/
public class Gamepads 
{
    //Create Drive Gamepad/Joystick
    public static Joystick driverJoyStick = new Joystick(Constants.GamePadIDs.DRIVER_GAMEPAD_ID);
    //Create Operator Gamepad/Joystick
    public static Joystick operatorJoyStick = new Joystick(Constants.GamePadIDs.OPERATOR_GAMEPAD_ID);

    public static Joystick getGamepad(int stickId)
    {
        if (stickId == Constants.GamePadIDs.DRIVER_GAMEPAD_ID)
        {
            return driverJoyStick;
        }
        if (stickId == Constants.GamePadIDs.OPERATOR_GAMEPAD_ID)
        {
            return operatorJoyStick;
        }
        return driverJoyStick; // failsafe
    }

    public static XboxController driverController = new XboxController(Constants.GamePadIDs.DRIVER_GAMEPAD_ID); 
    //public static XboxController operatorController = new XboxController(Constants.GamePadIDs.OPERATOR_GAMEPAD_ID); 
    public static CommandXboxController operatorController = new CommandXboxController(Constants.GamePadIDs.OPERATOR_GAMEPAD_ID);
    

    // Buttons are defined as follows:
    // static Button driver_ButtonName or operator_ButtonName = new JoystickButton(JoystickName, NumberOnController)
    //      static (allows for us to use in other classes)
    //      Trigger (Name of class)
    //      driver_ButtonName or operator_ButtonName (name of the button on the controller)
    //      new JoystickButton (name of the class for the Button)
    //      JoystickName (name of the joystick. will either be the driver or operator controller)
    //      NumberOnController (number that corresponds to the button on the controller)

    /********************
     * OPERATOR BUTTONS *
     ********************/
    static Trigger operator_A_Button = new Gamepads().operatorController.a(); //new JoystickButton(operatorController, XboxController.Button.kA.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton operator_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger operator_B_Button = new Gamepads().operatorController.b(); //new JoystickButton(operatorController, XboxController.Button.kB.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger operator_X_Button = new Gamepads().operatorController.x(); //new JoystickButton(operatorController, XboxController.Button.kX.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger operator_Y_Button = new Gamepads().operatorController.y(); //new JoystickButton(operatorController, XboxController.Button.kY.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger operator_leftShoulderButton = new Gamepads().operatorController.leftBumper(); //new JoystickButton(operatorController, XboxController.Button.kLeftBumper.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger operator_rightShoulderButton = new Gamepads().operatorController.rightBumper(); //new JoystickButton(operatorController, XboxController.Button.kRightBumper.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger operator_backButton = new Gamepads().operatorController.back(); //new JoystickButton(operatorController, XboxController.Button.kBack.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger operator_startButton = new Gamepads().operatorController.start(); //new JoystickButton(operatorController, XboxController.Button.kStart.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger operator_leftStickButton = new Gamepads().operatorController.leftStick(); //new JoystickButton(operatorController, XboxController.Button.kLeftStick.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger operator_rightStickButton = new Gamepads().operatorController.rightStick(); //new JoystickButton(operatorController, XboxController.Button.kRightStick.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger operator_leftTrigger = new Gamepads().operatorController.leftTrigger();
    static Trigger operator_rightTrigger = new Gamepads().operatorController.rightTrigger();
    
     /*
    static JoystickButton operator_A_Button = new JoystickButton(operatorJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static JoystickButton operator_B_Button = new JoystickButton(operatorJoyStick, Constants.ButtonIDs.B_BUTTON_ID);
    static JoystickButton operator_X_Button = new JoystickButton(operatorJoyStick, Constants.ButtonIDs.X_BUTTON_ID);
    static JoystickButton operator_Y_Button = new JoystickButton(operatorJoyStick, Constants.ButtonIDs.Y_BUTTON_ID);
    static JoystickButton operator_leftShoulderButton = new JoystickButton(operatorJoyStick, Constants.ButtonIDs.LEFT_SHOULDER_BUTTON_ID);
    static JoystickButton operator_rightShoulderButton = new JoystickButton(operatorJoyStick, Constants.ButtonIDs.RIGHT_SHOULDER_BUTTON_ID);
    static JoystickButton operator_backButton = new JoystickButton(operatorJoyStick, Constants.ButtonIDs.BACK_BUTTON_ID);
    static JoystickButton operator_startButton = new JoystickButton(operatorJoyStick, Constants.ButtonIDs.START_BUTTON_ID);
    static JoystickButton operator_leftStickButton = new JoystickButton(operatorJoyStick, Constants.ButtonIDs.LEFT_STICK_BUTTON_ID);
    static JoystickButton operator_rightStickButton = new JoystickButton(operatorJoyStick, Constants.ButtonIDs.RIGHT_STICK_BUTTON_ID);
    */
    static POVButton operator_POVButton = new POVButton(operatorJoyStick, 0);
    //static Trigger operator_leftTrigger = new Trigger();
    //static Trigger operator_rightTrigger = new Trigger();

    /******************
     * DRIVER BUTTONS *
     ******************/
    static Trigger driver_A_Button = new JoystickButton(driverController, XboxController.Button.kA.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger driver_B_Button = new JoystickButton(driverController, XboxController.Button.kB.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger driver_X_Button = new JoystickButton(driverController, XboxController.Button.kX.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger driver_Y_Button = new JoystickButton(driverController, XboxController.Button.kY.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger driver_leftShoulderButton = new JoystickButton(driverController, XboxController.Button.kLeftBumper.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger driver_rightShoulderButton = new JoystickButton(driverController, XboxController.Button.kRightBumper.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger driver_backButton = new JoystickButton(driverController, XboxController.Button.kBack.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger driver_startButton = new JoystickButton(driverController, XboxController.Button.kStart.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger driver_leftStickButton = new JoystickButton(driverController, XboxController.Button.kLeftStick.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    static Trigger driver_rightStickButton = new JoystickButton(driverController, XboxController.Button.kRightStick.value); // Creates a new JoystickButton object for the `Y` button on exampleController     static JoystickButton driver_A_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.A_BUTTON_ID);
    /* 
    static JoystickButton driver_B_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.B_BUTTON_ID);
    static JoystickButton driver_X_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.X_BUTTON_ID);
    static JoystickButton driver_Y_Button = new JoystickButton(driverJoyStick, Constants.ButtonIDs.Y_BUTTON_ID);
    static JoystickButton driver_leftShoulderButton = new JoystickButton(driverJoyStick, Constants.ButtonIDs.LEFT_SHOULDER_BUTTON_ID);
    static JoystickButton driver_rightShoulderButton = new JoystickButton(driverJoyStick, Constants.ButtonIDs.RIGHT_SHOULDER_BUTTON_ID);
    static JoystickButton driver_backButton = new JoystickButton(driverJoyStick, Constants.ButtonIDs.BACK_BUTTON_ID);
    static JoystickButton driver_startButton = new JoystickButton(driverJoyStick, Constants.ButtonIDs.START_BUTTON_ID);
    static JoystickButton driver_leftStickButton = new JoystickButton(driverJoyStick, Constants.ButtonIDs.LEFT_STICK_BUTTON_ID);
    static JoystickButton driver_rightStickButton = new JoystickButton(driverJoyStick, Constants.ButtonIDs.RIGHT_STICK_BUTTON_ID);
    */
    static POVButton driver_POVButton = new POVButton(driverJoyStick, 0);
    //static Trigger driver_leftTrigger = new Trigger();
    //static Trigger driver_rightTrigger = new Trigger();
}
