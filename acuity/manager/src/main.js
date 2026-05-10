// Acuity Manager — Electron main process.
//
// Owns the BrowserWindow, the mDNS discovery service, and the
// privileged Node-side handlers (ssh, pty, file-system writes for
// the library installer). The renderer talks to us via the
// contextBridge IPC channels declared in preload.js.

const { app, BrowserWindow, ipcMain, shell } = require('electron');
const path = require('path');

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
}

// IPC handlers. Each module returns { register(ipcMain) } so we wire
// them up here and they own their own channel namespace.
require('./ipc/discovery').register(ipcMain);
require('./ipc/ssh').register(ipcMain);
require('./ipc/pty').register(ipcMain);
require('./ipc/libraries').register(ipcMain);
require('./ipc/updater').register(ipcMain);

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
