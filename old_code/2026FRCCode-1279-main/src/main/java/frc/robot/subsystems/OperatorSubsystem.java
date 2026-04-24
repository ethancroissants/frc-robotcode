package frc.robot.subsystems;

import com.ctre.phoenix6.configs.Slot0Configs;

//import com.ctre.phoenix.motorcontrol.ControlMode;
//import com.ctre.phoenix.motorcontrol.FeedbackDevice;

//import com.ctre.phoenix6.StatusCode;
import com.ctre.phoenix6.configs.TalonFXConfiguration;
import com.ctre.phoenix6.controls.DutyCycleOut;
import com.ctre.phoenix6.controls.Follower;
//import com.ctre.phoenix6.controls.NeutralOut;
//import com.ctre.phoenix6.controls.PositionTorqueCurrentFOC;
import com.ctre.phoenix6.controls.PositionVoltage;
//import com.ctre.phoenix6.signals.getVelocity.VelocityValue;
//import com.ctre.phoenix6.signals.VelocityValue;
import com.ctre.phoenix6.controls.VelocityVoltage;
import com.ctre.phoenix6.signals.MotorAlignmentValue;

//import edu.wpi.first.units.measure.AngleUnit;
//import edu.wpi.first.units.measure.Angle;

//import edu.wpi.first.units.measure.*;
//import com.ctre.phoenix.motorcontrol.ControlMode;
import edu.wpi.first.wpilibj2.command.SubsystemBase;
import frc.robot.Constants;
import frc.robot.MotorControllers;
//import frc.robot.RobotContainer;

public class OperatorSubsystem extends SubsystemBase
{
      public Slot0Configs slot0Configs = new Slot0Configs();
 public final VelocityVoltage m_request = new VelocityVoltage(0).withSlot(0);
  TalonFXConfiguration configs = new TalonFXConfiguration();

  /* Be able to switch which control request to use based on a button press */
  PositionVoltage m_positionVoltage = new PositionVoltage(0);
  public boolean feederStatus = false;

  // Open-loop control request (percent output)
  private final DutyCycleOut dutyCycle = new DutyCycleOut(0);

  //Shooter Max speed
  private static final double SHOOTER_SPEED = 1.0; // Full speed

  /**
   * Creates a new OperatorSubsystem.
   */
  public OperatorSubsystem()
  {
      MotorControllers.Shooter2Motor.setControl(new Follower(10, MotorAlignmentValue.Aligned));

    slot0Configs.kP = 0.55;
    slot0Configs.kI = 0.05;
    slot0Configs.kD = 0.0;
    slot0Configs.kV = 0.12;

    MotorControllers.Shooter1Motor.getConfigurator().apply(slot0Configs);

  }

  @Override
  public void periodic()
  {
    // This method will be called once per scheduler run
  }

  /* START Feeder methods */
    public void feederIn()
    {
        MotorControllers.Feeder1Motor.set(Constants.MotorSpeeds.FEEDER); //CCW
        MotorControllers.Feeder2Motor.set(-1 * Constants.MotorSpeeds.FEEDER); //CW
        //MotorControllers.Feeder1Motor.setControl(MotorControllers.m_dutyCycleOut.withOutput(Constants.MotorSpeeds.FEEDER)); 
        //MotorControllers.Feeder2Motor.setControl(MotorControllers.m_dutyCycleOut.withOutput(-1 * Constants.MotorSpeeds.FEEDER));
    }
    
    public void feederOut()
    {
      MotorControllers.Feeder1Motor.set(-1 * Constants.MotorSpeeds.FEEDER); //CW
      MotorControllers.Feeder2Motor.set(Constants.MotorSpeeds.FEEDER); //CCW
    }
    
    public void stopFeeder()
    {
      MotorControllers.Feeder1Motor.stopMotor();
      MotorControllers.Feeder2Motor.stopMotor();
    }
  /* END Feeder methods */

  /* START Shooter methods */ 
    public void FIRE()
    {
      shooterOut();
      kickerIn();
      conveyorFwd();
    }

    public void LAUNCH()
    {
      farShooterOut();
      kickerIn();
      conveyorFwd();
    }

    public void ceaseFire()
    {
      stopKicker();
      stopConveyor();
      stopShooter();
    }

    public void shooterIn()
    {
        MotorControllers.Shooter1Motor.set(Constants.MotorSpeeds.SHOOTER); //CCW
  
      //  MotorControllers.Shooter2Motor.set(Constants.MotorSpeeds.SHOOTER); //CCW
    }
    
    public void shooterOut()
    {
      MotorControllers.Shooter1Motor.setControl(m_request.withVelocity(-39)); //CW
      //MotorControllers.Shooter2Motor.set(-1 * Constants.MotorSpeeds.SHOOTER); //CW
    }

    public void farShooterOut()
    {
      MotorControllers.Shooter1Motor.setControl(m_request.withVelocity(-60)); //CW
      //MotorControllers.Shooter2Motor.set(-1 * Constants.MotorSpeeds.LAUNCH); //CW
    }
    
    public void stopShooter()
    {
      MotorControllers.Shooter1Motor.set(0);
      //MotorControllers.Shooter2Motor.stopMotor();
    }

    public boolean isAtSpeed() {
        // Simplified: Assume instant readiness or check velocity sensor
        return true;
    }
  /* END Shooter methods */

  /* START Kicker methods */
    public void kickerIn()
    {
        MotorControllers.KickerMotor.set(Constants.MotorSpeeds.KICKER); //CCW
    }
    
    public void kickerOut()
    {
      MotorControllers.KickerMotor.set(-1 * Constants.MotorSpeeds.KICKER); //CW
    }
    
    public void stopKicker()
    {
      MotorControllers.KickerMotor.stopMotor();
    }
  /* END Kicker methods */
  
  /* START Carousel methods */
    public void conveyorFwd()
    {
        MotorControllers.ConveyorMotor.set(-1 * Constants.MotorSpeeds.CONVEYOR); //CW
    }
    
    public void conveyorRev()
    {
      MotorControllers.ConveyorMotor.set(Constants.MotorSpeeds.CONVEYOR); //CCW
    }
    
    public void stopConveyor()
    {
      MotorControllers.ConveyorMotor.stopMotor();
    }
  /* END Carousel methods */

  /* START Climber methods */
    public void elevatorUp()
    {
        MotorControllers.ElevatorMotor.set(-1 * Constants.MotorSpeeds.ELEVATOR);
    }
    
    public void elevatorDown()
    {
      MotorControllers.ElevatorMotor.set(Constants.MotorSpeeds.ELEVATOR);
    }
    
    public void stopElevator()
    {
      MotorControllers.ElevatorMotor.stopMotor();
    }
  /* END Climber methods */

  /* START Hood methods */
    public void hoodUp()
    {
        MotorControllers.HoodMotor.set(Constants.MotorSpeeds.HOOD); //CCW
    }
    
    public void hoodDown()
    {
      MotorControllers.HoodMotor.set(-1 * Constants.MotorSpeeds.HOOD); //CW
    }
    
    public void stopHood()
    {
      MotorControllers.HoodMotor.stopMotor();
    }

    public double getHoodMotorPosition()
    {
      return round(MotorControllers.HoodMotor.getPosition().getValueAsDouble(),1);
    }

    public void rotateHoodMotor(double rotRate)
    {
      MotorControllers.HoodMotor.set(rotRate * -1.0);
    }
  /* END Hood methods */

  /* START Wrist methods */
    public void wristUp()
    {
      if (limitSwitchForWristTop())
      {
        MotorControllers.WristMotor.stopMotor();
      //  MotorControllers.RightOperatorMotor.stopMotor();
      } else {
      //  MotorControllers.LeftOperatorMotor.set(1.0);
        MotorControllers.WristMotor.set(-1.0);
      }
    }
    
    public void wristDown()
    {
      if (limitSwitchForWristBottom())
      {
        MotorControllers.WristMotor.stopMotor();
      //  MotorControllers.RightOperatorMotor.stopMotor();
      } else {
      //  MotorControllers.LeftOperatorMotor.set(1.0);
        MotorControllers.WristMotor.set(1.0);
      }
      //MotorControllers.WristMotor.set(1.0);
    }
    
    public void stopWrist()
    {
      MotorControllers.WristMotor.stopMotor();
    }
  /* END Wrist methods */

  /*
   * These next 3 methods allow us to run a Test motor
   */
  public void runTestMotorFwd()
  {
    //MotorControllers.TestMotor.setControl(MotorControllers.m_dutyCycleOut.withOutput(0.5));
    MotorControllers.TestMotor.setControl(dutyCycle.withOutput(0.5));
    //talonFXS.setControl(dutyCycle.withOutput(output));
  }
  public void runTestMotorRev()
  {
    //MotorControllers.TestMotor.setControl(MotorControllers.m_dutyCycleOut.withOutput(-0.5));
    MotorControllers.TestMotor.setControl(dutyCycle.withOutput(-0.5));
  }
  public void stopTestMotor()
  {
    MotorControllers.TestMotor.stopMotor();
    MotorControllers.TestMotor.setControl(dutyCycle.withOutput(0.0));
  }

  public void configTestMotor()
  {
    /* Make sure we start at 0 */
    MotorControllers.TestMotor.setPosition(0);
  }

  public double getTestMotorPosition()
  {
    return round(MotorControllers.TestMotor.getPosition().getValueAsDouble(),1);
  }

  public void rotateTestMotor(double rotRate)
  {
    // One full revolution equals 2048 ticks (for Falcon 500 encoder)

    //System.out.println("Rotation Rate: " + rotRate);

    //System.out.println("IN ROTATETESTMOTOR - Current Position: " + getTestMotorPosition());
    MotorControllers.TestMotor.set(rotRate);
  }

  public boolean limitSwitchForWristTop()
  {
    //Boolean limitValue = true;
    //return MotorControllers.LimitSwitchForOperator.get();
    //The NO terminal makes the circuit on 
    //when the switch is pressed, and off when the switch is not pressed
    //if (MotorControllers.LimitSwitchForFeeder.get())
    //{
    //  limitValue = false;
    //}
    //return limitValue;
    return MotorControllers.WristTopLimitSwitch.get();
  }

  public boolean limitSwitchForWristBottom()
  {
    //Boolean limitValue = true;
    //return MotorControllers.LimitSwitchForOperator.get();
    //The NO terminal makes the circuit on 
    //when the switch is pressed, and off when the switch is not pressed
    //if (MotorControllers.LimitSwitchForFeeder.get())
    //{
    //  limitValue = false;
    //}
    //return limitValue;
    return MotorControllers.WristBottomLimitSwitch.get();
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
