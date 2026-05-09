# Acuity robot-side libraries

Three identical APIs in three languages. Pick the one your robot
project uses; they all read the same NT4 schema (see
[../docs/nt4-schema.md](../docs/nt4-schema.md)).

| Language | Distribution | Status |
|---|---|---|
| Java   | WPILib vendordep (JSON URL added via VS Code WPILib extension) | skeleton |
| Python | PyPI package, installed via `pip install acuity-vision`        | skeleton |
| C++    | WPILib vendordep                                               | skeleton |

## Common API

Each language exposes the same surface, named idiomatically.

```
class AcuityVision (singleton)

  Optional<TagDetection>     getBestTag()
  List<TagDetection>         getAllTags()
  Optional<ObjectDetection>  getBestObject()
  DeviceHealth               getHealth()
  bool                       isConnected()

class TagDetection
  int      id
  double   distanceMeters     // distance to tag center, m
  double   yawDeg             // signed yaw to tag, deg
  double   pitchDeg
  double   tx, ty             // pixel offset from frame center, normalized [-1, 1]
  double   area               // fraction of frame occupied
  double   timestamp          // FPGA seconds when frame was captured
  double   decisionMargin     // pyapriltags confidence

class ObjectDetection
  string   className
  double   confidence
  double   tx, ty

class DeviceHealth
  double   cpuPct
  double   tempC
  int      uptimeSeconds
```

Implementation details (NT4 topic paths, staleness windows, JSON
deserialization for `getAllTags()`) are hidden inside each language
binding. Schema changes that don't break compatibility (new fields,
new optional sections) ship as library updates without robot-code
changes.

## Why three SDKs instead of "just NT4"

Every team can talk NT4 directly. We ship libraries because:

* **Names.** `vision.getBestTag().yawDeg` reads better than
  `NetworkTableInstance.getDefault().getTable("acuity").getSubTable("tags").getSubTable("best").getEntry("yaw_deg").getDouble(0)`.
* **Staleness.** The library checks the heartbeat topic for you and
  returns `Optional.empty()` when the device disconnected; raw NT4
  silently returns the last cached value forever.
* **Schema upgrades.** When we go from `distance_m` to a `Pose3d`
  topic in v2, robot code that uses the library doesn't change — we
  ship a new library version that handles both. Raw NT4 users have
  to migrate manually.
