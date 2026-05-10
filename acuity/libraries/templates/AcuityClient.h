// AcuityClient.h
//
// Drop-in helper for reading from an Acuity vision coprocessor over
// NetworkTables 4. Subscribes to the /acuity/* topics the device's
// dashboard publishes; gives robot code a typed std::optional<TagDetection>
// so they don't have to deal with raw NT4 calls.
//
// Header-only — no .cpp to add to your gradle build, no library to
// link, no vendordep to install. Just `#include "acuity/AcuityClient.h"`.
//
// Usage:
//
//     #include "acuity/AcuityClient.h"
//
//     class Robot : public frc::TimedRobot {
//       acuity::AcuityClient acuity{};
//
//       void TeleopPeriodic() override {
//         if (auto tag = acuity.GetBestTag()) {
//           shooter.Aim(tag->yawDeg, tag->distanceMeters);
//         }
//       }
//     };
//
// Schema reference: see your Acuity device's Docs tab → "NetworkTables
// schema", or acuity/docs/nt4-schema.md in the firmware repo.

#pragma once

#include <chrono>
#include <cstdint>
#include <optional>

#include "networktables/DoubleTopic.h"
#include "networktables/IntegerTopic.h"
#include "networktables/NetworkTable.h"
#include "networktables/NetworkTableInstance.h"

namespace acuity {

struct TagDetection {
  int     id;
  double  distanceMeters;
  double  yawDeg;
  double  pitchDeg;
  double  tx;
  double  ty;
  double  area;
  double  timestamp;
  double  decisionMargin;
};

struct Health {
  double  cpuPct;
  double  tempC;
  int64_t uptimeS;
};

class AcuityClient {
 public:
  AcuityClient() {
    auto inst = nt::NetworkTableInstance::GetDefault();
    auto t    = inst.GetTable("acuity");
    heartbeat_          = t->GetIntegerTopic("heartbeat").Subscribe(0);
    bestId_             = t->GetIntegerTopic("tags/best/id").Subscribe(-1);
    bestDistanceM_      = t->GetDoubleTopic("tags/best/distance_m").Subscribe(0.0);
    bestYawDeg_         = t->GetDoubleTopic("tags/best/yaw_deg").Subscribe(0.0);
    bestPitchDeg_       = t->GetDoubleTopic("tags/best/pitch_deg").Subscribe(0.0);
    bestTx_             = t->GetDoubleTopic("tags/best/tx").Subscribe(0.0);
    bestTy_             = t->GetDoubleTopic("tags/best/ty").Subscribe(0.0);
    bestArea_           = t->GetDoubleTopic("tags/best/area").Subscribe(0.0);
    bestTimestamp_      = t->GetDoubleTopic("tags/best/timestamp").Subscribe(0.0);
    bestDecisionMargin_ = t->GetDoubleTopic("tags/best/decision_margin").Subscribe(0.0);
    cpuPct_             = t->GetDoubleTopic("health/cpu_pct").Subscribe(0.0);
    tempC_              = t->GetDoubleTopic("health/temp_c").Subscribe(0.0);
    uptimeS_            = t->GetIntegerTopic("health/uptime_s").Subscribe(0);
  }

  // True when the device has published an updated heartbeat in the
  // last 250 ms. Use this to gate display logic ("device offline").
  bool IsConnected() {
    int64_t h   = heartbeat_.Get();
    auto    now = std::chrono::steady_clock::now();
    if (h != lastHbValue_) {
      lastHbValue_  = h;
      lastHbChange_ = now;
    }
    using namespace std::chrono_literals;
    return lastHbChange_.time_since_epoch().count() != 0
        && (now - lastHbChange_) < 250ms;
  }

  // Best target in current frame, or std::nullopt if none / device
  // offline. "Best" = whichever tag the dashboard's selection logic
  // picked (operator-locked → preferred-list match → largest tag).
  std::optional<TagDetection> GetBestTag() {
    if (!IsConnected()) return std::nullopt;
    int64_t id = bestId_.Get();
    if (id < 0) return std::nullopt;
    return TagDetection{
        static_cast<int>(id),
        bestDistanceM_.Get(),
        bestYawDeg_.Get(),
        bestPitchDeg_.Get(),
        bestTx_.Get(),
        bestTy_.Get(),
        bestArea_.Get(),
        bestTimestamp_.Get(),
        bestDecisionMargin_.Get(),
    };
  }

  // SoC stats from /acuity/health/* — telemetry overlay material.
  Health GetHealth() {
    return Health{cpuPct_.Get(), tempC_.Get(), uptimeS_.Get()};
  }

 private:
  nt::IntegerSubscriber heartbeat_;
  nt::IntegerSubscriber bestId_;
  nt::DoubleSubscriber  bestDistanceM_;
  nt::DoubleSubscriber  bestYawDeg_;
  nt::DoubleSubscriber  bestPitchDeg_;
  nt::DoubleSubscriber  bestTx_;
  nt::DoubleSubscriber  bestTy_;
  nt::DoubleSubscriber  bestArea_;
  nt::DoubleSubscriber  bestTimestamp_;
  nt::DoubleSubscriber  bestDecisionMargin_;
  nt::DoubleSubscriber  cpuPct_;
  nt::DoubleSubscriber  tempC_;
  nt::IntegerSubscriber uptimeS_;

  int64_t                                lastHbValue_{INT64_MIN};
  std::chrono::steady_clock::time_point  lastHbChange_{};
};

}  // namespace acuity
