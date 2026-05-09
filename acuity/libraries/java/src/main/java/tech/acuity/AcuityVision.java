// Acuity Vision — Java client library.
//
// Thin wrapper around NetworkTables 4. Reads the schema documented in
// acuity/docs/nt4-schema.md and exposes a typed, idiomatic Java API
// so robot code never has to remember topic paths.
//
// Connection / staleness model:
//   * The library does not "connect" or "disconnect" — that's NT4's
//     job. We just observe whether the device's heartbeat topic has
//     been updated within `STALE_AFTER_SECONDS`.
//   * Every getter returns Optional.empty() (or a stale-flagged
//     DeviceHealth) when the device is gone, so robot code never sees
//     stale tag data treated as live.

package tech.acuity;

import edu.wpi.first.networktables.DoubleSubscriber;
import edu.wpi.first.networktables.IntegerSubscriber;
import edu.wpi.first.networktables.NetworkTable;
import edu.wpi.first.networktables.NetworkTableInstance;
import edu.wpi.first.networktables.PubSubOption;
import edu.wpi.first.networktables.StringSubscriber;
import edu.wpi.first.networktables.Topic;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * Singleton entry point for the Acuity vision coprocessor.
 *
 * <pre>
 * AcuityVision vision = AcuityVision.getInstance();
 * vision.getBestTag().ifPresent(tag -> {
 *   double yaw = tag.yawDeg;
 * });
 * </pre>
 */
public final class AcuityVision {

  /**
   * Heartbeat older than this means "the device is gone." 100ms is
   * one Acuity heartbeat interval at 10 Hz, plus a safety margin —
   * tight enough that robot code reacts fast when the device drops,
   * loose enough that a single skipped heartbeat doesn't flap.
   */
  private static final double STALE_AFTER_SECONDS = 0.25;

  private static AcuityVision instance;

  private final NetworkTable        root;
  private final NetworkTable        bestTag;
  private final NetworkTable        tags;
  private final NetworkTable        bestObj;
  private final NetworkTable        health;

  private final IntegerSubscriber   heartbeat;
  private final IntegerSubscriber   bestId;
  private final DoubleSubscriber    bestDistance;
  private final DoubleSubscriber    bestYaw;
  private final DoubleSubscriber    bestPitch;
  private final DoubleSubscriber    bestTx;
  private final DoubleSubscriber    bestTy;
  private final DoubleSubscriber    bestArea;
  private final DoubleSubscriber    bestTimestamp;
  private final DoubleSubscriber    bestDecisionMargin;
  private final StringSubscriber    allTagsJson;

  private final StringSubscriber    bestObjClass;
  private final DoubleSubscriber    bestObjConf;
  private final DoubleSubscriber    bestObjTx;
  private final DoubleSubscriber    bestObjTy;

  private final DoubleSubscriber    cpuPct;
  private final DoubleSubscriber    tempC;
  private final IntegerSubscriber   uptimeS;

  private AcuityVision() {
    NetworkTableInstance nt = NetworkTableInstance.getDefault();
    root    = nt.getTable("acuity");
    tags    = root.getSubTable("tags");
    bestTag = tags.getSubTable("best");
    bestObj = root.getSubTable("objects").getSubTable("best");
    health  = root.getSubTable("health");

    PubSubOption[] opts = { PubSubOption.keepDuplicates(false) };

    heartbeat          = root.getIntegerTopic("heartbeat").subscribe(0, opts);
    bestId             = bestTag.getIntegerTopic("id").subscribe(-1, opts);
    bestDistance       = bestTag.getDoubleTopic("distance_m").subscribe(0.0, opts);
    bestYaw            = bestTag.getDoubleTopic("yaw_deg").subscribe(0.0, opts);
    bestPitch          = bestTag.getDoubleTopic("pitch_deg").subscribe(0.0, opts);
    bestTx             = bestTag.getDoubleTopic("tx").subscribe(0.0, opts);
    bestTy             = bestTag.getDoubleTopic("ty").subscribe(0.0, opts);
    bestArea           = bestTag.getDoubleTopic("area").subscribe(0.0, opts);
    bestTimestamp      = bestTag.getDoubleTopic("timestamp").subscribe(0.0, opts);
    bestDecisionMargin = bestTag.getDoubleTopic("decision_margin").subscribe(0.0, opts);
    allTagsJson        = tags.getStringTopic("all").subscribe("[]", opts);

    bestObjClass = bestObj.getStringTopic("class").subscribe("", opts);
    bestObjConf  = bestObj.getDoubleTopic("conf").subscribe(0.0, opts);
    bestObjTx    = bestObj.getDoubleTopic("tx").subscribe(0.0, opts);
    bestObjTy    = bestObj.getDoubleTopic("ty").subscribe(0.0, opts);

    cpuPct  = health.getDoubleTopic("cpu_pct").subscribe(0.0, opts);
    tempC   = health.getDoubleTopic("temp_c").subscribe(0.0, opts);
    uptimeS = health.getIntegerTopic("uptime_s").subscribe(0, opts);
  }

  /** Returns the global Acuity client, creating it lazily. */
  public static synchronized AcuityVision getInstance() {
    if (instance == null) instance = new AcuityVision();
    return instance;
  }

  /**
   * Largest AprilTag in the camera's current frame, or empty if no
   * tag is in view (or the device is disconnected).
   */
  public Optional<TagDetection> getBestTag() {
    if (!isConnected()) return Optional.empty();
    int id = (int) bestId.get();
    if (id < 0) return Optional.empty();
    return Optional.of(new TagDetection(
        id,
        bestDistance.get(),
        bestYaw.get(),
        bestPitch.get(),
        bestTx.get(),
        bestTy.get(),
        bestArea.get(),
        bestTimestamp.get(),
        bestDecisionMargin.get()));
  }

  /**
   * Every AprilTag in the current frame. Empty list if none in view
   * or device is disconnected. Parsed once per call from the JSON
   * blob the device publishes — cheap, but call once per loop and
   * cache if you're iterating heavily.
   */
  public List<TagDetection> getAllTags() {
    if (!isConnected()) return List.of();
    String json = allTagsJson.get();
    if (json == null || json.isEmpty() || json.equals("[]")) return List.of();
    return TagDetection.parseJsonArray(json);
  }

  /** Highest-confidence detected object, if object detection is enabled. */
  public Optional<ObjectDetection> getBestObject() {
    if (!isConnected()) return Optional.empty();
    String klass = bestObjClass.get();
    if (klass == null || klass.isEmpty()) return Optional.empty();
    return Optional.of(new ObjectDetection(
        klass, bestObjConf.get(), bestObjTx.get(), bestObjTy.get()));
  }

  /** Current device health snapshot. Always returns; check {@link #isConnected()} for liveness. */
  public DeviceHealth getHealth() {
    return new DeviceHealth(cpuPct.get(), tempC.get(), uptimeS.get());
  }

  /** True if heartbeat has been seen within the staleness window. */
  public boolean isConnected() {
    long lastChangeMicros = heartbeat.getAtomic().timestamp;
    if (lastChangeMicros == 0) return false;  // never received
    double nowSec  = NetworkTableInstance.getDefault().getServerTimeOffset()
                       .map(off -> (System.currentTimeMillis() * 1000.0 + off) / 1e6)
                       .orElse(System.currentTimeMillis() / 1e3);
    double lastSec = lastChangeMicros / 1e6;
    return (nowSec - lastSec) < STALE_AFTER_SECONDS;
  }
}
