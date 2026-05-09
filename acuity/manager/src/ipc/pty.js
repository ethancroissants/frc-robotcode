// Acuity Manager — interactive SSH terminal.
//
// Pipes node-pty (a real PTY spawned in the main process) to xterm.js
// in the renderer. We use the system `ssh` client so the user gets the
// same key-handling, ProxyJump, agent-forwarding behavior they get
// from a normal terminal. node-pty just gives us a TTY for it to live
// in.

const pty = require('node-pty');
const { BrowserWindow } = require('electron');

const sessions = new Map();  // id → IPty
let nextId = 1;

function register(ipcMain) {
  ipcMain.handle('pty:open', (event, target) => {
    const id = String(nextId++);
    const window = BrowserWindow.fromWebContents(event.sender);

    // Launch ssh as a real PTY so the remote shell is fully
    // interactive (line editing, colors, ^C, etc.). We don't pass
    // `-t` here — node-pty already provides a TTY, so ssh detects it
    // and does the right thing.
    const args = [
      `${target.user || 'acuity'}@${target.host}`,
      '-p', String(target.port || 22),
      '-o', 'StrictHostKeyChecking=accept-new',
    ];

    const term = pty.spawn('ssh', args, {
      name: 'xterm-256color',
      cols: 100,
      rows: 30,
      env: process.env,
    });

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
