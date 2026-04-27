"""Smoke tests for the robot code.

pyfrc's builtin tests gate on robotInit() finishing within 2s in sim, which
Phoenix6 + a full swerve stack can't reliably hit when no CAN hardware is
present. These import-level checks catch the cases that actually break a
deploy (syntax errors, bad imports, missing modules) without needing to spin
up a simulated robot.
"""


def test_robot_module_imports():
    import robot

    assert hasattr(robot, "MyRobot")


def test_robotcontainer_module_imports():
    import robotcontainer

    assert hasattr(robotcontainer, "RobotContainer")
