// Acuity Manager — mDNS discovery.
//
// Scans the LAN for `_acuity._tcp.local` services. Each Acuity device
// publishes one via avahi-daemon (configured by the firmware
// install.sh). We emit `discovery:update` events to the renderer with
// the latest list of seen devices.

const { Bonjour } = require('bonjour-service');

let bonjour = null;
let browser = null;
const seen = new Map();  // host -> { name, ip, port, version, lastSeen }

function emitUpdate(window) {
  // Dedupe by IP. mDNS happily lets a single host advertise under
  // multiple service names — and that does happen in practice:
  // hostname changes mid-boot leave a stale `acuity._acuity._tcp`
  // alongside the renamed `acuity-1279._acuity._tcp`, multi-interface
  // hosts announce once per iface, etc. Without this dedupe, Manager
  // shows the same device two or three times. Real fix is in
  // acuity-firstboot.sh (restart avahi after rename) — this is just
  // a defensive net so a single rogue announcement doesn't poison
  // the UI.
  //
  // Strategy: prefer the entry whose IP we've actually resolved.
  // Same-IP duplicates → keep the one whose hostname matches the
  // device's expected `acuity-NNNN` pattern (i.e. the one with the
  // dash + team number) over a generic `acuity` shadow.
  const byKey = new Map();
  for (const svc of seen.values()) {
    // Prefer dedup by resolved IPv4. Fall back to host so we still
    // show *something* during the brief window between announce
    // and address resolution.
    const key = svc.ip || svc.host || svc.name;
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, svc);
      continue;
    }
    // Tie-break: prefer entries with an IP, then prefer ones whose
    // name has a digit suffix (the team-numbered hostname).
    const incHasIp = !!svc.ip;
    const existHasIp = !!existing.ip;
    const incIsTeamNamed = /-\d+$/.test(svc.name);
    const existIsTeamNamed = /-\d+$/.test(existing.name);
    if ((incHasIp && !existHasIp) ||
        (incHasIp === existHasIp && incIsTeamNamed && !existIsTeamNamed)) {
      byKey.set(key, svc);
    }
  }
  const devices = Array.from(byKey.values()).sort((a, b) =>
    a.name.localeCompare(b.name)
  );
  window.webContents.send('discovery:update', { devices });
}

function register(ipcMain) {
  ipcMain.handle('discovery:start', (event) => {
    const window = require('electron').BrowserWindow.fromWebContents(
      event.sender
    );
    if (browser) return { ok: true, alreadyRunning: true };

    bonjour = new Bonjour();
    browser = bonjour.find({ type: 'acuity' });

    browser.on('up', (svc) => {
      seen.set(svc.fqdn, {
        name: svc.name,
        host: svc.host,
        ip: (svc.addresses || []).find((a) => a.includes('.')) || svc.host,
        port: svc.port,
        version: (svc.txt && svc.txt.version) || 'unknown',
        lastSeen: Date.now(),
      });
      emitUpdate(window);
    });
    browser.on('down', (svc) => {
      seen.delete(svc.fqdn);
      emitUpdate(window);
    });

    return { ok: true };
  });

  ipcMain.handle('discovery:stop', () => {
    if (browser) { browser.stop(); browser = null; }
    if (bonjour) { bonjour.destroy(); bonjour = null; }
    seen.clear();
    return { ok: true };
  });
}

module.exports = { register };
