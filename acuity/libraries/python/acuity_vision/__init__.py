"""Acuity Vision — Python client.

Reads the NetworkTables 4 schema documented in
acuity/docs/nt4-schema.md and exposes a typed Python API.

The full implementation imports `ntcore` (from robotpy / pyntcore).
This skeleton keeps the import lazy so the module can be loaded in
non-robot environments (CI, dashboards) without WPILib pulled in.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional, List


# ---------------------------------------------------------------------
# Data classes — same shape across all three language bindings.
# ---------------------------------------------------------------------

@dataclass
class TagDetection:
    id: int
    distance_m: float
    yaw_deg: float
    pitch_deg: float
    tx: float          # normalized [-1, 1]
    ty: float
    area: float        # 0..1
    timestamp: float   # FPGA seconds when frame was captured
    decision_margin: float


@dataclass
class ObjectDetection:
    class_name: str
    confidence: float
    tx: float
    ty: float


@dataclass
class DeviceHealth:
    cpu_pct: float
    temp_c: float
    uptime_seconds: int


# How long without a heartbeat before we declare the device gone.
_STALE_AFTER_S = 0.1


class AcuityVision:
    """Singleton-style client. Construct once per robot."""

    def __init__(self) -> None:
        # Lazy-import ntcore so this module loads outside a robotpy env.
        import ntcore  # type: ignore

        self._nt = ntcore.NetworkTableInstance.getDefault()
        self._t = self._nt.getTable("acuity")

        # Pre-resolve subscribers — re-resolving on every call costs us
        # a noticeable amount in tight robot-periodic loops.
        self._heartbeat   = self._t.getEntry("heartbeat")
        self._best_id     = self._t.getSubTable("tags").getSubTable("best").getEntry("id")
        self._best_dist   = self._t.getSubTable("tags").getSubTable("best").getEntry("distance_m")
        self._best_yaw    = self._t.getSubTable("tags").getSubTable("best").getEntry("yaw_deg")
        self._best_pitch  = self._t.getSubTable("tags").getSubTable("best").getEntry("pitch_deg")
        self._best_tx     = self._t.getSubTable("tags").getSubTable("best").getEntry("tx")
        self._best_ty     = self._t.getSubTable("tags").getSubTable("best").getEntry("ty")
        self._best_area   = self._t.getSubTable("tags").getSubTable("best").getEntry("area")
        self._best_ts     = self._t.getSubTable("tags").getSubTable("best").getEntry("timestamp")
        self._best_marg   = self._t.getSubTable("tags").getSubTable("best").getEntry("decision_margin")
        self._all_json    = self._t.getSubTable("tags").getEntry("all")

    # ----- connection state -----

    def is_connected(self) -> bool:
        """Heartbeat fresh within the staleness window?"""
        last = self._heartbeat.getLastChange() / 1_000_000.0  # μs → s
        return (time.time() - last) < _STALE_AFTER_S

    # ----- tags -----

    def get_best_tag(self) -> Optional[TagDetection]:
        if not self.is_connected():
            return None
        tag_id = int(self._best_id.getDouble(-1))
        if tag_id < 0:
            return None
        return TagDetection(
            id=tag_id,
            distance_m=self._best_dist.getDouble(0.0),
            yaw_deg=self._best_yaw.getDouble(0.0),
            pitch_deg=self._best_pitch.getDouble(0.0),
            tx=self._best_tx.getDouble(0.0),
            ty=self._best_ty.getDouble(0.0),
            area=self._best_area.getDouble(0.0),
            timestamp=self._best_ts.getDouble(0.0),
            decision_margin=self._best_marg.getDouble(0.0),
        )

    def get_all_tags(self) -> List[TagDetection]:
        if not self.is_connected():
            return []
        raw = self._all_json.getString("[]")
        try:
            arr = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [
            TagDetection(
                id=int(t.get("id", -1)),
                distance_m=float(t.get("distance_m", 0.0)),
                yaw_deg=float(t.get("yaw_deg", 0.0)),
                pitch_deg=float(t.get("pitch_deg", 0.0)),
                tx=float(t.get("tx", 0.0)),
                ty=float(t.get("ty", 0.0)),
                area=float(t.get("area", 0.0)),
                timestamp=float(t.get("timestamp", 0.0)),
                decision_margin=float(t.get("decision_margin", 0.0)),
            )
            for t in arr
        ]

    # ----- objects (off by default in v1) -----

    def get_best_object(self) -> Optional[ObjectDetection]:
        # TODO: read /acuity/objects/best/*
        return None

    # ----- health -----

    def get_health(self) -> DeviceHealth:
        h = self._t.getSubTable("health")
        return DeviceHealth(
            cpu_pct=h.getEntry("cpu_pct").getDouble(0.0),
            temp_c=h.getEntry("temp_c").getDouble(0.0),
            uptime_seconds=int(h.getEntry("uptime_s").getDouble(0)),
        )


__all__ = [
    "AcuityVision",
    "TagDetection",
    "ObjectDetection",
    "DeviceHealth",
]
