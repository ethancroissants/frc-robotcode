package frc.robot.commands;

//import edu.wpi.first.wpilibj.Timer;
import edu.wpi.first.wpilibj2.command.Command;
//import frc.robot.MotorControllers;
import frc.robot.subsystems.ElevatorSubsystem;

public class RunElevatorToTopPID extends Command
{
  private final ElevatorSubsystem elevatorSubsystem;

  //private final Timer m_timer = new Timer();

  private double startPosition;
  private double position0 = 55.0; // This is the position we want the elevator motor to stop at for climbing
  private double rotationRate = 0.5; // This is the speed at which the elevator motor will rotate
  private double rotationdir;
  
  public RunElevatorToTopPID(ElevatorSubsystem elevator)
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
    //m_timer.reset();
    //m_timer.start();
    startPosition = elevatorSubsystem.getElevatorMotorPosition();
    //System.out.println("Button Clicked:");
    //System.out.println("================================");
    //System.out.println("Start Position: " + startPosition);
    //System.out.println("Position0: " + position0);
    if (startPosition < position0)
    {
      rotationdir = 1;
    }
    else if (startPosition > position0)
    {
      rotationdir = -1;
    }
    else
    {
      rotationdir = 0.0;
    }
    //System.out.println("Rotation Direction: " + rotationdir);

    elevatorSubsystem.rotateElevatorMotors(rotationdir * rotationRate);
  }
  
  // Called every time the scheduler runs while the command is scheduled.
  @Override
  public void execute()
  {
    //double rotationdir = 0.1;
    //intakeSubsystem.configElevatorMotor();
    //System.out.println("Elevator Motor Position: " + intakeSubsystem.getElevatorMotorPosition());
    double currPosition = elevatorSubsystem.getElevatorMotorPosition();
    System.out.println(currPosition + "--" + position0);
    if (rotationdir > 0 && elevatorSubsystem.getElevatorMotorPosition() >= position0)
    {
      elevatorSubsystem.stopElevator();
    }
    else if (rotationdir < 0 && elevatorSubsystem.getElevatorMotorPosition() <= position0)
    {
      elevatorSubsystem.stopElevator();
    } 
  }

  // Called once the command ends or is interrupted.
  @Override
  public void cancel()
  {
    elevatorSubsystem.stopElevator();
    System.out.println("Elevator CANCELED");
  }

  // Called once the command ends or is interrupted.
  @Override
  public void end(boolean interrupted)
  {
    elevatorSubsystem.stopElevator();
    System.out.println("================================");
    System.out.println("Finishing Position: " + elevatorSubsystem.getElevatorMotorPosition());
    System.out.println("================================");
  }

  // Returns true when the command should end.
  @Override
  public boolean isFinished()
  {
    /*
    boolean retVal = false;

    if (rotationdir > 0)
    {
      return elevatorSubsystem.getElevatorMotorPosition() >= position0;
    }
    else if (rotationdir < 0)
    {
      return elevatorSubsystem.getElevatorMotorPosition() <= position0;
    } else {
      return retVal;
    }
    */
    return false;
  }
}
