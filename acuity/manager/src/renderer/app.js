// Acuity Manager — renderer.
//
// Pure UI state. All privileged ops (mDNS, ssh, pty) come through
// `window.acuity.*` from preload.js — we never touch Node here.

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

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

function renderGrid() {
  if (!devices.length) {
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
  $('#dd-name').textContent    = selected.name;
  $('#dd-ip').textContent      = selected.ip;
  $('#dd-version').textContent = selected.version || 'unknown';
  $('#dd-uptime').textContent  = '—';  // TODO: pull from /acuity/health/uptime_s
}

// Action button wiring. Each calls into preload, which dispatches IPC.
$('#dd-open-dashboard').addEventListener('click', () => {
  if (!selected) return;
  // Open in default browser; we could also embed a webview here.
  window.open(`http://${selected.ip}:${selected.port || 8080}/`, '_blank');
});
$('#dd-update').addEventListener('click', async () => {
  if (!selected) return;
  logPane.hidden = false;
  logPane.textContent = '';
  await window.acuity.ssh.runUpdate(target(selected));
});
$('#dd-terminal').addEventListener('click', () => {
  if (!selected) return;
  // Switch to terminal tab and open a session.
  $('.tab[data-tab="terminal"]').click();
  openTerminal(selected);
});
$('#dd-reboot').addEventListener('click', async () => {
  if (!selected) return;
  if (!confirm(`Reboot ${selected.name}?`)) return;
  await window.acuity.ssh.reboot(target(selected));
});
$('#dd-forget').addEventListener('click', async () => {
  if (!selected) return;
  if (!confirm(
    `Forget WiFi on ${selected.name}? It will reboot into the AP-mode setup wizard.`
  )) return;
  await window.acuity.ssh.forgetWifi(target(selected));
});
$('#dd-diagnose').addEventListener('click', async () => {
  if (!selected) return;
  logPane.hidden = false;
  logPane.textContent = '';
  await window.acuity.ssh.diagnose(target(selected));
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

// Discovery — start on load, listen for updates.
window.acuity.discovery.onUpdate(({ devices: list }) => {
  devices = list || [];
  if (selected && !devices.find((d) => d.host === selected.host)) {
    selected = null;
  }
  renderGrid();
  renderDetail();
});
window.acuity.discovery.start();
$('#rescan').addEventListener('click', async () => {
  await window.acuity.discovery.stop();
  await window.acuity.discovery.start();
});

// ============== Terminal ==============
//
// xterm.js + node-pty. We dynamically import xterm so the app still
// boots if xterm isn't installed yet during early development.
let term = null;
let termId = null;

async function openTerminal(device) {
  if (!device) return;
  const { Terminal }  = await import('xterm');
  const { FitAddon }  = await import('xterm-addon-fit');

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
  card.addEventListener('click', async () => {
    const lang = card.dataset.lang;
    await runLibraryInstaller(lang);
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
