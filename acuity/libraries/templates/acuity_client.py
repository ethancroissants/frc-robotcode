"""acuity_client.py — drop-in helper for talking to an Acuity vision
coprocessor over NetworkTables 4 from robotpy.

Subscribes to /acuity/* topics published by the on-device dashboard;
gives robot code a typed `TagDetection` so they don't have to deal
with raw NT4 calls.

Zero pip dependencies beyond robotpy's bundled `ntcore`. Manager
dropped this file in for you; if you want to update it, re-run the
Libraries tab.

Usage:

    from acuity_client import AcuityClient

    class MyRobot(wpilib.TimedRobot):
        def robotInit(self):
            self.acuity = AcuityClient()

        def teleopPeriodic(self):
            tag = self.acuity.get_best_tag()
            if tag is not None:
                self.shooter.aim(tag.yaw_deg, tag.distance_m)

Schema reference: see your Acuity device's Docs tab → "NetworkTables
schema", or acuity/docs/nt4-schema.md in the firmware repo.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import List, Optional

import ntcore


@dataclass(frozen=True)
class TagDetection:
    id: int
    distance_m: float
    yaw_deg: float
    pitch_deg: float
    tx: float
    ty: float
    area: float
    timestamp: float
    decision_margin: float


@dataclass(frozen=True)
class Health:
    cpu_pct: float
    temp_c: float
    uptime_s: int


class AcuityClient:
    """Single-instance NT4 reader for an Acuity device.

    Construct one of these in robotInit and reuse it. Cheap to call
    `get_best_tag()` every periodic tick — it's just NT4 reads.
    """

    # Heartbeat-staleness window (ms). NT4 is push-based, so the
    # useful "is the device alive" check is "did we receive a fresh
    # heartbeat lately?" rather than a wire-level connection probe.
    STALE_MS = 250

    def __init__(self):
        inst = ntcore.NetworkTableInstance.getDefault()
        t = inst.getTable("acuity")
        self._heartbeat = t.getIntegerTopic("heartbeat").subscribe(0)
        self._best_id   = t.getIntegerTopic("tags/best/id").subscribe(-1)
        self._best_dist = t.getDoubleTopic("tags/best/distance_m").subscribe(0.0)
        self._best_yaw  = t.getDoubleTopic("tags/best/yaw_deg").subscribe(0.0)
        self._best_pitch = t.getDoubleTopic("tags/best/pitch_deg").subscribe(0.0)
        self._best_tx   = t.getDoubleTopic("tags/best/tx").subscribe(0.0)
        self._best_ty   = t.getDoubleTopic("tags/best/ty").subscribe(0.0)
        self._best_area = t.getDoubleTopic("tags/best/area").subscribe(0.0)
        self._best_ts   = t.getDoubleTopic("tags/best/timestamp").subscribe(0.0)
        self._best_dm   = t.getDoubleTopic("tags/best/decision_margin").subscribe(0.0)
        self._all_tags  = t.getStringTopic("tags/all").subscribe("[]")
        self._cpu_pct   = t.getDoubleTopic("health/cpu_pct").subscribe(0.0)
        self._temp_c    = t.getDoubleTopic("health/temp_c").subscribe(0.0)
        self._uptime    = t.getIntegerTopic("health/uptime_s").subscribe(0)

        # Heartbeat-change tracker. `_last_hb_change_ms == 0` means
        # "we've never seen a fresh value yet" — distinct from
        # "last fresh value was a long time ago".
        self._last_hb_value = -1
        self._last_hb_change_ms = 0

    def is_connected(self) -> bool:
        """True if the device has published a fresh heartbeat in the
        last STALE_MS milliseconds."""
        h = int(self._heartbeat.get())
        now_ms = int(time.monotonic() * 1000)
        if h != self._last_hb_value:
            self._last_hb_value = h
            self._last_hb_change_ms = now_ms
        return (self._last_hb_change_ms > 0
                and (now_ms - self._last_hb_change_ms) < self.STALE_MS)

    def get_best_tag(self) -> Optional[TagDetection]:
        """Best target in current frame, or None if none / device
        offline."""
        if not self.is_connected():
            return None
        id_ = int(self._best_id.get())
        if id_ < 0:
            return None
        return TagDetection(
            id=id_,
            distance_m=float(self._best_dist.get()),
            yaw_deg=float(self._best_yaw.get()),
            pitch_deg=float(self._best_pitch.get()),
            tx=float(self._best_tx.get()),
            ty=float(self._best_ty.get()),
            area=float(self._best_area.get()),
            timestamp=float(self._best_ts.get()),
            decision_margin=float(self._best_dm.get()),
        )

    def get_all_tags(self) -> List[TagDetection]:
        """Every tag visible in the latest frame. The all-tags topic
        is JSON-encoded — we parse it here so callers don't have to."""
        if not self.is_connected():
            return []
        try:
            data = json.loads(self._all_tags.get() or "[]")
        except (ValueError, TypeError):
            return []
        out: List[TagDetection] = []
        for d in data:
            if not isinstance(d, dict):
                continue
            try:
                out.append(TagDetection(
                    id=int(d.get("id", -1)),
                    distance_m=float(d.get("distance_m", 0.0)),
                    yaw_deg=float(d.get("yaw_deg", 0.0)),
                    pitch_deg=float(d.get("pitch_deg", 0.0)),
                    tx=float(d.get("tx", 0.0)),
                    ty=float(d.get("ty", 0.0)),
                    area=float(d.get("area", 0.0)),
                    timestamp=float(d.get("timestamp", 0.0)),
                    decision_margin=float(d.get("decision_margin", 0.0)),
                ))
            except (TypeError, ValueError):
                continue
        return out

    def get_health(self) -> Health:
        return Health(
            cpu_pct=float(self._cpu_pct.get()),
            temp_c=float(self._temp_c.get()),
            uptime_s=int(self._uptime.get()),
        )
