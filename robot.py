"""
Copyright (c) FIRST and other WPILib contributors.
Open Source Software; you can modify and/or share it under the terms of
the WPILib BSD license file in the root directory of this project.
"""

import wpilib
from commands2 import CommandScheduler
from phoenix6 import HootAutoReplay
from phoenix6.controls import NeutralOut

import gamepads
import tunables
from generated import tuner_constants
from robotcontainer import RobotContainer


class MyRobot(wpilib.TimedRobot):
    def robotInit(self) -> None:
        self.m_autonomousCommand = None
        self.m_robotContainer = RobotContainer()

        tunables.publish_defaults()
        # Shooter1 (Kraken) is loud and idle outside of fire commands; disabledInit already
        # clears its cached control, so it's the safest motor to commandeer for beeps.
        tunables.configure_beep_motor(self.m_robotContainer.motors.Shooter1Motor)

        # Log and replay timestamp and joystick data
        self.m_timeAndJoystickReplay = (
            HootAutoReplay().with_timestamp_replay().with_joystick_replay()
        )

    def robotPeriodic(self) -> None:
        self.m_timeAndJoystickReplay.update()
        CommandScheduler.getInstance().run()
        tunables.update(self.isEnabled())

        driver_Y_Button = gamepads.driver_Y_Button.getAsBoolean()

    def disabledInit(self) -> None:
        # Phoenix 6 caches the last control request and resumes it on re-enable. Without this,
        # disabling while the shooter is mid-fire leaves VelocityVoltage(-95) cached, and the
        # wheel starts spinning the instant the robot is re-enabled. Only clear the leader;
        # Shooter2's Follower request follows the leader's output to neutral.
        self.m_robotContainer.motors.Shooter1Motor.set_control(NeutralOut())

    def disabledPeriodic(self) -> None:
        pass

    def disabledExit(self) -> None:
        pass

    def autonomousInit(self) -> None:
        self.m_autonomousCommand = self.m_robotContainer.getAutonomousCommand()

        if self.m_autonomousCommand is not None:
            CommandScheduler.getInstance().schedule(self.m_autonomousCommand)

    def autonomousPeriodic(self) -> None:
        pass

    def autonomousExit(self) -> None:
        pass

    def teleopInit(self) -> None:
        if self.m_autonomousCommand is not None:
            CommandScheduler.getInstance().cancel(self.m_autonomousCommand)
        # Apply Current Limits to Shooter Motors at the start of Teleop
        self.m_robotContainer.motors.Shooter1Motor.configurator.apply(
            tuner_constants.kShooterInitialConfigs
        )
        self.m_robotContainer.motors.Shooter2Motor.configurator.apply(
            tuner_constants.kShooterInitialConfigs
        )

    def teleopPeriodic(self) -> None:
        # Operator triggers drive the feeder motors directly
        triggerLeftValue = gamepads.operatorController.getLeftTriggerAxis()
        triggerRightValue = gamepads.operatorController.getRightTriggerAxis()

        triggerValue = triggerLeftValue * tunables.feeder_speed()
        if triggerRightValue > 0.05:
            triggerValue = -triggerRightValue

        self.m_robotContainer.motors.Feeder1Motor.set_control(
            self.m_robotContainer.motors.m_dutyCycleOut.with_output(triggerValue)
        )
        self.m_robotContainer.motors.Feeder2Motor.set_control(
            self.m_robotContainer.motors.m_dutyCycleOut.with_output(-1 * triggerValue)
        )

    def teleopExit(self) -> None:
        pass

    def testInit(self) -> None:
        CommandScheduler.getInstance().cancelAll()

    def testPeriodic(self) -> None:
        pass

    def testExit(self) -> None:
        pass

    def simulationPeriodic(self) -> None:
        pass


if __name__ == "__main__":
    wpilib.run(MyRobot)
