# Getting started

Five-minute walk from a sealed box to AprilTag data on your robot.

## What's in the box

* The device (Pi Zero 2 W in case, SD pre-flashed, camera attached)
* Micro-USB B → USB-A power cable (~30 cm)
* Mounting hardware (M2.5 screws + standoffs OR a VHB pad)
* Quick-start card (this doc, abridged, on a 4×6")

## 1. Mount on the robot

Mount the device with the camera pointing at whatever you want to track
(the AprilTag layout, the field, the intake). Two mounting options:

* **Screws.** M2.5 threaded mounts on the back of the case. Most rigid.
* **VHB tape.** Strip on the back. Faster, less ideal for vibration.

Aim the camera. Loose is fine for now — you'll fine-tune in the
calibrate step.

## 2. Power it

Plug the included micro-USB cable into the device, the USB-A end into
the **RoboRIO's USB-A port**. The Pi draws ~250 mA idle, ~600 mA peak.
The RIO supplies up to 2.5 A. Plenty.

Power on the robot. The status LED on the case will:

* **Solid yellow for ~20 s** while the Pi boots.
* **Slow yellow blink** = AP mode (no team WiFi configured yet).
* **Steady green** = STA mode (joined team WiFi).

## 3. First-boot setup (AP mode)

If the LED is slow-blinking yellow, the device is broadcasting an open
WiFi network for setup.

1. **On a phone** (or any laptop), open WiFi settings. Look for a
   network called `Acuity-Setup-XXXX` (the suffix is the device's MAC
   tail, so two devices on the same bench show up distinctly).
2. **Connect to it.** No password.
3. **The captive portal opens automatically** on most phones —
   iOS pops a sheet, Android pops a notification you tap. If nothing
   pops, open a browser and visit:

   `http://192.168.50.1/`

4. **Fill in the form:**
   * **Team number** → your FRC team (drives hostname + static IP).
   * **Robot WiFi SSID** → the name your radio broadcasts. For most
     teams this is just the team number.
   * **Password** → leave blank if open network.
   * **Country** → `US` (or your country code).
5. **Hit save.** The device reboots and joins your team WiFi.

After ~30 seconds, the LED goes steady green. The device is at:

* **`10.TE.AM.11`** (FRC standard: e.g. team 1279 → `10.12.79.11`)
* **`acuity-NNNN.local`** (mDNS, also works)

## 4. Open the dashboard

From any laptop on the team WiFi, browse to:

```
http://10.TE.AM.11:8080/
```

You'll see the camera feed with AprilTag overlays. Click around — there
are panels for the camera, target lock, calibration, and a NetworkTables
topic browser.

## 5. Wire it into your robot code

Add the Acuity library to your robot project (one of three):

* **Java:** [WPILib vendordep](../libraries/java/README.md)
* **Python (robotpy):** [PyPI package](../libraries/python/README.md)
* **C++:** [WPILib vendordep](../libraries/cpp/README.md)

Minimum example (Java):

```java
private final AcuityVision vision = AcuityVision.getInstance();

@Override
public void robotPeriodic() {
  vision.getBestTag().ifPresent(tag -> {
    SmartDashboard.putNumber("tag/id",         tag.id);
    SmartDashboard.putNumber("tag/distance_m", tag.distanceMeters);
    SmartDashboard.putNumber("tag/yaw_deg",    tag.yawDeg);
  });
}
```

That's the full integration. The library handles NT4 connection,
deserialization, and staleness checking.

## 6. Reconfigure or recover

* **Switch WiFi networks.** Open the dashboard → Settings → "Forget
  network" → device reboots into AP mode for fresh setup.
* **Locked out / lost the IP.** Power-cycle the device. If it can't
  join the team WiFi (radio is off, password changed), it falls back
  into AP mode automatically.
* **Bricked SD.** Reflash with the recovery USB stick (or any laptop
  + the master image).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| AP not appearing | Pi didn't finish boot | Wait 60 s. Power-cycle if still nothing. |
| Captive portal doesn't open | OS suppressed it | Open `http://192.168.50.1/` manually. |
| Form saves but Pi never joins WiFi | SSID/password typo | Power-cycle → AP appears again → fix and re-save. |
| Dashboard loads but no camera | Ribbon cable loose | Open case, reseat the camera ribbon. |
| `10.TE.AM.11` unreachable | Not on team WiFi, or radio off | Confirm laptop is on the team SSID. |

If you're still stuck: open the [Manager app](../manager/README.md) on
your laptop — it has a one-click diagnostics bundle that captures logs
+ config and emails them in.
