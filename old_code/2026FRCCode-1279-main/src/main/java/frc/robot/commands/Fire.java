package frc.robot.commands;

import edu.wpi.first.wpilibj.Timer;
import edu.wpi.first.wpilibj2.command.Command;
//import frc.robot.RobotContainer;
import frc.robot.subsystems.OperatorSubsystem;

public class Fire extends Command
{
  private final OperatorSubsystem operatorSubsystem;

  private final Timer m_timer = new Timer();
  /**
   * Creates a new ShootCargo. 
   */
  public Fire(OperatorSubsystem operator)
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
  }

  // Called every time the scheduler runs while the command is scheduled.
  @Override
  public void execute()
  {
    //operatorSubsystem.shooterOut();
    operatorSubsystem.FIRE();
  }

  // Called once the command ends or is interrupted.
  @Override
  public void cancel()
  {
    operatorSubsystem.ceaseFire();
  }

  // Called once the command ends or is interrupted.
  @Override
  public void end(boolean interrupted)
  {
    operatorSubsystem.ceaseFire();
  }

  // Returns true when the command should end.
  @Override
  public boolean isFinished()
  {
    return false;
  }
}
