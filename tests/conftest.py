# ============================================================
# TEST SETUP - Mock all hardware before any tests run
# ============================================================
# Since we don't have a real robot, we replace all the hardware
# libraries (motors, sensors) with fakes before importing our code.
# ============================================================

import sys
import types
from unittest.mock import MagicMock


def _make_mock_module(name):
    """Create a MagicMock that also looks like a real module.

    Python 3.14's importlib_resources checks __spec__ on modules.
    A bare MagicMock raises AttributeError for dunder attrs, which
    crashes phoenix6's native library loader. Setting __spec__ and
    other module-like attrs avoids this.
    """
    mock = MagicMock()
    mock.__spec__ = types.SimpleNamespace(
        name=name, loader=None, origin=None, submodule_search_locations=[]
    )
    mock.__name__ = name
    mock.__package__ = name
    mock.__path__ = []
    mock.__file__ = None
    return mock


# Mock all hardware modules BEFORE our code tries to import them.
# This way, when our subsystems say "from phoenix6.hardware import TalonFX",
# they get a fake TalonFX instead of trying to talk to real hardware.

for mod_name in [
    "commands2", "commands2.button", "commands2.cmd",
    "phoenix6", "phoenix6.hardware", "phoenix6.controls",
    "phoenix6.configs", "phoenix6.signals",
    "phoenix6.hardware.talon_fx", "phoenix6.hardware.talon_fxs",
    "phoenix6.hardware.core", "phoenix6.hardware.core.core_talon_fx",
    "phoenix6.hardware.core.core_talon_fxs",
    "phoenix6.hardware.parent_device", "phoenix6.hardware.device_identifier",
    "phoenix6.phoenix_native",
    "ntcore",
    "wpilib", "wpimath", "wpimath.geometry", "wpimath.kinematics",
]:
    sys.modules[mod_name] = _make_mock_module(mod_name)

# Now make SubsystemBase.__init__ a no-op so our classes can instantiate
mock_commands2 = sys.modules["commands2"]
mock_commands2.SubsystemBase = type("SubsystemBase", (), {"__init__": lambda self: None, "setDefaultCommand": lambda self, cmd: None})
