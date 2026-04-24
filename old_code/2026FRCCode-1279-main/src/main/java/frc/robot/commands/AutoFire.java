package frc.robot.commands;

import edu.wpi.first.wpilibj.Timer;
import edu.wpi.first.wpilibj2.command.Command;
//import frc.robot.RobotContainer;
import frc.robot.subsystems.OperatorSubsystem;

public class AutoFire extends Command
{
  private final OperatorSubsystem operatorSubsystem;

  private final Timer m_timer = new Timer();
  /**
   * Creates a new ShootCargo. 
   */
  public AutoFire(OperatorSubsystem operator)
  {
    operatorSubsystem = operator;
    // Use addRequirements() here to declare subsystem dependencies.
    addRequirements(operatorSubsystem);
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
    if (m_timer.get() < 0.7) // Spin up the shooter for 0.5 seconds before running the kicker and conveyor to feed balls into the shooter
    {
      operatorSubsystem.shooterOut(); //Run the shooter only to get it up to speed before feeding balls into it
    } else {
      operatorSubsystem.FIRE(); //Run the kicker and conveyor to feed balls into the shooter
    }
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
    if (m_timer.get() > 4.0) // command will run for 4 seconds, then end
    {
      return true;
    } else {
      return false;
    }
  }
}
