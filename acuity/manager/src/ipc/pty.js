// Acuity Manager — interactive SSH terminal.
//
// Pipes node-pty (a real PTY spawned in the main process) to xterm.js
// in the renderer. We use the system `ssh` client so the user gets the
// same key-handling, ProxyJump, agent-forwarding behavior they get
// from a normal terminal. node-pty just gives us a TTY for it to live
// in.

const pty = require('node-pty');
const fs  = require('fs');
const { execSync } = require('child_process');
const { BrowserWindow } = require('electron');

const sessions = new Map();  // id → IPty
let nextId = 1;

// Resolve the absolute path to the system `ssh` binary.
//
// Why this isn't just "ssh": Electron on Windows doesn't reliably
// inherit the full user PATH (it gets the system PATH at process
// start, missing user-installed entries), so `pty.spawn('ssh', ...)`
// can fail with a cryptic "File not found:" even when `where ssh`
// works fine in the user's shell. We probe well-known install
// paths first, fall back to PATH-based resolution, and only as a
// last resort hand "ssh" to node-pty unmodified.
const SSH_BIN = (() => {
  if (process.platform !== 'win32') {
    return fs.existsSync('/usr/bin/ssh') ? '/usr/bin/ssh' : 'ssh';
  }
  const candidates = [
    'C:\\Windows\\System32\\OpenSSH\\ssh.exe',     // Win10 1809+, default
    'C:\\Windows\\Sysnative\\OpenSSH\\ssh.exe',    // 32-bit process on 64-bit Windows
    'C:\\Program Files\\Git\\usr\\bin\\ssh.exe',   // Git Bash
    'C:\\Program Files\\OpenSSH\\ssh.exe',         // standalone OpenSSH
    'C:\\Program Files (x86)\\OpenSSH\\ssh.exe',
  ];
  for (const c of candidates) {
    try { if (fs.existsSync(c)) return c; } catch (e) { /* keep going */ }
  }
  // Last-ditch: `where ssh` against PATH, take the first hit.
  try {
    const out = execSync('where ssh', { encoding: 'utf8' }).trim().split(/\r?\n/)[0];
    if (out && fs.existsSync(out)) return out;
  } catch (e) { /* not in PATH either */ }
  return 'ssh';
})();

function register(ipcMain) {
  ipcMain.handle('pty:open', (event, target) => {
    const id = String(nextId++);
    const window = BrowserWindow.fromWebContents(event.sender);

    // Refuse up front if we couldn't find ssh.exe on disk —
    // node-pty's own error includes no path on Windows, which makes
    // it impossible for the user to know what to install.
    if (SSH_BIN !== 'ssh' && !fs.existsSync(SSH_BIN)) {
      throw new Error(
        `ssh client not found at ${SSH_BIN}. ` +
        'Install OpenSSH from Settings → Apps → Optional Features.'
      );
    }

    // Launch ssh as a real PTY so the remote shell is fully
    // interactive (line editing, colors, ^C, etc.). We don't pass
    // `-t` here — node-pty already provides a TTY, so ssh detects it
    // and does the right thing. Disabling host-key checking +
    // pointing UserKnownHostsFile at /dev/null (NUL on Windows) is
    // OK here because the device sits on a closed FRC robot radio
    // and we'd otherwise spam the user with "host key changed" the
    // first time the firmware reflashes (every clone gets new keys).
    const args = [
      `${target.user || 'acuity-root'}@${target.host}`,
      '-p', String(target.port || 22),
      '-o', 'StrictHostKeyChecking=no',
      '-o', `UserKnownHostsFile=${process.platform === 'win32' ? 'NUL' : '/dev/null'}`,
      '-o', 'LogLevel=ERROR',
    ];

    let term;
    try {
      term = pty.spawn(SSH_BIN, args, {
        name: 'xterm-256color',
        cols: 100,
        rows: 30,
        cwd: process.platform === 'win32' ? 'C:\\' : (process.env.HOME || '/'),
        env: process.env,
      });
    } catch (e) {
      throw new Error(
        `Failed to start ssh PTY: ${e.message}. ssh path: ${SSH_BIN}. ` +
        'If this is a packaged build, node-pty may not be asar-unpacked.'
      );
    }

    sessions.set(id, term);

    term.onData((data) => {
      if (!window.isDestroyed()) {
        window.webContents.send('pty:data', { id, data });
      }
    });
    term.onExit(({ exitCode, signal }) => {
      sessions.delete(id);
      if (!window.isDestroyed()) {
        window.webContents.send('pty:exit', { id, exitCode, signal });
      }
    });

    return { id };
  });

  ipcMain.on('pty:write', (_e, { id, data }) => {
    const term = sessions.get(id);
    if (term) term.write(data);
  });
  ipcMain.on('pty:resize', (_e, { id, cols, rows }) => {
    const term = sessions.get(id);
    if (term) term.resize(cols, rows);
  });
  ipcMain.on('pty:close', (_e, { id }) => {
    const term = sessions.get(id);
    if (term) {
      term.kill();
      sessions.delete(id);
    }
  });
}

module.exports = { register };
