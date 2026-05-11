// Acuity Manager — Electron main process.
//
// Owns the BrowserWindow, the mDNS discovery service, and the
// privileged Node-side handlers (ssh, pty, file-system writes for
// the library installer). The renderer talks to us via the
// contextBridge IPC channels declared in preload.js.

const { app, BrowserWindow, Menu, ipcMain, shell } = require('electron');
const path = require('path');

// Remove the default Electron application menu (File / Edit / View /
// Window / Help). We have our own top-bar tabs in the renderer for
// everything Manager actually does; the OS menu just adds visual
// clutter and exposes generic Electron actions (Reload, Toggle
// DevTools, Zoom, etc.) that a packaged-product user shouldn't see.
// Setting to null removes the bar entirely; we lose the default
// accelerators with it, which is fine — none of them are useful for
// this app, and Cmd/Ctrl+C, Cmd/Ctrl+V, Cmd/Ctrl+W etc. still work
// because Chromium provides them at the widget layer regardless of
// the application menu.
Menu.setApplicationMenu(null);

// Pin the Windows AppUserModelID before anything else runs.
//
// Windows groups taskbar entries — and looks up which icon to show —
// by AUMID, not by the .exe path. Electron does NOT derive this
// from package.json's `build.appId` at runtime; you have to call
// setAppUserModelId() yourself, and you have to do it before the
// first window opens or Windows caches the wrong identity.
//
// Symptom this fixes: title-bar icon updates fine via
// BrowserWindow({ icon }), but the taskbar entry keeps showing
// Electron's default icon even after uninstall + reinstall —
// because without an explicit AUMID, Windows can't tie the running
// window back to the NSIS-installed shortcut that has our icon
// embedded, so it falls through to the cached Electron default.
//
// The string MUST match `build.appId` in package.json. NSIS bakes
// the same AUMID into the shortcut at install time.
if (process.platform === 'win32') {
  app.setAppUserModelId('tech.acuity.manager');
}

let mainWindow = null;

// Title-bar / taskbar / dock icon. Two paths because the file lives in
// different places at dev time vs in a packaged build:
//   * Dev (`npm run dev`): __dirname is /…/acuity/manager/src, so we
//     reach the brand glyph at /…/acuity/img/AcuityAppIcon.ico with a
//     simple `..` walk.
//   * Packaged: __dirname is inside app.asar (no img/ next door). The
//     `nsis.extraResources` entry in package.json copies the .ico to
//     `<app>/resources/AcuityAppIcon.ico`, which Electron exposes as
//     `process.resourcesPath`. Without this branch the BrowserWindow
//     ends up showing Electron's default-shipped icon — the bug this
//     comment was added to fix.
const ICON_PATH = app.isPackaged
  ? path.join(process.resourcesPath, 'AcuityAppIcon.ico')
  : path.resolve(__dirname, '..', '..', 'img', 'AcuityAppIcon.ico');

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 740,
    minWidth: 900,
    minHeight: 600,
    title: 'Acuity Manager',
    backgroundColor: '#eef0f3',
    icon: ICON_PATH,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,  // node-pty needs unsandboxed renderer
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer/index.html'));

  // Let webviews / external links open in the OS browser, not a new
  // Electron window — keeps the manager from becoming a browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // DevTools keyboard shortcuts — F12 and Ctrl/Cmd+Shift+I.
  //
  // We strip the default Electron application menu (see
  // Menu.setApplicationMenu(null) up top) because users don't need
  // its boilerplate File/Edit/View entries, but the menu also carried
  // the default View → Toggle DevTools accelerator. Without it,
  // there's no way to open DevTools in a packaged build — which
  // matters when the renderer breaks silently (e.g. a missing IPC
  // handler) and we need to read its console to diagnose. Register
  // the accelerators directly on the window so they keep working.
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown') return;
    const isMac = process.platform === 'darwin';
    const ctrlOrCmd = isMac ? input.meta : input.control;
    const f12          = input.key === 'F12';
    const shiftCtrlI   = ctrlOrCmd && input.shift && input.key.toLowerCase() === 'i';
    if (f12 || shiftCtrlI) {
      mainWindow.webContents.toggleDevTools();
      event.preventDefault();
    }
  });
}

// IPC handlers. Each module returns { register(ipcMain) } so we wire
// them up here and they own their own channel namespace.
require('./ipc/discovery').register(ipcMain);
require('./ipc/ssh').register(ipcMain);
require('./ipc/pty').register(ipcMain);
require('./ipc/libraries').register(ipcMain);
require('./ipc/scripts-fs').register(ipcMain);
require('./ipc/updater').register(ipcMain);

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
