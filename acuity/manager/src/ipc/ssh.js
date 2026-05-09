// Acuity Manager — SSH one-shots.
//
// Wraps the privileged actions (update firmware, reboot, forget WiFi,
// pull diagnostics bundle) behind a small set of IPC channels. Streams
// stdout/stderr back to the renderer as `ssh:log` events so the UI can
// show a live progress pane.

const { Client } = require('ssh2');
const { BrowserWindow } = require('electron');

// Path on the device where the latest install.sh lives. Set during
// firmware build — defaulting to the public raw URL until then.
const INSTALL_URL =
  'https://raw.githubusercontent.com/ethancroissants/frc-robotcode/master/acuity/firmware/install.sh';

function exec(target, cmd, onData) {
  return new Promise((resolve, reject) => {
    const conn = new Client();
    conn
      .on('ready', () => {
        conn.exec(cmd, (err, stream) => {
          if (err) { reject(err); conn.end(); return; }
          stream.on('data', (data) => onData(data.toString()));
          stream.stderr.on('data', (data) => onData(data.toString()));
          stream.on('close', (code) => {
            conn.end();
            resolve({ code });
          });
        });
      })
      .on('error', reject)
      .connect({
        host: target.host,
        port: target.port || 22,
        username: target.user || 'acuity',
        // Production: use installed key. Dev: fall back to password
        // if user typed one. Real Manager will prompt + remember.
        privateKey: target.privateKey,
        password: target.password,
        readyTimeout: 8000,
      });
  });
}

function streamTo(window, line) {
  if (window && !window.isDestroyed()) {
    window.webContents.send('ssh:log', line);
  }
}

function register(ipcMain) {
  // Pull latest install.sh and re-run it. Idempotent on the device.
  ipcMain.handle('ssh:run-update', async (event, target) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    const cmd = `curl -fsSL ${INSTALL_URL} | sudo bash`;
    streamTo(window, `[update] running: ${cmd}\n`);
    try {
      const { code } = await exec(target, cmd, (data) => streamTo(window, data));
      streamTo(window, `[update] exit code: ${code}\n`);
      return { ok: code === 0, code };
    } catch (e) {
      streamTo(window, `[update] error: ${e.message}\n`);
      return { ok: false, error: e.message };
    }
  });

  ipcMain.handle('ssh:reboot', async (event, target) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    streamTo(window, `[reboot] sudo reboot\n`);
    try {
      await exec(target, 'sudo reboot', (data) => streamTo(window, data));
      return { ok: true };
    } catch (e) {
      // ssh dies when the host reboots — that's fine, exec resolves
      // with a non-zero code or rejects. Treat as success.
      return { ok: true };
    }
  });

  // Removes /boot/firmware/acuity.conf and reboots so the device
  // re-enters AP-mode setup wizard.
  ipcMain.handle('ssh:forget-wifi', async (event, target) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    const cmd = 'sudo rm -f /boot/firmware/acuity.conf && sudo reboot';
    streamTo(window, `[forget-wifi] ${cmd}\n`);
    try {
      await exec(target, cmd, (data) => streamTo(window, data));
      return { ok: true };
    } catch (e) {
      return { ok: true };  // ssh death on reboot is expected
    }
  });

  // One-shot diagnostics dump. Captures the same things support
  // would ask for, tarballs them, streams the file back.
  ipcMain.handle('ssh:diagnose', async (event, target) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    const cmd =
      'sudo bash -c "' +
      'mkdir -p /tmp/acuity-diag && ' +
      'journalctl -b --no-pager > /tmp/acuity-diag/journal.log && ' +
      'cp /var/log/acuity-hostapd.log /tmp/acuity-diag/ 2>/dev/null; ' +
      'cp /boot/firmware/acuity.conf  /tmp/acuity-diag/ 2>/dev/null; ' +
      'tar czf /tmp/acuity-diag.tgz -C /tmp acuity-diag && ' +
      'echo /tmp/acuity-diag.tgz' +
      '"';
    streamTo(window, `[diagnose] collecting…\n`);
    try {
      await exec(target, cmd, (data) => streamTo(window, data));
      // TODO: scp the tarball back to a user-chosen save path.
      return { ok: true, remotePath: '/tmp/acuity-diag.tgz' };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  });

  // Connection test (used by the UI before showing per-device controls).
  ipcMain.handle('ssh:connect', async (event, target) => {
    try {
      await exec(target, 'echo ok', () => {});
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  });
}

module.exports = { register };
