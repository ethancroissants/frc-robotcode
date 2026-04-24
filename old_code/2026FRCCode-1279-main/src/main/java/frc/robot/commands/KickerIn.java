package frc.robot.commands;

import edu.wpi.first.wpilibj.Timer;
import edu.wpi.first.wpilibj2.command.Command;
import frc.robot.MotorControllers;
//import frc.robot.RobotContainer;
import frc.robot.subsystems.OperatorSubsystem;

public class KickerIn extends Command
{
  private final OperatorSubsystem operatorSubsystem;

  private final Timer m_timer = new Timer();
  /**
   * Creates a new ShootCargo. 
   */
  public KickerIn(OperatorSubsystem operator)
  {
    operatorSubsystem = operator;
  // Use addRequirements() here to declare subsystem dependencies.
    addRequirements(operatorSubsystem);
  //  addRequirements(RobotContainer.conveyor);
  }

  // Called when the command is initially scheduled.
  @Override
  public void initialize()
  {
    m_timer.reset();
    m_timer.start();
    //operatorSubsystem.kickerStatus = false;
    //if (MotorControllers.FeederLimitSwitch.get()) //switch is pressed
    //{
    //  operatorSubsystem.feederStatus = true;
    //}
  }

  // Called every time the scheduler runs while the command is scheduled.
  @Override
  public void execute()
  {
    //if (MotorControllers.FeederLimitSwitch.get() && !operatorSubsystem.feederStatus) //switch is pressed & switch was NOT previously pressed
    //{
    //  operatorSubsystem.feederStatus = true;
    //}
    //if (!MotorControllers.FeederLimitSwitch.get() && operatorSubsystem.feederStatus) //switch is NOT pressed & switch was previously pressed
    //{ 
       //operatorSubsystem.feederStop();
    //} else {
      operatorSubsystem.kickerIn();
    //}
  }

  // Called once the command ends or is interrupted.
  @Override
  public void cancel()
  {
    operatorSubsystem.stopKicker();
    //operatorSubsystem.feederStatus = true;
  }

  // Called once the command ends or is interrupted.
  @Override
  public void end(boolean interrupted)
  {
    operatorSubsystem.stopKicker();
    //operatorSubsystem.feederStatus = true;
  }

  // Returns true when the command should end.
  @Override
  public boolean isFinished()
  {
    boolean retValue = false;
    //if (MotorControllers.FeederLimitSwitch.get() && operatorSubsystem.feederStatus)
    //{ 
    //   retValue = true;
    //}
    return retValue;
  }
}
