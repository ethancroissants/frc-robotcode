"""
Copyright (c) FIRST and other WPILib contributors.
Open Source Software; you can modify and/or share it under the terms of
the WPILib BSD license file in the root directory of this project.
"""

import wpilib
from commands2 import CommandScheduler
from phoenix6 import HootAutoReplay
from phoenix6.controls import NeutralOut
from wpilib import DriverStation, SmartDashboard, XboxController

import gamepads
import orangepi_pusher
import tunables
from generated import tuner_constants
from robotcontainer import RobotContainer


# Gamepad-state mirror for the Pi UI — published every robotPeriodic so the
# web client's Operator + Driver panels stay in sync with reality without
# the Pi having to know which buttons are which. Operator stays at the
# original /Sight/Buttons/* path (back-compat with older Pi code); Driver
# is namespaced under /Sight/Buttons/Driver/*.
_GP_BUTTONS = (
    ("A", int(XboxController.Button.kA)),
    ("B", int(XboxController.Button.kB)),
    ("X", int(XboxController.Button.kX)),
    ("Y", int(XboxController.Button.kY)),
    ("LB", int(XboxController.Button.kLeftBumper)),
    ("RB", int(XboxController.Button.kRightBumper)),
)


def _publish_stick(js, prefix: str) -> None:
    """Mirror one Joystick into NT under /SmartDashboard/<prefix>{POV,A,...}.

    Cheap (1 POV read + 6 raw button reads); a try/except around each
    access keeps a missing-controller from spamming joystick warnings.
    """
    try:
        SmartDashboard.putNumber(f"{prefix}POV", js.getPOV())
    except Exception:
        SmartDashboard.putNumber(f"{prefix}POV", -1)
    for label, idx in _GP_BUTTONS:
        try:
            SmartDashboard.putBoolean(f"{prefix}{label}", js.getRawButton(idx))
        except Exception:
            SmartDashboard.putBoolean(f"{prefix}{label}", False)


def _publish_gamepad_state() -> None:
    _publish_stick(gamepads.operatorJoyStick, "Sight/Buttons/")
    _publish_stick(gamepads.driverJoyStick,   "Sight/Buttons/Driver/")


class MyRobot(wpilib.TimedRobot):
    def robotInit(self) -> None:
        # Without this, every JoystickButton trigger spams "Joystick Button N missing
        # (max 0)" once per loop when no controller is plugged in. That print burns
        # enough of the 20ms loop budget to push RobotPeriodic over the watchdog.
        DriverStation.silenceJoystickConnectionWarning(True)

        self.m_autonomousCommand = None
        self.m_robotContainer = RobotContainer()

        tunables.publish_defaults()
        # MusicTone has no software volume control, so loudness scales with how many
        # coils we vibrate at once. Recruit every idle TalonFX we can — both shooters
        # plus the conveyor/elevator/wrist — so the chirp is audible across the pit.
        motors = self.m_robotContainer.motors
        tunables.configure_beep_motors(
            motors.Shooter1Motor,
            motors.Shooter2Motor,
            motors.ConveyorMotor,
            motors.ElevatorMotor,
            motors.WristMotor,
        )

        # Log and replay timestamp and joystick data
        self.m_timeAndJoystickReplay = (
            HootAutoReplay().with_timestamp_replay().with_joystick_replay()
        )

        # Camera + overlay live on the Orange Pi 5 now (see orangepi/server.py).
        # The Pi connects to NetworkTables and reads the same tunables we publish;
        # we just need to mirror the operator gamepad so its UI lights up.

        # Hand off the deployed orangepi/ folder to the Pi over SSH. Runs on a
        # daemon thread so it never blocks robotInit; if the Pi is offline or
        # SSH fails, the rio still drives normally.
        orangepi_pusher.start()

    def robotPeriodic(self) -> None:
        self.m_timeAndJoystickReplay.update()
        CommandScheduler.getInstance().run()
        tunables.update(self.isEnabled())
        _publish_gamepad_state()
        # Mirror the DS enabled state to the Pi so the Sight UI can grey
        # out the SHOOT button + manual controls while the robot is
        # disabled. Pi-side default is True so this is just a downgrade
        # signal; if we forget to publish, the UI stays usable.
        SmartDashboard.putBoolean("Sight/RobotEnabled", self.isEnabled())

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
        # The full TalonFXConfiguration apply above wipes audio settings, so
        # restore the "allow music while disabled" flag the beep code relies on.
        tunables.apply_beep_audio()

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
