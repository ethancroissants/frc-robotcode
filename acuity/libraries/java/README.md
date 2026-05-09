# Acuity Vision — Java vendordep

Drop-in WPILib vendordep for the Acuity vision coprocessor.

## Install

In VS Code with the WPILib extension:

1. **WPILib → Manage Vendor Libraries → Install new library (online)**
2. Paste:
   ```
   https://acuity.tech/vendordep/Acuity.json
   ```
   (URL TBD — currently a placeholder; will be served from GitHub Pages
   once the publish pipeline lands.)
3. Hit OK.

Or copy `Acuity.json` from this folder into your project's `vendordeps/`
directory manually.

## Use

```java
import tech.acuity.AcuityVision;
import tech.acuity.TagDetection;

public class Robot extends TimedRobot {
  private final AcuityVision vision = AcuityVision.getInstance();

  @Override
  public void robotPeriodic() {
    vision.getBestTag().ifPresent(tag -> {
      SmartDashboard.putNumber("acuity/id",         tag.id);
      SmartDashboard.putNumber("acuity/distance_m", tag.distanceMeters);
      SmartDashboard.putNumber("acuity/yaw_deg",    tag.yawDeg);
    });
  }
}
```

## Status

Skeleton. Class layout is in [src/main/java/tech/acuity/](src/main/java/tech/acuity/).
The Gradle wiring + GitHub Pages publishing of the vendordep JSON is
still TODO — see the product plan.
