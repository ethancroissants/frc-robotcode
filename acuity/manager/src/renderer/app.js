// Acuity Manager — renderer.
//
// Pure UI state. All privileged ops (mDNS, ssh, pty) come through
// `window.acuity.*` from preload.js — we never touch Node here.

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// =========== UI feedback primitives ===========
//
// Three knobs the rest of the file uses for "this is happening" state:
//   * `withBusy(button, fn)` — disables the button + shows a spinner
//     while `fn` runs. Re-enables on resolve OR reject.
//   * `withGlobalLoading(fn)` — flips on the top-of-window loading
//     bar for the duration of `fn`. Use for long ops where the user
//     might think the app froze.
//   * `bumpValue(el, newText)` — sets text content + adds a brief
//     yellow flash via CSS animation. Used on telemetry updates so
//     changes are visible without staring at numbers.

let _globalLoadingDepth = 0;
function setGlobalLoading(on) {
  _globalLoadingDepth = Math.max(0, _globalLoadingDepth + (on ? 1 : -1));
  $('#global-loading').hidden = _globalLoadingDepth === 0;
}
async function withGlobalLoading(fn) {
  setGlobalLoading(true);
  try { return await fn(); } finally { setGlobalLoading(false); }
}

async function withBusy(button, fn) {
  if (!button) return fn();
  const original = button.innerHTML;
  button.classList.add('busy');
  button.disabled = true;
  // Drop a span so the spinner ends up on top via absolute positioning.
  const spin = document.createElement('span');
  spin.className = 'button-spinner';
  spin.innerHTML = '<span class="spinner small"></span>';
  button.appendChild(spin);
  try {
    return await fn();
  } finally {
    button.classList.remove('busy');
    button.disabled = false;
    button.innerHTML = original;
  }
}

function bumpValue(el, newText) {
  if (!el) return;
  if (el.textContent !== String(newText)) {
    el.textContent = newText;
    el.classList.remove('bump');
    // Force reflow so the next add reliably triggers the keyframe.
    void el.offsetWidth;
    el.classList.add('bump');
  }
}

// ============== Tab routing ==============

$$('.tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('.tab').forEach((t) => t.classList.toggle('active', t === btn));
    const target = btn.dataset.tab;
    $$('.page').forEach((p) =>
      p.classList.toggle('active', p.dataset.page === target)
    );
    if (target === 'camera') {
      // The Camera tab was `display: none` until just now, which means
      // every getBoundingClientRect inside it returned 0×0 and the SVG
      // overlay sized to nothing. Re-sync once the layout has actually
      // settled — without this, snapshots arriving while you were on
      // a different tab leave the overlay invisible the first time
      // you switch in.
      requestAnimationFrame(() =>
        typeof updateCamOverlaySize === 'function' && updateCamOverlaySize()
      );
      // Reconnect the stream now that the tab is visible. The dashboard
      // server enforces a single-viewer policy: this connection takes
      // over from any other client (web dashboard, second tab, etc.).
      if (typeof reconnectCamStream === 'function') reconnectCamStream();
    } else {
      // Leaving the Camera tab — stop the MJPEG so the slot is free for
      // the on-device dashboard or another viewer. Browsers normally
      // keep <img> connections alive until the tag is removed; clearing
      // src forces a TCP disconnect.
      if (typeof releaseCamStream === 'function') releaseCamStream();
    }
  });
});

// ============== Devices ==============

const grid     = $('#device-grid');
const detail   = $('#device-detail');
const logPane  = $('#dd-log');
const globalLog = $('#global-log');

let devices  = [];
let selected = null;

// Tracks whether discovery is actively scanning. We start "scanning"
// on launch and after a manual Rescan; flip off the first time a
// device announces (or after a 6 s grace period if nothing shows up).
let _scanningSince = Date.now();
let _scanGraceTimer = null;

function startScanning() {
  _scanningSince = Date.now();
  if (_scanGraceTimer) clearTimeout(_scanGraceTimer);
  _scanGraceTimer = setTimeout(() => {
    _scanningSince = 0;
    if (!devices.length) renderGrid();
  }, 6000);
  if (!devices.length) renderGrid();
}

function renderGrid() {
  if (!devices.length) {
    if (_scanningSince) {
      grid.innerHTML = `
        <div class="device-empty scanning">
          <span class="spinner large"></span>
          <h2>Scanning the network…</h2>
          <p>
            Looking for Acuity devices announcing themselves over
            mDNS. This usually takes only a few seconds.
          </p>
        </div>`;
    } else {
      grid.innerHTML = `
        <div class="device-empty">
          <h2>No devices found</h2>
          <p>
            Make sure your laptop is on the team WiFi. Acuity devices
            announce themselves via mDNS and should appear here within
            a few seconds.
          </p>
          <p class="hint">
            First-time setup? Connect your phone to the open
            <code>Acuity-Setup-XXXX</code> network the device
            broadcasts, then come back here.
          </p>
        </div>`;
    }
    detail.hidden = true;
    return;
  }
  grid.innerHTML = devices
    .map(
      (d) => `
      <div class="device-card${d.host === (selected && selected.host) ? ' selected' : ''}"
           data-host="${d.host}">
        <div class="name"><span class="status"></span>${d.name}</div>
        <div class="ip">${d.ip}:${d.port}</div>
      </div>`
    )
    .join('');
  $$('.device-card').forEach((el) => {
    el.addEventListener('click', () => {
      selected = devices.find((d) => d.host === el.dataset.host) || null;
      renderGrid();
      renderDetail();
    });
  });
}

function renderDetail() {
  if (!selected) { detail.hidden = true; return; }
  detail.hidden = false;
  bumpValue($('#dd-name'),    selected.name);
  bumpValue($('#dd-ip'),      selected.ip);
  bumpValue($('#dd-version'), selected.version || 'unknown');
  bumpValue($('#dd-uptime'),  '—');  // TODO: pull from /acuity/health/uptime_s
}

// Action button wiring. Each calls into preload, which dispatches IPC.
$('#dd-open-dashboard').addEventListener('click', () => {
  if (!selected) return;
  window.open(`http://${selected.ip}:${selected.port || 8080}/`, '_blank');
});
$('#dd-update').addEventListener('click', async (e) => {
  if (!selected) return;
  const wifi = await promptUpdateCredentials(selected);
  if (!wifi) return;
  logPane.hidden = false;
  logPane.textContent = '';
  await withBusy(e.currentTarget, () =>
    withGlobalLoading(() => withSshAuth((c) => {
      if (wifi.skipBridge) {
        return window.acuity.ssh.runUpdate(target(selected, c));
      }
      return window.acuity.ssh.runUpdateBridged(
        target(selected, c), wifi.ssid, wifi.psk
      );
    }))
  );
});
$('#dd-terminal').addEventListener('click', () => {
  if (!selected) return;
  $('.tab[data-tab="terminal"]').click();
  openTerminal(selected);
});
$('#dd-reboot').addEventListener('click', async (e) => {
  if (!selected) return;
  if (!confirm(`Reboot ${selected.name}?`)) return;
  await withBusy(e.currentTarget, () =>
    withSshAuth((c) => window.acuity.ssh.reboot(target(selected, c)))
  );
});
$('#dd-forget').addEventListener('click', async (e) => {
  if (!selected) return;
  if (!confirm(
    `Forget WiFi on ${selected.name}? It will reboot into the AP-mode setup wizard.`
  )) return;
  await withBusy(e.currentTarget, () =>
    withSshAuth((c) => window.acuity.ssh.forgetWifi(target(selected, c)))
  );
});
$('#dd-diagnose').addEventListener('click', async (e) => {
  if (!selected) return;
  logPane.hidden = false;
  logPane.textContent = '';
  await withBusy(e.currentTarget, () =>
    withSshAuth((c) => window.acuity.ssh.diagnose(target(selected, c)))
  );
});

// Topbar SSH-creds button — opens the credential editor any time.
$('#ssh-creds-btn').addEventListener('click', () => promptSshCreds({}));

// SSH credential storage. Single set of creds reused across every
// device — production cards are imaged identically so per-device
// creds would be wasted UI. Stored in localStorage rather than
// keychain because the user explicitly traded security for UX (the
// device sits on a closed FRC robot radio anyway).
//
// The default `acuity-root` / `acuity-root` is what install.sh
// provisions on every Acuity-imaged Pi:
//   * acuity-root user, member of `sudo`, full NOPASSWD sudoers
//   * password literally `acuity-root`
//   * sshd_config.d/ snippet allowing password auth
// → Manager's default works out of the box; users only need to
// touch the credentials button if they're SSHing into a non-Acuity
// account for debugging.
const SSH_USER_KEY = 'acuity.ssh.user';
const SSH_PASS_KEY = 'acuity.ssh.pass';
const SSH_DEFAULT_USER = 'acuity-root';
const SSH_DEFAULT_PASS = 'acuity-root';

function getSshCreds() {
  // Reads from localStorage if populated. Falls through to the
  // shipped defaults so a fresh Manager install just works against
  // a freshly-imaged Pi without prompting first.
  const u = localStorage.getItem(SSH_USER_KEY);
  const p = localStorage.getItem(SSH_PASS_KEY);
  return {
    user: (u != null && u !== '') ? u : SSH_DEFAULT_USER,
    pass: (p != null) ? p : SSH_DEFAULT_PASS,
  };
}
function setSshCreds(user, pass) {
  if (user) localStorage.setItem(SSH_USER_KEY, user);
  if (pass != null) localStorage.setItem(SSH_PASS_KEY, pass);
}

function target(d, credsOverride = null) {
  const c = credsOverride || getSshCreds();
  return {
    host: d.ip,
    port: 22,
    user: c.user,
    password: c.pass,
  };
}

function isAuthError(msg) {
  return /auth|permission denied|password/i.test(String(msg || ''));
}

// Wrap an SSH op so it transparently uses saved creds on the
// happy path and only prompts when the Pi actually rejects them.
// `invoke` takes a `creds` argument so we can re-run with override
// values without touching localStorage.
//
// Flow:
//   1. Run with saved creds. Almost always succeeds — no UI noise.
//   2. If we get a real auth error, show the prompt with TWO escape
//      hatches: "Save & retry" (overwrites saved, expected when the
//      saved password is wrong) and "Try once" (one-shot debug, e.g.
//      logging in as a different user without burning the default).
//   3. Retry with whatever the prompt returned. If it fails again
//      we surface the result; we don't loop endlessly.
async function withSshAuth(invoke) {
  let result = await invoke(getSshCreds());
  if (result && result.ok === false && isAuthError(result.error)) {
    const r = await promptSshCreds({ reason: 'auth-failed', err: result.error });
    if (r) {
      if (r.save) setSshCreds(r.user, r.pass);
      result = await invoke({ user: r.user, pass: r.pass });
    }
  }
  return result;
}

// Modal returns null on cancel, or { user, pass, save: bool }.
function promptSshCreds({ reason, err } = {}) {
  return new Promise((resolve) => {
    const cur = getSshCreds();
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const headline = reason === 'auth-failed'
      ? 'SSH login failed'
      : 'SSH credentials';
    const body = reason === 'auth-failed'
      ? "The Acuity device rejected the saved password. Try again with corrected credentials, or uncheck \"Save\" to log in as a different user just for this run."
      : 'Saved SSH credentials. Reused for every Acuity device.';
    overlay.innerHTML = `
      <div class="modal-card">
        <header><h2>${escapeHtml(headline)}</h2></header>
        <p>${escapeHtml(body)}</p>
        ${err ? `<p class="modal-path">${escapeHtml(err)}</p>` : ''}
        <div class="upd-form">
          <label>SSH username
            <input id="cred-user" type="text" autocomplete="off"
                   spellcheck="false" autocapitalize="off"
                   value="${escapeHtml(cur.user)}" />
          </label>
          <label>SSH password
            <input id="cred-pass" type="password" autocomplete="off"
                   value="${escapeHtml(cur.pass)}" />
          </label>
          <label class="upd-check">
            <input id="cred-save" type="checkbox" checked />
            <span>Save as default for every device</span>
          </label>
        </div>
        <div class="modal-actions">
          <button class="ghost"   data-act="cancel">Cancel</button>
          <button class="primary" data-act="ok">Retry</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const userIn = overlay.querySelector('#cred-user');
    const passIn = overlay.querySelector('#cred-pass');
    const saveBox = overlay.querySelector('#cred-save');

    const close = (val) => { overlay.remove(); resolve(val); };
    overlay.querySelector('[data-act="cancel"]').addEventListener('click', () => close(null));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(null); });

    const submit = () => {
      const user = userIn.value.trim();
      const pass = passIn.value;
      if (!user) { userIn.focus(); userIn.style.borderColor = 'var(--bad)'; return; }
      close({ user, pass, save: saveBox.checked });
    };
    overlay.querySelector('[data-act="ok"]').addEventListener('click', submit);
    [userIn, passIn].forEach((el) =>
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); })
    );
    setTimeout(() => (cur.pass ? passIn : userIn).focus(), 50);
  });
}

// Stream ssh logs into both the device-detail log pane and the
// global Logs tab so the user can review history. Also peek at the
// stream so we can pop the firmware-update modal the moment the
// bridge brings down the management connection (after which all
// future log lines come from the device's stdout buffer being
// drained, not from real progress).
window.acuity.ssh.onLog((line) => {
  if (!logPane.hidden) logPane.textContent += line;
  globalLog.textContent += line;
  globalLog.scrollTop = globalLog.scrollHeight;
  fwUpdateOnSshLog(line);
});

// Discovery — start on load, listen for updates. We track a
// "scanning" state so the empty grid shows a spinner instead of
// "no devices" until we've waited long enough that no devices
// is genuinely the answer.
window.acuity.discovery.onUpdate(({ devices: list }) => {
  devices = list || [];
  // First device announce → end the scanning state.
  if (devices.length && _scanningSince) {
    _scanningSince = 0;
    if (_scanGraceTimer) { clearTimeout(_scanGraceTimer); _scanGraceTimer = null; }
  }
  if (selected && !devices.find((d) => d.host === selected.host)) {
    selected = null;
  }
  renderGrid();
  renderDetail();
  fwUpdateOnDiscovery(devices);
});
startScanning();
window.acuity.discovery.start();

$('#rescan').addEventListener('click', async (e) => {
  await withBusy(e.currentTarget, async () => {
    await window.acuity.discovery.stop();
    devices = [];
    startScanning();          // shows the spinner immediately
    await window.acuity.discovery.start();
    // Hold the busy state for ~2s so the click feels acknowledged
    // even when there are no devices to find.
    await new Promise(r => setTimeout(r, 2000));
  });
});

// ============== Terminal ==============
//
// xterm.js + node-pty. We dynamically import xterm so the app still
// boots if xterm isn't installed yet during early development.
let term = null;
let termId = null;

async function openTerminal(device) {
  if (!device) return;
  // xterm + FitAddon are loaded as UMD globals via <script> tags in
  // index.html (we don't bundle modules). Both UMD wrappers can
  // expose either the class directly or wrap it in a namespace
  // object — handle both.
  const TermClass =
    typeof Terminal !== 'undefined' ? Terminal : window.Terminal;
  const FitClass =
    (window.FitAddon && window.FitAddon.FitAddon) ||
    (typeof FitAddon !== 'undefined' ? FitAddon : window.FitAddon);
  if (!TermClass || !FitClass) {
    alert(
      'xterm libraries didn\'t load. The terminal feature is broken on '
      + 'this build — please report it. ('
      + (TermClass ? '' : 'no Terminal ')
      + (FitClass  ? '' : 'no FitAddon')
      + ')'
    );
    return;
  }

  if (term) { term.dispose(); term = null; }
  term = new TermClass({
    fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    fontSize: 12,
    theme: { background: '#0e1014', foreground: '#e7e9ef' },
    convertEol: true,
  });
  const fit = new FitClass();
  term.loadAddon(fit);
  const host = $('#term-host');
  host.innerHTML = '';
  term.open(host);
  fit.fit();

  $('#term-title').textContent = `${device.name} — ${device.ip}`;

  const { id } = await window.acuity.pty.open(target(device));
  termId = id;

  term.onData((data)  => window.acuity.pty.write(id, data));
  term.onResize(({ cols, rows }) => window.acuity.pty.resize(id, cols, rows));

  window.acuity.pty.onData(({ id: msgId, data }) => {
    if (msgId === id) term.write(data);
  });
  window.acuity.pty.onExit(({ id: msgId }) => {
    if (msgId === id) {
      term.write('\r\n\x1b[33m[connection closed]\x1b[0m\r\n');
      termId = null;
    }
  });

  // Keep xterm sized to its host on window resize.
  new ResizeObserver(() => fit.fit()).observe(host);
}

// ============== Libraries ==============

$$('.lang-card').forEach((card) => {
  card.addEventListener('click', async (e) => {
    const lang = card.dataset.lang;
    await withBusy(e.currentTarget, () =>
      withGlobalLoading(() => runLibraryInstaller(lang))
    );
  });
});

async function runLibraryInstaller(requestedLang) {
  // Step 1: pick the robot project folder.
  const pick = await window.acuity.libraries.pickAndDetect();
  if (!pick.ok) return;

  const { dir, detected } = pick;
  let lang = requestedLang;

  // If the picked dir matches a different language than the card the
  // user clicked, prompt before doing anything destructive.
  if (detected && detected !== lang) {
    const ok = confirm(
      `That folder looks like a ${detected.toUpperCase()} project, ` +
      `but you picked the ${lang.toUpperCase()} installer.\n\n` +
      `Continue with ${lang.toUpperCase()} anyway?`
    );
    if (!ok) {
      lang = detected;
    }
  } else if (!detected) {
    const ok = confirm(
      "That folder doesn't look like a recognizable robot project " +
      "(no build.gradle, no pyproject.toml).\n\n" +
      `Install ${lang.toUpperCase()} library here anyway?`
    );
    if (!ok) return;
  }

  // Step 2: install.
  const result = await window.acuity.libraries.install(dir, lang);
  if (!result.ok) {
    alert(`Install failed: ${result.error || 'unknown error'}`);
    return;
  }

  // Step 3: show a success modal with a copy-pastable code snippet.
  const snip = await window.acuity.libraries.snippet(lang);
  showInstallSuccessModal({
    lang,
    action: result.action,
    destPath: result.destPath || result.tomlPath,
    snippet: snip.snippet,
  });
}

function showInstallSuccessModal({ lang, action, destPath, snippet }) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  const actionText = {
    'wrote-helper':       'Helper file added.',
    'already-installed':  'Already installed — no changes needed.',
  }[action] || 'Helper file added.';
  const followup = lang === 'python'
    ? 'Import it from <code>robot.py</code>: <code>from acuity_client import AcuityClient</code>. Re-deploy with <code>robotpy deploy</code>.'
    : 'Rebuild your robot project (<strong>WPILib → Build Robot Code</strong>) and the new class will be on the classpath.';
  overlay.innerHTML = `
    <div class="modal-card">
      <header>
        <span class="pill good">Done</span>
        <h2>${actionText}</h2>
      </header>
      <p class="modal-path">${destPath || ''}</p>
      <p>Next: ${followup}</p>
      <h3>Sample code</h3>
      <pre class="modal-snippet">${escapeHtml(snippet)}</pre>
      <div class="modal-actions">
        <button class="ghost" data-act="copy">Copy snippet</button>
        ${destPath
          ? '<button class="ghost" data-act="reveal">Show in folder</button>'
          : ''}
        <button class="primary" data-act="close">Done</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  overlay.querySelector('[data-act="close"]').addEventListener('click', () => overlay.remove());
  overlay.querySelector('[data-act="copy"]').addEventListener('click', async () => {
    await navigator.clipboard.writeText(snippet);
    overlay.querySelector('[data-act="copy"]').textContent = 'Copied';
  });
  const reveal = overlay.querySelector('[data-act="reveal"]');
  if (reveal) {
    reveal.addEventListener('click', () => window.acuity.libraries.reveal(destPath));
  }
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Modal that asks for the WiFi creds the Pi will briefly bridge
// through to fetch the new firmware. Resolves to an object on
// continue, or null if the user cancels.
//   { ssid: string, psk: string, skipBridge: boolean }
function promptUpdateCredentials(device) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal-card">
        <header>
          <h2>Update ${escapeHtml(device.name)}</h2>
        </header>
        <p>
          The device usually sits on the team radio with no internet,
          so we briefly bridge it onto a WiFi network of your choice
          to fetch the new firmware. Once the install finishes we
          drop the temp connection and the device returns to the team
          radio automatically.
        </p>

        <div class="upd-form">
          <label>WiFi SSID
            <input id="upd-ssid" type="text" autocomplete="off"
                   spellcheck="false" autocapitalize="off"
                   placeholder="e.g. MyHomeWiFi" />
          </label>
          <label>Password
            <input id="upd-psk" type="password" autocomplete="off"
                   placeholder="(leave blank for an open network)" />
          </label>
          <label class="upd-check">
            <input id="upd-skip" type="checkbox" />
            <span>This device already has internet — skip the bridge</span>
          </label>
        </div>

        <div class="modal-actions">
          <button class="ghost"   data-act="cancel">Cancel</button>
          <button class="primary" data-act="ok">Update firmware</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    const ssidInput = overlay.querySelector('#upd-ssid');
    const pskInput  = overlay.querySelector('#upd-psk');
    const skipBox   = overlay.querySelector('#upd-skip');
    const okBtn     = overlay.querySelector('[data-act="ok"]');

    const close = (val) => { overlay.remove(); resolve(val); };

    overlay.querySelector('[data-act="cancel"]').addEventListener('click', () => close(null));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(null); });
    overlay.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(null); });

    skipBox.addEventListener('change', () => {
      const sk = skipBox.checked;
      ssidInput.disabled = sk;
      pskInput .disabled = sk;
      ssidInput.required = !sk;
    });

    okBtn.addEventListener('click', () => {
      const skipBridge = skipBox.checked;
      const ssid = ssidInput.value.trim();
      const psk  = pskInput.value;   // don't strip — passwords can be space-padded
      if (!skipBridge && !ssid) {
        ssidInput.focus();
        ssidInput.style.borderColor = 'var(--bad)';
        return;
      }
      close({ ssid, psk, skipBridge });
    });

    setTimeout(() => ssidInput.focus(), 50);
  });
}

// ============== Auto-updater ==============
//
// On launch we ask main to check GitHub Releases. If there's a newer
// version we surface a banner; the user clicks Download to actually
// pull the bytes (we don't auto-download — see updater.js for the
// rationale). When the download finishes we offer Restart & Install.
//
// All errors are best-effort — Manager keeps working if the updater
// can't reach GitHub.

const updateBanner   = $('#update-banner');
const updatePill     = $('#update-pill');
const updateTitle    = $('#update-banner-title');
const updateDetail   = $('#update-banner-detail');
const updateDownload = $('#update-download');
const updateInstall  = $('#update-install');
const updateDismiss  = $('#update-dismiss');

function showUpdateBanner({ title, detail, mode }) {
  updateBanner.hidden = false;
  updateTitle.textContent  = title;
  updateDetail.textContent = detail || '';
  updateDownload.hidden = mode !== 'available';
  updateInstall.hidden  = mode !== 'downloaded';
  updatePill.hidden = false;
  updatePill.textContent = mode === 'downloaded' ? 'restart to update' : 'update';
  updatePill.classList.toggle('warn', mode === 'available');
  updatePill.classList.toggle('good', mode === 'downloaded');
}

function hideUpdateBanner() {
  updateBanner.hidden = true;
  updatePill.hidden = true;
}

window.acuity.updater.onStatus((s) => {
  if (s.state === 'available') {
    showUpdateBanner({
      title:  `Acuity Manager ${s.version} is available`,
      detail: s.releaseDate
        ? `Released ${new Date(s.releaseDate).toLocaleDateString()}`
        : '',
      mode: 'available',
    });
  } else if (s.state === 'progress') {
    showUpdateBanner({
      title:  'Downloading update…',
      detail: `${(s.percent || 0).toFixed(0)}% — ${(s.transferred / 1e6).toFixed(1)} / ${(s.total / 1e6).toFixed(1)} MB`,
      mode:   'progress',
    });
  } else if (s.state === 'downloaded') {
    showUpdateBanner({
      title:  `Update ${s.version} downloaded`,
      detail: 'Restart to install.',
      mode:   'downloaded',
    });
  } else if (s.state === 'error') {
    // Soft failure — don't bother the user. Logged for debugging.
    console.warn('[updater]', s.message);
  }
});

updateDownload.addEventListener('click', () => window.acuity.updater.download());
updateInstall .addEventListener('click', () => window.acuity.updater.install());
updateDismiss .addEventListener('click', hideUpdateBanner);
updatePill   .addEventListener('click', () => { updateBanner.hidden = !updateBanner.hidden; });

// Kick off a check ~3s after launch so the UI has time to settle.
setTimeout(() => window.acuity.updater.check().catch(() => {}), 3000);

// Show current version in the topbar version pill on hover for diagnostics.
window.acuity.updater.currentVersion().then((v) => {
  document.title = `Acuity Manager v${v}`;
}).catch(() => {});

// ============== Onboarding wizard ==============

const ONB_KEY = 'acuity.onboarding.complete.v1';
const onb        = $('#onboarding');
const onbDots    = $$('.onb-dot');
const helpBtn    = $('#help-btn');

function setOnbStep(idx, flow = null) {
  $$('.onb-step').forEach((el) => {
    const matchesIdx  = Number(el.dataset.step) === idx;
    const matchesFlow = !el.dataset.onbFlow || el.dataset.onbFlow === flow;
    el.classList.toggle('active', matchesIdx && matchesFlow);
  });
  onbDots.forEach((d, i) => d.classList.toggle('active', i <= idx));
  onb.dataset.flow = flow || '';
}

function openOnboarding() {
  onb.hidden = false;
  setOnbStep(0);
}
function finishOnboarding(action) {
  localStorage.setItem(ONB_KEY, '1');
  onb.hidden = true;
  if (action === 'rescan') {
    $('#rescan').click();
    $('.tab[data-tab="devices"]').click();
  }
}

// First-launch trigger.
if (!localStorage.getItem(ONB_KEY)) {
  // Defer slightly so the rest of the UI is laid out behind it.
  setTimeout(openOnboarding, 200);
}
helpBtn.addEventListener('click', openOnboarding);

// Step 0 → 1
$$('[data-onb-next]').forEach((b) => b.addEventListener('click', () => {
  setOnbStep(1);
}));

// Step 1 choice → 2 (with flow)
$$('[data-onb-choice]').forEach((b) => b.addEventListener('click', () => {
  const flow = b.dataset.onbChoice;
  setOnbStep(2, flow);
}));

// Step 2 → 1 (back)
$$('[data-onb-prev]').forEach((b) => b.addEventListener('click', () => {
  setOnbStep(1);
}));

// Step 2 → done (rescan or library trigger)
$$('[data-onb-finish]').forEach((b) => b.addEventListener('click', () => {
  const action = b.dataset.onbFinish || '';
  finishOnboarding(action);
}));

// Library language picker inside the wizard kicks the install flow.
$$('[data-onb-lang]').forEach((b) => b.addEventListener('click', async () => {
  const lang = b.dataset.onbLang;
  finishOnboarding();
  $('.tab[data-tab="libraries"]').click();
  await runLibraryInstaller(lang);
}));

// Skip button.
$('#onb-skip').addEventListener('click', () => finishOnboarding());

// ============== Camera tab ==============
//
// Embeds the device's MJPEG stream + AprilTag overlay right in
// Manager. Same visual language as the device dashboard's Live
// tab — tag boxes drawn as SVG, best-target panel + detection list
// off to the side. We drive the device picker from the discovered
// devices list so users don't have to type IPs.

const camDevicePick = $('#cam-device-pick');
const camFrame      = $('#cam-frame');
const camImg        = $('#cam-img');
const camOverlay    = $('#cam-overlay');
const camLoadingTxt = $('#cam-loading-text');
const camLinkPill   = $('#cam-link-pill');
const camFpsPill    = $('#cam-fps-pill');
const camMetaRes    = $('#cam-meta-res');
const camMetaTags   = $('#cam-meta-tags');
const camMetaFps    = $('#cam-meta-fps');
const camDetList    = $('#cam-det-list');
const camDetCount   = $('#cam-det-count');
const camOpenDash   = $('#cam-open-dashboard');

let camWs        = null;
let camWsBackoff = 250;
let camDevice    = null;
let camFrameSize = { w: 0, h: 0 };

function camOptionLabel(d) {
  return `${d.name}  —  ${d.ip}`;
}

function refreshCamDeviceList() {
  // Preserve the current selection if the device is still around.
  const prev = camDevicePick.value;
  camDevicePick.innerHTML = '<option value="">— select a device —</option>';
  for (const d of devices) {
    const opt = document.createElement('option');
    opt.value = d.host;
    opt.textContent = camOptionLabel(d);
    camDevicePick.appendChild(opt);
  }
  if (devices.find((d) => d.host === prev)) {
    camDevicePick.value = prev;
  } else if (devices.length === 1) {
    // Auto-pick when there's exactly one device — saves a click in
    // the common single-coprocessor case.
    camDevicePick.value = devices[0].host;
    onCamDeviceChange();
  }
}

function onCamDeviceChange() {
  const host = camDevicePick.value;
  const dev = devices.find((d) => d.host === host) || null;
  setCamDevice(dev);
}

function setCamDevice(d) {
  if (camWs) { try { camWs.close(); } catch (e) {} camWs = null; }
  camDevice = d;
  if (!d) {
    camImg.src = '';
    camFrame.classList.add('connecting');
    camLoadingTxt.textContent = 'Pick a device to start streaming';
    camLinkPill.hidden = true;
    camFpsPill.hidden  = true;
    camOpenDash.removeAttribute('href');
    setCamBest(null);
    setCamDetList([], null);
    return;
  }

  // Always remember the open-dashboard link so users on the Devices
  // tab can still click "Open dashboard" via the camera toolbar's
  // anchor — that doesn't actually start a stream.
  const base = `http://${d.ip}:${d.port || 8080}`;
  camOpenDash.href = `${base}/`;

  // Only open the MJPEG + WS while the Camera tab is actually
  // visible. mDNS auto-picks fire any time, and we don't want a
  // background stream burning the device's single-viewer slot when
  // the user isn't even looking.
  if (!_camStreamActive) return;

  camImg.src = `${base}/stream.mjpg?cb=${Date.now()}`;
  camFrame.classList.add('connecting');
  camLoadingTxt.textContent = `Connecting to ${d.name}…`;
  camLinkPill.hidden = false; camLinkPill.textContent = 'connecting';
  camLinkPill.classList.remove('good', 'bad');
  camFpsPill.hidden  = true;

  // WebSocket for live detections.
  connectCamWs(d);
}

// Tracks whether the Camera tab is the currently-active tab AND
// has a selected device. We only auto-reconnect the WS when both
// are true — without this, the renderer keeps spamming reconnect
// attempts after the user has navigated away from Camera, which
// generates noisy "WebSocket opening handshake timed out" errors
// in the console (and wastes a TCP slot the device's web UI might
// want).
let _camStreamActive = false;

function connectCamWs(d) {
  const url = `ws://${d.ip}:${d.port || 8080}/api/detections.ws`;
  try {
    camWs = new WebSocket(url);
  } catch (e) {
    camLinkPill.textContent = 'no link'; camLinkPill.classList.add('bad');
    return;
  }
  camWs.onopen = () => { camWsBackoff = 250; };
  camWs.onmessage = (ev) => {
    try { applyCamSnapshot(JSON.parse(ev.data)); } catch (e) {}
  };
  camWs.onclose = () => {
    camLinkPill.textContent = 'no link';
    camLinkPill.classList.remove('good'); camLinkPill.classList.add('bad');
    // Only reconnect if the user is still actively on the Camera
    // tab AND we haven't switched to a different device meanwhile.
    if (_camStreamActive && camDevice && camDevice.host === d.host) {
      setTimeout(() => {
        if (_camStreamActive) connectCamWs(d);
      }, camWsBackoff);
      camWsBackoff = Math.min(camWsBackoff * 2, 4000);
    }
  };
  camWs.onerror = () => { try { camWs.close(); } catch (e) {} };
}

function camSvg(tag, attrs = {}, text = null) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  if (text != null) el.textContent = text;
  return el;
}

function updateCamOverlaySize() {
  if (!camFrameSize.w || !camFrameSize.h) return;
  camOverlay.setAttribute('viewBox', `0 0 ${camFrameSize.w} ${camFrameSize.h}`);
  const imgRect = camImg.getBoundingClientRect();
  const fr = camFrame.getBoundingClientRect();
  camOverlay.style.width  = imgRect.width + 'px';
  camOverlay.style.height = imgRect.height + 'px';
  camOverlay.style.left   = (imgRect.left - fr.left) + 'px';
  camOverlay.style.top    = (imgRect.top  - fr.top)  + 'px';
}
new ResizeObserver(updateCamOverlaySize).observe(camFrame);
window.addEventListener('resize', updateCamOverlaySize);

// Most recent tags array, kept for the click hit-test. Holds the
// `corners` field even when the broadcast didn't (we use the WS
// `tags_full` payload).
let _camLastTags = [];
let _camSelectedId = -1;

function renderCamOverlay(tags, bestId) {
  camOverlay.innerHTML = '';
  if (!tags) return;
  _camLastTags = tags;
  for (const t of tags) {
    if (!t.corners) continue;
    const isBest = bestId != null && t.id === bestId;
    const isSelected = _camSelectedId === t.id;
    const cls = isSelected ? 'selected'
              : isBest     ? 'best'
              : 'other';
    const points = t.corners.map(([x, y]) => `${x},${y}`).join(' ');
    camOverlay.appendChild(camSvg('polygon', {
      points,
      class: 'tag-poly ' + cls,
    }));
    const cx = t.corners.reduce((a, [x]) => a + x, 0) / 4;
    const cy = t.corners.reduce((a, [, y]) => a + y, 0) / 4;
    camOverlay.appendChild(camSvg('text', {
      x: cx, y: cy,
      'text-anchor': 'middle', 'dominant-baseline': 'middle',
      class: 'tag-label ' + cls,
    }, String(t.id)));
  }
}

// Hit-test a click against the most-recent tags. Click coords come
// in viewport space; we translate into the camera image's native
// pixel space (the same space `corners` uses) so the test works at
// any window size.
function camClickToTagId(ev) {
  if (!camFrameSize.w || !camFrameSize.h || !_camLastTags.length) return null;
  const imgRect = camImg.getBoundingClientRect();
  if (imgRect.width <= 0 || imgRect.height <= 0) return null;
  const px = (ev.clientX - imgRect.left) * (camFrameSize.w / imgRect.width);
  const py = (ev.clientY - imgRect.top)  * (camFrameSize.h / imgRect.height);
  // Score by smallest tag whose bounding box contains the click —
  // smallest wins so overlapping tags resolve to the more specific.
  let best = null;
  let bestArea = Infinity;
  for (const t of _camLastTags) {
    if (!t.corners) continue;
    const xs = t.corners.map(([x]) => x);
    const ys = t.corners.map(([, y]) => y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    if (px < minX || px > maxX || py < minY || py > maxY) continue;
    const area = (maxX - minX) * (maxY - minY);
    if (area < bestArea) { bestArea = area; best = t; }
  }
  return best ? best.id : null;
}

async function camPostTarget(id) {
  if (!camDevice) return;
  const base = `http://${camDevice.ip}:${camDevice.port || 8080}`;
  try {
    const r = await fetch(`${base}/api/target`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    });
    if (r.ok) {
      const data = await r.json();
      _camSelectedId = data.selected_tag_id ?? -1;
      $('#cam-clear-target').hidden = _camSelectedId < 0;
    }
  } catch (e) { /* ignore — server will reflect state on next frame */ }
}

function fmtMetersUS(m) {
  // FRC drivers think in feet — show "1.42 m (4.66 ft)" for clarity.
  if (m == null) return '—';
  const ft = m * 3.28084;
  if (m < 1) return `${(m * 100).toFixed(1)} cm  (${ft.toFixed(2)} ft)`;
  return `${m.toFixed(2)} m  (${ft.toFixed(2)} ft)`;
}
function fmtDeg(d) { return d == null ? '—' : `${d.toFixed(1)}°`; }
function fmtPct(x) { return x == null ? '—' : `${(x * 100).toFixed(1)}%`; }

function setCamBest(best) {
  const fields = {
    'cam-best-id':   best ? `#${best.id}`         : '—',
    'cam-best-dist': best ? fmtMetersUS(best.distance_m) : '—',
    'cam-best-yaw':  best ? fmtDeg(best.yaw_deg)  : '—',
    'cam-best-pitch':best ? fmtDeg(best.pitch_deg): '—',
    'cam-best-area': best ? fmtPct(best.area)     : '—',
  };
  for (const [id, val] of Object.entries(fields)) {
    const el = document.getElementById(id);
    bumpValue(el, val);
    el.classList.toggle('v-stale', best == null);
  }
}

function setCamDetList(tags, bestId) {
  if (!tags || !tags.length) {
    camDetList.innerHTML = '<div class="det-empty">No tags in view.</div>';
    camDetCount.textContent = '0';
    bumpValue(camMetaTags, '0');
    return;
  }
  bumpValue(camMetaTags, String(tags.length));
  camDetCount.textContent = String(tags.length);
  camDetList.innerHTML = tags
    .slice()
    .sort((a, b) => b.area - a.area)
    .map((t) => {
      const isBest = t.id === bestId;
      return `
        <div class="det-row${isBest ? ' best' : ''}">
          <span class="id">#${t.id}</span>
          <span>${fmtMetersUS(t.distance_m).split('  ')[0]}</span>
          <span>${fmtDeg(t.yaw_deg)}</span>
          <span><span class="label">area</span> ${fmtPct(t.area)}</span>
        </div>`;
    })
    .join('');
}

function applyCamSnapshot(s) {
  if (s.width && s.height) {
    camFrameSize = { w: s.width, h: s.height };
    bumpValue(camMetaRes, `${s.width}×${s.height}`);
    updateCamOverlaySize();
  }
  if (s.fps != null) {
    bumpValue(camMetaFps, s.fps.toFixed(1));
    camFpsPill.hidden = false;
    camFpsPill.textContent = `${s.fps.toFixed(0)} fps`;
  }
  camLinkPill.hidden = false;
  if (s.connected) {
    camLinkPill.textContent = 'live';
    camLinkPill.classList.add('good'); camLinkPill.classList.remove('bad');
    camFrame.classList.remove('connecting');
  } else {
    camLinkPill.textContent = 'no camera';
    camLinkPill.classList.remove('good'); camLinkPill.classList.add('bad');
  }
  const bestId = s.best ? s.best.id : null;
  setCamBest(s.best);
  setCamDetList(s.tags_full || s.tags, bestId);
  renderCamOverlay(s.tags_full || s.tags, bestId);
}

camDevicePick.addEventListener('change', onCamDeviceChange);

// Stream lifecycle helpers used by the tab-switch handler so we
// only hold the device's single MJPEG slot while the Camera tab
// is actually visible. The server's single-viewer policy means
// even if we don't release, a new connection from the web
// dashboard will take over — this is just a courtesy that avoids
// thrashing the slot back and forth on every tab switch.
function releaseCamStream() {
  // Clearing src closes the underlying TCP connection (browsers
  // gc-finalize the request when the resource ref is dropped).
  // Flipping _camStreamActive false BEFORE closing the WS prevents
  // the onclose handler from scheduling a reconnect.
  _camStreamActive = false;
  if (camImg.src) camImg.src = '';
  if (camWs) {
    try { camWs.close(); } catch (e) {}
    camWs = null;
  }
  camFrame.classList.add('connecting');
}
function reconnectCamStream() {
  if (!camDevice) return;
  _camStreamActive = true;
  const base = `http://${camDevice.ip}:${camDevice.port || 8080}`;
  camImg.src = `${base}/stream.mjpg?cb=${Date.now()}`;
  camFrame.classList.add('connecting');
  if (!camWs) connectCamWs(camDevice);
}

// Click-to-lock: clicking on a tag tells the device "lock onto
// this id." Clicking on empty space clears the lock. Same UX as
// the legacy team dashboard.
camFrame.addEventListener('click', (ev) => {
  if (!camDevice) return;
  // Don't intercept clicks on toolbar children.
  if (ev.target.closest('.cam-toolbar')) return;
  const id = camClickToTagId(ev);
  if (id == null) {
    // Clicked outside any tag → clear.
    if (_camSelectedId >= 0) camPostTarget(null);
    return;
  }
  // Toggle: click the same tag again to clear.
  camPostTarget(id === _camSelectedId ? null : id);
});

$('#cam-clear-target').addEventListener('click', () => camPostTarget(null));

// Quality presets. Three knobs in one — capture stays at full res
// for AprilTag detection range; we tune what the BROWSER receives.
const CAM_QUALITY_PRESETS = {
  low:  { stream_resolution: [480, 270], stream_quality: 50, stream_max_fps: 20 },
  med:  { stream_resolution: [640, 360], stream_quality: 60, stream_max_fps: 30 },
  high: { stream_resolution: [960, 540], stream_quality: 75, stream_max_fps: 30 },
};
$('#cam-quality').addEventListener('change', async (ev) => {
  if (!camDevice) return;
  const preset = CAM_QUALITY_PRESETS[ev.target.value];
  if (!preset) return;
  const base = `http://${camDevice.ip}:${camDevice.port || 8080}`;
  try {
    await fetch(`${base}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(preset),
    });
    // Force the <img> to reconnect so the new resolution takes
    // effect (browsers stick to whatever resolution they got on
    // the initial multipart-MJPEG content-type sniff).
    camImg.src = `${base}/stream.mjpg?cb=${Date.now()}`;
  } catch (e) { /* user can retry */ }
});

// Hook into the discovery update we already process for the
// Devices tab. preload registers each `onUpdate(cb)` call as an
// independent listener via `ipcRenderer.on`, so this *adds* a
// handler — the Devices grid renderer above keeps working
// untouched. This second handler keeps the camera-tab picker in
// sync as devices come and go.
window.acuity.discovery.onUpdate(() => {
  refreshCamDeviceList();
});

// ============== Docs tab ==============
//
// Sidebar nav scroll-spies the content; clicking a link smooth-
// scrolls the section into view. Code-block copy buttons copy the
// adjacent <pre> text to the clipboard.

const docsContent = $('#docs-content');

$$('.docs-link').forEach((link) => {
  link.addEventListener('click', (ev) => {
    ev.preventDefault();
    const id = link.getAttribute('href').slice(1);
    const target = document.getElementById(id);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    // Active state flips immediately on click; scroll-spy updates
    // the rest as the user scrolls.
    $$('.docs-link').forEach((l) => l.classList.toggle('active', l === link));
  });
});

// Scroll-spy: highlight the nav link for whichever section is
// closest to the top of the content viewport.
docsContent.addEventListener('scroll', () => {
  const scrollTop = docsContent.scrollTop;
  let bestSection = null;
  let bestDelta = Infinity;
  for (const sec of $$('.docs-section')) {
    const delta = sec.offsetTop - scrollTop - 8;
    if (delta <= 0 && Math.abs(delta) < bestDelta) {
      bestDelta = Math.abs(delta);
      bestSection = sec;
    }
  }
  if (bestSection) {
    const id = bestSection.id;
    $$('.docs-link').forEach((l) =>
      l.classList.toggle('active', l.getAttribute('href') === `#${id}`)
    );
  }
});

// Copy buttons on every code block.
$$('.copy-btn').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const block = btn.closest('.code-block');
    const code = block?.querySelector('code')?.textContent || '';
    try {
      await navigator.clipboard.writeText(code);
      const orig = btn.textContent;
      btn.textContent = 'Copied';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = orig;
        btn.classList.remove('copied');
      }, 1400);
    } catch (e) {
      btn.textContent = 'Copy failed';
    }
  });
});

// ============== Firmware-update modal ==============
//
// The bridge flow takes the device offline mid-update (the moment
// `nmcli connection up acuity-temp-update` runs, the team-WiFi IP
// goes away → our SSH session dies). From the user's perspective
// it looks like the update silently froze. This modal handles that
// gap: pops the moment we see the bridge log line, stays up while
// the device is missing from mDNS, flips to a "Firmware updated!"
// success state when the device reappears, and auto-dismisses.
//
// The modal is intentionally NOT user-dismissible during the
// updating state — closing it would leave the device hung in an
// unknown state and the user wouldn't know whether to power-cycle.
// A 7-minute safety timeout adds a "Dismiss" escape hatch in case
// the device doesn't come back at all.

// Module-private state. Null when no update is in progress.
let _fwUpdate = null;

const FW_BRIDGE_LOG_TRIGGERS = [
  'connecting wlan0 to the temp WiFi',
  '[bridge] connecting wlan0',
];

function fwUpdateOnSshLog(line) {
  if (_fwUpdate) return;  // already showing
  if (!selected) return;
  if (FW_BRIDGE_LOG_TRIGGERS.some((t) => line.includes(t))) {
    showFirmwareUpdateModal(selected);
  }
}

function fwUpdateOnDiscovery(deviceList) {
  if (!_fwUpdate) return;
  const present = deviceList.some((d) => d.host === _fwUpdate.host);
  if (!present) {
    _fwUpdate.sawMissing = true;
    return;
  }
  // We need to see the device DROP first — otherwise a discovery
  // tick that fires between "modal opens" and "Pi actually
  // disconnects" would immediately false-positive into success.
  if (_fwUpdate.sawMissing) fwUpdateMarkSuccess();
}

function showFirmwareUpdateModal(device) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay fw-update-overlay';
  overlay.innerHTML = `
    <div class="modal-card fw-update-card">
      <div class="fw-update-icon" id="fw-update-icon">
        <span class="spinner large"></span>
      </div>
      <h2 id="fw-update-title">Firmware is updating</h2>
      <p id="fw-update-body">
        Please <strong>do not turn off the Acuity device</strong>,
        <strong>don't close this app</strong>, and
        <strong>don't put this computer to sleep</strong>.
      </p>
      <p class="muted" id="fw-update-detail">
        The device downloads the new firmware over a temporary WiFi
        bridge, then reboots itself to load the new code. Total
        time is usually 3–6 minutes. We'll let you know the moment
        it comes back online.
      </p>
      <p class="muted" id="fw-update-elapsed">elapsed: 0:00</p>
      <div class="modal-actions" id="fw-update-actions" hidden>
        <button class="primary" data-act="dismiss">Dismiss</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  _fwUpdate = {
    host: device.host,
    name: device.name,
    overlay,
    sawMissing: false,
    startedAt: Date.now(),
    elapsedTimer: null,
    safetyTimer: null,
  };

  // Tick the elapsed counter once a second so the user can see
  // progress is being made even when nothing else updates.
  _fwUpdate.elapsedTimer = setInterval(() => {
    if (!_fwUpdate) return;
    const s = Math.round((Date.now() - _fwUpdate.startedAt) / 1000);
    const mm = Math.floor(s / 60);
    const ss = String(s % 60).padStart(2, '0');
    const el = document.getElementById('fw-update-elapsed');
    if (el) el.textContent = `elapsed: ${mm}:${ss}`;
  }, 1000);

  // Safety: if the device doesn't come back after 7 minutes, give
  // the user a way out. Most updates land in 2–4 min so 7 is the
  // "something has gone wrong" threshold.
  _fwUpdate.safetyTimer = setTimeout(fwUpdateMarkStuck, 7 * 60 * 1000);
}

function fwUpdateMarkSuccess() {
  if (!_fwUpdate) return;
  const { overlay, elapsedTimer, safetyTimer, name } = _fwUpdate;
  if (elapsedTimer) clearInterval(elapsedTimer);
  if (safetyTimer)  clearTimeout(safetyTimer);
  overlay.classList.add('fw-update-success');
  $('#fw-update-icon').innerHTML = `
    <svg viewBox="0 0 52 52" class="fw-update-check" aria-hidden="true">
      <circle class="fw-update-check-bg" cx="26" cy="26" r="24" fill="none"/>
      <path  class="fw-update-check-mk" fill="none"
             d="M14 27 l8 8 l16 -18"/>
    </svg>`;
  $('#fw-update-title').textContent = 'Firmware updated!';
  $('#fw-update-body').innerHTML =
    `<strong>${escapeHtml(name)}</strong> is back online and ready to use.`;
  $('#fw-update-detail').textContent = '';
  $('#fw-update-elapsed').textContent = '';
  // Auto-close after a beat so the user gets the "ta-da" moment but
  // isn't blocked from continuing to work.
  setTimeout(() => fwUpdateClose(), 3500);
}

function fwUpdateMarkStuck() {
  if (!_fwUpdate) return;
  const { overlay, elapsedTimer } = _fwUpdate;
  if (elapsedTimer) clearInterval(elapsedTimer);
  overlay.classList.add('fw-update-stuck');
  $('#fw-update-title').textContent = "Couldn't verify the update";
  $('#fw-update-body').innerHTML =
    "The device hasn't reappeared on the network after 7 minutes. " +
    "It might still be working through a slow install, or it might " +
    "have hit an error. Power-cycle the device if it stays unreachable; " +
    "the new firmware probably did install but couldn't auto-rejoin " +
    "the team WiFi.";
  $('#fw-update-detail').textContent = '';
  $('#fw-update-actions').hidden = false;
  $('#fw-update-actions').querySelector('[data-act="dismiss"]')
    .addEventListener('click', () => fwUpdateClose());
}

function fwUpdateClose() {
  if (!_fwUpdate) return;
  const { overlay, elapsedTimer, safetyTimer } = _fwUpdate;
  if (elapsedTimer) clearInterval(elapsedTimer);
  if (safetyTimer)  clearTimeout(safetyTimer);
  overlay.remove();
  _fwUpdate = null;
}
