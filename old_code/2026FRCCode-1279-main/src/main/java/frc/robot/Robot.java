// Copyright (c) FIRST and other WPILib contributors.
// Open Source Software; you can modify and/or share it under the terms of
// the WPILib BSD license file in the root directory of this project.

package frc.robot;

import com.ctre.phoenix6.HootAutoReplay;

import edu.wpi.first.wpilibj.TimedRobot;
import edu.wpi.first.wpilibj2.command.Command;
import edu.wpi.first.wpilibj2.command.CommandScheduler;
import frc.robot.generated.TunerConstants;

public class Robot extends TimedRobot {
    private Command m_autonomousCommand;

    private final RobotContainer m_robotContainer;

    /* log and replay timestamp and joystick data */
    private final HootAutoReplay m_timeAndJoystickReplay = new HootAutoReplay()
        .withTimestampReplay()
        .withJoystickReplay();

    public Robot() {
        m_robotContainer = new RobotContainer();
    }

    @Override
    public void robotPeriodic() {
        m_timeAndJoystickReplay.update();
        CommandScheduler.getInstance().run(); 
/*
        //Rotate Wrist Motor based on Operator Left Joystick Y value
        double joystickLeftValue = Gamepads.operatorController.getLeftY();
        ////m_robotContainer.motors.WristMotor.setControl(m_robotContainer.motors.m_dutyCycleOut.withOutput(joystickLeftValue));
        //double joystickRightValue = Gamepads.operatorController.getRightY();
        //m_robotContainer.motors.TestMotor.setControl(m_robotContainer.motors.m_dutyCycleOut.withOutput(joystickRightValue));
        //Rotate Wrist Motor based on Operator Triggers
        double triggerLeftValue = Gamepads.operatorController.getLeftTriggerAxis();
        double triggerRightValue = Gamepads.operatorController.getRightTriggerAxis();
        if (triggerLeftValue > 0.05 || triggerRightValue > 0.05)
        {
            double triggerValue = triggerLeftValue * Constants.MotorSpeeds.FEEDER;
            if (triggerRightValue > 0.05)
            {
                triggerValue = -triggerRightValue;
            }
            m_robotContainer.motors.Feeder1Motor.setControl(m_robotContainer.motors.m_dutyCycleOut.withOutput(triggerValue));
            m_robotContainer.motors.Feeder2Motor.setControl(m_robotContainer.motors.m_dutyCycleOut.withOutput(-1 * triggerValue));
        }
*/
        boolean driver_Y_Button = Gamepads.driver_Y_Button.getAsBoolean();
    }

    @Override
    public void disabledInit() {}

    @Override
    public void disabledPeriodic() {}

    @Override
    public void disabledExit() {}

    @Override
    public void autonomousInit() {
        m_autonomousCommand = m_robotContainer.getAutonomousCommand();

        if (m_autonomousCommand != null) {
            CommandScheduler.getInstance().schedule(m_autonomousCommand);
        }
    }

    @Override
    public void autonomousPeriodic() {}

    @Override
    public void autonomousExit() {}

    @Override
    public void teleopInit() {
        if (m_autonomousCommand != null) {
            CommandScheduler.getInstance().cancel(m_autonomousCommand);
        }
        // Apply Current Limits to Shooter Motors at the start of Teleop
        m_robotContainer.motors.Shooter1Motor.getConfigurator().apply(TunerConstants.kShooterInitialConfigs);
        m_robotContainer.motors.Shooter2Motor.getConfigurator().apply(TunerConstants.kShooterInitialConfigs);
    }

    @Override
    public void teleopPeriodic() {
        //Rotate Wrist Motor based on Operator Left Joystick Y value
        double joystickLeftValue = Gamepads.operatorController.getLeftY();
        ////m_robotContainer.motors.WristMotor.setControl(m_robotContainer.motors.m_dutyCycleOut.withOutput(joystickLeftValue));
        //double joystickRightValue = Gamepads.operatorController.getRightY();
        //m_robotContainer.motors.TestMotor.setControl(m_robotContainer.motors.m_dutyCycleOut.withOutput(joystickRightValue));
        //Rotate Wrist Motor based on Operator Triggers
        double triggerLeftValue = Gamepads.operatorController.getLeftTriggerAxis();
        double triggerRightValue = Gamepads.operatorController.getRightTriggerAxis();
        //if (triggerLeftValue > 0.05 || triggerRightValue > 0.05)
        //{
            double triggerValue = triggerLeftValue * Constants.MotorSpeeds.FEEDER;
            if (triggerRightValue > 0.05)
            {
                triggerValue = -triggerRightValue;
            }
            m_robotContainer.motors.Feeder1Motor.setControl(m_robotContainer.motors.m_dutyCycleOut.withOutput(triggerValue));
            m_robotContainer.motors.Feeder2Motor.setControl(m_robotContainer.motors.m_dutyCycleOut.withOutput(-1 * triggerValue));
        //}
    }

    @Override
    public void teleopExit() {}

    @Override
    public void testInit() {
        CommandScheduler.getInstance().cancelAll();
    }

    @Override
    public void testPeriodic() {}

    @Override
    public void testExit() {}

    @Override
    public void simulationPeriodic() {}
}
