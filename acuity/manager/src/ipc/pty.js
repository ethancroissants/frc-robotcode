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

// Set the env var ACUITY_PTY_DEBUG=0 to silence the main-process
// terminal logs; on by default because every regression we've shipped
// in this code path was first noticed because someone was watching
// these lines scroll. Cheap (a handful of console.log per session +
// a max-80-char sample per data chunk).
const DEBUG = process.env.ACUITY_PTY_DEBUG !== '0';
function dlog(...a) { if (DEBUG) console.log('[pty]', ...a); }
function dwarn(...a) {              console.warn('[pty]', ...a); }

// Trim+escape a chunk for log lines so we can read what the remote
// is actually sending without a terminal full of ANSI cursor codes.
function sample(s, max = 80) {
  if (s == null) return '<null>';
  const str = Buffer.isBuffer(s) ? s.toString('utf8') : String(s);
  const esc = str
    .replace(/\x1b/g, '\\e')
    .replace(/\r/g, '\\r')
    .replace(/\n/g, '\\n')
    .replace(/\t/g, '\\t');
  return esc.length <= max ? esc : esc.slice(0, max) + `…(+${esc.length - max})`;
}

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

dlog('SSH_BIN resolved to', SSH_BIN);

function register(ipcMain) {
  ipcMain.handle('pty:open', (event, target) => {
    const id = String(nextId++);
    const window = BrowserWindow.fromWebContents(event.sender);
    const t0 = Date.now();

    dlog(`[#${id}] pty:open requested`, {
      host: target && target.host,
      port: (target && target.port) || 22,
      user: (target && target.user) || 'acuity-root',
      hasPassword: !!(target && target.password),
      sshBin: SSH_BIN,
    });

    // Refuse up front if we couldn't find ssh.exe on disk —
    // node-pty's own error includes no path on Windows, which makes
    // it impossible for the user to know what to install.
    if (SSH_BIN !== 'ssh' && !fs.existsSync(SSH_BIN)) {
      const msg = `ssh client not found at ${SSH_BIN}. ` +
        'Install OpenSSH from Settings → Apps → Optional Features.';
      dwarn(`[#${id}]`, msg);
      throw new Error(msg);
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
    dlog(`[#${id}] spawn argv =`, [SSH_BIN, ...args].join(' '));

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
      const msg = `Failed to start ssh PTY: ${e.message}. ssh path: ${SSH_BIN}. ` +
        'If this is a packaged build, node-pty may not be asar-unpacked.';
      dwarn(`[#${id}] pty.spawn threw:`, e.message);
      throw new Error(msg);
    }

    dlog(`[#${id}] pty.spawn ok, pid =`, term.pid);

    sessions.set(id, term);

    // Auto-inject the saved password if ssh asks for one.
    //
    // CRITICAL UX RULE: never buffer the terminal output. If we hold
    // bytes back waiting for a "password:" prompt that's never coming,
    // the user sees a blank cursor and the whole tab looks dead. We
    // forward every byte the moment it arrives; the auto-injector
    // only watches a small rolling tail of the stream for the prompt
    // pattern. Worst case if our regex misses, the prompt shows up
    // and the user types their password — same as plain ssh.
    //
    // The state machine has just two states now:
    //   "watching"  — auto-injector active. Forwards every byte;
    //                 keeps a 256-char rolling tail; if the tail ends
    //                 in /password:\s*$/i we write the password to
    //                 the pty and flip to "done". Auto-disarms after
    //                 4 s with no match (key-based auth path).
    //   "done"      — passthrough only, no matching.
    let authState = (target && target.password) ? 'watching' : 'done';
    let authTail  = '';
    const TAIL_CAP   = 256;
    const DEADLINE   = Date.now() + 4000;
    let dataChunks   = 0;
    let dataBytes    = 0;

    function send(data) {
      if (!window.isDestroyed()) {
        window.webContents.send('pty:data', { id, data });
      }
    }

    term.onData((data) => {
      dataChunks += 1;
      dataBytes  += data.length;
      // Sample the first ~5 chunks then sample every 50th to keep the
      // log from drowning during an `ls -laR /` style flood.
      if (dataChunks <= 5 || dataChunks % 50 === 0) {
        dlog(`[#${id}] onData #${dataChunks} (${data.length}B) state=${authState} sample="${sample(data)}"`);
      }

      // Always forward, immediately.
      send(data);

      // Watch for the password prompt if we still have a password to
      // inject. Concatenate into a rolling tail bounded by TAIL_CAP
      // so the regex stays cheap even on heavy output.
      if (authState !== 'watching') return;
      if (Date.now() > DEADLINE) {
        dlog(`[#${id}] auth watcher disarming on deadline (no password prompt seen in 4s)`);
        authState = 'done';
        authTail = '';
        return;
      }
      authTail = (authTail + data).slice(-TAIL_CAP);
      if (/password:\s*$/i.test(authTail)) {
        dlog(`[#${id}] saw password prompt, injecting saved password`);
        try {
          term.write(`${target.password}\r`);
        } catch (e) {
          dwarn(`[#${id}] password write failed:`, e.message);
        }
        authState = 'done';
        authTail  = '';
      }
    });

    term.onExit(({ exitCode, signal }) => {
      const elapsed = Date.now() - t0;
      dlog(`[#${id}] onExit exitCode=${exitCode} signal=${signal} ` +
           `after ${elapsed}ms · chunks=${dataChunks} bytes=${dataBytes}`);
      sessions.delete(id);
      if (!window.isDestroyed()) {
        window.webContents.send('pty:exit', { id, exitCode, signal });
      }
    });

    return { id };
  });

  ipcMain.on('pty:write', (_e, { id, data }) => {
    const term = sessions.get(id);
    if (!term) {
      dwarn(`[#${id}] pty:write to dead session (ignored), ${data && data.length}B`);
      return;
    }
    term.write(data);
  });
  ipcMain.on('pty:resize', (_e, { id, cols, rows }) => {
    const term = sessions.get(id);
    if (!term) {
      dwarn(`[#${id}] pty:resize to dead session (ignored)`);
      return;
    }
    dlog(`[#${id}] resize → ${cols}x${rows}`);
    term.resize(cols, rows);
  });
  ipcMain.on('pty:close', (_e, { id }) => {
    const term = sessions.get(id);
    if (term) {
      dlog(`[#${id}] pty:close (renderer asked us to kill)`);
      term.kill();
      sessions.delete(id);
    } else {
      dwarn(`[#${id}] pty:close to dead session (ignored)`);
    }
  });
}

module.exports = { register };
