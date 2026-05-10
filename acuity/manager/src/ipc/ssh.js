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
        // Wrap every remote command in `sudo -S` and feed it the SSH
        // password through stdin. Why: ssh2's exec channel has no
        // TTY, and any `sudo` call inside the script (the bridge
        // update is full of `sudo nmcli` / `sudo systemctl`) would
        // otherwise die with "a terminal is required to read the
        // password" the first time we hit a Pi whose SSH user
        // doesn't have full NOPASSWD configured. With -S, sudo reads
        // its first line of stdin as the password, then runs the
        // command — and once we're root, every nested `sudo` inside
        // the script is a no-op (root→root authenticates without a
        // prompt). The chicken-and-egg is real: a fresh Pi can't
        // run install.sh (which provisions acuity-root + NOPASSWD)
        // until we can already sudo. Feeding the password breaks it.
        //
        // -p '' suppresses sudo's prompt so it doesn't bleed into
        // streamed UI log output. -k forgets any cached creds so
        // the password we just sent is what gets used (otherwise a
        // long-lived sudo timestamp could mask wrong-password bugs).
        // base64-encode the inner script so we don't have to think
        // about nested-shell quoting; bash decodes + execs it.
        const encoded = Buffer.from(cmd, 'utf8').toString('base64');
        const wrapped =
          `sudo -k -S -p '' bash -c "$(echo ${encoded} | base64 -d)"`;

        conn.exec(wrapped, (err, stream) => {
          if (err) { reject(err); conn.end(); return; }

          // Feed sudo the password. -S reads up to one '\n' for
          // the password, then everything else on stdin is the
          // command's stdin (our scripts don't read it).
          if (target.password) {
            stream.write(target.password + '\n');
          } else {
            // No password set: send a blank line so sudo fails
            // immediately with "no password" rather than hanging.
            stream.write('\n');
          }

          stream.on('data',        (d) => onData(d.toString()));
          stream.stderr.on('data', (d) => onData(d.toString()));
          stream.on('close', (code) => {
            conn.end();
            resolve({ code });
          });
        });
      })
      .on('error', reject)
      // Some Pi OS sshd configs treat password auth as a
      // keyboard-interactive challenge instead of straight
      // PasswordAuth. Without `tryKeyboard: true` and a handler,
      // ssh2 hangs at the auth phase against those builds.
      .on('keyboard-interactive', (_n, _i, _l, _p, finish) => {
        finish([target.password || '']);
      })
      .connect({
        host: target.host,
        port: target.port || 22,
        username: target.user || 'acuity-root',
        password: target.password,
        tryKeyboard: true,
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
  // Use this only when the device already has internet (e.g. it's
  // on home WiFi). For deployed Pis sitting on a no-internet team
  // radio, use `ssh:run-update-bridged` below instead.
  //
  // We always reboot at the end — it's empirically more reliable
  // than trying to restart every changed service in place. Avahi
  // tends to get wedged after package upgrades, the dashboard
  // python process keeps the OLD bytecode in memory until restart,
  // and a reboot is the one operation that guarantees every part
  // of the upgraded firmware is actually loaded. Costs the user
  // ~30–60 s; the firmware-update modal in the renderer waits for
  // mDNS to re-announce.
  ipcMain.handle('ssh:run-update', async (event, target) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    const cmd = [
      `curl -fsSL ${INSTALL_URL} | sudo bash`,
      'echo "[update] install.sh finished — rebooting"',
      // `nohup … &` so the reboot kicks in even after this SSH
      // session dies. `sleep 2` gives the SSH channel time to flush
      // the "rebooting" line back to Manager before the link drops.
      'nohup sh -c "sleep 2 && sudo reboot" >/dev/null 2>&1 &',
    ].join(' && ');
    streamTo(window, `[update] running install.sh + reboot\n`);
    try {
      const { code } = await exec(target, cmd, (data) => streamTo(window, data));
      streamTo(window, `[update] exit code: ${code}\n`);
      return { ok: code === 0, code };
    } catch (e) {
      streamTo(window, `[update] error: ${e.message}\n`);
      return { ok: false, error: e.message };
    }
  });

  // Bridge-based update — for the common case where the device is
  // sitting on the team radio (no internet). We:
  //   1. Bring up wlan0 on a user-supplied internet WiFi via nmcli
  //      (temporary connection profile, deleted on EXIT — including
  //       on Ctrl-C / install.sh failure).
  //   2. Force wlan0's default route to win (route-metric 50 vs
  //      eth0's default 100), since the team ethernet has no
  //      internet and apt would otherwise pick that route.
  //   3. Sanity-check internet over wlan0 before running install.
  //   4. Sync the wall clock from an HTTPS Date header — apt's
  //      signature verifier rejects 'not yet live' signatures, and
  //      a Pi without an RTC battery often boots into the past.
  //   5. curl + sudo bash the install.sh from GitHub.
  //   6. Trap-EXIT cleanup tears the bridge down regardless of
  //      success or failure.
  // Returns when install.sh exits OR the SSH session dies (which
  // happens if install.sh restarts the dashboard service itself).
  ipcMain.handle('ssh:run-update-bridged', async (event, { target, ssid, psk }) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    if (!ssid) return { ok: false, error: 'WiFi SSID is required' };

    // shlex-quote-equivalent for bash. We control the surrounding
    // command, so single-quote-and-escape any embedded single quotes
    // is enough.
    const sq = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`;
    const ssidQ = sq(ssid);
    const pskQ  = sq(psk || '');
    const installUrl = INSTALL_URL;

    const script = [
      'set -e',
      // Trap cleanup tears the temp profile down on any exit path.
      'cleanup() {',
      '  echo "[bridge] tearing down temp WiFi"',
      '  sudo nmcli connection down acuity-temp-update >/dev/null 2>&1 || true',
      '  sudo nmcli connection delete acuity-temp-update >/dev/null 2>&1 || true',
      '}',
      'trap cleanup EXIT',
      'if ! command -v nmcli >/dev/null; then',
      '  echo "[bridge] nmcli missing — Pi OS Bookworm should ship it; aborting" >&2',
      '  exit 2',
      'fi',
      'if command -v rfkill >/dev/null; then sudo rfkill unblock wifi || true; fi',
      'sudo nmcli radio wifi on || true',
      'sleep 1',
      `sudo nmcli connection add type wifi con-name acuity-temp-update ` +
        `ifname wlan0 ssid ${ssidQ} >/dev/null`,
      ...(psk ? [
        `sudo nmcli connection modify acuity-temp-update ` +
          `wifi-sec.key-mgmt wpa-psk wifi-sec.psk ${pskQ}`,
      ] : []),
      'sudo nmcli connection modify acuity-temp-update ' +
        'connection.autoconnect no ' +
        'ipv4.route-metric 50 ipv6.route-metric 50',
      'echo "[bridge] connecting wlan0 to the temp WiFi…"',
      'sudo nmcli connection up acuity-temp-update',
      'sleep 5',
      'echo "[bridge] verifying internet over wlan0…"',
      'if ! curl -s --max-time 8 --interface wlan0 -o /dev/null ' +
        'http://archive.raspberrypi.com/debian/dists/trixie/InRelease; then',
      '  echo "[bridge] cannot reach the package mirror over wlan0." >&2',
      '  ip route >&2 || true',
      '  exit 3',
      'fi',
      // Sync clock from HTTPS Date header.
      'echo "[bridge] syncing system clock from HTTPS Date header…"',
      'http_date=$(curl -sI --max-time 8 --interface wlan0 ' +
        'https://archive.raspberrypi.com/ ' +
        '| awk -F\': \' \'tolower($1)=="date"{print $2}\' | tr -d \'\\r\')',
      'if [ -n "$http_date" ]; then',
      '  sudo date -u -s "$http_date" >/dev/null && echo "[bridge] clock set to $(date -u)"',
      'else',
      '  echo "[bridge] could not read Date header — continuing anyway" >&2',
      'fi',
      'echo "[update] running install.sh from GitHub…"',
      `curl -fsSL ${installUrl} | sudo bash`,
      'echo "[update] install.sh finished — rebooting in 2 s"',
      // Detach the reboot so we get out cleanly: trap EXIT can run
      // its `nmcli connection delete acuity-temp-update` first
      // (cosmetic — reboot would discard that anyway), the SSH
      // channel can flush the "rebooting" line back to Manager,
      // and THEN the kernel reboots. Without `nohup … &` the
      // reboot races the trap and the user occasionally sees a
      // half-printed line with no closing message.
      'nohup sh -c "sleep 2 && sudo reboot" >/dev/null 2>&1 &',
    ].join('\n');

    streamTo(window, '[bridge] starting bridged firmware update\n');
    try {
      const { code } = await exec(target, script, (data) => streamTo(window, data));
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
