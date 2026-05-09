// Acuity dashboard — renderer.
//
// Live tab pulls a WebSocket of detections and draws SVG overlays
// in sync with the MJPEG <img>. We never re-encode JPEG client-side
// for the overlay — SVG is layered on top, scaling with the image.

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// --------------------------- tab routing ---------------------------

$$('.tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('.tab').forEach((t) => t.classList.toggle('active', t === btn));
    const target = btn.dataset.tab;
    $$('.page').forEach((p) =>
      p.classList.toggle('active', p.dataset.page === target)
    );
    if (target === 'logs')    refreshLogs();
    if (target === 'network') refreshHealth();
  });
});

// --------------------------- live tab ---------------------------

const overlay     = $('#overlay');
const cameraImg   = $('#camera-img');
const cameraFrame = $('#camera-frame');
const detList     = $('#det-list');
const detCount    = $('#det-count');
const linkPill    = $('#link-pill');
const fpsPill     = $('#fps-pill');
const metaRes     = $('#meta-res');
const metaFps     = $('#meta-fps');
const metaTags    = $('#meta-tags');

let frameSize = { w: 0, h: 0 };

// Resize the SVG viewBox so polygon coords (which come in pixel space
// from the server) line up with the rendered image, even when the
// image is letterboxed inside its flex container.
function updateOverlaySize() {
  if (!frameSize.w || !frameSize.h) return;
  overlay.setAttribute('viewBox', `0 0 ${frameSize.w} ${frameSize.h}`);
  // Match aspect-ratio of the image element by sizing the overlay to
  // the rendered <img>'s bounding box rather than its parent.
  const imgRect = cameraImg.getBoundingClientRect();
  const frameRect = cameraFrame.getBoundingClientRect();
  overlay.style.width  = imgRect.width  + 'px';
  overlay.style.height = imgRect.height + 'px';
  overlay.style.left   = (imgRect.left - frameRect.left) + 'px';
  overlay.style.top    = (imgRect.top  - frameRect.top)  + 'px';
}
window.addEventListener('resize', updateOverlaySize);
new ResizeObserver(updateOverlaySize).observe(cameraFrame);

function svgEl(tag, attrs = {}, text = null) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  if (text != null) el.textContent = text;
  return el;
}

function renderOverlay(tags, bestId) {
  overlay.innerHTML = '';
  if (!tags || !tags.length) return;
  for (const t of tags) {
    if (!t.corners) continue;
    const isBest = bestId != null && t.id === bestId;
    const points = t.corners.map(([x, y]) => `${x},${y}`).join(' ');
    overlay.appendChild(svgEl('polygon', {
      points,
      class: 'tag-poly ' + (isBest ? 'best' : 'other'),
    }));
    const cx = t.corners.reduce((a, [x]) => a + x, 0) / 4;
    const cy = t.corners.reduce((a, [, y]) => a + y, 0) / 4;
    overlay.appendChild(svgEl('text', {
      x: cx, y: cy,
      'text-anchor': 'middle', 'dominant-baseline': 'middle',
      class: 'tag-label ' + (isBest ? 'best' : 'other'),
    }, String(t.id)));
  }
}

function fmtMeters(m) {
  if (m == null) return '—';
  if (m < 1)  return `${(m * 100).toFixed(1)} cm`;
  return `${m.toFixed(2)} m`;
}
function fmtDeg(d) { return d == null ? '—' : `${d.toFixed(1)}°`; }
function fmtPct(x) { return x == null ? '—' : `${(x * 100).toFixed(1)}%`; }

function setBest(best) {
  const fields = {
    'best-id':   best ? String(best.id) : '—',
    'best-dist': best ? fmtMeters(best.distance_m) : '—',
    'best-yaw':  best ? fmtDeg(best.yaw_deg)  : '—',
    'best-pitch':best ? fmtDeg(best.pitch_deg): '—',
    'best-area': best ? fmtPct(best.area)     : '—',
  };
  for (const [id, val] of Object.entries(fields)) {
    const el = document.getElementById(id);
    el.textContent = val;
    el.classList.toggle('v-stale', best == null);
  }
}

function setDetList(tags, bestId) {
  if (!tags || !tags.length) {
    detList.innerHTML = '<div class="det-empty">No tags in view.</div>';
    detCount.textContent = '0';
    metaTags.textContent = '0';
    return;
  }
  detCount.textContent = tags.length;
  metaTags.textContent = tags.length;
  detList.innerHTML = tags
    .slice()
    .sort((a, b) => b.area - a.area)
    .map((t) => {
      const isBest = t.id === bestId;
      return `
        <div class="det-row${isBest ? ' best' : ''}">
          <span class="id">#${t.id}</span>
          <span>${fmtMeters(t.distance_m)}</span>
          <span>${fmtDeg(t.yaw_deg)}</span>
          <span><span class="label">area</span> ${fmtPct(t.area)}</span>
        </div>`;
    })
    .join('');
}

function setLinkPill(connected) {
  linkPill.textContent = connected ? 'live' : 'no link';
  linkPill.classList.toggle('good', !!connected);
  linkPill.classList.toggle('bad',  !connected);
}

function applySnapshot(s) {
  if (s.width && s.height) {
    frameSize = { w: s.width, h: s.height };
    metaRes.textContent = `${s.width}×${s.height}`;
    updateOverlaySize();
  }
  if (s.fps != null) {
    metaFps.textContent  = s.fps.toFixed(1);
    fpsPill.textContent  = `${s.fps.toFixed(0)} fps`;
  }
  setLinkPill(s.connected);
  const bestId = s.best ? s.best.id : null;
  setBest(s.best);
  setDetList(s.tags_full || s.tags, bestId);
  renderOverlay(s.tags_full || s.tags, bestId);
}

// WebSocket; reconnect on drop with a short backoff.
let ws = null;
let wsBackoff = 250;
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/api/detections.ws`);
  ws.onopen = () => { wsBackoff = 250; };
  ws.onmessage = (ev) => {
    try { applySnapshot(JSON.parse(ev.data)); } catch (e) {}
  };
  ws.onclose = () => {
    setLinkPill(false);
    setTimeout(connectWS, wsBackoff);
    wsBackoff = Math.min(wsBackoff * 2, 4000);
  };
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
}
connectWS();

// --------------------------- health poll (cpu/temp/uptime) ---------------------------

const metaCpu  = $('#meta-cpu');
const metaTemp = $('#meta-temp');
const netHost  = $('#net-host');
const netIp    = $('#net-ip');
const netMode  = $('#net-mode');
const netConf  = $('#net-conf');
const netBuild = $('#net-build');
const netUpt   = $('#net-uptime');

function fmtUptime(s) {
  if (!s) return '—';
  const d = Math.floor(s / 86400);
  const h = Math.floor(s / 3600) % 24;
  const m = Math.floor(s / 60) % 60;
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

async function refreshHealth() {
  try {
    const r = await fetch('/api/health');
    if (!r.ok) return;
    const h = await r.json();
    metaCpu.textContent  = `${(h.cpu_pct).toFixed(0)}%`;
    metaTemp.textContent = h.temp_c ? `${h.temp_c.toFixed(1)} °C` : '—';
    netHost.textContent  = h.net?.hostname || '—';
    netIp.textContent    = h.net?.ip || '—';
    netMode.textContent  = h.net?.mode || '—';
    netConf.textContent  = h.net?.conf_set ? 'team WiFi configured' : 'unset (AP mode)';
    netBuild.textContent = h.build || '—';
    netUpt.textContent   = fmtUptime(h.uptime_s);
    $('#dev-name').textContent = (h.net?.hostname || 'acuity') + ' • vision coprocessor';
  } catch (e) { /* offline; leave displayed values stale */ }
}
setInterval(refreshHealth, 5000);
refreshHealth();

// --------------------------- settings tab ---------------------------

const setRes      = $('#set-resolution');
const setFps      = $('#set-fps');
const setFlipH    = $('#set-flip-h');
const setFlipV    = $('#set-flip-v');
const setCamIdx   = $('#set-cam-idx');
const setTagSize  = $('#set-tag-size');
const setMinMargin= $('#set-min-margin');
const setPrefTags = $('#set-pref-tags');
const setTeam     = $('#set-team');
const setNtHost   = $('#set-nt-host');
const settingsStatus = $('#settings-status');

async function loadSettings() {
  try {
    const r = await fetch('/api/settings');
    const s = await r.json();
    setRes.value      = `${s.resolution[0]}x${s.resolution[1]}`;
    setFps.value      = s.target_fps;
    setFlipH.checked  = s.flip_horizontal;
    setFlipV.checked  = s.flip_vertical;
    setCamIdx.value   = s.camera_index;
    setTagSize.value  = s.tag_size_m;
    setMinMargin.value= s.min_decision_margin;
    setPrefTags.value = (s.preferred_tag_ids || []).join(', ');
    setTeam.value     = s.nt_team;
    setNtHost.value   = s.nt_server_host;
  } catch (e) {
    settingsStatus.textContent = 'Failed to load settings.';
    settingsStatus.className = 'settings-status err';
  }
}
loadSettings();

$('#settings-save').addEventListener('click', async () => {
  const [w, h] = setRes.value.split('x').map(Number);
  const prefIds = setPrefTags.value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => Number.isFinite(n));
  const body = {
    resolution: [w, h],
    target_fps: Number(setFps.value),
    flip_horizontal: setFlipH.checked,
    flip_vertical: setFlipV.checked,
    camera_index: Number(setCamIdx.value),
    tag_size_m: Number(setTagSize.value),
    min_decision_margin: Number(setMinMargin.value),
    preferred_tag_ids: prefIds,
    nt_team: Number(setTeam.value),
    nt_server_host: setNtHost.value,
  };
  try {
    const r = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    settingsStatus.textContent = 'Saved.';
    settingsStatus.className = 'settings-status ok';
    setTimeout(() => settingsStatus.textContent = '', 2200);
  } catch (e) {
    settingsStatus.textContent = `Save failed: ${e.message || e}`;
    settingsStatus.className = 'settings-status err';
  }
});

// --------------------------- network tab actions ---------------------------

$('#action-reboot').addEventListener('click', async () => {
  if (!confirm('Reboot the device now?')) return;
  await fetch('/api/reboot', { method: 'POST' });
  alert('Reboot scheduled. The dashboard will be unreachable for ~30 s.');
});

$('#action-forget').addEventListener('click', async () => {
  if (!confirm(
    'Forget WiFi and reboot?\n\n' +
    'The device will come back as the open Acuity-Setup-XXXX AP. ' +
    'You\'ll need to reconnect to it from a phone or laptop and ' +
    'walk through the setup wizard again.')) return;
  await fetch('/api/forget-wifi', { method: 'POST' });
  alert('Forgetting WiFi + rebooting. Look for the Acuity-Setup-XXXX network.');
});

// --------------------------- logs tab ---------------------------

const logPane = $('#log-pane');
async function refreshLogs() {
  logPane.textContent = 'loading…';
  try {
    const r = await fetch('/api/logs?lines=400');
    logPane.textContent = await r.text();
    logPane.scrollTop = logPane.scrollHeight;
  } catch (e) {
    logPane.textContent = `failed to load logs: ${e.message || e}`;
  }
}
$('#logs-refresh').addEventListener('click', refreshLogs);
