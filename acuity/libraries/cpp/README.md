# Acuity Vision — C++ vendordep

WPILib vendordep for the Acuity vision coprocessor, in C++.

## Install

In VS Code with the WPILib extension:

1. **WPILib → Manage Vendor Libraries → Install new library (online)**
2. Paste:
   ```
   https://acuity.tech/vendordep/Acuity.json
   ```
   (Same JSON as the Java vendordep — WPILib's vendordep system
   serves both targets from one manifest.)
3. Hit OK.

## Use

```cpp
#include <acuity/AcuityVision.h>

class Robot : public frc::TimedRobot {
 public:
  void RobotPeriodic() override {
    if (auto tag = vision.GetBestTag()) {
      frc::SmartDashboard::PutNumber("acuity/id",         tag->id);
      frc::SmartDashboard::PutNumber("acuity/distance_m", tag->distanceMeters);
      frc::SmartDashboard::PutNumber("acuity/yaw_deg",    tag->yawDeg);
    }
  }

 private:
  acuity::AcuityVision vision = acuity::AcuityVision::GetInstance();
};
```

## Status

Skeleton only. Header sketches the API in
[include/acuity/AcuityVision.h](include/acuity/AcuityVision.h);
the .cpp sources + Gradle build are TODO.
