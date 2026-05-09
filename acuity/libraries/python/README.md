# Acuity Vision — Python (robotpy)

Pure-Python client for the Acuity vision coprocessor. Built on top of
the `pyntcore` NetworkTables 4 client that ships with robotpy.

## Install

```sh
pip install acuity-vision
```

(Once published. For now: `pip install -e acuity/libraries/python`
from a checkout.)

For robotpy projects, add to your `pyproject.toml`:

```toml
[tool.robotpy]
robotpy_extras = ["all"]
requires = ["acuity-vision>=0.1"]
```

## Use

```python
import wpilib
import acuity_vision

class MyRobot(wpilib.TimedRobot):
    def robotInit(self):
        self.vision = acuity_vision.AcuityVision()

    def robotPeriodic(self):
        tag = self.vision.get_best_tag()
        if tag is not None:
            wpilib.SmartDashboard.putNumber("acuity/id",         tag.id)
            wpilib.SmartDashboard.putNumber("acuity/distance_m", tag.distance_m)
            wpilib.SmartDashboard.putNumber("acuity/yaw_deg",    tag.yaw_deg)
```

## Status

Skeleton. Module entry point lives at
[acuity_vision/\_\_init\_\_.py](acuity_vision/__init__.py).
Publishing to PyPI is on the roadmap.
