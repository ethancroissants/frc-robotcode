// Acuity Vision — C++ client implementation.
//
// Reads the NetworkTables 4 schema documented in
// acuity/docs/nt4-schema.md. Same connection / staleness model as
// the Java + Python bindings: every getter checks heartbeat
// freshness and returns nullopt when the device has dropped.

#include "acuity/AcuityVision.h"

#include <chrono>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

#include <networktables/DoubleTopic.h>
#include <networktables/IntegerTopic.h>
#include <networktables/NetworkTable.h>
#include <networktables/NetworkTableInstance.h>
#include <networktables/StringTopic.h>

namespace acuity {

// Heartbeat older than this means "the device is gone." See the Java
// binding for the rationale on the exact value.
static constexpr double kStaleAfterSeconds = 0.25;

// ---------------------------------------------------------------------
// Internal state
// ---------------------------------------------------------------------

namespace {

class AcuityImpl {
 public:
  AcuityImpl() {
    auto inst    = nt::NetworkTableInstance::GetDefault();
    m_root       = inst.GetTable("acuity");
    auto tags    = m_root->GetSubTable("tags");
    auto bestTag = tags->GetSubTable("best");
    auto bestObj = m_root->GetSubTable("objects")->GetSubTable("best");
    auto health  = m_root->GetSubTable("health");

    m_heartbeat        = m_root->GetIntegerTopic("heartbeat").Subscribe(0);
    m_bestId           = bestTag->GetIntegerTopic("id").Subscribe(-1);
    m_bestDistance     = bestTag->GetDoubleTopic("distance_m").Subscribe(0.0);
    m_bestYaw          = bestTag->GetDoubleTopic("yaw_deg").Subscribe(0.0);
    m_bestPitch        = bestTag->GetDoubleTopic("pitch_deg").Subscribe(0.0);
    m_bestTx           = bestTag->GetDoubleTopic("tx").Subscribe(0.0);
    m_bestTy           = bestTag->GetDoubleTopic("ty").Subscribe(0.0);
    m_bestArea         = bestTag->GetDoubleTopic("area").Subscribe(0.0);
    m_bestTimestamp    = bestTag->GetDoubleTopic("timestamp").Subscribe(0.0);
    m_bestDecisionMargin = bestTag->GetDoubleTopic("decision_margin").Subscribe(0.0);
    m_allTagsJson      = tags->GetStringTopic("all").Subscribe("[]");

    m_bestObjClass = bestObj->GetStringTopic("class").Subscribe("");
    m_bestObjConf  = bestObj->GetDoubleTopic("conf").Subscribe(0.0);
    m_bestObjTx    = bestObj->GetDoubleTopic("tx").Subscribe(0.0);
    m_bestObjTy    = bestObj->GetDoubleTopic("ty").Subscribe(0.0);

    m_cpuPct  = health->GetDoubleTopic("cpu_pct").Subscribe(0.0);
    m_tempC   = health->GetDoubleTopic("temp_c").Subscribe(0.0);
    m_uptimeS = health->GetIntegerTopic("uptime_s").Subscribe(0);
  }

  bool IsConnected() const {
    auto atomic = m_heartbeat.GetAtomic();
    if (atomic.time == 0) return false;
    double nowSec  = static_cast<double>(
        std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count()) / 1e6;
    double lastSec = static_cast<double>(atomic.time) / 1e6;
    return (nowSec - lastSec) < kStaleAfterSeconds;
  }

  std::optional<TagDetection> GetBestTag() const {
    if (!IsConnected()) return std::nullopt;
    int id = static_cast<int>(m_bestId.Get());
    if (id < 0) return std::nullopt;
    return TagDetection{
        id,
        m_bestDistance.Get(),
        m_bestYaw.Get(),
        m_bestPitch.Get(),
        m_bestTx.Get(),
        m_bestTy.Get(),
        m_bestArea.Get(),
        m_bestTimestamp.Get(),
        m_bestDecisionMargin.Get(),
    };
  }

  std::vector<TagDetection> GetAllTags() const {
    if (!IsConnected()) return {};
    std::string json = m_allTagsJson.Get();
    return ParseTagJsonArray(json);
  }

  std::optional<ObjectDetection> GetBestObject() const {
    if (!IsConnected()) return std::nullopt;
    std::string klass = m_bestObjClass.Get();
    if (klass.empty()) return std::nullopt;
    return ObjectDetection{std::move(klass),
                           m_bestObjConf.Get(),
                           m_bestObjTx.Get(),
                           m_bestObjTy.Get()};
  }

  DeviceHealth GetHealth() const {
    return DeviceHealth{
        m_cpuPct.Get(),
        m_tempC.Get(),
        static_cast<int64_t>(m_uptimeS.Get()),
    };
  }

 private:
  // Hand-rolled JSON parser — we only need to extract a flat list of
  // {"id":..., "distance_m":..., ...} objects, and pulling in nlohmann
  // / RapidJSON as a vendordep transitive dep isn't worth it.
  static std::vector<TagDetection> ParseTagJsonArray(const std::string& s) {
    std::vector<TagDetection> out;
    size_t i = 0, n = s.size();
    while (i < n && s[i] != '[') i++;
    if (i == n) return out;
    i++;
    while (i < n) {
      while (i < n && (std::isspace(static_cast<unsigned char>(s[i])) || s[i] == ',')) i++;
      if (i >= n || s[i] == ']') break;
      if (s[i] != '{') break;
      size_t objStart = i;
      int depth = 0;
      while (i < n) {
        char c = s[i];
        if (c == '{') depth++;
        else if (c == '}') { depth--; if (depth == 0) { i++; break; } }
        else if (c == '"') {
          i++;
          while (i < n && s[i] != '"') {
            if (s[i] == '\\' && i + 1 < n) i++;
            i++;
          }
        }
        i++;
      }
      out.push_back(TagFromObject(s.substr(objStart, i - objStart)));
    }
    return out;
  }

  static TagDetection TagFromObject(const std::string& obj) {
    return TagDetection{
        static_cast<int>(ExtractDouble(obj, "id", -1)),
        ExtractDouble(obj, "distance_m", 0),
        ExtractDouble(obj, "yaw_deg", 0),
        ExtractDouble(obj, "pitch_deg", 0),
        ExtractDouble(obj, "tx", 0),
        ExtractDouble(obj, "ty", 0),
        ExtractDouble(obj, "area", 0),
        ExtractDouble(obj, "timestamp", 0),
        ExtractDouble(obj, "decision_margin", 0),
    };
  }

  static double ExtractDouble(const std::string& obj, const std::string& key, double def) {
    std::string needle = "\"" + key + "\"";
    auto k = obj.find(needle);
    if (k == std::string::npos) return def;
    auto colon = obj.find(':', k + needle.size());
    if (colon == std::string::npos) return def;
    auto j = colon + 1;
    while (j < obj.size() && std::isspace(static_cast<unsigned char>(obj[j]))) j++;
    auto start = j;
    while (j < obj.size()) {
      char c = obj[j];
      if (c == ',' || c == '}' || std::isspace(static_cast<unsigned char>(c))) break;
      j++;
    }
    try {
      return std::stod(obj.substr(start, j - start));
    } catch (...) {
      return def;
    }
  }

  std::shared_ptr<nt::NetworkTable> m_root;

  nt::IntegerSubscriber m_heartbeat;
  nt::IntegerSubscriber m_bestId;
  nt::DoubleSubscriber  m_bestDistance;
  nt::DoubleSubscriber  m_bestYaw;
  nt::DoubleSubscriber  m_bestPitch;
  nt::DoubleSubscriber  m_bestTx;
  nt::DoubleSubscriber  m_bestTy;
  nt::DoubleSubscriber  m_bestArea;
  nt::DoubleSubscriber  m_bestTimestamp;
  nt::DoubleSubscriber  m_bestDecisionMargin;
  nt::StringSubscriber  m_allTagsJson;

  nt::StringSubscriber m_bestObjClass;
  nt::DoubleSubscriber m_bestObjConf;
  nt::DoubleSubscriber m_bestObjTx;
  nt::DoubleSubscriber m_bestObjTy;

  nt::DoubleSubscriber  m_cpuPct;
  nt::DoubleSubscriber  m_tempC;
  nt::IntegerSubscriber m_uptimeS;
};

AcuityImpl& Impl() {
  // Lazy singleton — same lifetime as the parent process.
  static AcuityImpl impl;
  return impl;
}

}  // namespace

// ---------------------------------------------------------------------
// Public API — delegates to the singleton impl.
// ---------------------------------------------------------------------

AcuityVision::AcuityVision() = default;

AcuityVision& AcuityVision::GetInstance() {
  static AcuityVision instance;
  Impl();  // ensure constructed
  return instance;
}

std::optional<TagDetection> AcuityVision::GetBestTag() const {
  return Impl().GetBestTag();
}

std::vector<TagDetection> AcuityVision::GetAllTags() const {
  return Impl().GetAllTags();
}

std::optional<ObjectDetection> AcuityVision::GetBestObject() const {
  return Impl().GetBestObject();
}

DeviceHealth AcuityVision::GetHealth() const {
  return Impl().GetHealth();
}

bool AcuityVision::IsConnected() const {
  return Impl().IsConnected();
}

}  // namespace acuity
