// Copyright (c) FIRST and other WPILib contributors.
// Open Source Software; you can modify and/or share it under the terms of
// the WPILib BSD license file in the root directory of this project.

package frc.robot;

import static edu.wpi.first.units.Units.*;

import edu.wpi.first.wpilibj.DriverStation;
import edu.wpi.first.wpilibj.Timer;
import frc.robot.commands.*;
import frc.robot.subsystems.*;
import com.ctre.phoenix6.swerve.SwerveModule.DriveRequestType;
import com.ctre.phoenix6.swerve.SwerveRequest;

import java.util.Set;

import com.pathplanner.lib.auto.AutoBuilder;
import com.pathplanner.lib.auto.NamedCommands;

import edu.wpi.first.math.geometry.Rotation2d;
import edu.wpi.first.wpilibj2.command.Command;
import edu.wpi.first.wpilibj2.command.CommandScheduler;import edu.wpi.first.wpilibj.smartdashboard.SendableChooser;
import edu.wpi.first.wpilibj.smartdashboard.SmartDashboard;
import edu.wpi.first.wpilibj2.command.Commands;
import edu.wpi.first.wpilibj2.command.button.CommandXboxController;
import edu.wpi.first.wpilibj2.command.button.RobotModeTriggers;
import edu.wpi.first.wpilibj2.command.sysid.SysIdRoutine.Direction;

import frc.robot.generated.TunerConstants;
import edu.wpi.first.math.filter.Debouncer;

public class RobotContainer {
    private double MaxSpeed = 1.0 * TunerConstants.kSpeedAt12Volts.in(MetersPerSecond); // kSpeedAt12Volts desired top speed
    private double MaxAngularRate = RotationsPerSecond.of(0.75).in(RadiansPerSecond); // 3/4 of a rotation per second max angular velocity

    /* Setting up bindings for necessary control of the swerve drive platform */
    private final SwerveRequest.FieldCentric drive = new SwerveRequest.FieldCentric()
            .withDeadband(MaxSpeed * 0.1).withRotationalDeadband(MaxAngularRate * 0.1) // Add a 10% deadband
            .withDriveRequestType(DriveRequestType.OpenLoopVoltage); // Use open-loop control for drive motors
    private final SwerveRequest.SwerveDriveBrake brake = new SwerveRequest.SwerveDriveBrake();
    private final SwerveRequest.PointWheelsAt point = new SwerveRequest.PointWheelsAt();

    private final Telemetry logger = new Telemetry(MaxSpeed);

    public final CommandSwerveDrivetrain drivetrain = TunerConstants.createDrivetrain();

    private final SendableChooser<Command> autoChooser;
    
    
  public static OperatorSubsystem operator = new OperatorSubsystem();
  public static ElevatorSubsystem elevator = new ElevatorSubsystem();

  public static MotorControllers motors = new MotorControllers();

  // Feeder Commands
  private FeederIn feederIn = new FeederIn(operator);
  private FeederOut feederOut = new FeederOut(operator);
  private StopFeeder stopFeeder = new StopFeeder(operator);
  // Shooter Commands
  private Fire fire = new Fire(operator);
  private AutoFire autoFire = new AutoFire(operator);
  private Launch launch = new Launch(operator);
  private CeaseFire ceaseFire = new CeaseFire(operator);
  private ClearOut clearOut = new ClearOut(operator);
  //private Shoot shoot = new Shoot(operator);
  private StopShooter stopShooter = new StopShooter(operator);
  private ClearShooter clearShooter = new ClearShooter(operator);
  public static String targetingMessage = "";
  //private AutoScoreCommand autoScoreCommand = new AutoScoreCommand(drivetrain, vision, operator);
  // Kicker Commands
  private KickerIn kickerIn = new KickerIn(operator);
  private KickerOut kickerOut = new KickerOut(operator);
  private StopKicker stopKicker = new StopKicker(operator);
  // Conveyor Commands
  private ConveyorFwd conveyorFwd = new ConveyorFwd(operator);
  private ConveyorRev conveyorRev = new ConveyorRev(operator);
  private StopConveyor stopConveyor = new StopConveyor(operator);
  // Hood Commands
  private HoodUp hoodUp = new HoodUp(operator);
  private HoodDown hoodDown = new HoodDown(operator);
  private StopHood stopHood = new StopHood(operator);
  // Elevator Commands
  private RunElevatorToTopPID runElevatorToTopPID = new RunElevatorToTopPID(elevator);
  private ElevatorUp elevatorUp = new ElevatorUp(elevator);
  private ElevatorDown elevatorDown = new ElevatorDown(elevator);
  private StopElevator stopElevator = new StopElevator(elevator);

  // AprilTagAlign
  // AprilTagAlign ATA = new AprilTagAlign(drivetrain);

  private DriveSlow driveSlow = new DriveSlow(drivetrain);
  private DriveNormal driveNormal = new DriveNormal(drivetrain);

    public RobotContainer() {
        // Register named commands with PathPlanner before AutoBuilder is used.
        // Replace Commands.none() with the real command once each subsystem is added.
        NamedCommands.registerCommand("Shoot",        Commands.defer(() -> new AutoFire(operator),   Set.of(operator))); // Turn on shooter, kicker, and conveyor to shoot balls
        NamedCommands.registerCommand("FeederIn",     Commands.defer(() -> new FeederIn(operator),   Set.of(operator))); // Pickup balls from the floor
    
        // Build the auto chooser from all .auto files in deploy/pathplanner/autos/
        autoChooser = AutoBuilder.buildAutoChooser(); 
        SmartDashboard.putData("Auto Chooser", autoChooser); 

        configureBindings();
    }

    private void configureBindings() {
        // Note that X is defined as forward according to WPILib convention,
        // and Y is defined as to the left according to WPILib convention.
        drivetrain.setDefaultCommand(
            // Drivetrain will execute this command periodically
            drivetrain.applyRequest(() ->
                //drive.withVelocityX(-joystick.getLeftY() * MaxSpeed) // Drive forward with negative Y (forward)
                drive.withVelocityX(-Gamepads.driverController.getLeftY() * MaxSpeed) // Drive forward with negative Y (forward)
                    .withVelocityY(-Gamepads.driverController.getLeftX() * MaxSpeed) // Drive left with negative X (left)
                    .withRotationalRate(Gamepads.driverController.getRightX() * MaxAngularRate) // Drive counterclockwise with negative X (left)
            )
        );

        // Idle while the robot is disabled. This ensures the configured
        // neutral mode is applied to the drive motors while disabled.
        final var idle = new SwerveRequest.Idle();
        RobotModeTriggers.disabled().whileTrue(
            drivetrain.applyRequest(() -> idle).ignoringDisable(true)
        );

        // Apply brake when X button pressed
        Gamepads.driver_X_Button.whileTrue(drivetrain.applyRequest(() -> brake));
        // Automatically point robot in ??? direction when B button pressed ????
        Gamepads.driver_B_Button.whileTrue(drivetrain.applyRequest(() -> point.withModuleDirection(
        new Rotation2d(-Gamepads.driverController.getLeftY(), -Gamepads.driverController.getLeftX()))));
        //joystick.a().whileTrue(drivetrain.applyRequest(() -> brake));
        //joystick.b().whileTrue(drivetrain.applyRequest(() ->
        //    point.withModuleDirection(new Rotation2d(-joystick.getLeftY(), -joystick.getLeftX()))
        //));

        // Run SysId routines when holding back/start and X/Y.
        // Note that each routine should be run exactly once in a single log.
        //joystick.back().and(joystick.y()).whileTrue(drivetrain.sysIdDynamic(Direction.kForward));
        Gamepads.driver_backButton.and(Gamepads.driver_Y_Button).whileTrue(drivetrain.sysIdDynamic(Direction.kForward));
        Gamepads.driver_backButton.and(Gamepads.driver_X_Button).whileTrue(drivetrain.sysIdDynamic(Direction.kReverse));
        //joystick.start().and(joystick.y()).whileTrue(drivetrain.sysIdQuasistatic(Direction.kForward));
        Gamepads.driver_startButton.and(Gamepads.driver_Y_Button).whileTrue(drivetrain.sysIdQuasistatic(Direction.kForward));
        //joystick.start().and(joystick.x()).whileTrue(drivetrain.sysIdQuasistatic(Direction.kReverse));
        Gamepads.driver_startButton.and(Gamepads.driver_X_Button).whileTrue(drivetrain.sysIdQuasistatic(Direction.kReverse));

        // Reset the field-centric heading on left bumper press.
        Gamepads.driver_leftShoulderButton.debounce(0.1, Debouncer.DebounceType.kBoth)
        .onTrue(drivetrain.runOnce(() -> drivetrain.seedFieldCentric()));
	/***************************
     * Driver Controller Setup *
     ***************************/
    // Drive slow when right bumper is held
    Gamepads.driver_rightShoulderButton.debounce(0.1, Debouncer.DebounceType.kBoth)
        .whileTrue(driveSlow)
        .onFalse(driveNormal);

	// reset the field-centric heading on left bumper press
    Gamepads.driver_leftShoulderButton.debounce(0.1, Debouncer.DebounceType.kBoth)
        .onTrue(drivetrain.runOnce(() -> drivetrain.seedFieldCentric()));

    /*****************************
     * Configure Button Bindings *
     *****************************/
    //// OPERATOR BUTTONS
    // Hood Buttons
    Gamepads.operator_X_Button.debounce(0.1, Debouncer.DebounceType.kBoth)
        .whileTrue(hoodDown)
        .onFalse(stopHood);
    Gamepads.operator_B_Button.debounce(0.1, Debouncer.DebounceType.kBoth)
        .whileTrue(hoodUp)
        .onFalse(stopHood);
    // Elevator Buttons
    Gamepads.operator_Y_Button.debounce(0.1, Debouncer.DebounceType.kBoth)
        .onTrue(runElevatorToTopPID)
        .onFalse(stopElevator);
    Gamepads.operator_A_Button.debounce(0.1, Debouncer.DebounceType.kBoth)
        .whileTrue(elevatorDown)
        .onFalse(stopElevator);
    // Shooter Buttons
    Gamepads.operator_leftShoulderButton.debounce(0.1, Debouncer.DebounceType.kBoth)
        .whileTrue(
            operator.run(() -> operator.shooterOut())
                .withTimeout(0.7)
                .andThen(operator.run(() -> {
                    //operator.kickerIn();
                    operator.FIRE();
                }))
        )
        .onFalse(ceaseFire);
    Gamepads.operator_rightShoulderButton.debounce(0.1, Debouncer.DebounceType.kBoth)
        .whileTrue(clearOut)
        .onFalse(ceaseFire);
    Gamepads.operator_leftStickButton.debounce(0.1, Debouncer.DebounceType.kBoth)
        .whileTrue(launch)
        .onFalse(ceaseFire);
    // Conveyor Buttons
    Gamepads.operator_startButton.debounce(0.1, Debouncer.DebounceType.kBoth)
        .whileTrue(conveyorFwd)
        .onFalse(stopConveyor);
    Gamepads.operator_backButton.debounce(0.1, Debouncer.DebounceType.kBoth)
        .whileTrue(conveyorRev)
        .onFalse(stopConveyor);
    // Feeder Buttons
    Gamepads.operator_rightStickButton.debounce(0.1, Debouncer.DebounceType.kBoth)
        .whileTrue(feederIn)
        .onFalse(stopFeeder);
        
    drivetrain.registerTelemetry(logger::telemeterize);
    }

  /* 
  public void driveSwerve(double xSpeed, double ySpeed, double rotRate) {
    Command driveCommand = drivetrain.applyRequest(() -> autoDrive.withVelocityX(xSpeed)
      .withVelocityY(ySpeed)
      .withRotationalRate(rotRate));
    CommandScheduler.getInstance().schedule(driveCommand);
  }
    */
  
    public Command getAutonomousCommand() {
        return autoChooser.getSelected();
    }
}
