/* Cold Fusion Sight — modal dialogs.
 *
 * Drop-in replacement for the browser's `alert()` and `confirm()`. Both
 * return a Promise so callers can `await`. The main reasons not to use
 * the natives:
 *   - they block the page (nothing else can update during prompt)
 *   - they're styled by the OS, which clashes with the dashboard look
 *   - they can be muted by the browser if a page fires them too fast
 *   - mobile browsers sometimes mis-render them on small viewports
 *
 * API (global, no ESM):
 *   await cfAlert("message", { title?, ok?, kind? })
 *   const yes = await cfConfirm("are you sure?", { title?, ok?, cancel?, danger? })
 *
 * Keyboard:
 *   Enter  → primary button (OK / Yes)
 *   Esc    → cancel button (or dismiss for alert)
 */

(function () {
  "use strict";

  function ensureMount() {
    let m = document.getElementById("cf-modal-mount");
    if (!m) {
      m = document.createElement("div");
      m.id = "cf-modal-mount";
      document.body.appendChild(m);
    }
    return m;
  }

  function showModal(opts) {
    return new Promise((resolve) => {
      const mount = ensureMount();

      const overlay = document.createElement("div");
      overlay.className = "cf-modal-overlay";

      const box = document.createElement("div");
      box.className = "cf-modal-box";
      if (opts.kind) box.classList.add(`cf-modal-${opts.kind}`);
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");

      if (opts.title) {
        const h = document.createElement("div");
        h.className = "cf-modal-title";
        h.textContent = opts.title;
        box.appendChild(h);
      }

      if (opts.body) {
        const b = document.createElement("div");
        b.className = "cf-modal-body";
        // textContent (not innerHTML) — we never want callers' messages
        // to be parsed as markup. \n turns into a visible newline via
        // white-space: pre-wrap in CSS.
        b.textContent = opts.body;
        box.appendChild(b);
      }

      const row = document.createElement("div");
      row.className = "cf-modal-buttons";

      let resolved = false;
      const finish = (val) => {
        if (resolved) return;
        resolved = true;
        document.removeEventListener("keydown", onKey);
        // Fade-out via class so the close feels intentional, not abrupt.
        overlay.classList.add("cf-modal-leaving");
        setTimeout(() => overlay.remove(), 100);
        resolve(val);
      };

      let primaryBtn = null;
      let cancelBtn = null;
      (opts.buttons || []).forEach((spec) => {
        const btn = document.createElement("button");
        btn.textContent = spec.label;
        btn.className = spec.class || "ghost";
        btn.addEventListener("click", () => finish(spec.value));
        row.appendChild(btn);
        if (spec.primary) primaryBtn = btn;
        if (spec.cancel) cancelBtn = btn;
      });
      box.appendChild(row);

      overlay.appendChild(box);
      mount.appendChild(overlay);

      // Click outside the box = cancel (if there's a cancel button to fire).
      overlay.addEventListener("click", (ev) => {
        if (ev.target === overlay && cancelBtn) cancelBtn.click();
      });

      const onKey = (ev) => {
        if (ev.key === "Escape" && cancelBtn) {
          ev.preventDefault();
          cancelBtn.click();
        } else if (ev.key === "Enter" && primaryBtn) {
          ev.preventDefault();
          primaryBtn.click();
        }
      };
      document.addEventListener("keydown", onKey);

      // Focus the primary button so Enter/Space hit it immediately.
      requestAnimationFrame(() => {
        (primaryBtn || cancelBtn || row.querySelector("button"))?.focus();
      });
    });
  }

  /**
   * cfAlert — block-style modal with a single OK button.
   * Returns Promise<undefined>; await it if you want to chain after dismissal.
   */
  window.cfAlert = function (message, opts) {
    opts = opts || {};
    return showModal({
      title: opts.title || null,
      body: String(message || ""),
      kind: opts.kind || null,
      buttons: [
        {
          label: opts.ok || "OK",
          primary: true,
          cancel: true,
          value: undefined,
          class: opts.kind === "error" ? "danger" : "primary",
        },
      ],
    });
  };

  /**
   * cfConfirm — modal with Cancel / OK buttons. Returns Promise<bool>.
   * Pass `{danger: true}` to style the OK button red (for delete-style
   * confirmations).
   */
  window.cfConfirm = function (message, opts) {
    opts = opts || {};
    return showModal({
      title: opts.title || "Confirm",
      body: String(message || ""),
      buttons: [
        { label: opts.cancel || "Cancel", value: false, cancel: true, class: "ghost" },
        {
          label: opts.ok || "OK",
          primary: true,
          value: true,
          class: opts.danger ? "danger" : "primary",
        },
      ],
    });
  };
})();
