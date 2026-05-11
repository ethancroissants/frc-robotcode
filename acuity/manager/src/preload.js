// Acuity Manager — preload.
//
// Bridges privileged Node APIs from the main process into the
// renderer via contextIsolation. The renderer never sees the raw
// `ipcRenderer` — it gets a typed `window.acuity` object with only
// the calls we explicitly allow.

const { contextBridge, ipcRenderer } = require('electron');

// Touch the xterm UMD packages here so electron-builder keeps them
// bundled. The renderer loads them via <script> tags pointing at
// `../../node_modules/@xterm/...`, but electron-builder's pruning
// step removes deps it can't trace through `require()` graphs — so
// without these requires the asar would ship without them and the
// terminal feature would silently break in packaged builds. The
// require calls are otherwise unused; they're a "keep this on disk"
// signal, not real imports.
try { require('@xterm/xterm');     } catch (e) { /* dev-only; ignore */ }
try { require('@xterm/addon-fit'); } catch (e) { /* dev-only; ignore */ }

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

  // Scripts-tab local-file helpers. The Scripts tab itself does
  // every device-side operation (list, upload, run, schedule)
  // straight over the device's HTTP API; these handlers only exist
  // to bridge the renderer to the OS file dialogs + default editor,
  // which the sandboxed renderer can't reach directly. Source of
  // truth for scripts themselves is /var/lib/acuity/scripts/ ON THE
  // DEVICE — never the laptop.
  scriptsFs: {
    pickNew:      (suggestedName) =>
      ipcRenderer.invoke('scripts-fs:pick-new', { suggestedName }),
    pickExisting: () =>
      ipcRenderer.invoke('scripts-fs:pick-existing'),
    read:         (path) => ipcRenderer.invoke('scripts-fs:read', path),
    open:         (path) => ipcRenderer.invoke('scripts-fs:open', path),
    saveAs:       (suggestedName, content) =>
      ipcRenderer.invoke('scripts-fs:save-as', { suggestedName, content }),
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
