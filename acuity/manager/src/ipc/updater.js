// Acuity Manager — auto-updater.
//
// Wraps electron-updater so the app can pull new releases from
// GitHub Releases (configured as the publish target in
// package.json's `build.publish`). We're shipping unsigned
// binaries on purpose, so we explicitly disable signature
// verification — Windows users will see SmartScreen warnings on
// first run + first install of each update; we accept that for now
// in exchange for not paying $200/yr for a code-signing cert.
//
// Flow from the renderer's perspective:
//   1. updater.check()           → starts a check
//   2. 'updater:status' events   → 'checking', 'available',
//                                  'not-available', 'progress',
//                                  'downloaded', 'error'
//   3. updater.installAndRestart() → applies the downloaded update
//
// We don't auto-download by default — the renderer prompts the user.
// On laptops at a competition this matters: a forced 80 MB download
// when the field is 200 ms RTT to the world is exactly what nobody
// wants.

const { autoUpdater } = require('electron-updater');
const { app, BrowserWindow } = require('electron');

let initialized = false;

function broadcast(channel, payload) {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send(channel, payload);
    }
  }
}

function init() {
  if (initialized) return;
  initialized = true;

  // Unsigned-on-purpose. electron-updater otherwise refuses to install
  // a Windows update that doesn't carry a signature matching the
  // currently-installed binary, which would break our entire
  // release pipeline.
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = false;
  // forceDevUpdateConfig lets us test the update path during dev
  // (electron-builder normally skips updates when running unpackaged).
  autoUpdater.forceDevUpdateConfig = process.env.ACUITY_DEV_UPDATE === '1';

  autoUpdater.on('checking-for-update', () => {
    broadcast('updater:status', { state: 'checking' });
  });
  autoUpdater.on('update-available', (info) => {
    broadcast('updater:status', {
      state: 'available',
      version: info.version,
      releaseNotes: typeof info.releaseNotes === 'string'
        ? info.releaseNotes : '',
      releaseDate: info.releaseDate,
    });
  });
  autoUpdater.on('update-not-available', (info) => {
    broadcast('updater:status', {
      state: 'not-available',
      version: info.version,
    });
  });
  autoUpdater.on('download-progress', (p) => {
    broadcast('updater:status', {
      state: 'progress',
      percent: p.percent,
      bytesPerSecond: p.bytesPerSecond,
      transferred: p.transferred,
      total: p.total,
    });
  });
  autoUpdater.on('update-downloaded', (info) => {
    broadcast('updater:status', {
      state: 'downloaded',
      version: info.version,
    });
  });
  autoUpdater.on('error', (err) => {
    broadcast('updater:status', {
      state: 'error',
      message: err && err.message ? err.message : String(err),
    });
  });
}

function register(ipcMain) {
  init();

  ipcMain.handle('updater:current-version', () => app.getVersion());

  ipcMain.handle('updater:check', async () => {
    try {
      const r = await autoUpdater.checkForUpdates();
      return { ok: true, info: r ? r.updateInfo : null };
    } catch (e) {
      return { ok: false, error: e && e.message ? e.message : String(e) };
    }
  });

  ipcMain.handle('updater:download', async () => {
    try {
      await autoUpdater.downloadUpdate();
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e && e.message ? e.message : String(e) };
    }
  });

  ipcMain.handle('updater:install', () => {
    // isSilent=false so the user sees the NSIS installer again
    // (good — confirms the new version visually).
    // isForceRunAfter=true so the new app launches automatically.
    setImmediate(() => autoUpdater.quitAndInstall(false, true));
    return { ok: true };
  });
}

module.exports = { register, init };
