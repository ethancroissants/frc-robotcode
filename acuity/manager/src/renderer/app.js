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
  logPane.hidden = false;
  logPane.textContent = '';
  await withBusy(e.currentTarget, () =>
    withGlobalLoading(() => window.acuity.ssh.runUpdate(target(selected)))
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
  await withBusy(e.currentTarget, () => window.acuity.ssh.reboot(target(selected)));
});
$('#dd-forget').addEventListener('click', async (e) => {
  if (!selected) return;
  if (!confirm(
    `Forget WiFi on ${selected.name}? It will reboot into the AP-mode setup wizard.`
  )) return;
  await withBusy(e.currentTarget, () => window.acuity.ssh.forgetWifi(target(selected)));
});
$('#dd-diagnose').addEventListener('click', async (e) => {
  if (!selected) return;
  logPane.hidden = false;
  logPane.textContent = '';
  await withBusy(e.currentTarget, () => window.acuity.ssh.diagnose(target(selected)));
});

function target(d) {
  return { host: d.ip, port: 22, user: 'acuity' };
}

// Stream ssh logs into both the device-detail log pane and the
// global Logs tab so the user can review history.
window.acuity.ssh.onLog((line) => {
  if (!logPane.hidden) logPane.textContent += line;
  globalLog.textContent += line;
  globalLog.scrollTop = globalLog.scrollHeight;
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
  const { Terminal }  = await import('@xterm/xterm');
  const { FitAddon }  = await import('@xterm/addon-fit');

  if (term) { term.dispose(); term = null; }
  term = new Terminal({
    fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    fontSize: 12,
    theme: { background: '#0e1014', foreground: '#e7e9ef' },
    convertEol: true,
  });
  const fit = new FitAddon();
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
    'wrote-vendordep':    'Vendordep installed.',
    'updated-pyproject':  'pyproject.toml updated.',
    'already-installed':  'Already installed — no changes needed.',
  }[action] || 'Library installed.';
  const followup = lang === 'python'
    ? 'Run <code>pip install -e .</code> in the project to pull the new dep.'
    : 'In VS Code: <strong>WPILib → Manage Vendor Libraries → Install new library (offline)</strong>.';
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

  // MJPEG stream — straight <img src> hookup.
  const base = `http://${d.ip}:${d.port || 8080}`;
  camImg.src = `${base}/stream.mjpg?cb=${Date.now()}`;
  camOpenDash.href = `${base}/`;
  camFrame.classList.add('connecting');
  camLoadingTxt.textContent = `Connecting to ${d.name}…`;
  camLinkPill.hidden = false; camLinkPill.textContent = 'connecting';
  camLinkPill.classList.remove('good', 'bad');
  camFpsPill.hidden  = true;

  // WebSocket for live detections.
  connectCamWs(d);
}

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
    if (camDevice && camDevice.host === d.host) {
      setTimeout(() => connectCamWs(d), camWsBackoff);
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

function renderCamOverlay(tags, bestId) {
  camOverlay.innerHTML = '';
  if (!tags) return;
  for (const t of tags) {
    if (!t.corners) continue;
    const isBest = bestId != null && t.id === bestId;
    const points = t.corners.map(([x, y]) => `${x},${y}`).join(' ');
    camOverlay.appendChild(camSvg('polygon', {
      points,
      class: 'tag-poly ' + (isBest ? 'best' : 'other'),
    }));
    const cx = t.corners.reduce((a, [x]) => a + x, 0) / 4;
    const cy = t.corners.reduce((a, [, y]) => a + y, 0) / 4;
    camOverlay.appendChild(camSvg('text', {
      x: cx, y: cy,
      'text-anchor': 'middle', 'dominant-baseline': 'middle',
      class: 'tag-label ' + (isBest ? 'best' : 'other'),
    }, String(t.id)));
  }
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
