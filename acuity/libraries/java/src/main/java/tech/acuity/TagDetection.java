package tech.acuity;

import java.util.ArrayList;
import java.util.List;

/**
 * One AprilTag, projected into the Acuity coordinate system.
 *
 * <p>Sentinel: {@code id == -1} means "no tag" — we encode absence
 * with a sentinel rather than null because the call sites (e.g.
 * {@code AcuityVision.getBestTag().ifPresent(...)}) already wrap
 * absence in {@link java.util.Optional}.
 *
 * <p>{@link #tx} and {@link #ty} are normalized pixel offsets from
 * frame center, both in {@code [-1, 1]}, so they don't depend on
 * camera resolution.
 */
public final class TagDetection {
  public final int id;
  public final double distanceMeters;
  public final double yawDeg;
  public final double pitchDeg;
  public final double tx;
  public final double ty;
  public final double area;
  public final double timestamp;
  public final double decisionMargin;

  public TagDetection(
      int id,
      double distanceMeters,
      double yawDeg,
      double pitchDeg,
      double tx,
      double ty,
      double area,
      double timestamp,
      double decisionMargin) {
    this.id = id;
    this.distanceMeters = distanceMeters;
    this.yawDeg = yawDeg;
    this.pitchDeg = pitchDeg;
    this.tx = tx;
    this.ty = ty;
    this.area = area;
    this.timestamp = timestamp;
    this.decisionMargin = decisionMargin;
  }

  /**
   * Parse the JSON array from {@code /acuity/tags/all}. We hand-roll
   * a minimal parser instead of pulling Jackson / Gson in as a
   * vendordep dep — the schema is fixed, the input is small, and a
   * 60-line state machine keeps the library footprint trivial.
   *
   * <p>The format is a flat JSON array of objects with the same field
   * names as this class. We tolerate missing fields (default 0 / -1)
   * and ignore unknown ones, so device-side schema additions don't
   * break old library versions.
   */
  static List<TagDetection> parseJsonArray(String json) {
    List<TagDetection> out = new ArrayList<>();
    int i = 0, n = json.length();

    // Skip to first '[' (we tolerate leading whitespace / a wrapper).
    while (i < n && json.charAt(i) != '[') i++;
    if (i == n) return out;
    i++;  // past [

    while (i < n) {
      while (i < n && (Character.isWhitespace(json.charAt(i)) || json.charAt(i) == ',')) i++;
      if (i >= n || json.charAt(i) == ']') break;
      if (json.charAt(i) != '{') break;
      int objStart = i;
      int depth = 0;
      while (i < n) {
        char c = json.charAt(i);
        if (c == '{') depth++;
        else if (c == '}') { depth--; if (depth == 0) { i++; break; } }
        else if (c == '"') {
          i++;
          while (i < n && json.charAt(i) != '"') {
            if (json.charAt(i) == '\\' && i + 1 < n) i++;
            i++;
          }
        }
        i++;
      }
      String obj = json.substring(objStart, Math.min(i, n));
      out.add(fromObject(obj));
    }
    return out;
  }

  /** Parse a single {"id":..., "distance_m":..., ...} object. */
  private static TagDetection fromObject(String obj) {
    return new TagDetection(
        (int) extractDouble(obj, "id", -1),
        extractDouble(obj, "distance_m", 0),
        extractDouble(obj, "yaw_deg", 0),
        extractDouble(obj, "pitch_deg", 0),
        extractDouble(obj, "tx", 0),
        extractDouble(obj, "ty", 0),
        extractDouble(obj, "area", 0),
        extractDouble(obj, "timestamp", 0),
        extractDouble(obj, "decision_margin", 0));
  }

  /** Pull "key": <number> out of a JSON object string. Returns {@code def} if missing. */
  private static double extractDouble(String obj, String key, double def) {
    String needle = "\"" + key + "\"";
    int k = obj.indexOf(needle);
    if (k < 0) return def;
    int colon = obj.indexOf(':', k + needle.length());
    if (colon < 0) return def;
    int j = colon + 1;
    while (j < obj.length() && Character.isWhitespace(obj.charAt(j))) j++;
    int start = j;
    while (j < obj.length()) {
      char c = obj.charAt(j);
      if (c == ',' || c == '}' || Character.isWhitespace(c)) break;
      j++;
    }
    try {
      return Double.parseDouble(obj.substring(start, j));
    } catch (NumberFormatException e) {
      return def;
    }
  }
}
