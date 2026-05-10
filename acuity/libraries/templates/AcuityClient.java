// AcuityClient.java
//
// Drop-in helper for reading from an Acuity vision coprocessor over
// NetworkTables 4. Subscribes to the /acuity/* topics the device's
// dashboard publishes; gives robot code a typed Optional<TagDetection>
// so they don't have to deal with raw NT4 calls.
//
// Zero external dependencies — just WPILib's bundled NT4. No vendordep
// to install, no Maven artifact to fetch. Manager dropped this file
// in for you; if you need to update it, re-run the Libraries tab.
//
// Usage:
//
//     import frc.robot.acuity.AcuityClient;
//
//     private final AcuityClient acuity = AcuityClient.getInstance();
//
//     @Override
//     public void teleopPeriodic() {
//       acuity.getBestTag().ifPresent(tag -> {
//         shooter.aim(tag.yawDeg(), tag.distanceMeters());
//       });
//     }
//
// Schema reference: see your Acuity device's Docs tab → "NetworkTables
// schema", or acuity/docs/nt4-schema.md in the firmware repo.

package frc.robot.acuity;

import edu.wpi.first.networktables.DoubleSubscriber;
import edu.wpi.first.networktables.IntegerSubscriber;
import edu.wpi.first.networktables.NetworkTable;
import edu.wpi.first.networktables.NetworkTableInstance;

import java.util.Optional;

public final class AcuityClient {

  /** Single tag detection from the device's "best target" topic. */
  public static record TagDetection(
      int id,
      double distanceMeters,
      double yawDeg,
      double pitchDeg,
      double tx,
      double ty,
      double area,
      double timestamp,
      double decisionMargin) {}

  /** On-device system health, mirrored from /acuity/health/*. */
  public static record Health(double cpuPct, double tempC, long uptimeS) {}

  // Heartbeat-staleness window. NT4 itself is push-based, so the
  // useful question isn't "is the wire connected" but "have we
  // received a fresh value lately?". 250 ms is comfortably bigger
  // than one frame at the slowest expected publish rate (10 Hz).
  private static final long STALE_MS = 250;

  private static AcuityClient instance;

  /** Process-wide singleton. Call this from robotInit / RobotPeriodic. */
  public static AcuityClient getInstance() {
    if (instance == null) instance = new AcuityClient();
    return instance;
  }

  private final IntegerSubscriber heartbeat;
  private final IntegerSubscriber bestId;
  private final DoubleSubscriber  bestDistanceM;
  private final DoubleSubscriber  bestYawDeg;
  private final DoubleSubscriber  bestPitchDeg;
  private final DoubleSubscriber  bestTx;
  private final DoubleSubscriber  bestTy;
  private final DoubleSubscriber  bestArea;
  private final DoubleSubscriber  bestTimestamp;
  private final DoubleSubscriber  bestDecisionMargin;
  private final DoubleSubscriber  cpuPct;
  private final DoubleSubscriber  tempC;
  private final IntegerSubscriber uptimeS;

  // We tell "stale" from "fresh" by watching the heartbeat int change.
  // The dashboard increments it once per published frame; if we keep
  // reading the same value, the device has gone away.
  private long lastHeartbeatValue = Long.MIN_VALUE;
  private long lastHeartbeatChangeMs = 0;

  private AcuityClient() {
    NetworkTable t = NetworkTableInstance.getDefault().getTable("acuity");
    heartbeat          = t.getIntegerTopic("heartbeat").subscribe(0);
    bestId             = t.getIntegerTopic("tags/best/id").subscribe(-1);
    bestDistanceM      = t.getDoubleTopic("tags/best/distance_m").subscribe(0.0);
    bestYawDeg         = t.getDoubleTopic("tags/best/yaw_deg").subscribe(0.0);
    bestPitchDeg       = t.getDoubleTopic("tags/best/pitch_deg").subscribe(0.0);
    bestTx             = t.getDoubleTopic("tags/best/tx").subscribe(0.0);
    bestTy             = t.getDoubleTopic("tags/best/ty").subscribe(0.0);
    bestArea           = t.getDoubleTopic("tags/best/area").subscribe(0.0);
    bestTimestamp      = t.getDoubleTopic("tags/best/timestamp").subscribe(0.0);
    bestDecisionMargin = t.getDoubleTopic("tags/best/decision_margin").subscribe(0.0);
    cpuPct             = t.getDoubleTopic("health/cpu_pct").subscribe(0.0);
    tempC              = t.getDoubleTopic("health/temp_c").subscribe(0.0);
    uptimeS            = t.getIntegerTopic("health/uptime_s").subscribe(0);
  }

  /** True when the device has published an updated heartbeat in the
   *  last 250 ms. Use this to gate display logic ("device offline"). */
  public boolean isConnected() {
    long h = heartbeat.get();
    long now = System.currentTimeMillis();
    if (h != lastHeartbeatValue) {
      lastHeartbeatValue = h;
      lastHeartbeatChangeMs = now;
    }
    return lastHeartbeatChangeMs > 0
        && (now - lastHeartbeatChangeMs) < STALE_MS;
  }

  /** Best target in current frame, or empty if none / device offline.
   *  "Best" is whichever tag the dashboard's selection logic picked
   *  (operator-locked tag → preferred-list match → largest tag). */
  public Optional<TagDetection> getBestTag() {
    if (!isConnected()) return Optional.empty();
    int id = (int) bestId.get();
    if (id < 0) return Optional.empty();
    return Optional.of(new TagDetection(
        id,
        bestDistanceM.get(),
        bestYawDeg.get(),
        bestPitchDeg.get(),
        bestTx.get(),
        bestTy.get(),
        bestArea.get(),
        bestTimestamp.get(),
        bestDecisionMargin.get()));
  }

  /** SoC stats — mostly useful for telemetry overlays. */
  public Health getHealth() {
    return new Health(cpuPct.get(), tempC.get(), uptimeS.get());
  }
}
