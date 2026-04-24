package frc.robot.commands;

import edu.wpi.first.wpilibj2.command.Command;
//import frc.robot.MotorControllers;
//import frc.robot.RobotContainer;
import frc.robot.subsystems.OperatorSubsystem;

public class FeederIn extends Command
{
  private final OperatorSubsystem operatorSubsystem;

  /**
   * Creates a new ShootCargo. 
   */
  public FeederIn(OperatorSubsystem operator)
  {
    operatorSubsystem = operator;
    // Use addRequirements() here to declare subsystem dependencies.
    addRequirements(operatorSubsystem);
  }

  // Called when the command is initially scheduled.
  @Override
  public void initialize()
  {
  }

  // Called every time the scheduler runs while the command is scheduled.
  @Override
  public void execute()
  {
      operatorSubsystem.feederIn();
  }

  // Called once the command ends or is interrupted.
  @Override
  public void cancel()
  {
    operatorSubsystem.stopFeeder();
  }

  // Called once the command ends or is interrupted.
  @Override
  public void end(boolean interrupted)
  {
    operatorSubsystem.stopFeeder();
  }

  // Returns true when the command should end.
  @Override
  public boolean isFinished()
  {
    return false; // PathPlanner zoned event controls start/stop
  }
}
