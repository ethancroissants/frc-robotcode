/* Cold Fusion Sight — browser-side controller.
 *
 * The Pi server owns AprilTag detection + RPS lookup; this file just:
 *   1. Subscribes to /api/state SSE and renders a live HUD (target lock,
 *      range/bearing/RPS readouts, gamepad mirror, lockout indicator).
 *   2. Wires the SHOOT button → POST /api/shoot. The rio takes over.
 *   3. Manages the calibration table (CRUD via /api/calibration*).
 *
 * No bundler, no framework — keep it serveable as static files from the Pi.
 */

const $ = (id) => document.getElementById(id);

// --- Status pills ----------------------------------------------------------
const connPill   = $("conn-pill");
const targetPill = $("target-pill");
const lockoutPill = $("lockout-pill");
const aimPill    = $("aim-pill");

function setConnected(ok) {
  connPill.textContent = ok ? "CONNECTED" : "DISCONNECTED";
  connPill.className = "pill " + (ok ? "pill-good" : "pill-bad");
}

function setTarget(detected, tagId) {
  if (detected) {
    targetPill.textContent = `LOCK #${tagId}`;
    targetPill.className = "pill pill-good";
  } else {
    targetPill.textContent = "NO TARGET";
    targetPill.className = "pill pill-bad";
  }
}

function setLockout(locked) {
  lockoutPill.style.display = locked ? "" : "none";
  lockoutPill.textContent = "DRIVER LOCKED";
}

function setAimStatus(text, klass) {
  const el = $("aim-status");
  el.textContent = text;
  el.className = "aim-status";
  if (klass) el.classList.add(klass);
  aimPill.textContent = `AIM ${text}`;
  aimPill.className = "pill " + (
    klass === "active" ? "pill-warn"
    : klass === "done" ? "pill-good"
    : klass === "fail" ? "pill-bad"
    : ""
  );
}

// --- SHOOT button ----------------------------------------------------------
const shootBtn = $("shoot-btn");
const shootSub = $("shoot-sub");

let lastTargetState = { detected: false, range_m: 0 };

function refreshShootButton(state) {
  // Armed = we have a target AND a known range (LaserCAN valid OR PnP > 0).
  const hasRange = (state.lasercan_valid && state.lasercan_m > 0)
                || (state.target?.detected && state.target.range_m > 0);
  const hasTarget = !!state.target?.detected;
  const armed = hasTarget && hasRange && !state.driver_lockout;

  shootBtn.classList.toggle("armed", armed);
  shootBtn.disabled = state.driver_lockout || !hasTarget;

  if (state.driver_lockout) {
    shootSub.textContent = "AutoAim running";
  } else if (!hasTarget) {
    shootSub.textContent = "no target";
  } else if (!hasRange) {
    shootSub.textContent = `tag #${state.target.tag_id} — no range`;
  } else {
    const r = state.lasercan_valid ? state.lasercan_m : state.target.range_m;
    const rps = state.recommended_rps;
    shootSub.textContent = rps != null
      ? `tag #${state.target.tag_id}  ${r.toFixed(2)}m → ${rps.toFixed(1)} rps`
      : `tag #${state.target.tag_id}  ${r.toFixed(2)}m`;
  }
}

shootBtn.addEventListener("click", async () => {
  if (shootBtn.disabled) return;
  // Optimistic UI: flash the button to confirm the press, even before the
  // rio responds. The aim status pill catches up via SSE.
  shootBtn.classList.add("armed");
  try {
    const r = await fetch("/api/shoot", { method: "POST" });
    if (!r.ok) throw new Error(await r.text());
  } catch (err) {
    console.error(err);
    setAimStatus("REQUEST FAILED", "fail");
  }
});

// --- Bearing tick on overlay -----------------------------------------------
// The server-side overlay already draws the tag box on the JPEG, but the
// SVG here adds a vertical "bearing tick" that lags by zero and follows the
// SSE feed even if the MJPEG stream stalls — useful as a sanity check.
const bearingTickG = $("bearing-tick");
const bearingLine  = $("bearing-line");

function updateBearingTick(target) {
  if (!target?.detected) {
    bearingTickG.style.display = "none";
    return;
  }
  const x = target.cx_norm * 1000;
  bearingLine.setAttribute("x1", x);
  bearingLine.setAttribute("x2", x);
  bearingTickG.style.display = "";
}

// --- Dial bumps ------------------------------------------------------------
document.querySelectorAll("[data-dial]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const delta = parseFloat(btn.dataset.dial);
    const cur = parseFloat($("dial-big").textContent) || 0;
    const next = Math.max(0, cur + delta);
    await fetch("/api/dial", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ft: next }),
    });
  });
});

// --- LaserCAN-as-dial ------------------------------------------------------
$("apply-laser").addEventListener("click", async () => {
  const m = parseFloat($("laser-big").textContent);
  if (!isFinite(m)) return;
  const ft = m / 0.3048;
  await fetch("/api/dial", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ft }),
  });
});

// --- Calibration table -----------------------------------------------------
const calBody = $("cal-body");

function renderCalibration(points) {
  calBody.innerHTML = "";
  for (const p of points) {
    const tr = document.createElement("tr");
    const td1 = document.createElement("td");
    td1.textContent = p.distance_ft.toFixed(2);
    const td2 = document.createElement("td");
    td2.textContent = p.rps.toFixed(1);
    const td3 = document.createElement("td");
    td3.className = "right-edge";
    const del = document.createElement("button");
    del.textContent = "remove";
    del.className = "row-del";
    del.addEventListener("click", () => removeCalPoint(p.distance_ft));
    td3.appendChild(del);
    tr.append(td1, td2, td3);
    calBody.appendChild(tr);
  }
}

async function loadCalibration() {
  try {
    const r = await fetch("/api/calibration");
    const j = await r.json();
    renderCalibration(j.points || []);
  } catch (err) {
    console.error("calibration load failed", err);
  }
}

async function addCalPoint(distance_ft, rps) {
  const r = await fetch("/api/calibration/add", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ distance_ft, rps }),
  });
  const j = await r.json();
  renderCalibration(j.points || []);
}

async function removeCalPoint(distance_ft) {
  const r = await fetch("/api/calibration/remove", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ distance_ft }),
  });
  const j = await r.json();
  renderCalibration(j.points || []);
}

$("cal-add-btn").addEventListener("click", () => {
  const d = parseFloat($("cal-add-dist").value);
  const r = parseFloat($("cal-add-rps").value);
  if (!isFinite(d) || !isFinite(r) || d < 0 || r < 0) {
    $("cal-add-dist").focus();
    return;
  }
  addCalPoint(d, r);
  $("cal-add-dist").value = "";
  $("cal-add-rps").value = "";
});

$("cal-snapshot-btn").addEventListener("click", () => {
  // "Snapshot current shot": use the live LaserCAN distance + currently
  // dialed RPS (computed from the manual dial via the same RPS-per-foot
  // mapping the rio uses). If the laser isn't valid, fall back to dial.
  const m = parseFloat($("laser-big").textContent);
  const dialFt = parseFloat($("dial-big").textContent);
  const distFt = isFinite(m) ? m / 0.3048 : dialFt;
  // Rough RPS assumption: 10 rps/ft from the rio's _SHOOTER_RPS_PER_FOOT
  // default. Operator can correct it inline before saving by editing the
  // table, but giving them a starting value beats a blank input.
  const rps = isFinite(dialFt) ? dialFt * 10.0 : 0;
  if (!isFinite(distFt) || distFt <= 0) return;
  addCalPoint(distFt, rps);
});

// --- Live state via SSE ----------------------------------------------------
const POV_TO_NAME = {
  0: "N", 45: "NE", 90: "E", 135: "SE",
  180: "S", 225: "SW", 270: "W", 315: "NW",
};

function fmt(v, digits, unit) {
  if (!isFinite(v)) return `--.- ${unit}`.trim();
  const u = unit ? ` ${unit}` : "";
  return `${v.toFixed(digits)}${u}`;
}

function applyState(s) {
  setConnected(!!s.connected);
  setLockout(!!s.driver_lockout);
  const t = s.target || { detected: false };
  setTarget(t.detected, t.tag_id);
  lastTargetState = t;

  // Top-bar readouts
  if (t.detected) {
    $("r-range").textContent   = fmt(t.range_m, 2, "m");
    $("r-bearing").textContent = `${t.bearing_deg >= 0 ? "+" : ""}${t.bearing_deg.toFixed(1)}°`;
    $("r-tag").textContent     = `#${t.tag_id}`;
  } else {
    $("r-range").textContent   = "—";
    $("r-bearing").textContent = "—";
    $("r-tag").textContent     = "—";
  }
  $("r-rps").textContent = isFinite(s.recommended_rps)
    ? s.recommended_rps.toFixed(1)
    : "—";

  // Manual dial readouts
  $("dial-big").textContent  = isFinite(s.dial_ft) ? s.dial_ft.toFixed(1) : "--.-";
  $("laser-big").textContent = isFinite(s.lasercan_m) ? s.lasercan_m.toFixed(2) : "--.--";

  const laserPill = $("laser-pill");
  if (s.lasercan_valid) {
    laserPill.textContent = "LIVE";
    laserPill.className = "pill pill-good";
  } else {
    laserPill.textContent = "NO READING";
    laserPill.className = "pill pill-bad";
  }

  // Gamepad mirror
  const povName = POV_TO_NAME[s.pov] || null;
  document.querySelectorAll(".dpad-cell").forEach((c) => {
    const want = c.dataset.pov;
    c.classList.toggle("active", want && want !== "C" && want === povName);
  });
  for (const k of ["A", "B", "X", "Y", "LB", "RB"]) {
    const el = document.querySelector(`[data-btn="${k}"]`);
    if (el) el.classList.toggle("active", !!s[`btn_${k.toLowerCase()}`]);
  }

  // Aim status
  const status = String(s.aim_status || "idle").toUpperCase();
  let klass = "";
  if (status === "ROTATING" || status === "SPINNING_UP" || status === "FIRING") {
    klass = "active";
  } else if (status === "DONE") {
    klass = "done";
  } else if (status === "ERROR") {
    klass = "fail";
  }
  setAimStatus(status, klass);

  updateBearingTick(t);
  refreshShootButton(s);
}

function startSSE() {
  const es = new EventSource("/api/state");
  es.onmessage = (ev) => {
    try { applyState(JSON.parse(ev.data)); } catch (e) { console.error(e); }
  };
  es.onerror = () => {
    setConnected(false);
    es.close();
    setTimeout(startSSE, 1000);
  };
}

// --- Healthz + tag list bootstrap ------------------------------------------
async function loadHealth() {
  try {
    const j = await (await fetch("/api/healthz")).json();
    if (j.target_tag_ids?.length) {
      $("target-tag-list").textContent = j.target_tag_ids.join(", ");
    } else {
      $("target-tag-list").textContent = "(any)";
    }
  } catch (err) {
    $("target-tag-list").textContent = "?";
  }
}

// --- Stream FPS estimator --------------------------------------------------
const fpsMeter = $("fps-meter");
const stream   = $("stream");
let frameWindow = [];
stream.addEventListener("load", () => {
  const t = performance.now();
  frameWindow.push(t);
  while (frameWindow.length > 30) frameWindow.shift();
  if (frameWindow.length > 1) {
    const dt = (frameWindow[frameWindow.length - 1] - frameWindow[0]) / 1000;
    const fps = (frameWindow.length - 1) / dt;
    fpsMeter.textContent = `stream: ${fps.toFixed(1)} fps`;
  }
});

// Local clock (uptime indicator).
setInterval(() => {
  const d = new Date();
  $("ts").textContent = d.toLocaleTimeString();
}, 1000);

// Bootstrap.
loadHealth();
loadCalibration();
startSSE();
