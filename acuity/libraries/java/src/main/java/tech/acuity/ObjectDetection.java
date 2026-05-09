package tech.acuity;

/** A single object detected by the on-device classifier. */
public final class ObjectDetection {
  public final String className;
  public final double confidence;
  public final double tx;
  public final double ty;

  public ObjectDetection(String className, double confidence, double tx, double ty) {
    this.className = className;
    this.confidence = confidence;
    this.tx = tx;
    this.ty = ty;
  }
}
