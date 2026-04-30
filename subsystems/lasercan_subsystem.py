"""Grapple Robotics LaserCAN distance sensor.

Wraps the grapplefrc.LaserCan API in a Subsystem that:
  - publishes the live measurement to NT every periodic tick so the Pi UI
    (and any other dashboard consumer) can show it.
  - returns a float distance in meters via `distance_m()` for command code,
    or None when the latest measurement is invalid (out of range, ambient,
    or a CAN dropout).

Configure the CAN ID via constants.CANIDs.LASERCAN. Wire the LaserCAN to the
robot's CAN bus and assign that ID with Grapple's web flasher.
"""

from __future__ import annotations

from commands2 import Subsystem
from wpilib import SmartDashboard

import constants

try:
    from grapplefrc import LaserCan
    _HAS_LASERCAN = True
except Exception:  # pragma: no cover — runs only on the rio
    LaserCan = None  # type: ignore[assignment]
    _HAS_LASERCAN = False


_NT_DIST = "Sight/LaserCAN/DistanceM"
_NT_VALID = "Sight/LaserCAN/Valid"
_NT_AMBIENT = "Sight/LaserCAN/Ambient"


class LaserCanSubsystem(Subsystem):
    """LaserCAN distance reader + NT publisher."""

    # Grapple's Measurement.status codes: 0 = valid, others = noise/out-of-range.
    _STATUS_VALID = 0

    def __init__(self) -> None:
        super().__init__()
        self.setName("LaserCAN")
        self._sensor = None
        if _HAS_LASERCAN:
            try:
                self._sensor = LaserCan(constants.CANIDs.LASERCAN)
            except Exception as e:
                # Don't crash robotInit if the sensor isn't on the bus —
                # the rio still needs to drive without it.
                print(f"LaserCAN init failed (continuing): {e}")
                self._sensor = None
        self._last_valid_m: float | None = None

    def periodic(self) -> None:
        d, valid, ambient = self._read()
        if valid and d is not None:
            self._last_valid_m = d
        SmartDashboard.putNumber(_NT_DIST, d if d is not None else 0.0)
        SmartDashboard.putBoolean(_NT_VALID, valid)
        SmartDashboard.putNumber(_NT_AMBIENT, ambient)

    # ----- public API for commands -----

    def distance_m(self) -> float | None:
        """Latest *valid* distance, or None if the most recent reading was bad."""
        d, valid, _ = self._read()
        return d if valid else None

    def last_known_distance_m(self) -> float | None:
        """Most recent valid reading we ever saw, even if the current one is bad.

        Useful for `AutoAim`: a momentary CAN dropout shouldn't abort a shot if
        we had a good distance a few cycles ago.
        """
        return self._last_valid_m

    # ----- internals -----

    def _read(self) -> tuple[float | None, bool, float]:
        if self._sensor is None:
            return None, False, 0.0
        try:
            m = self._sensor.getMeasurement()
        except Exception:
            return None, False, 0.0
        if m is None:
            return None, False, 0.0
        # grapplefrc's Measurement carries `distance_mm`, `status`, `ambient`.
        # `status == 0` means a clean reading; any other code is noisy.
        ambient = float(getattr(m, "ambient", 0))
        if getattr(m, "status", 0) != self._STATUS_VALID:
            return None, False, ambient
        d_m = float(m.distance_mm) / 1000.0
        return d_m, True, ambient
