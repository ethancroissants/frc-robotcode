package frc.robot.commands;

import edu.wpi.first.wpilibj.Timer;
import edu.wpi.first.wpilibj2.command.Command;
//import frc.robot.subsystems.ElevatorSubsystem;
import frc.robot.subsystems.OperatorSubsystem;

public class POVPressed extends Command
{
  //private final ElevatorSubsystem elevatorSubsystem;

  private final Timer m_timer = new Timer();
  /**
   * Creates a new ShootCargo. 
   */
  public POVPressed(OperatorSubsystem operator)
  {
    //elevatorSubsystem = elevator;
  // Use addRequirements() here to declare subsystem dependencies.
    //addRequirements(elevatorSubsystem);
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
    /*
    .getPOV() returns an int, either -1 if nothing is pressed, or:
    up: 0
    topRight: 45
    right: 90
    bottomRight: 135
    bottom: 180
    bottomLeft: 225
    left: 270
    topLeft: 315
    */
    //Get POV value an call command based on value
  }

  // Called once the command ends or is interrupted.
  @Override
  public void cancel()
  {
    //operatorSubsystem.operatorStop();
  }

  // Called once the command ends or is interrupted.
  @Override
  public void end(boolean interrupted)
  {
    //operatorSubsystem.operatorStop();
  }

  // Returns true when the command should end.
  @Override
  public boolean isFinished()
  {
    return false;
  }
}
