package tech.acuity;

/** CPU / temperature / uptime snapshot from the device. */
public final class DeviceHealth {
  public final double cpuPct;
  public final double tempC;
  public final long   uptimeSeconds;

  public DeviceHealth(double cpuPct, double tempC, long uptimeSeconds) {
    this.cpuPct = cpuPct;
    this.tempC  = tempC;
    this.uptimeSeconds = uptimeSeconds;
  }
}
