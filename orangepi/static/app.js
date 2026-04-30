/* Cold Fusion Sight — browser-side controller.
 *
 * Three concerns:
 *   1. Subscribe to /api/state SSE and update the live HUD (dial/predicted/
 *      RPS/laser/gamepad/aim status).
 *   2. Capture clicks on the camera frame, normalize to 0..1, and POST to
 *      /api/aim. The rio takes it from there.
 *   3. Wire up dial bumps, calibrate, laser-as-dial buttons.
 *
 * No bundler, no framework — keeping the bundle path simple so the Pi can
 * serve everything statically with zero build step.
 */

const $ = (id) => document.getElementById(id);

// --- Connection pill -------------------------------------------------------
const connPill = $("conn-pill");
const aimPill = $("aim-pill");

function setConnected(ok) {
  if (ok) {
    connPill.textContent = "CONNECTED";
    connPill.className = "pill pill-good";
  } else {
    connPill.textContent = "DISCONNECTED";
    connPill.className = "pill pill-bad";
  }
}

// --- Click-to-aim ----------------------------------------------------------
const cameraFrame = $("camera-frame");
const overlay = $("overlay");
const targetMarker = $("target-marker");

cameraFrame.addEventListener("click", async (e) => {
  // Map the click position to the *image* coordinate system. The <img> is
  // object-fit: contain, so there can be letterboxing. We reuse the SVG's
  // 1000x1000 viewBox so the marker lines up with the click visually
  // regardless of the actual image resolution.
  const rect = cameraFrame.getBoundingClientRect();
  const xNorm = (e.clientX - rect.left) / rect.width;
  const yNorm = (e.clientY - rect.top) / rect.height;
  showTargetMarker(xNorm, yNorm);
  try {
    const r = await fetch("/api/aim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ x: xNorm, y: yNorm }),
    });
    if (!r.ok) throw new Error(await r.text());
  } catch (err) {
    setAimStatus("REQUEST FAILED", "fail");
    console.error(err);
  }
});

function showTargetMarker(xNorm, yNorm) {
  // SVG is 1000x1000 logical; convert.
  const x = xNorm * 1000;
  const y = yNorm * 1000;
  document.getElementById("target-ring").setAttribute("cx", x);
  document.getElementById("target-ring").setAttribute("cy", y);
  document.getElementById("target-dot").setAttribute("cx", x);
  document.getElementById("target-dot").setAttribute("cy", y);
  targetMarker.style.display = "";
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

// --- Calibrate -------------------------------------------------------------
$("cal-go").addEventListener("click", async () => {
  const v = parseFloat($("cal-true").value);
  if (!isFinite(v) || v <= 0) {
    $("cal-true").focus();
    return;
  }
  await fetch("/api/calibrate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ true_ft: v }),
  });
});

// --- Aim cancel ------------------------------------------------------------
$("aim-cancel").addEventListener("click", async () => {
  await fetch("/api/aim/cancel", { method: "POST" });
  targetMarker.style.display = "none";
});

// --- Live state via SSE ----------------------------------------------------
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

const POV_TO_NAME = {
  0: "N", 45: "NE", 90: "E", 135: "SE",
  180: "S", 225: "SW", 270: "W", 315: "NW",
};

function applyState(s) {
  setConnected(!!s.connected);

  $("r-dial").textContent  = fmt(s.dial_ft, 1, "ft");
  $("r-pred").textContent  = fmt(s.predicted_ft, 1, "ft");
  $("r-rps").textContent   = fmt(s.rps_setpoint, 1, "");
  $("r-laser").textContent = s.lasercan_valid ? fmt(s.lasercan_m, 2, "m") : "—";

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
  if (status === "IDLE") targetMarker.style.display = "none";
}

function fmt(v, digits, unit) {
  if (!isFinite(v)) return `--.- ${unit}`.trim();
  const u = unit ? ` ${unit}` : "";
  return `${v.toFixed(digits)}${u}`;
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
startSSE();

// --- Stream FPS estimator --------------------------------------------------
// The MJPEG <img> doesn't expose frame events; we measure decoded frames by
// listening for repeated 'load' events triggered by multipart boundaries.
// (Not all browsers fire it reliably; we just show "live" if we detect any.)
let lastUpdate = 0;
const fpsMeter = $("fps-meter");
const stream = $("stream");
let frameCount = 0;
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
