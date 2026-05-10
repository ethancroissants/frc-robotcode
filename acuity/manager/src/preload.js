// Acuity Manager — preload.
//
// Bridges privileged Node APIs from the main process into the
// renderer via contextIsolation. The renderer never sees the raw
// `ipcRenderer` — it gets a typed `window.acuity` object with only
// the calls we explicitly allow.

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('acuity', {
  // mDNS discovery — emits { devices: [{name, ip, port, version}] }
  discovery: {
    start: () => ipcRenderer.invoke('discovery:start'),
    stop:  () => ipcRenderer.invoke('discovery:stop'),
    onUpdate: (cb) => ipcRenderer.on('discovery:update', (_e, data) => cb(data)),
  },

  // Remote actions over SSH (one-shots: update, reboot, diagnose).
  ssh: {
    connect:    (target) => ipcRenderer.invoke('ssh:connect', target),
    runUpdate:  (target) => ipcRenderer.invoke('ssh:run-update', target),
    runUpdateBridged: (target, ssid, psk) =>
      ipcRenderer.invoke('ssh:run-update-bridged', { target, ssid, psk }),
    reboot:     (target) => ipcRenderer.invoke('ssh:reboot', target),
    forgetWifi: (target) => ipcRenderer.invoke('ssh:forget-wifi', target),
    diagnose:   (target) => ipcRenderer.invoke('ssh:diagnose', target),
    onLog: (cb) => ipcRenderer.on('ssh:log', (_e, line) => cb(line)),
  },

  // Interactive terminal (xterm.js in renderer ↔ node-pty here).
  pty: {
    open:  (target) => ipcRenderer.invoke('pty:open', target),
    write: (id, data) => ipcRenderer.send('pty:write', { id, data }),
    resize: (id, cols, rows) => ipcRenderer.send('pty:resize', { id, cols, rows }),
    close: (id) => ipcRenderer.send('pty:close', { id }),
    onData: (cb) => ipcRenderer.on('pty:data', (_e, msg) => cb(msg)),
    onExit: (cb) => ipcRenderer.on('pty:exit', (_e, msg) => cb(msg)),
  },

  // Library installer — drops the Acuity vendordep / pyproject dep
  // into a robot project the user picks via a folder dialog.
  libraries: {
    pickAndDetect: () => ipcRenderer.invoke('libraries:pick-and-detect'),
    install: (dir, lang) => ipcRenderer.invoke('libraries:install', { dir, lang }),
    snippet: (lang) => ipcRenderer.invoke('libraries:snippet', { lang }),
    reveal: (path) => ipcRenderer.invoke('libraries:reveal', path),
  },

  // Auto-updater — pulls new releases from GitHub Releases.
  updater: {
    currentVersion: () => ipcRenderer.invoke('updater:current-version'),
    check:    () => ipcRenderer.invoke('updater:check'),
    download: () => ipcRenderer.invoke('updater:download'),
    install:  () => ipcRenderer.invoke('updater:install'),
    onStatus: (cb) => ipcRenderer.on('updater:status', (_e, msg) => cb(msg)),
  },
});
