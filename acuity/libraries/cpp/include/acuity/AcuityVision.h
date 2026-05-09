// Acuity Vision — C++ client library.
//
// Reads the NetworkTables 4 schema documented in
// acuity/docs/nt4-schema.md and exposes a typed C++ API.
//
// Skeleton — networktables/ntcore.h includes are TODO until the
// vendordep build is wired up.

#pragma once

#include <optional>
#include <string>
#include <vector>

namespace acuity {

struct TagDetection {
  int    id;
  double distanceMeters;
  double yawDeg;
  double pitchDeg;
  double tx;             // normalized [-1, 1]
  double ty;
  double area;
  double timestamp;      // FPGA seconds when frame was captured
  double decisionMargin;
};

struct ObjectDetection {
  std::string className;
  double      confidence;
  double      tx;
  double      ty;
};

struct DeviceHealth {
  double  cpuPct;
  double  tempC;
  int64_t uptimeSeconds;
};

class AcuityVision {
 public:
  /** Returns the global Acuity client. */
  static AcuityVision& GetInstance();

  /** Largest AprilTag in view, or nullopt. */
  std::optional<TagDetection> GetBestTag() const;

  /** Every AprilTag in the current frame. */
  std::vector<TagDetection> GetAllTags() const;

  /** Best detected object if object detection is on. */
  std::optional<ObjectDetection> GetBestObject() const;

  /** Current device health snapshot. */
  DeviceHealth GetHealth() const;

  /** True if heartbeat is fresh (within ~100ms). */
  bool IsConnected() const;

 private:
  AcuityVision();
  AcuityVision(const AcuityVision&)            = delete;
  AcuityVision& operator=(const AcuityVision&) = delete;
};

}  // namespace acuity
