package frc.robot.commands;

import edu.wpi.first.wpilibj.Timer;
import edu.wpi.first.wpilibj2.command.Command;
//import frc.robot.RobotContainer;
import frc.robot.subsystems.ElevatorSubsystem;

public class ElevatorDown extends Command
{
  private final ElevatorSubsystem elevatorSubsystem;

  private final Timer m_timer = new Timer();
  /**
   * Creates a new ShootCargo. 
   */
  public ElevatorDown(ElevatorSubsystem elevator)
  {
    elevatorSubsystem = elevator;
  // Use addRequirements() here to declare subsystem dependencies.
    addRequirements(elevatorSubsystem);
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
    elevatorSubsystem.elevatorDown();
  }

  // Called once the command ends or is interrupted.
  @Override
  public void cancel()
  {
    elevatorSubsystem.stopElevator();
  }

  // Called once the command ends or is interrupted.
  @Override
  public void end(boolean interrupted)
  {
    elevatorSubsystem.stopElevator();
  }

  // Returns true when the command should end.
  @Override
  public boolean isFinished()
  {
    return false;
  }
}
