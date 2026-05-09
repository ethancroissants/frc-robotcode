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
  const devices = Array.from(seen.values()).sort((a, b) =>
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
