package frc.robot;

//import com.ctre.phoenix.motorcontrol.can.TalonSRX;
//import com.ctre.phoenix.motorcontrol.can.TalonFX;
//import com.ctre.phoenix.motorcontrol.can.TalonFXConfiguration;
//import com.ctre.phoenix.motorcontrol.can.TalonFXPIDSetConfiguration;
import com.ctre.phoenix6.hardware.TalonFX;
import com.ctre.phoenix6.hardware.TalonFXS;

import com.ctre.phoenix6.configs.*;
import com.ctre.phoenix6.controls.DutyCycleOut; //Control request for percent output
import com.ctre.phoenix6.signals.InvertedValue;
import com.ctre.phoenix6.signals.NeutralModeValue;
//import com.ctre.phoenix.motorcontrol.ControlMode;
//import com.ctre.phoenix.motorcontrol.FeedbackDevice;
//import com.ctre.phoenix.motorcontrol.SupplyCurrentLimitConfiguration; //StatorCurrentLimitConfiguration;

import com.ctre.phoenix.motorcontrol.can.WPI_TalonSRX; //Talon Motor Controllers
//import com.ctre.phoenix.motorcontrol.can.WPI_TalonFX; //Falcon 500 Controller
//import com.ctre.phoenix.motorcontrol.can.WPI_VictorSPX;
//import edu.wpi.first.wpilibj.SpeedControllerGroup;
//import edu.wpi.first.wpilibj.motorcontrol.MotorController;
//import edu.wpi.first.wpilibj.motorcontrol.MotorControllerGroup;
//import edu.wpi.first.wpilibj.motorcontrol.PWMTalonFX;
//import edu.wpi.first.wpilibj.motorcontrol.PWMMotorController;
import edu.wpi.first.wpilibj.DigitalInput;

/**
* Contains the Motor Controller definitions
*/
public class MotorControllers 
{
    /*******************************************/
    /* START OF MOTOR CONTOLLER CONFIGURATIONS */
    /*******************************************/
        /* Way to define a Motor Controller */
        /* public static WPI_TalonSRX nameOfTalon = new WPI_TalonSRX(TalonNumber); */
    
    /***********************************************/
    /* For competition drive train w/ Falcon 500's */
    /***********************************************/
    public static TalonFX frontLeftSteer = new TalonFX(Constants.ControllerIDs.FALCON_FRONT_LEFT_STEER_ID);
    public static TalonFX rearLeftSteer = new TalonFX(Constants.ControllerIDs.FALCON_REAR_LEFT_STEER_ID);
    public static TalonFX frontRightSteer = new TalonFX(Constants.ControllerIDs.FALCON_FRONT_RIGHT_STEER_ID);
    public static TalonFX rearRightSteer = new TalonFX(Constants.ControllerIDs.FALCON_REAR_RIGHT_STEER_ID);
    public static TalonFX frontLeftDrive = new TalonFX(Constants.ControllerIDs.KRAKEN_FRONT_LEFT_DRIVE_ID);
    public static TalonFX rearLeftDrive = new TalonFX(Constants.ControllerIDs.KRAKEN_REAR_LEFT_DRIVE_ID);
    public static TalonFX frontRightDrive = new TalonFX(Constants.ControllerIDs.KRAKEN_FRONT_RIGHT_DRIVE_ID);
    public static TalonFX rearRightDrive = new TalonFX(Constants.ControllerIDs.KRAKEN_REAR_RIGHT_DRIVE_ID);
    
    //public static WPI_VictorSPX rearLeft = new WPI_VictorSPX(Constants.ControllerIDs.TALON_REAR_LEFT_DRIVE_ID);
    /******************************/
    /* Game component controllers */
    /******************************/
    //Operator
    //Feeder - Minion
    public static TalonFXS Feeder1Motor = new TalonFXS(Constants.ControllerIDs.FEEDER1_DRIVE_ID); //LEFT MOTOR
    public static TalonFXS Feeder2Motor = new TalonFXS(Constants.ControllerIDs.FEEDER2_DRIVE_ID); //RIGHT MOTOR
    //Shooter - Kraken
    public static TalonFX Shooter1Motor = new TalonFX(Constants.ControllerIDs.SHOOTER1_DRIVE_ID); //FRONT MOTOR
    public static TalonFX Shooter2Motor = new TalonFX(Constants.ControllerIDs.SHOOTER2_DRIVE_ID); //REAR MOTOR

    // Apply the config added to TunerConstants
    //Shooter1Motor.getConfigurator().apply(TunerConstants.kShooterInitialConfigs);
    //Shooter2Motor.getConfigurator().apply(TunerConstants.kShooterInitialConfigs);

    //Kicker - Minion
    public static TalonFXS KickerMotor = new TalonFXS(Constants.ControllerIDs.KICKER_DRIVE_ID);
    //Carousel - Kraken
    public static TalonFX ConveyorMotor = new TalonFX(Constants.ControllerIDs.CONVEYOR_DRIVE_ID);
    //Hood - Minion
    public static TalonFXS HoodMotor = new TalonFXS(Constants.ControllerIDs.HOOD_DRIVE_ID);
    //Climber - Kraken
    public static TalonFX ElevatorMotor = new TalonFX(Constants.ControllerIDs.ELEVATOR_DRIVE_ID);
    //Wrist - Kraken
    public static TalonFX WristMotor = new TalonFX(Constants.ControllerIDs.WRIST_DRIVE_ID);
    //Test Motor
    public static TalonFXS TestMotor = new TalonFXS(Constants.ControllerIDs.MINION_DRIVE_ID);
    public static DutyCycleOut m_dutyCycleOut = new DutyCycleOut(0);


    //Code for Vector Motor Controllers
    //public static WPI_VictorSPX frontRight = new WPI_VictorSPX(11);
    //public static WPI_VictorSPX rearRight = new WPI_VictorSPX(10);

    /*****************************************/
    /* END OF MOTOR CONTROLLER CONFIGURATIONS */
    /*****************************************/

    /*******************************/
    /* LIMIT SWITCH CONFIGURATIONS */
    /*******************************/
    public static DigitalInput TopElevatorLimitSwitch = new DigitalInput(Constants.Switches.elevatorTopLimitSwitch);
    public static DigitalInput BottomElevatorLimitSwitch = new DigitalInput(Constants.Switches.elevatorBottomLimitSwitch);
    public static DigitalInput WristTopLimitSwitch = new DigitalInput(Constants.Switches.wristTopLimitSwitch);
    public static DigitalInput WristBottomLimitSwitch = new DigitalInput(Constants.Switches.wristBottomLimitSwitch);

    /*************************/
    /* SWITCH CONFIGURATIONS */
    /*************************/
    //public static DigitalInput autoSettingSwitch = new DigitalInput(Constants.Switches.autonomousSettingSwitch);
}
