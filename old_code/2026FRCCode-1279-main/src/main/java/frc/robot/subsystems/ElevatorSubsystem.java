package frc.robot.subsystems;

//import com.ctre.phoenix.motorcontrol.ControlMode;
import edu.wpi.first.wpilibj2.command.SubsystemBase;
import frc.robot.MotorControllers;
import frc.robot.Constants;
//import frc.robot.Gamepads;
//import edu.wpi.first.wpilibj.Joystick;

public class ElevatorSubsystem extends SubsystemBase
{
  /**
   * Creates a new IntakeSubsystem.
   */
  public ElevatorSubsystem()
  {

  }

  //static Joystick operatorStick = Gamepads.operatorJoyStick;

  @Override
  public void periodic()
  {
    // This method will be called once per scheduler run
  }

  /*
  public void runElevator()
  {
    //double leftJoystickVal = operatorStick.getRawAxis(Constants.JoystickAxisIDs.LEFT_Y_AXIS);
    //double rightJoystickVal = operatorStick.getRawAxis(Constants.JoystickAxisIDs.RIGHT_Y_AXIS);
    double leftJoystickVal = operatorStick.getY();
    double rightJoystickVal = operatorStick.getY();

    if (leftJoystickVal != 0)
    {
      System.out.println("Left Trigger Value: " + leftJoystickVal);
      //MotorControllers.ElevatorMotor.set(leftTriggerVal);
      MotorControllers.ElevatorMotor.set(leftJoystickVal);
    } else {
      MotorControllers.ElevatorMotor.set(0.0);
    }
    if (rightJoystickVal != 0)
    {
      System.out.println("Right Trigger Value: " + rightJoystickVal);
      MotorControllers.RightElevatorMotor.set(rightJoystickVal);
    } else {
      MotorControllers.RightElevatorMotor.set(0.0);
    }
  }
    */

  public void elevatorUp()
  {
    if (MotorControllers.TopElevatorLimitSwitch.get())
    {
      MotorControllers.ElevatorMotor.set(-0.5);
      //MotorControllers.RightElevatorMotor.set(0.5);
    } else {
      stopElevator();
      MotorControllers.ElevatorMotor.set(0.0);
      //MotorControllers.RightElevatorMotor.set(0.0);
    }
  }

  public void elevatorDown()
  {
    if (MotorControllers.BottomElevatorLimitSwitch.get())
    {
      MotorControllers.ElevatorMotor.set(0.5);
      //MotorControllers.RightElevatorMotor.set(-0.5);
    } else {
      stopElevator();
      MotorControllers.ElevatorMotor.set(0.0);
      //MotorControllers.RightElevatorMotor.set(0.0);
    }
  }

  public void stopElevator()
  {
    MotorControllers.ElevatorMotor.stopMotor();
    //MotorControllers.RightElevatorMotor.stopMotor();
  }

  //public void rightElevatorExtend()
  //{
    //double rightTriggerVal = operatorStick.getRawAxis(Constants.JoystickAxisIDs.RIGHT_TRIGGER_ID);

    //if (rightTriggerVal > 0)
    //{
      //MotorControllers.RightElevatorMotor.set(ControlMode.PercentOutput, rightTriggerVal);
    //} else {
      //MotorControllers.RightElevatorMotor.set(ControlMode.PercentOutput,0.0);
    //}
    //MotorControllers.RightElevatorMotor.set(0.5);
  //}

  //public void rightElevatorRetract()
  //{
    //double rightTriggerVal = operatorStick.getRawAxis(Constants.JoystickAxisIDs.RIGHT_TRIGGER_ID);

    //if (rightTriggerVal > 0)
    //{
      //MotorControllers.RightElevatorMotor.set(ControlMode.PercentOutput, rightTriggerVal * -1.0);
    //} else {
      //MotorControllers.RightElevatorMotor.set(ControlMode.PercentOutput,0.0);
    //}
   // MotorControllers.RightElevatorMotor.set(-0.5);
  //}

  //public void rightElevatorStop()
  //{
  //  MotorControllers.RightElevatorMotor.stopMotor();
  //}

  public void ElevatorExtend()
  {
    //double leftTriggerVal = operatorStick.getRawAxis(Constants.JoystickAxisIDs.LEFT_TRIGGER_ID);

    //if (leftTriggerVal > 0)
    //{
      //MotorControllers.ElevatorMotor.set(ControlMode.PercentOutput, leftTriggerVal);
    //} else {
      //MotorControllers.ElevatorMotor.set(ControlMode.PercentOutput,0.0);
    //}
    MotorControllers.ElevatorMotor.set(0.5);
  }

  public void ElevatorRetract()
  {
    //double leftTriggerVal = operatorStick.getRawAxis(Constants.JoystickAxisIDs.LEFT_TRIGGER_ID);

    //if (leftTriggerVal > 0)
    //{
      //MotorControllers.ElevatorMotor.set(ControlMode.PercentOutput, leftTriggerVal * -1.0);
    //} else {
      //MotorControllers.ElevatorMotor.set(ControlMode.PercentOutput,0.0);
    //}
    MotorControllers.ElevatorMotor.set(-0.5);
  }

  public void zeroElevatorMotor()
  {
    /* Make sure we start at 0 */
    //MotorControllers.RightElevatorMotor.setPosition(0);
    MotorControllers.ElevatorMotor.setPosition(0);
  }

  public double getElevatorMotorPosition()
  {
    return round(MotorControllers.ElevatorMotor.getPosition().getValueAsDouble(),1);
  }

  public void rotateElevatorMotors(double rotRate)
  {
    // One full revolution equals 2048 ticks (for Falcon 500 encoder)

    //System.out.println("Rotation Rate: " + rotRate);

    //System.out.println("IN ROTATETESTMOTOR - Current Position: " + getTestMotorPosition());
    //MotorControllers.RightElevatorMotor.set(rotRate);
    MotorControllers.ElevatorMotor.set(rotRate * -1.0);
  }

  public boolean getTopElevatorLimitSwitch()
  {
    //Boolean limitValue = true;
    //return MotorControllers.LimitSwitchForIntake.get();
    //The NO terminal makes the circuit on 
    //when the switch is pressed, and off when the switch is not pressed
    //if (MotorControllers.LimitSwitchForFeeder.get())
    //{
    //  limitValue = false;
    //}
    //return limitValue;
    return MotorControllers.TopElevatorLimitSwitch.get();
  }

  public boolean getBottomElevatorLimitSwitch()
  {
    //Boolean limitValue = true;
    //return MotorControllers.LimitSwitchForIntake.get();
    //The NO terminal makes the circuit on 
    //when the switch is pressed, and off when the switch is not pressed
    //if (MotorControllers.LimitSwitchForFeeder.get())
    //{
    //  limitValue = false;
    //}
    //return limitValue;
    return MotorControllers.BottomElevatorLimitSwitch.get();
  }

  public static double round (double value, int decimalPlaces) 
  {
    if(decimalPlaces < 0 || decimalPlaces > 9) {
        throw new IllegalArgumentException("The specified decimalPlaces must be between 0 and 9 (inclusive).");
    }
    int scale = (int) Math.pow(10, decimalPlaces);
    double scaledUp = value * scale;
    double dec = scaledUp % 1d;
    double fixedDec = Math.round(dec*10)/10.;
    double newValue = scaledUp+fixedDec;

    return (double) Math.round( newValue )/scale;
  }

}
