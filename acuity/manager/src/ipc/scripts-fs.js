// Acuity Manager — scripts-tab file helpers (main-process side).
//
// The Scripts tab deliberately does NOT have an in-app editor. Users
// pick a file on their laptop in their preferred editor, then upload
// it to the Acuity device. The device is the source of truth — scripts
// live in /var/lib/acuity/scripts/ on the device, and Manager talks to
// the device's HTTP API to enumerate / upload / delete them.
//
// These IPC handlers exist to let the renderer reach the local
// filesystem and the OS file dialogs / default-editor shell, which the
// renderer is sandboxed away from. Three operations:
//
//   scripts-fs:pick-new      → save dialog for a brand-new script.
//                              Writes a starter template at the chosen
//                              path if the file didn't exist, then
//                              opens it in the OS default editor.
//                              Returns { path, name, content } so the
//                              renderer can immediately PUT to the
//                              device.
//
//   scripts-fs:pick-existing → open dialog. Returns the file content
//                              + path so the renderer can upload.
//
//   scripts-fs:read          → re-read a previously-picked file
//                              (used by "Re-upload from disk").
//
//   scripts-fs:open          → open a local file in the OS default
//                              editor. Used by "Edit locally."
//
//   scripts-fs:save-as       → save dialog + write content to disk
//                              (used by "Download" so users can pull
//                              a script off the device and edit it).

const { dialog, ipcMain, shell, BrowserWindow } = require('electron');
const fs   = require('fs');
const path = require('path');

// Starter content for brand-new scripts. We pick the shebang from the
// filename extension so the device's script runner picks the right
// interpreter (Python by .py, exec'd directly for everything else).
function starterFor(filename) {
  const ext = path.extname(filename).toLowerCase();
  if (ext === '.py' || ext === '') {
    return [
      '#!/usr/bin/env python3',
      '"""Acuity coprocessor script.',
      '',
      'Runs on the Acuity device, not the robot. Outputs are visible',
      'in Manager → Scripts → Run output, and any prints go into the',
      'per-run buffer (capped at 256 KB).',
      '"""',
      '',
      'print("hello from acuity")',
      '',
    ].join('\n');
  }
  if (ext === '.sh' || ext === '.bash') {
    return '#!/usr/bin/env bash\nset -euo pipefail\n\necho "hello from acuity"\n';
  }
  if (ext === '.js' || ext === '.mjs') {
    return '#!/usr/bin/env node\nconsole.log("hello from acuity");\n';
  }
  // Unknown extension — leave it empty; user knows what they're doing.
  return '';
}

function register(ipcMain) {
  ipcMain.handle('scripts-fs:pick-new', async (event, { suggestedName }) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    const result = await dialog.showSaveDialog(win, {
      title: 'Choose where to keep the new script on your computer',
      defaultPath: suggestedName || 'acuity_script.py',
      // Filters are advisory — users can type any extension. We list
      // the common ones so the macOS / Windows save panel offers a
      // helpful default.
      filters: [
        { name: 'Python',      extensions: ['py'] },
        { name: 'Shell',       extensions: ['sh', 'bash'] },
        { name: 'JavaScript',  extensions: ['js', 'mjs'] },
        { name: 'All files',   extensions: ['*'] },
      ],
    });
    if (result.canceled || !result.filePath) {
      return { ok: false, reason: 'cancelled' };
    }
    const filePath = result.filePath;
    const name = path.basename(filePath);

    // Don't blow away an existing file the user pointed us at; reuse
    // its content instead. Only write the starter when the path is
    // brand-new — that way "New script…" against an existing local
    // file behaves like "Open it." too.
    let content;
    let createdStarter = false;
    if (fs.existsSync(filePath)) {
      content = fs.readFileSync(filePath, 'utf8');
    } else {
      content = starterFor(name);
      try {
        fs.writeFileSync(filePath, content, 'utf8');
        createdStarter = true;
      } catch (e) {
        return { ok: false, error: `could not write ${filePath}: ${e.message}` };
      }
    }
    // Pop the OS default editor so the user can start hacking. We
    // intentionally don't block on it; openPath returns the moment
    // the OS hands the file off, and the user comes back to Manager
    // to upload when they're done.
    shell.openPath(filePath).catch(() => { /* user can re-open manually */ });
    return { ok: true, path: filePath, name, content, createdStarter };
  });

  ipcMain.handle('scripts-fs:pick-existing', async (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    const result = await dialog.showOpenDialog(win, {
      title: 'Pick a script to upload to the Acuity device',
      properties: ['openFile'],
    });
    if (result.canceled || !result.filePaths.length) {
      return { ok: false, reason: 'cancelled' };
    }
    const filePath = result.filePaths[0];
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      return { ok: true, path: filePath, name: path.basename(filePath), content };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  });

  ipcMain.handle('scripts-fs:read', async (_e, filePath) => {
    if (!filePath || !fs.existsSync(filePath)) {
      return { ok: false, reason: 'missing' };
    }
    try {
      return { ok: true, path: filePath, content: fs.readFileSync(filePath, 'utf8') };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  });

  ipcMain.handle('scripts-fs:open', async (_e, filePath) => {
    if (!filePath || !fs.existsSync(filePath)) {
      return { ok: false, reason: 'missing' };
    }
    // shell.openPath resolves to '' on success, a non-empty error
    // string otherwise. Flip that to a typed shape for the renderer.
    const err = await shell.openPath(filePath);
    return err ? { ok: false, error: err } : { ok: true };
  });

  ipcMain.handle('scripts-fs:save-as', async (event, { suggestedName, content }) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    const result = await dialog.showSaveDialog(win, {
      title: 'Save script to your computer',
      defaultPath: suggestedName || 'acuity_script.py',
    });
    if (result.canceled || !result.filePath) {
      return { ok: false, reason: 'cancelled' };
    }
    try {
      fs.writeFileSync(result.filePath, content ?? '', 'utf8');
      return { ok: true, path: result.filePath };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  });
}

module.exports = { register };
