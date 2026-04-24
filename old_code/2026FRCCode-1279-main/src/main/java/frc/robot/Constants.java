/*----------------------------------------------------------------------------*/
/* Copyright (c) 2018-2019 FIRST. All Rights Reserved.                        */
/* Open Source Software - may be modified and shared by FRC teams. The code   */
/* must be accompanied by the FIRST BSD license file in the root directory of */
/* the project.                                                               */
/*----------------------------------------------------------------------------*/

package frc.robot;

import edu.wpi.first.math.util.Units;
import frc.robot.Constants.CancoderIDs;
import frc.robot.Constants.ControllerIDs;
import edu.wpi.first.math.controller.PIDController;
import edu.wpi.first.math.geometry.Translation2d;
import edu.wpi.first.math.kinematics.DifferentialDriveKinematics;
import edu.wpi.first.math.kinematics.SwerveDriveKinematics;
import edu.wpi.first.math.trajectory.TrapezoidProfile;

//import com.revrobotics.CANSparkMax.IdleMode;
/**
 * The Constants class provides a convenient place for teams to hold robot-wide
 * numerical or boolean constants. This class should not be used for any other
 * purpose. All constants should be declared globally (i.e. public static). Do
 * not put anything functional in this class.
 *
 * <p>
 * It is advised to statically import this class (or one of its inner classes)
 * wherever the constants are needed, to reduce verbosity.
 */
public final class Constants
{
    public static final class MotorSpeeds
    {
        public static final double SHOOTER = 0.5;
        public static final double KICKER = 0.9;
        public static final double CONVEYOR = 1.0;
        public static final double HOOD = 0.2;
        public static final double FEEDER = 0.5;
        public static final double ELEVATOR = 0.6;
        public static final double LAUNCH = 0.7;
    }

    public static final class ControllerIDs
    {
        //This is where you can define the ID's for each motor controller on the robot
        public static final int FALCON_FRONT_RIGHT_STEER_ID = 27; 
        public static final int FALCON_REAR_RIGHT_STEER_ID = 25; 
        public static final int FALCON_FRONT_LEFT_STEER_ID = 23; 
        public static final int FALCON_REAR_LEFT_STEER_ID = 21; 
        public static final int KRAKEN_FRONT_RIGHT_DRIVE_ID = 28;
        public static final int KRAKEN_REAR_RIGHT_DRIVE_ID = 26;
        public static final int KRAKEN_FRONT_LEFT_DRIVE_ID = 24;
        public static final int KRAKEN_REAR_LEFT_DRIVE_ID = 22;


        public static final int MINION_DRIVE_ID = 3;

        public static final int FEEDER1_DRIVE_ID = 4; //MINION
        public static final int FEEDER2_DRIVE_ID = 5; //MINION
        public static final int CONVEYOR_DRIVE_ID = 6; //KRAKEN
        public static final int WRIST_DRIVE_ID = 7; //KRAKEN
        public static final int ELEVATOR_DRIVE_ID = 8; //KRAKEN
        public static final int KICKER_DRIVE_ID = 9; //MINION
        public static final int SHOOTER1_DRIVE_ID = 10; //KRAKEN
        public static final int SHOOTER2_DRIVE_ID = 11; //KRAKEN
        public static final int HOOD_DRIVE_ID = 12; //MINION

        public static final int TEST_DRIVE_ID = 40;
    }

    public static final class CancoderIDs
    {
        //This is where you can define the ID's for each motor controller on the robot
        public static final int FRONT_LEFT_CANCODER_ID = 32; 
        public static final int FRONT_RIGHT_CANCODER_ID = 34;
        public static final int REAR_LEFT_CANCODER_ID = 31;
        public static final int REAR_RIGHT_CANCODER_ID = 33;
    }

    public static final class GamePadIDs
    {
        //This is where you can define the ID's for each motor controller on the robot
        public static final int DRIVER_GAMEPAD_ID = 0; 
        public static final int OPERATOR_GAMEPAD_ID = 1; 
    }

    public static final class PneumaticIDs
    {
        //This is where you can define the ID's for each pneumatic solenoid on the robot
        public static final int ARM_EXTEND_ID = 6; //6
        public static final int ARM_RETRACT_ID = 7; //7
        public static final int CONE_GRAB_ID = 4; 
        public static final int CONE_RELEASE_ID = 5;
        public static final int CUBE_GRAB_ID = 2; 
        public static final int CUBE_RELEASE_ID = 3;
    }
    
    public static final class ButtonIDs
    {
        public static final int A_BUTTON_ID = 1;
        public static final int B_BUTTON_ID = 2;
        public static final int X_BUTTON_ID = 3;
        public static final int Y_BUTTON_ID = 4;
        public static final int LEFT_SHOULDER_BUTTON_ID = 5;
        public static final int RIGHT_SHOULDER_BUTTON_ID = 6;
        public static final int BACK_BUTTON_ID = 7;
        public static final int START_BUTTON_ID = 8;
        public static final int LEFT_STICK_BUTTON_ID = 9;
        public static final int RIGHT_STICK_BUTTON_ID = 10;
    }

    public static final class JoystickAxisIDs
    {
        public static final int LEFT_X_AXIS = 0;
        public static final int LEFT_Y_AXIS = 1;
         public static final int RIGHT_X_AXIS = 4;
        public static final int RIGHT_Y_AXIS = 5;
        
        public static final int LEFT_TRIGGER_ID = 2;
        public static final int RIGHT_TRIGGER_ID = 3;
    }

    public static final class Cameras 
    {
        public static String AprilTagIP = "10.12.79.2"; // IP Address of the AprilTag Camera
        public static int AprilTagPort = 5810; // Port number for the AprilTag Camera
        //public static String AprilTagURL = "http://<orange_pi_ip>:8080/?action=stream";
        //public static String AprilTagURL = "http://10.12.79.11:5800/?action=stream"; // WiFi Address?
        public static String AprilTagURL = "http://" + AprilTagIP + ":" + AprilTagPort + "/?action=stream"; // USB address?
    }

    public static final class Switches
    {
        public static int elevatorTopLimitSwitch = 0;
        public static int elevatorBottomLimitSwitch = 1;
        public static int wristTopLimitSwitch = 2;
        public static int wristBottomLimitSwitch = 3;

        //public static int autonomousSettingSwitch = 2;
    }

    public static final class ElevatorPositions
    {
        public static double bottom = 0.0; //Elevator bottom
        public static double loading = 19.0; //Elevator at coral loading height
        public static double level1 = 58.0; //Elevator at lowest reef height
        public static double level2 = 86.0; //Elevator at middle reef height
        public static double level3 = 110; //Elevator at highest reef height
    }

    //////
    public static final class DriveConstants 
    {
        // Multipliers for slow speed vs full speed driving
        public static final double fullSpeed = 1.0;
        public static final double slowSpeed = 0.6;
        
        // Driving Parameters - Note that these are not the maximum capable speeds of
        // the robot, rather the allowed maximum speeds
        public static final double kMaxSpeedMetersPerSecond = 1.0;
        // public static final double kMaxSpeedMetersPerSecond = 4.8; // Commented while testing autonomous
        public static final double kMaxAngularSpeed = 2 * Math.PI; // radians per second

        public static final double kDirectionSlewRate = 1.2; // radians per second
        public static final double kMagnitudeSlewRate = 1.8; // percent per second (1 = 100%)
        public static final double kRotationalSlewRate = 2.0; // percent per second (1 = 100%)

        // Chassis configuration
        public static final double kTrackWidth = Units.inchesToMeters(21.5);
        // Distance between centers of right and left wheels on robot
        public static final double kWheelBase = Units.inchesToMeters(21.5);
        // Distance between front and back wheels on robot
        public static final SwerveDriveKinematics kDriveKinematics = new SwerveDriveKinematics(
            new Translation2d(kWheelBase / 2, kTrackWidth / 2),
            new Translation2d(kWheelBase / 2, -kTrackWidth / 2),
            new Translation2d(-kWheelBase / 2, kTrackWidth / 2),
            new Translation2d(-kWheelBase / 2, -kTrackWidth / 2));

        // Angular offsets of the modules relative to the chassis in radians
        public static final double kFrontLeftChassisAngularOffset = -Math.PI / 2;
        public static final double kFrontRightChassisAngularOffset = 0;
        public static final double kBackLeftChassisAngularOffset = Math.PI;
        public static final double kBackRightChassisAngularOffset = Math.PI / 2;

        // SPARK MAX CAN IDs
        public static final int kFrontLeftDrivingCanId = 4;
        public static final int kRearLeftDrivingCanId = 2;
        public static final int kFrontRightDrivingCanId = 6;
        public static final int kRearRightDrivingCanId = 8;

        public static final int kFrontLeftTurningCanId = 3;
        public static final int kRearLeftTurningCanId = 1;
        public static final int kFrontRightTurningCanId = 5;
        public static final int kRearRightTurningCanId = 7;

        public static final boolean kGyroReversed = true;
    }

    public static final class ModuleConstants 
    {
        // The MAXSwerve module can be configured with one of three pinion gears: 12T, 13T, or 14T.
        // This changes the drive speed of the module (a pinion gear with more teeth will result in a
        // robot that drives faster).
        public static final int kDrivingMotorPinionTeeth = 13;

        // Invert the turning encoder, since the output shaft rotates in the opposite direction of
        // the steering motor in the MAXSwerve Module.
        public static final boolean kTurningEncoderInverted = true;

        // Calculations required for driving motor conversion factors and feed forward
        public static final double kDrivingMotorFreeSpeedRps = NeoMotorConstants.kFreeSpeedRpm / 60;
        public static final double kWheelDiameterMeters = 0.0762;
        public static final double kWheelCircumferenceMeters = kWheelDiameterMeters * Math.PI;
        // 45 teeth on the wheel's bevel gear, 22 teeth on the first-stage spur gear, 15 teeth on the bevel pinion
        public static final double kDrivingMotorReduction = (45.0 * 22) / (kDrivingMotorPinionTeeth * 15);
        public static final double kDriveWheelFreeSpeedRps = (kDrivingMotorFreeSpeedRps * kWheelCircumferenceMeters)
            / kDrivingMotorReduction;

        public static final double kDrivingEncoderPositionFactor = (kWheelDiameterMeters * Math.PI)
            / kDrivingMotorReduction; // meters
        public static final double kDrivingEncoderVelocityFactor = ((kWheelDiameterMeters * Math.PI)
            / kDrivingMotorReduction) / 60.0; // meters per second

        public static final double kTurningEncoderPositionFactor = (2 * Math.PI); // radians
        public static final double kTurningEncoderVelocityFactor = (2 * Math.PI) / 60.0; // radians per second

        public static final double kTurningEncoderPositionPIDMinInput = 0; // radians
        public static final double kTurningEncoderPositionPIDMaxInput = kTurningEncoderPositionFactor; // radians

        public static final double kDrivingP = 0.04;
        public static final double kDrivingI = 0;
        public static final double kDrivingD = 0;
        public static final double kDrivingFF = 1 / kDriveWheelFreeSpeedRps;
        // drive speed

        /*
        * SPEED 
        * 
        * 
        * 
        */
        public static final double kDrivingMinOutput = -0.4;
        public static final double kDrivingMaxOutput = 0.4;

        public static final double kTurningP = 1;
        public static final double kTurningI = 0;
        public static final double kTurningD = 0;
        public static final double kTurningFF = 0;
        public static final double kTurningMinOutput = -1;
        public static final double kTurningMaxOutput = 1;
    // Here you can change the idle mode to coast 
        //public static final IdleMode kDrivingMotorIdleMode = IdleMode.kCoast;
        //public static final IdleMode kTurningMotorIdleMode = IdleMode.kCoast;

        public static final int kDrivingMotorCurrentLimit = 50; // amps
        public static final int kSteerMotorCurrentLimit = 30; // amps
        public static final int kDrivingMotorCurrentThreshold = 55; // amps
        public static final int kSteerMotorCurrentThreshold = 30; // amps
        public static final double kDrivingMotorCurrentThresholdTime = 0.1; // seconds
        public static final double kSteerMotorCurrentThresholdTime = 0.1; // seconds

        // Max continuous current for shooter motors in amps — tune to your robot.
        public static final double kShooterMotorCurrentLimit = 60.0;
    }

    public static final class OIConstants 
    {
        public static final int kDriverControllerPort = 0;
        public static final double kDriveDeadband = 0.05;
        public static final double kDeadband = 0.09;
    }

    public static final class AutoConstants 
    {
        public static final double kMaxSpeedMetersPerSecond = 1;
        //public static final double kMaxSpeedMetersPerSecond = 3;
        public static final double kMaxAccelerationMetersPerSecondSquared = 1;
        //public static final double kMaxAccelerationMetersPerSecondSquared = 3;
        public static final double kMaxAngularSpeedRadiansPerSecond = Math.PI;
        public static final double kMaxAngularSpeedRadiansPerSecondSquared = Math.PI;

        public static final double kPXController = 1;
        public static final double kPYController = 1;
        public static final double kPThetaController = 1;

        // Constraint for the motion profiled robot angle controller
        public static final TrapezoidProfile.Constraints kThetaControllerConstraints = new TrapezoidProfile.Constraints(
            kMaxAngularSpeedRadiansPerSecond, kMaxAngularSpeedRadiansPerSecondSquared);
    }


    public static final class NeoMotorConstants 
    {
        public static final double kFreeSpeedRpm = 5676;
    }

    /***************************************************************************
     *          END OF TEAM 1279 CONSTANTS                                     *
     ***************************************************************************/

    public static final class RobotLimits
    {
        // distance in inches the robot wants to stay from an object
        private static final double kHoldDistance = 12.0;

        // factor to convert sensor values to a distance in inches
        private static final double kValueToInches = 0.125;

        // proportional speed constant
        private static final double kP = 0.05;
        private static final int kUltrasonicPort = 0;
    }

    /**
     * Constants regarding the DriveTrain
     */
    public static class DriveTrain 
    {
        public static final double driveSpeed = 0.8;

        public static final double kWheelRadiusInches = 2;

        public static final double kDriveReduction = 1.0;
        /**
        * Encoder constants
        */
        public static class Encoders 
        {

            /* Encoder slots */
            public static final int LEFT_ENCODER_SLOT = 1;
            public static final int RIGHT_ENCODER_SLOT = 1;

            /* Encoder phases */
            public static final boolean LEFT_SENSOR_PHASE = true;
            public static final boolean RIGHT_SENSOR_PHASE = false;

            /* Ticks per revolution of the encoder */
            public static final int PULSES_PER_REVOLUTION = 5760; // 4096;// 1024 // 2880;//1440; // (isCompBot())? 4096
                                                                    // : 1440;

        }

        /**
         * Component measurements
         */
        public static class Measurements 
        {
            public static final double WHEEL_DIAMETER = Units.inchesToMeters(6.0);
            public static final double WHEEL_CIRCUMFERENCE = Math.PI * WHEEL_DIAMETER;

            public static final double DRIVEBASE_WIDTH = Units.inchesToMeters(28.0);
            public static final double DRIVEBASE_LENGTH = Units.inchesToMeters(28.0);

            public static final double GEAR_RATIO = 8.45;

            public static final int MOTOR_MAX_RPM = 5330; // For cim motors

        }

        public static int ALIGNMENT_EPSILON = 3;
    }

    /**
     * Constants regarding the operator
     */
    public static class Operator 
    {

        // Motor controller IDs
        public static final int OPERATOR_ACTUATOR_TALON = 13;
        public static final int OPERATOR_ROLLER_TALON = 14;

        public static final boolean OPERATOR_ACTUATOR_TALON_INVERTED = false;
        public static final boolean OPERATOR_ROLLER_TALON_INVERTED = true;

        // Sensors DIO ports
        public static final int OPERATOR_LIMIT_BOTTOM = 0;
        public static final int OPERATOR_LIMIT_TOP = 1;

        // PID values
        public static final double kPArm = 0.011111111111;
        public static final double kIArm = 0.0;
        public static final double kDArm = 0.0;

        public static final double ARM_TICKS_PER_DEGREE = 1000;

        public static final double ARM_UP_SPEED = -0.85;
        public static final double ARM_DOWN_SPEED = 0.35;

        public static final double ROLLER_SPEED = 0.4;
    }

    /**
     * Control Gains Measurements
     */
    public static class ControlGains 
    {

        // Feedforward Gains
        public static final double ksVolts = 1.02; // Practice Base 0.837; // MiniBot 2.37
        public static final double kvVoltsSecondsPerMeter = 7.01; // Practice Base 2.46; // 1.8 MiniBot 1.73
        public static final double kaVoltsSecondsSquaredPerMeter = 2.64; // Practice Base 0.0455; // 0.0231 MiniBot
                                                                         // .0304

        // Optimal Control Gain for driving
        public static final double kPDriveVel = 0.478;// 0.68; //0.478;
        public static final double kIDriveVel = 0.0;
        public static final double kDDriveVel = 0.008;

        // Optimal Control Gain for turning
        // 2.86 2.83 2.77 2.71 2.83 2.67 over shot
        public static final double kPTurnVel = 0.0088;//0.0028;// 0.008; /// 0.0085;// 0.030;
        public static final double kITurnVel = 0.01;//0.0;//0.01; // 0.07; // 0.12;
        public static final double kDTurnVel = 0.0106; // 0.0066

        // Basic P control for encoder-only distance driving
        public static final double kRP = 0.05;

        // P = 0.027 I = 0.1 D = 0.006

        // Optimal Control Gain for driving
        public static final double kPElevatorVel = 0.478;
        public static final double kIElevatorVel = 0.0;
        public static final double kDElevatorVel = 0.0;

        // Closest: 3.34m

        // PID Controller
        public static PIDController turningPIDController = new PIDController(kPTurnVel, kITurnVel, kDTurnVel);

        public static PIDController drivePidController = new PIDController(kPTurnVel, kITurnVel, kDTurnVel);

        public static PIDController elevatorPidController = new PIDController(kPElevatorVel, kIElevatorVel, kDElevatorVel);

        // DifferentialDriveKinematics allows for the use of the track length
        public static final double kTrackWidthMeters = 0.1524;
        public static final DifferentialDriveKinematics kDriveKinematics = new DifferentialDriveKinematics(
                kTrackWidthMeters);

        // Max Trajectory of Velocity and Acceleration
        public static final double kMaxSpeedMetersPerSecond = 3; // This value will most likely need to be changed
        public static final double kMaxAccelerationMetersPerSecondSquared = 1.5; // This value will most likely need to
                                                                                 // be
                                                                                 // changed

        // Ramsete Parameters (Not sure if this is nessacary for trajectory and may need
        // changes)
        public static final double kRamseteB = 2; // in meters
        public static final double kRamseteZeta = .7; // in Seconds

    }

    public static class Autonomous 
    {

        /**
         * Number of seconds to wait before robot is allowed to score
         */
        public static final double SCORE_LATE_DELAY = 5.0;

        // Vision-based distance P Gain
        public static final double VISION_DISTANCE_KP = -0.1;

        public static final double AUTO_TARGET_DISTANCE_EPSILON = 5.0;

    }

    /**
     * The left-to-right distance between the drivetrain wheels
     *
     * Should be measured from center to center.
     */
    public static final double DRIVETRAIN_TRACKWIDTH_METERS = 1.0; // FIXME Measure and set trackwidth
    /**
     * The front-to-back distance between the drivetrain wheels.
     *
     * Should be measured from center to center.
     */
    public static final double DRIVETRAIN_WHEELBASE_METERS = 1.0; // FIXME Measure and set wheelbase

    public static final int DRIVETRAIN_PIGEON_ID = 0; // FIXME Set Pigeon ID

    public static final int FRONT_LEFT_MODULE_DRIVE_MOTOR = ControllerIDs.KRAKEN_FRONT_LEFT_DRIVE_ID; // FIXME Set front left module drive motor ID
    public static final int FRONT_LEFT_MODULE_STEER_MOTOR = ControllerIDs.FALCON_FRONT_LEFT_STEER_ID; // FIXME Set front left module steer motor ID
    public static final int FRONT_LEFT_MODULE_STEER_ENCODER = CancoderIDs.FRONT_LEFT_CANCODER_ID; // FIXME Set front left steer encoder ID
    public static final double FRONT_LEFT_MODULE_STEER_OFFSET = -Math.toRadians(0.0); // FIXME Measure and set front left steer offset

    public static final int FRONT_RIGHT_MODULE_DRIVE_MOTOR = ControllerIDs.KRAKEN_FRONT_RIGHT_DRIVE_ID; // FIXME Set front right drive motor ID
    public static final int FRONT_RIGHT_MODULE_STEER_MOTOR = ControllerIDs.FALCON_FRONT_RIGHT_STEER_ID; // FIXME Set front right steer motor ID
    public static final int FRONT_RIGHT_MODULE_STEER_ENCODER = CancoderIDs.FRONT_RIGHT_CANCODER_ID; // FIXME Set front right steer encoder ID
    public static final double FRONT_RIGHT_MODULE_STEER_OFFSET = -Math.toRadians(0.0); // FIXME Measure and set front right steer offset

    public static final int BACK_LEFT_MODULE_DRIVE_MOTOR = ControllerIDs.KRAKEN_REAR_LEFT_DRIVE_ID; // FIXME Set back left drive motor ID
    public static final int BACK_LEFT_MODULE_STEER_MOTOR = ControllerIDs.FALCON_REAR_LEFT_STEER_ID; // FIXME Set back left steer motor ID
    public static final int BACK_LEFT_MODULE_STEER_ENCODER = CancoderIDs.REAR_LEFT_CANCODER_ID; // FIXME Set back left steer encoder ID
    public static final double BACK_LEFT_MODULE_STEER_OFFSET = -Math.toRadians(0.0); // FIXME Measure and set back left steer offset

    public static final int BACK_RIGHT_MODULE_DRIVE_MOTOR = ControllerIDs.KRAKEN_REAR_RIGHT_DRIVE_ID; // FIXME Set back right drive motor ID
    public static final int BACK_RIGHT_MODULE_STEER_MOTOR = ControllerIDs.FALCON_REAR_RIGHT_STEER_ID; // FIXME Set back right steer motor ID
    public static final int BACK_RIGHT_MODULE_STEER_ENCODER = CancoderIDs.REAR_RIGHT_CANCODER_ID; // FIXME Set back right steer encoder ID
    public static final double BACK_RIGHT_MODULE_STEER_OFFSET = -Math.toRadians(0.0); // FIXME Measure and set back right steer offset
}