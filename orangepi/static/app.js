/* Cold Fusion Sight — windowed dashboard.
 *
 * Architecture:
 *   - WindowManager owns each .panel: drag, resize, minimize, persistence
 *     (localStorage key "cfsight.layout"). On first load (no key) it
 *     applies a sane default layout computed from workspace dimensions.
 *   - One EventSource on /api/state pumps the dashboard. Every view
 *     listener reads from `state` (the latest snapshot) instead of
 *     re-fetching — no polling. SSE flagged values are passed straight
 *     through with their _ages_ms so the UI can dim stale data instead
 *     of confidently displaying a default zero.
 *   - One EventSource on /api/logs pumps the debug-console log tail.
 *   - The camera panel hit-tests pointer clicks against the authoritative
 *     pixel-corner data the server publishes for every detected tag, then
 *     POSTs /api/target. No client-side detection — the server is the
 *     source of truth so all dashboards stay consistent.
 *
 * No bundler, no framework. Run as static files.
 */

"use strict";

// ============================================================
// Tiny helpers
// ============================================================
const $  = (id) => document.getElementById(id);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

// Bumped to v4: v3 layouts were computed against a topbar that wrapped
// to two rows (4 children but only 3 grid columns) so the workspace
// was 38px shorter than reality. Forcing fresh defaults instead of
// asking everyone to click "reset layout" manually.
const LAYOUT_KEY = "cfsight.layout.v4";

// Workspace background grid is 24px (see .workspace::backround-image
// in style.css). Snap drag + resize to it so panels line up cleanly
// with the grid the eye is already trained to see.
const GRID = 24;
const snap = (v) => Math.round(v / GRID) * GRID;

function fmt(v, digits, unit) {
  if (v == null || !Number.isFinite(v)) return unit ? `—` : "—";
  return `${v.toFixed(digits)}${unit ? unit : ""}`;
}

function signFmt(v, digits) {
  if (v == null || !Number.isFinite(v)) return "—";
  const s = v >= 0 ? "+" : "";
  return `${s}${v.toFixed(digits)}°`;
}

// ============================================================
// Window manager
// ============================================================
//
// Each .panel inside #workspace becomes a draggable, resizable,
// minimizable window. Layout for all panels is persisted as a single
// blob under LAYOUT_KEY so we read/write once per change.

class WindowManager {
  constructor(workspaceEl) {
    this.workspace = workspaceEl;
    this.panels = new Map();  // id -> {el, minimized}
    this._zCounter = 1;
    $$(".panel", workspaceEl).forEach((el) => this._registerPanel(el));
    this._loadLayout();
    window.addEventListener("resize", () => this._clampAll());
    $("reset-layout-btn").addEventListener("click", () => this.resetLayout());
  }

  _registerPanel(el) {
    const id = el.id;
    const rec = { el, minimized: false };
    this.panels.set(id, rec);
    const header = el.querySelector(".panel-header");
    const resize = el.querySelector(".panel-resize");
    const minBtn = el.querySelector(".panel-min");
    if (header) this._installDrag(rec, header);
    if (resize) this._installResize(rec, resize);
    if (minBtn) {
      minBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._toggleMinimize(rec);
      });
    }
    el.addEventListener("pointerdown", () => this._bringToFront(rec));
  }

  _installDrag(rec, header) {
    header.addEventListener("pointerdown", (e) => {
      // Don't start a drag if the click landed on a button inside the header.
      if (e.target.closest("button")) return;
      const r = rec.el.getBoundingClientRect();
      const ws = this.workspace.getBoundingClientRect();
      const startX = e.clientX, startY = e.clientY;
      const startLeft = r.left - ws.left;
      const startTop  = r.top  - ws.top;
      header.setPointerCapture(e.pointerId);
      rec.el.classList.add("dragging");
      this._bringToFront(rec);
      const onMove = (ev) => {
        const w = rec.el.offsetWidth;
        const h = rec.el.offsetHeight;
        const maxX = this.workspace.clientWidth  - 24; // keep at least the corner visible
        const maxY = this.workspace.clientHeight - 24;
        const minX = -w + 80;                          // and 80px draggable handle on the other side
        const minY = 0;
        let x = startLeft + (ev.clientX - startX);
        let y = startTop  + (ev.clientY - startY);
        // Snap to the workspace's 24px grid so panels line up visibly.
        x = snap(x);
        y = snap(y);
        x = Math.max(minX, Math.min(maxX, x));
        y = Math.max(minY, Math.min(maxY, y));
        rec.el.style.left = `${x}px`;
        rec.el.style.top  = `${y}px`;
      };
      const onUp = (ev) => {
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
        rec.el.classList.remove("dragging");
        try { header.releasePointerCapture(ev.pointerId); } catch (_) {}
        this._saveLayout();
      };
      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", onUp);
    });
  }

  _installResize(rec, handle) {
    handle.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      const r = rec.el.getBoundingClientRect();
      const startX = e.clientX, startY = e.clientY;
      const startW = r.width, startH = r.height;
      handle.setPointerCapture(e.pointerId);
      rec.el.classList.add("resizing");
      this._bringToFront(rec);
      const onMove = (ev) => {
        let w = Math.max(200, startW + (ev.clientX - startX));
        let h = Math.max(100, startH + (ev.clientY - startY));
        // Snap to grid; clamp again post-snap in case snap pulled below
        // the minimum.
        w = Math.max(GRID * 8, snap(w));
        h = Math.max(GRID * 4, snap(h));
        rec.el.style.width  = `${w}px`;
        rec.el.style.height = `${h}px`;
      };
      const onUp = (ev) => {
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
        rec.el.classList.remove("resizing");
        try { handle.releasePointerCapture(ev.pointerId); } catch (_) {}
        this._saveLayout();
      };
      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", onUp);
    });
  }

  _toggleMinimize(rec) {
    rec.minimized = !rec.minimized;
    rec.el.classList.toggle("minimized", rec.minimized);
    rec.el.querySelector(".panel-min").textContent = rec.minimized ? "+" : "−";
    this._saveLayout();
  }

  _bringToFront(rec) {
    this._zCounter += 1;
    rec.el.style.zIndex = String(this._zCounter);
  }

  _layoutData() {
    const out = {};
    const ws = this.workspace.getBoundingClientRect();
    for (const [id, rec] of this.panels) {
      const r = rec.el.getBoundingClientRect();
      out[id] = {
        x: Math.round(r.left - ws.left),
        y: Math.round(r.top  - ws.top),
        w: Math.round(r.width),
        h: Math.round(r.height),
        z: parseInt(rec.el.style.zIndex || "1", 10),
        m: rec.minimized,
      };
    }
    return out;
  }

  _applyLayout(layout) {
    let maxZ = 0;
    for (const [id, rec] of this.panels) {
      const d = layout[id];
      if (!d) continue;
      rec.el.style.left = `${d.x}px`;
      rec.el.style.top  = `${d.y}px`;
      rec.el.style.width  = `${d.w}px`;
      rec.el.style.height = `${d.h}px`;
      rec.el.style.zIndex = String(d.z || 1);
      maxZ = Math.max(maxZ, d.z || 1);
      rec.minimized = !!d.m;
      rec.el.classList.toggle("minimized", rec.minimized);
      const minBtn = rec.el.querySelector(".panel-min");
      if (minBtn) minBtn.textContent = rec.minimized ? "+" : "−";
    }
    this._zCounter = maxZ;
  }

  _saveLayout() {
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(this._layoutData()));
    } catch (_) {}
  }

  _loadLayout() {
    let raw = null;
    try { raw = localStorage.getItem(LAYOUT_KEY); } catch (_) {}
    if (raw) {
      try { this._applyLayout(JSON.parse(raw)); return; } catch (_) {}
    }
    this._applyLayout(this._defaultLayout());
  }

  resetLayout() {
    try { localStorage.removeItem(LAYOUT_KEY); } catch (_) {}
    this._applyLayout(this._defaultLayout());
    this._saveLayout();
  }

  _clampAll() {
    // After window resize, drag any panel that's now off-screen back in.
    const W = this.workspace.clientWidth;
    const H = this.workspace.clientHeight;
    for (const [, rec] of this.panels) {
      const r = rec.el.getBoundingClientRect();
      const ws = this.workspace.getBoundingClientRect();
      const x = r.left - ws.left;
      const y = r.top  - ws.top;
      const w = r.width;
      const newX = Math.max(0, Math.min(W - 80, x));
      const newY = Math.max(0, Math.min(H - 24, y));
      if (newX !== x) rec.el.style.left = `${newX}px`;
      if (newY !== y) rec.el.style.top  = `${newY}px`;
    }
    this._saveLayout();
  }

  _defaultLayout() {
    // Computed from current workspace size, rounded to the 24px grid so
    // the default layout looks tidy on the grid background. Layout:
    //   left top: camera (dominant)
    //   right top column: target / fire / dial (stacked)
    //   bottom row: calibration | operator | driver | debug (across full width)
    const ws = this.workspace;
    const W = Math.max(960, ws.clientWidth);
    const H = Math.max(640, ws.clientHeight);
    const m = GRID;            // outer margin on all sides
    const gap = GRID;          // gap between panels
    const usableW = W - 2 * m;
    const usableH = H - 2 * m;

    // Right column (target/fire/dial) — narrow. Snap to grid.
    let rightW = snap(Math.max(240, Math.min(312, Math.floor(W * 0.22))));
    let leftW  = snap(usableW - rightW - gap);

    // Top half is the camera + right column.
    let topH = snap(Math.max(360, Math.floor(H * 0.60)));
    let bottomH = snap(usableH - topH - gap);
    let rightItemH = snap(Math.floor((topH - 2 * gap) / 3));

    // Bottom row: 4 panels side by side. Each gets a snap-aligned share
    // of the total bottom width.
    const bottomTotalW = usableW;
    const calW = snap(Math.floor(bottomTotalW * 0.28));
    const opW  = snap(Math.floor(bottomTotalW * 0.18));
    const drW  = snap(Math.floor(bottomTotalW * 0.18));
    // Debug fills the rest so the row reaches the right edge regardless
    // of rounding.
    const dbgW = bottomTotalW - calW - opW - drW - 3 * gap;

    const rightX = m + leftW + gap;
    const bottomY = m + topH + gap;

    return {
      "panel-camera":   { x: m, y: m, w: leftW, h: topH, z: 1, m: false },
      "panel-target":   { x: rightX, y: m,                              w: rightW, h: rightItemH, z: 2, m: false },
      "panel-fire":     { x: rightX, y: m + rightItemH + gap,           w: rightW, h: rightItemH, z: 3, m: false },
      "panel-dial":     { x: rightX, y: m + 2 * (rightItemH + gap),     w: rightW, h: rightItemH, z: 4, m: false },
      "panel-cal":      { x: m,                                  y: bottomY, w: calW, h: bottomH, z: 5, m: false },
      "panel-operator": { x: m + calW + gap,                     y: bottomY, w: opW,  h: bottomH, z: 6, m: false },
      "panel-driver":   { x: m + calW + opW + 2 * gap,           y: bottomY, w: drW,  h: bottomH, z: 7, m: false },
      "panel-debug":    { x: m + calW + opW + drW + 3 * gap,     y: bottomY, w: dbgW, h: bottomH, z: 8, m: false },
    };
  }
}

// ============================================================
// Click-to-target
// ============================================================

function pointInQuad(px, py, quad) {
  // Same-sign-cross test for a convex quad. AprilTag corners are always
  // convex so this is exact.
  let sign = 0;
  for (let i = 0; i < 4; i++) {
    const [x1, y1] = quad[i];
    const [x2, y2] = quad[(i + 1) % 4];
    const c = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1);
    if (c !== 0) {
      const s = c > 0 ? 1 : -1;
      if (sign === 0) sign = s;
      else if (sign !== s) return false;
    }
  }
  return true;
}

class CameraPanel {
  constructor() {
    this.frame = $("camera-frame");
    this.svg = $("overlay");
    this.hoverLayer = $("tag-hover-layer");
    this.selectLayer = $("tag-select-layer");
    this.imgEl = $("stream");
    this.imageW = 1;
    this.imageH = 1;
    this.allTags = [];
    this.selectedId = null;

    this.frame.addEventListener("click", (e) => this._onClick(e));
    this.frame.addEventListener("mousemove", (e) => this._onMove(e));
    this.frame.addEventListener("mouseleave", () => this._clearHover());

    $("clear-target-btn").addEventListener("click", () => this._post(null));
  }

  setImageSize(w, h) {
    if (w === this.imageW && h === this.imageH) return;
    this.imageW = w;
    this.imageH = h;
    // SVG viewBox in image-pixel space + preserveAspectRatio="xMidYMid meet"
    // makes the SVG content area match the IMG's object-fit:contain area.
    // We can then draw with raw pixel coords and they line up exactly.
    this.svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    this.svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  }

  setTags(allTags, selectedId) {
    this.allTags = allTags || [];
    this.selectedId = (selectedId == null) ? null : Number(selectedId);
    this._render();
  }

  _render() {
    // Selection ring around the locked tag (if any + visible).
    while (this.selectLayer.firstChild) this.selectLayer.removeChild(this.selectLayer.firstChild);
    if (this.selectedId != null) {
      const tag = this.allTags.find(t => Number(t.tag_id) === this.selectedId);
      if (tag && tag.corners_px) {
        const poly = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        poly.setAttribute("points", tag.corners_px.map(([x,y]) => `${x},${y}`).join(" "));
        poly.setAttribute("class", "tag-box");
        this.selectLayer.appendChild(poly);
      }
    }
  }

  _eventToImagePoint(ev) {
    // Converts a screen-space click into image-pixel space using the
    // SVG's CTM (which already accounts for preserveAspectRatio meet).
    const pt = this.svg.createSVGPoint();
    pt.x = ev.clientX;
    pt.y = ev.clientY;
    const ctm = this.svg.getScreenCTM();
    if (!ctm) return null;
    return pt.matrixTransform(ctm.inverse());
  }

  _onClick(ev) {
    const p = this._eventToImagePoint(ev);
    if (!p) return;
    // Out of image bounds = clicked the letterbox; clear selection.
    if (p.x < 0 || p.y < 0 || p.x > this.imageW || p.y > this.imageH) {
      this._post(null);
      return;
    }
    let hit = null;
    for (const tag of this.allTags) {
      if (!tag.corners_px || tag.corners_px.length < 4) continue;
      if (pointInQuad(p.x, p.y, tag.corners_px)) { hit = tag; break; }
    }
    this._post(hit ? Number(hit.tag_id) : null);
  }

  _onMove(ev) {
    const p = this._eventToImagePoint(ev);
    if (!p) return this._clearHover();
    if (p.x < 0 || p.y < 0 || p.x > this.imageW || p.y > this.imageH) {
      return this._clearHover();
    }
    while (this.hoverLayer.firstChild) this.hoverLayer.removeChild(this.hoverLayer.firstChild);
    for (const tag of this.allTags) {
      if (!tag.corners_px || tag.corners_px.length < 4) continue;
      if (Number(tag.tag_id) === this.selectedId) continue;
      if (pointInQuad(p.x, p.y, tag.corners_px)) {
        const poly = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        poly.setAttribute("points", tag.corners_px.map(([x,y]) => `${x},${y}`).join(" "));
        poly.setAttribute("class", "tag-box");
        this.hoverLayer.appendChild(poly);
        break;
      }
    }
  }

  _clearHover() {
    while (this.hoverLayer.firstChild) this.hoverLayer.removeChild(this.hoverLayer.firstChild);
  }

  async _post(tagId) {
    try {
      await fetch("/api/target", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tag_id: tagId }),
      });
    } catch (e) {
      console.error("target post failed", e);
    }
  }
}

// ============================================================
// State view (top bar pills + most readouts)
// ============================================================

const STALE_MS = 2000;  // values older than this dim out

function isStale(ageMs) {
  return ageMs == null || ageMs > STALE_MS;
}

class StateView {
  constructor(camera) {
    this.camera = camera;

    this.rioStatus   = $("rio-status");
    this.enabledPill = $("enabled-pill");
    this.lockPill    = $("lock-pill");
    this.readyPill   = $("ready-pill");
    this.lockoutPill = $("lockout-pill");
    this.recPill     = $("recording-pill");
    this.recBtn      = $("rec-btn");
    this.calPill     = $("calibrate-pill");

    this.lastTopics = {};

    // Record toggle. The button reflects the server's view of recording
    // state via _refreshRecording() each tick — clicks just flip it.
    if (this.recBtn) {
      this.recBtn.addEventListener("click", async () => {
        const isRec = this.recBtn.classList.contains("recording");
        const url = isRec ? "/api/record/stop" : "/api/record/start";
        try {
          const r = await fetch(url, { method: "POST" });
          if (!r.ok) {
            const text = await r.text();
            console.error("record toggle failed", text);
            cfAlert("Recording failed:\n\n" + text, { title: "Recording", kind: "error" });
          }
        } catch (e) {
          console.error(e);
          cfAlert("Recording failed:\n\n" + e.message, { title: "Recording", kind: "error" });
        }
      });
    }

    // Manual dial bumpers. Click → POST /api/dial with new value.
    $$("[data-dial]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const delta = parseFloat(btn.dataset.dial);
        const cur = parseFloat($("dial-big").textContent) || 0;
        const next = Math.max(0, cur + delta);
        try {
          await fetch("/api/dial", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ft: next }),
          });
        } catch (e) { console.error(e); }
      });
    });

    // Tag-PnP range → dial. The Distance panel shows the live tag range
    // (in feet); this button copies it into the manual dial so the
    // operator can hand-tune around it.
    $("apply-tag-range").addEventListener("click", async () => {
      const ft = parseFloat($("tag-range-big").textContent);
      if (!Number.isFinite(ft) || ft <= 0) return;
      try {
        await fetch("/api/dial", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ft }),
        });
      } catch (e) { console.error(e); }
    });

    // SHOOT button.
    $("shoot-btn").addEventListener("click", async () => {
      if ($("shoot-btn").disabled) return;
      try {
        const r = await fetch("/api/shoot", { method: "POST" });
        if (!r.ok) throw new Error(await r.text());
      } catch (e) {
        console.error(e);
        $("aim-status").textContent = "request failed";
        $("aim-status").className = "aim-status-line fail";
      }
    });
  }

  apply(s) {
    const connected = !!s.connected;
    const ntHost = s.nt_host || null;
    const ages = s._ages_ms || {};

    // Wrap each independent section in safe(): if a downstream selector
    // is missing or a value is malformed, that section logs and skips
    // — but every other section (especially click-to-target via
    // setTags) still runs. The previous structure had every section
    // share one execution path, so a single null DOM ref could black
    // out the whole UI.
    const safe = (label, fn) => {
      try { fn(); } catch (e) { console.error(`apply.${label}`, e); }
    };

    safe("rioStatus", () => this._setRioStatus(connected, ntHost));

    const enabled = s.robot_enabled !== false;
    safe("enabledPill", () => {
      if (!connected) {
        this._setPill(this.enabledPill, "rio offline", "");
      } else if (enabled) {
        this._setPill(this.enabledPill, "enabled", "good");
      } else {
        this._setPill(this.enabledPill, "disabled", "bad");
      }
    });

    safe("lockPill", () => {
      if (s.selected_tag_id != null) {
        this._setPill(this.lockPill, `lock #${s.selected_tag_id}`, "info");
      } else {
        this._setPill(this.lockPill, "no lock", "");
      }
    });

    const ready = !!(s.target && s.target.ready);
    safe("readyPill", () => {
      this._setPill(this.readyPill, ready ? "ready" : "not ready",
                    ready ? "good" : "bad");
    });

    safe("lockoutPill", () => {
      if (this.lockoutPill) {
        this.lockoutPill.style.display = s.driver_lockout ? "" : "none";
      }
    });

    safe("controlsClass", () => {
      document.body.classList.toggle("controls-disabled", !connected || !enabled);
    });

    // ----- target panel -----
    const t = s.target || { detected: false };
    safe("targetPanel", () => {
      if (t.detected) {
        $("r-tag").textContent     = `#${t.tag_id}`;
        // Display in feet to match the dial / calibration table units; the
        // wire format from the Pi is meters (range_m) — convert here.
        $("r-range").textContent   = fmt(
          Number.isFinite(t.range_m) ? t.range_m / 0.3048 : null, 1, " ft");
        $("r-bearing").textContent = signFmt(t.bearing_deg, 1);
      } else {
        $("r-tag").textContent     = "—";
        $("r-range").textContent   = "—";
        $("r-bearing").textContent = "—";
      }
      $("r-rps").textContent = Number.isFinite(s.recommended_rps)
        ? s.recommended_rps.toFixed(1) : "—";

      const stateEl = $("r-target-state");
      if (!stateEl) return;
      if (t.detected) {
        if (t.selected_locked) {
          stateEl.textContent = `locked #${t.tag_id}${ready ? " · on target" : " · off-bearing"}`;
          stateEl.className = "target-state locked";
        } else {
          stateEl.textContent = `auto-pick #${t.tag_id}${ready ? " · on target" : " · off-bearing"}`;
          stateEl.className = "target-state locked";
        }
      } else if (s.selected_tag_id != null) {
        stateEl.textContent = `searching for #${s.selected_tag_id}…`;
        stateEl.className = "target-state searching";
      } else {
        stateEl.textContent = "no target";
        stateEl.className = "target-state notarget";
      }
    });

    // ----- distance panel (manual dial + live tag-PnP range) -----
    safe("distance", () => {
      const dialEl = $("dial-big");
      if (dialEl) {
        const dialFresh = Number.isFinite(s.dial_ft) && !isStale(ages.dial_ft);
        if (dialFresh) {
          dialEl.textContent = s.dial_ft.toFixed(1);
          dialEl.classList.remove("stale");
        } else {
          dialEl.textContent = "—";
          dialEl.classList.add("stale");
        }
      }
      const tagRangeEl = $("tag-range-big");
      if (tagRangeEl) {
        if (t.detected && Number.isFinite(t.range_m) && t.range_m > 0) {
          tagRangeEl.textContent = (t.range_m / 0.3048).toFixed(1);
          tagRangeEl.classList.remove("stale");
        } else {
          tagRangeEl.textContent = "—";
          tagRangeEl.classList.add("stale");
        }
      }
    });

    safe("gamepads", () => {
      this._applyStick('[data-stick="operator"]', s.operator || {});
      this._applyStick('[data-stick="driver"]',   s.driver   || {});
    });

    safe("aimStatus", () => {
      const raw = String(s.aim_status || "idle").toLowerCase();
      let klass = "";
      if (["rotating", "spinning_up", "firing"].includes(raw)) klass = "active";
      else if (raw === "done") klass = "done";
      else if (raw === "error") klass = "fail";
      const aimEl = $("aim-status");
      if (!aimEl) return;
      aimEl.textContent = raw.replace(/_/g, " ");
      aimEl.className = `aim-status-line ${klass}`;
    });

    safe("shoot", () => this._refreshShoot(s, t, ready, connected, enabled));
    safe("recording", () => this._refreshRecording(s.recording || { active: false }));

    safe("calPill", () => {
      if (this.calPill) {
        const calActive = !!(s.calibrate && s.calibrate.active);
        this.calPill.style.display = calActive ? "" : "none";
      }
    });

    // Camera overlay update is the load-bearing path for click-to-lock —
    // give it its own try block so absolutely nothing earlier in this
    // method can knock it out.
    safe("camera", () => {
      if (s.image_size) {
        this.camera.setImageSize(s.image_size.w, s.image_size.h);
      }
      this.camera.setTags(s.all_tags || [], s.selected_tag_id);
    });

    safe("stats", () => this._refreshStats(s));
    safe("topics", () => this._refreshTopics(s, ages));
  }

  _setPill(el, text, kind) {
    el.textContent = text;
    el.className = "pill" + (kind ? ` pill-${kind}` : "");
  }

  _setRioStatus(connected, host) {
    if (!this.rioStatus) return;
    this.rioStatus.classList.toggle("connected", connected);
    this.rioStatus.classList.toggle("disconnected", !connected);
    const txt = this.rioStatus.querySelector(".rio-text");
    if (!txt) return;
    if (connected) {
      txt.textContent = host ? `rio link up · ${host}` : "rio link up";
    } else {
      // When the link is down, surface the address we're dialing — turns
      // a useless "rio disconnected" into something the operator can
      // verify against their actual rio IP.
      txt.textContent = host
        ? `rio disconnected · trying ${host}`
        : "rio disconnected";
    }
  }

  _applyStick(rootSelector, data) {
    const root = document.querySelector(rootSelector);
    if (!root) return;
    const POV_TO_NAME = {
      0: "N", 45: "NE", 90: "E", 135: "SE",
      180: "S", 225: "SW", 270: "W", 315: "NW",
    };
    const povName = POV_TO_NAME[data.pov] || null;
    root.querySelectorAll(".dpad-cell").forEach((c) => {
      const want = c.dataset.pov;
      c.classList.toggle("active", !!want && want === povName);
    });
    for (const k of ["A", "B", "X", "Y", "LB", "RB"]) {
      const el = root.querySelector(`[data-btn="${k}"]`);
      if (el) el.classList.toggle("active", !!data[`btn_${k.toLowerCase()}`]);
    }
  }

  _refreshRecording(rec) {
    const active = !!rec.active;
    if (this.recBtn) {
      this.recBtn.classList.toggle("recording", active);
      this.recBtn.textContent = active ? "■ stop" : "● rec";
      this.recBtn.title = active ? "Stop recording" : "Start recording";
    }
    if (this.recPill) {
      if (active) {
        this.recPill.style.display = "";
        const elapsed = Math.max(0, Math.floor(rec.elapsed_s || 0));
        const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
        const ss = String(elapsed % 60).padStart(2, "0");
        this.recPill.textContent = `● rec ${mm}:${ss}`;
      } else {
        this.recPill.style.display = "none";
      }
    }
  }

  _refreshShoot(s, t, ready, connected, enabled) {
    const btn = $("shoot-btn");
    const sub = $("shoot-sub");
    const hasRange = t.detected && t.range_m > 0;
    const armed = connected && t.detected && hasRange
                  && enabled && !s.driver_lockout && ready;
    btn.classList.toggle("armed", armed);
    btn.disabled = !armed;

    if (!connected)             sub.textContent = "rio offline";
    else if (!enabled)          sub.textContent = "robot disabled";
    else if (s.driver_lockout)  sub.textContent = "AutoAim running";
    else if (!t.detected) {
      sub.textContent = s.selected_tag_id != null
        ? `searching for #${s.selected_tag_id}`
        : "click a tag to lock";
    }
    else if (!hasRange)         sub.textContent = `tag #${t.tag_id} · no range`;
    else if (!ready)            sub.textContent = `tag #${t.tag_id} · off-bearing`;
    else {
      const rps = s.recommended_rps;
      const ft = (t.range_m / 0.3048).toFixed(1);
      sub.textContent = rps != null
        ? `#${t.tag_id} · ${ft}ft · ${rps.toFixed(1)} rps`
        : `#${t.tag_id} · ${ft}ft`;
    }
  }

  _refreshStats(s) {
    // Every line guards on the element existing — _refreshStats runs on
    // every SSE tick, so a single null .textContent= here used to take
    // out the rest of apply() (and silently broke click-to-lock for any
    // operator on a stale index.html). Defensive lookup costs nothing.
    const setText = (id, text) => {
      const el = $(id);
      if (el) el.textContent = text;
    };
    if (s.fps) {
      setText("s-cap-fps", Number.isFinite(s.fps.capture) ? s.fps.capture.toFixed(1) : "—");
      setText("s-det-fps", Number.isFinite(s.fps.detect)  ? s.fps.detect.toFixed(1)  : "—");
    }
    if (s.image_size) setText("s-imgsize", `${s.image_size.w}×${s.image_size.h}`);
    if (s.intrinsics_source) setText("s-intrinsics", s.intrinsics_source);
    setText("s-nt-host", s.nt_host || "—");
    if (s.target_tag_ids) setText("s-target-tags", s.target_tag_ids.join(", ") || "(any)");
    if (Array.isArray(s.seen_tags)) setText("s-seen-tags", s.seen_tags.length ? s.seen_tags.join(", ") : "(none)");
    if (s.version) setText("s-version", s.version);
    setText("brand-version", s.version ? `v${s.version}` : "");
  }

  _refreshTopics(s, ages) {
    // Render a small fixed set of NT topics that matter for debugging.
    // The full state object is too noisy to dump verbatim. Operator +
    // driver buttons share rows so the table stays scannable; ages key
    // is still flat (op_btn_a/dr_btn_a etc.) since we expose ages per
    // raw NT topic, not per-stick.
    const tbody = $("topic-body");
    const op = s.operator || {};
    const dr = s.driver || {};
    const rows = [
      ["connected", s.connected, null],
      ["robot_enabled", s.robot_enabled, ages.robot_enabled],
      ["driver_lockout", s.driver_lockout, ages.driver_lockout],
      ["aim_status", s.aim_status, ages.aim_status],
      ["dial_ft", s.dial_ft, ages.dial_ft],
      ["operator.pov", op.pov, ages.op_pov],
      ["operator.A/B/X/Y", `${+!!op.btn_a}${+!!op.btn_b}${+!!op.btn_x}${+!!op.btn_y}`, ages.op_btn_a],
      ["operator.LB/RB", `${+!!op.btn_lb}${+!!op.btn_rb}`, ages.op_btn_lb],
      ["driver.pov", dr.pov, ages.dr_pov],
      ["driver.A/B/X/Y", `${+!!dr.btn_a}${+!!dr.btn_b}${+!!dr.btn_x}${+!!dr.btn_y}`, ages.dr_btn_a],
      ["driver.LB/RB", `${+!!dr.btn_lb}${+!!dr.btn_rb}`, ages.dr_btn_lb],
      ["selected_tag_id", s.selected_tag_id, null],
      ["target.detected", s.target ? s.target.detected : false, null],
      ["target.tag_id", s.target ? s.target.tag_id : null, null],
      ["target.bearing_deg", s.target ? s.target.bearing_deg : null, null],
      ["target.range_m", s.target ? s.target.range_m : null, null],
      ["target.ready", s.target ? s.target.ready : false, null],
      ["recommended_rps", s.recommended_rps, null],
      ["recording.active", s.recording ? s.recording.active : false, null],
    ];
    const html = rows.map(([k, v, age]) => {
      const stale = age != null && age > STALE_MS;
      const ageStr = age == null ? "—"
                   : age < 1000 ? `${age}ms`
                   : `${(age/1000).toFixed(1)}s`;
      const vStr = v == null ? "—"
                 : typeof v === "number" ? Number(v).toFixed(3).replace(/\.?0+$/, "")
                 : String(v);
      return `<tr class="${stale ? "stale" : ""}">
        <td class="k">${k}</td>
        <td class="v">${escapeHtml(vStr)}</td>
        <td class="age ${stale ? "stale" : ""}">${ageStr}</td>
      </tr>`;
    }).join("");
    tbody.innerHTML = html;
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ============================================================
// Calibration table view
// ============================================================

class CalibrationView {
  constructor() {
    this.body = $("cal-body");
    this.lastTagRangeFt = NaN;
    this.lastDialFt = NaN;

    $("cal-add-btn").addEventListener("click", () => {
      const d = parseFloat($("cal-add-dist").value);
      const r = parseFloat($("cal-add-rps").value);
      if (!Number.isFinite(d) || !Number.isFinite(r) || d < 0 || r < 0) {
        $("cal-add-dist").focus();
        return;
      }
      this._add(d, r);
      $("cal-add-dist").value = "";
      $("cal-add-rps").value = "";
    });

    $("cal-snapshot-btn").addEventListener("click", () => {
      // Prefer the live tag-PnP range; fall back to the dial (operator
      // measured the distance themselves and dialed it in).
      const distFt = Number.isFinite(this.lastTagRangeFt) && this.lastTagRangeFt > 0
        ? this.lastTagRangeFt
        : this.lastDialFt;
      // 10 rps/ft is the rio's _SHOOTER_RPS_PER_FOOT default. Operator
      // can edit the row inline before saving — better than blank.
      const rps = Number.isFinite(this.lastDialFt) ? this.lastDialFt * 10.0 : 0;
      if (!Number.isFinite(distFt) || distFt <= 0) return;
      this._add(distFt, rps);
    });

    this._load();
  }

  noteState(s) {
    const t = s.target || {};
    if (t.detected && Number.isFinite(t.range_m) && t.range_m > 0) {
      this.lastTagRangeFt = t.range_m / 0.3048;
    } else {
      this.lastTagRangeFt = NaN;
    }
    if (Number.isFinite(s.dial_ft)) this.lastDialFt = s.dial_ft;
  }

  async _load() {
    try {
      const r = await fetch("/api/calibration");
      const j = await r.json();
      this._render(j.points || []);
    } catch (e) { console.error(e); }
  }

  async _add(d, r) {
    try {
      const resp = await fetch("/api/calibration/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ distance_ft: d, rps: r }),
      });
      const j = await resp.json();
      this._render(j.points || []);
    } catch (e) { console.error(e); }
  }

  async _remove(d) {
    try {
      const resp = await fetch("/api/calibration/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ distance_ft: d }),
      });
      const j = await resp.json();
      this._render(j.points || []);
    } catch (e) { console.error(e); }
  }

  _render(points) {
    this.body.innerHTML = "";
    for (const p of points) {
      const tr = document.createElement("tr");
      const td1 = document.createElement("td");
      td1.textContent = p.distance_ft.toFixed(2);
      const td2 = document.createElement("td");
      td2.textContent = p.rps.toFixed(1);
      const td3 = document.createElement("td");
      td3.style.textAlign = "right";
      const del = document.createElement("button");
      del.textContent = "remove";
      del.className = "row-del";
      del.addEventListener("click", () => this._remove(p.distance_ft));
      td3.appendChild(del);
      tr.append(td1, td2, td3);
      this.body.appendChild(tr);
    }
  }
}

// ============================================================
// Debug-console log tail (SSE on /api/logs)
// ============================================================

class LogConsole {
  constructor() {
    this.el = $("debug-log");
    this.maxLines = 400;
    this.start();
  }

  start() {
    if (this._es) try { this._es.close(); } catch (_) {}
    this._es = new EventSource("/api/logs");
    this._es.onmessage = (ev) => {
      try {
        const entry = JSON.parse(ev.data);
        this.append(entry);
      } catch (_) {}
    };
    this._es.onerror = () => {
      try { this._es.close(); } catch (_) {}
      setTimeout(() => this.start(), 1500);
    };
  }

  append(entry) {
    const div = document.createElement("div");
    div.className = `log-line lvl-${entry.level || "INFO"}`;
    const ts = new Date((entry.ts || 0) * 1000)
      .toTimeString().slice(0, 8);
    const tsSpan = document.createElement("span");
    tsSpan.className = "ts";
    tsSpan.textContent = ts;
    div.appendChild(tsSpan);
    div.appendChild(document.createTextNode(entry.msg || ""));
    this.el.appendChild(div);
    while (this.el.childNodes.length > this.maxLines) {
      this.el.removeChild(this.el.firstChild);
    }
    // Auto-scroll only if user is already at the bottom.
    if (this.el.scrollHeight - this.el.scrollTop - this.el.clientHeight < 40) {
      this.el.scrollTop = this.el.scrollHeight;
    }
  }
}

// ============================================================
// State SSE (one connection, all consumers fan out from here)
// ============================================================

class StateFeed {
  constructor(consumers) {
    this.consumers = consumers;
    this.start();
  }

  start() {
    if (this._es) try { this._es.close(); } catch (_) {}
    this._es = new EventSource("/api/state");
    this._es.onmessage = (ev) => {
      let s;
      try { s = JSON.parse(ev.data); } catch (e) { return; }
      // Update the rio pill *before* handing state to consumers. If a
      // downstream consumer throws (stale DOM, missing element, bad
      // value), the rio pill still reflects truth. This is the single
      // most-asked question on the dashboard — protect it accordingly.
      try { applyRioStatus(s); } catch (e) { console.error("rio pill", e); }
      for (const c of this.consumers) {
        try { c(s); } catch (e) { console.error(e); }
      }
    };
    this._es.onerror = () => {
      try { this._es.close(); } catch (_) {}
      // Don't touch the rio pill on SSE drop — we don't actually know
      // the rio state, and showing "rio disconnected" when the rio is
      // actually fine misleads the operator. The next reconnect's first
      // SSE event will refresh it within ~1s.
      setTimeout(() => this.start(), 1000);
    };
  }
}

// Standalone rio-pill updater — used by the SSE handler and the one-shot
// healthz fetch on page load, so the pill reflects truth even before
// EventSource has opened.
function applyRioStatus(s) {
  const rs = document.getElementById("rio-status");
  if (!rs) return;
  const connected = !!(s && (s.connected || s.nt_connected));
  const host = (s && (s.nt_host || null));
  rs.classList.toggle("connected", connected);
  rs.classList.toggle("disconnected", !connected);
  const txt = rs.querySelector(".rio-text");
  if (!txt) return;
  if (connected) {
    txt.textContent = host ? `rio link up · ${host}` : "rio link up";
  } else {
    txt.textContent = host
      ? `rio disconnected · trying ${host}`
      : "rio disconnected";
  }
}

// ============================================================
// Debug-tab switching
// ============================================================

function wireDebugTabs() {
  $$(".debug-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const which = btn.dataset.tab;
      $$(".debug-tab").forEach((b) => b.classList.toggle("active", b === btn));
      $$(".debug-pane").forEach((p) => {
        p.classList.toggle("active", p.dataset.pane === which);
      });
    });
  });
}

// ============================================================
// Stream FPS estimator
// ============================================================

function wireStreamFps() {
  const stream = $("stream");
  const target = $("s-stream-fps");
  if (!stream || !target) return;
  const window_ = [];
  stream.addEventListener("load", () => {
    const t = performance.now();
    window_.push(t);
    while (window_.length > 30) window_.shift();
    if (window_.length > 1) {
      const dt = (window_[window_.length - 1] - window_[0]) / 1000;
      const fps = (window_.length - 1) / dt;
      target.textContent = fps.toFixed(1);
    }
  });
}

// ============================================================
// Bootstrap
// ============================================================

window.addEventListener("DOMContentLoaded", () => {
  new WindowManager($("workspace"));
  wireDebugTabs();
  wireStreamFps();

  // One-shot rio status fetch — populates the pill before the SSE has
  // even opened. If the SSE-driven UI bootstrap throws somewhere, the
  // rio pill at least starts at the *truth* instead of the static
  // "connecting…" baked into the HTML.
  fetch("/api/healthz")
    .then(r => r.json())
    .then(applyRioStatus)
    .catch((e) => console.error("healthz fetch", e));

  const camera = new CameraPanel();
  const stateView = new StateView(camera);
  const calView = new CalibrationView();
  new LogConsole();

  new StateFeed([
    (s) => stateView.apply(s),
    (s) => calView.noteState(s),
  ]);
});
