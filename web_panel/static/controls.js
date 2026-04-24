// ========== TABS ==========

document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
        tab.classList.add("active");
        const target = document.getElementById("tab-" + tab.dataset.tab);
        if (target) target.classList.add("active");
        if (tab.dataset.tab === "bindings") renderBindings();
    });
});

// ========== GLOBALS ==========

let slowMode = false;
const activeKeys = new Set();
let driveX = 0, driveY = 0, rotation = 0;
const DEADZONE = 0.12;
let cmdCounter = 1;

function sendCommand(subsystem, command, value = 1.0) {
    const sendValue = (value === 0) ? 0 : cmdCounter++;
    fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subsystem, command, value: sendValue }),
    });
}

let lastDriveSend = 0;
const DRIVE_INTERVAL = 50;
function sendDrive(force) {
    const now = Date.now();
    const isZero = driveX === 0 && driveY === 0 && rotation === 0;
    if (!force && !isZero && now - lastDriveSend < DRIVE_INTERVAL) return;
    lastDriveSend = now;
    fetch("/api/drive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ vx: driveY, vy: driveX, omega: rotation }),
    });
}

function applyDeadzone(val) {
    return Math.abs(val) < DEADZONE ? 0 : val;
}

// ========== STATUS ==========

function pollStatus() {
    fetch("/api/status")
        .then(r => r.json())
        .then(data => {
            const dot = document.getElementById("status-dot");
            const label = document.getElementById("status-label");
            if (data.connected) {
                dot.classList.add("on");
                label.classList.add("on");
                label.textContent = "Connected";
            } else {
                dot.classList.remove("on");
                label.classList.remove("on");
                label.textContent = "Disconnected";
            }
            const pos = data.elevator?.position || 0;
            const car = document.getElementById("elevator-car");
            if (car) car.style.bottom = Math.min(pos / 110, 1) * 100 + "%";

            const mode = data.mode || "disabled";
            ["disabled", "auto", "teleop", "test"].forEach(m => {
                const el = document.getElementById("mode-" + m);
                if (el) el.classList.toggle("active", m === mode);
            });

            const timer = document.getElementById("mode-timer");
            if (timer) {
                const t = data.match_time;
                if (t >= 0) {
                    const mins = Math.floor(t / 60);
                    const secs = Math.floor(t % 60);
                    timer.textContent = mins + ":" + (secs < 10 ? "0" : "") + secs;
                } else {
                    timer.textContent = "";
                }
            }

            // Debug info panel
            const diNt = document.getElementById("di-nt");
            const diIp = document.getElementById("di-ip");
            const diMode = document.getElementById("di-mode");
            const diTime = document.getElementById("di-time");
            const diElev = document.getElementById("di-elev");
            const diShooter = document.getElementById("di-shooter");
            if (diNt) diNt.textContent = data.connected ? "Connected" : "Disconnected";
            if (diMode) diMode.textContent = mode.toUpperCase();
            if (diTime) diTime.textContent = data.match_time >= 0 ? data.match_time.toFixed(1) + "s" : "--";
            if (diElev) diElev.textContent = (data.elevator?.position || 0).toFixed(1);
            if (diShooter) diShooter.textContent = (data.shooter?.velocity || 0).toFixed(1) + " rps";
        })
        .catch(() => {});
}

setInterval(pollStatus, 500);

// ========== MODE SWITCHING ==========

function setRobotMode(mode) {
    fetch("/api/set_mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
    });
    ["disabled", "auto", "teleop", "test"].forEach(m => {
        const el = document.getElementById("mode-" + m);
        if (el) el.classList.toggle("active", m === mode);
    });
}

// ========== CUSTOMIZABLE BINDINGS ==========

const GAMEPAD_BUTTON_NAMES = {
    0: "A", 1: "B", 2: "X", 3: "Y",
    4: "LB", 5: "RB", 6: "LT", 7: "RT",
    8: "Back", 9: "Start", 10: "L3", 11: "R3",
    12: "D-Up", 13: "D-Down", 14: "D-Left", 15: "D-Right",
};

const DEFAULT_BINDINGS = {
    "Intake":          { btn: 0, press: ["feeder", "intake"],    release: ["feeder", "stop"] },
    "Fire":            { btn: 1, press: ["shooter", "fire"],     release: ["shooter", "cease_fire"] },
    "Launch":          { btn: 2, press: ["shooter", "launch"],   release: ["shooter", "cease_fire"] },
    "Clear":           { btn: 3, press: ["shooter", "clear"],    release: ["shooter", "cease_fire"] },
    "Hood Down":       { btn: 4, press: ["hood", "down"],        release: ["hood", "stop"] },
    "Hood Up":         { btn: 5, press: ["hood", "up"],          release: ["hood", "stop"] },
    "Elevator Down":   { btn: 6, press: ["elevator", "down"],    release: ["elevator", "stop"] },
    "Elevator Up":     { btn: 7, press: ["elevator", "up"],      release: ["elevator", "stop"] },
    "Slow Mode":       { btn: 8, press: "toggle_slow", release: null },
    "E-Stop":          { btn: 9, press: "estop", release: null },
    "Brake":           { btn: 10, press: ["drivetrain", "brake"], release: null },
    "Reset Heading":   { btn: 11, press: ["drivetrain", "reset_heading"], release: null },
    "Elevator Preset+":{ btn: 12, press: "preset_up", release: null },
    "Elevator Preset-":{ btn: 13, press: "preset_down", release: null },
};

function loadBindings() {
    try {
        const saved = localStorage.getItem("cf1279_bindings");
        if (saved) {
            const parsed = JSON.parse(saved);
            for (const [name, data] of Object.entries(parsed)) {
                if (DEFAULT_BINDINGS[name]) {
                    DEFAULT_BINDINGS[name].btn = data.btn;
                }
            }
        }
    } catch (e) {}
}

function saveBindings() {
    const toSave = {};
    for (const [name, data] of Object.entries(DEFAULT_BINDINGS)) {
        toSave[name] = { btn: data.btn };
    }
    localStorage.setItem("cf1279_bindings", JSON.stringify(toSave));
}

function getBindingForButton(btnIdx) {
    for (const [name, data] of Object.entries(DEFAULT_BINDINGS)) {
        if (data.btn === btnIdx) return { name, ...data };
    }
    return null;
}

let listeningBinding = null;

function renderBindings() {
    const list = document.getElementById("bindings-list");
    if (!list) return;
    list.innerHTML = "";
    for (const [name, data] of Object.entries(DEFAULT_BINDINGS)) {
        const row = document.createElement("div");
        row.className = "binding-row";
        const action = document.createElement("span");
        action.className = "binding-action";
        action.textContent = name;
        const key = document.createElement("span");
        key.className = "binding-key";
        key.textContent = GAMEPAD_BUTTON_NAMES[data.btn] || "Button " + data.btn;
        key.dataset.action = name;
        key.addEventListener("click", () => startListening(name, key));
        row.appendChild(action);
        row.appendChild(key);
        list.appendChild(row);
    }
}

function startListening(actionName, keyEl) {
    if (listeningBinding) {
        const prev = document.querySelector(".binding-key.listening");
        if (prev) prev.classList.remove("listening");
    }
    listeningBinding = actionName;
    keyEl.classList.add("listening");
    keyEl.textContent = "Press a button...";
}

function handleBindingCapture(btnIdx) {
    if (!listeningBinding) return false;
    DEFAULT_BINDINGS[listeningBinding].btn = btnIdx;
    listeningBinding = null;
    saveBindings();
    renderBindings();
    return true;
}

loadBindings();

// ========== JOYSTICK CLASS ==========

class Joystick {
    constructor(wrapperId, knobId, onMove) {
        this.wrapper = document.getElementById(wrapperId);
        this.knob = document.getElementById(knobId);
        this.onMove = onMove;
        this.active = false;

        this.wrapper.addEventListener("mousedown", e => this.start(e));
        this.wrapper.addEventListener("touchstart", e => this.start(e), { passive: false });
        document.addEventListener("mousemove", e => this.move(e));
        document.addEventListener("touchmove", e => this.move(e), { passive: false });
        document.addEventListener("mouseup", () => this.end());
        document.addEventListener("touchend", () => this.end());
    }

    start(e) {
        e.preventDefault();
        this.active = true;
        this.rect = this.wrapper.getBoundingClientRect();
        this.cx = this.rect.left + this.rect.width / 2;
        this.cy = this.rect.top + this.rect.height / 2;
        this.r = this.rect.width / 2 - 20;
        this.knob.classList.add("active");
        this.move(e);
    }

    move(e) {
        if (!this.active) return;
        e.preventDefault();
        const p = e.touches ? e.touches[0] : e;
        let dx = p.clientX - this.cx;
        let dy = p.clientY - this.cy;
        const d = Math.sqrt(dx * dx + dy * dy);
        if (d > this.r) { dx = dx / d * this.r; dy = dy / d * this.r; }
        this.knob.style.left = (this.rect.width / 2 + dx) + "px";
        this.knob.style.top = (this.rect.height / 2 + dy) + "px";
        this.onMove(dx / this.r, -dy / this.r);
    }

    end() {
        if (!this.active) return;
        this.active = false;
        this.knob.classList.remove("active");
        this.knob.style.left = "50%";
        this.knob.style.top = "50%";
        this.onMove(0, 0);
    }

    setVisual(nx, ny) {
        if (this.active) return;
        const rect = this.wrapper.getBoundingClientRect();
        const r = rect.width / 2 - 20;
        this.knob.style.left = (rect.width / 2 + nx * r) + "px";
        this.knob.style.top = (rect.height / 2 - ny * r) + "px";
    }
}

const driveJoy = new Joystick("drive-joystick", "drive-knob", (x, y) => {
    if (gamepadActive) return;
    driveX = +x.toFixed(2);
    driveY = +y.toFixed(2);
    document.getElementById("joy-x").textContent = driveX.toFixed(2);
    document.getElementById("joy-y").textContent = driveY.toFixed(2);
    sendDrive();
});

const rotJoy = new Joystick("rot-joystick", "rot-knob", (x, _y) => {
    if (gamepadActive) return;
    rotation = +x.toFixed(2);
    document.getElementById("rot-value").textContent = rotation.toFixed(2);
    sendDrive();
});

// ========== HOLD / CLICK BUTTONS ==========

function holdBtn(id, sub, start, stop) {
    const btn = document.getElementById(id);
    if (!btn) return;
    const on = e => { e.preventDefault(); btn.classList.add("pressed"); sendCommand(sub, start); };
    const off = e => { e.preventDefault(); btn.classList.remove("pressed"); sendCommand(sub, stop); };
    btn.addEventListener("mousedown", on);
    btn.addEventListener("touchstart", on, { passive: false });
    btn.addEventListener("mouseup", off);
    btn.addEventListener("mouseleave", off);
    btn.addEventListener("touchend", off, { passive: false });
    btn.addEventListener("touchcancel", off, { passive: false });
}

function clickBtn(id, fn) {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.addEventListener("click", fn);
}

holdBtn("btn-fire", "shooter", "fire", "cease_fire");
holdBtn("btn-launch", "shooter", "launch", "cease_fire");
holdBtn("btn-clear-jam", "shooter", "clear", "cease_fire");
holdBtn("btn-conveyor-fwd", "shooter", "conveyor_fwd", "stop_conveyor");
holdBtn("btn-conveyor-rev", "shooter", "conveyor_rev", "stop_conveyor");
holdBtn("btn-intake", "feeder", "intake", "stop");
holdBtn("btn-eject", "feeder", "eject", "stop");
holdBtn("btn-hood-up", "hood", "up", "stop");
holdBtn("btn-hood-down", "hood", "down", "stop");
holdBtn("btn-elev-up", "elevator", "up", "stop");
holdBtn("btn-elev-down", "elevator", "down", "stop");

clickBtn("btn-slow", () => {
    slowMode = !slowMode;
    document.getElementById("btn-slow").classList.toggle("active", slowMode);
    sendCommand("drivetrain", "slow_mode", slowMode ? 1 : 0);
});

clickBtn("btn-brake", () => {
    sendCommand("drivetrain", "brake", 1);
    const b = document.getElementById("btn-brake");
    b.classList.add("active");
    setTimeout(() => b.classList.remove("active"), 300);
});

clickBtn("btn-reset-heading", () => {
    sendCommand("drivetrain", "reset_heading", 1);
    const b = document.getElementById("btn-reset-heading");
    b.classList.add("active");
    setTimeout(() => b.classList.remove("active"), 300);
});

document.querySelectorAll(".btn-preset").forEach(btn => {
    btn.addEventListener("click", () => {
        const p = parseFloat(btn.dataset.preset);
        sendCommand("elevator", "preset", p);
        document.querySelectorAll(".btn-preset").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const car = document.getElementById("elevator-car");
        if (car) car.style.bottom = Math.min(p / 110 * 100, 100) + "%";
    });
});

function estop() {
    sendCommand("shooter", "cease_fire");
    sendCommand("feeder", "stop");
    sendCommand("hood", "stop");
    sendCommand("elevator", "stop");
    sendCommand("drivetrain", "brake");
    driveX = 0; driveY = 0; rotation = 0;
    sendDrive();
}

clickBtn("btn-estop", estop);

clickBtn("btn-reset-bindings", () => {
    const RESET = {
        "Intake": 0, "Fire": 1, "Launch": 2, "Clear": 3,
        "Hood Down": 4, "Hood Up": 5, "Elevator Down": 6, "Elevator Up": 7,
        "Slow Mode": 8, "E-Stop": 9, "Brake": 10, "Reset Heading": 11,
        "Elevator Preset+": 12, "Elevator Preset-": 13,
    };
    for (const [name, btn] of Object.entries(RESET)) {
        if (DEFAULT_BINDINGS[name]) DEFAULT_BINDINGS[name].btn = btn;
    }
    saveBindings();
    renderBindings();
});

// ========== KEYBOARD ==========

const keyMap = {
    w: () => { driveY = 1; sendDrive(); },
    s: () => { driveY = -1; sendDrive(); },
    a: () => { driveX = -1; sendDrive(); },
    d: () => { driveX = 1; sendDrive(); },
    q: () => { rotation = -0.7; sendDrive(); },
    e: () => { rotation = 0.7; sendDrive(); },
    f: () => sendCommand("shooter", "fire"),
    g: () => sendCommand("shooter", "launch"),
    r: () => sendCommand("feeder", "intake"),
    x: () => sendCommand("feeder", "eject"),
    h: () => sendCommand("drivetrain", "reset_heading"),
    t: () => sendCommand("hood", "up"),
    y: () => sendCommand("hood", "down"),
    ArrowUp: () => sendCommand("elevator", "up"),
    ArrowDown: () => sendCommand("elevator", "down"),
    b: () => sendCommand("drivetrain", "brake"),
    " ": estop,
};

const keyStop = {
    w: () => { driveY = 0; sendDrive(); },
    s: () => { driveY = 0; sendDrive(); },
    a: () => { driveX = 0; sendDrive(); },
    d: () => { driveX = 0; sendDrive(); },
    q: () => { rotation = 0; sendDrive(); },
    e: () => { rotation = 0; sendDrive(); },
    f: () => sendCommand("shooter", "cease_fire"),
    g: () => sendCommand("shooter", "cease_fire"),
    r: () => sendCommand("feeder", "stop"),
    x: () => sendCommand("feeder", "stop"),
    t: () => sendCommand("hood", "stop"),
    y: () => sendCommand("hood", "stop"),
    ArrowUp: () => sendCommand("elevator", "stop"),
    ArrowDown: () => sendCommand("elevator", "stop"),
};

document.addEventListener("keydown", e => {
    // Don't capture keys when typing in search/input fields
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (activeKeys.has(e.key)) return;
    activeKeys.add(e.key);
    if (keyMap[e.key]) { e.preventDefault(); keyMap[e.key](); }
});

document.addEventListener("keyup", e => {
    activeKeys.delete(e.key);
    if (keyStop[e.key]) { e.preventDefault(); keyStop[e.key](); }
});

// ========== USB GAMEPAD ==========

let gamepadActive = false;
let gamepadIndex = null;
const gpBtnState = {};
const presets = [0, 19, 58, 86, 110];
let currentPresetIdx = 0;

window.addEventListener("gamepadconnected", e => {
    gamepadIndex = e.gamepad.index;
    gamepadActive = true;
    document.getElementById("gamepad-dot").classList.add("on");
    const lbl = document.getElementById("gamepad-label");
    lbl.classList.add("on");
    lbl.textContent = e.gamepad.id.substring(0, 30);
    document.getElementById("gamepad-info").style.display = "none";
    document.getElementById("gamepad-map").style.display = "grid";
});

window.addEventListener("gamepaddisconnected", e => {
    if (e.gamepad.index === gamepadIndex) {
        gamepadActive = false;
        gamepadIndex = null;
        document.getElementById("gamepad-dot").classList.remove("on");
        const lbl = document.getElementById("gamepad-label");
        lbl.classList.remove("on");
        lbl.textContent = "No Gamepad";
        document.getElementById("gamepad-info").style.display = "block";
        document.getElementById("gamepad-map").style.display = "none";
    }
});

function gpPressed(idx, pressed) {
    const was = gpBtnState[idx] || false;
    gpBtnState[idx] = pressed;
    return pressed && !was;
}

function gpReleased(idx, pressed) {
    const was = gpBtnState[idx] || false;
    gpBtnState[idx] = pressed;
    return !pressed && was;
}

function pollGamepad() {
    if (!gamepadActive || gamepadIndex === null) {
        requestAnimationFrame(pollGamepad);
        return;
    }

    const gp = navigator.getGamepads()[gamepadIndex];
    if (!gp) { requestAnimationFrame(pollGamepad); return; }

    const lx = applyDeadzone(gp.axes[0] || 0);
    const ly = applyDeadzone(-(gp.axes[1] || 0));
    const rx = applyDeadzone(gp.axes[2] || 0);

    driveX = +lx.toFixed(2);
    driveY = +ly.toFixed(2);
    rotation = +rx.toFixed(2);
    sendDrive();

    document.getElementById("joy-x").textContent = driveX.toFixed(2);
    document.getElementById("joy-y").textContent = driveY.toFixed(2);
    document.getElementById("rot-value").textContent = rotation.toFixed(2);

    driveJoy.setVisual(lx, ly);
    rotJoy.setVisual(rx, 0);

    // Check if we're capturing a binding
    if (listeningBinding) {
        for (let i = 0; i < gp.buttons.length; i++) {
            if (gp.buttons[i]?.pressed) {
                handleBindingCapture(i);
                break;
            }
        }
        requestAnimationFrame(pollGamepad);
        return;
    }

    // Process all bindings dynamically
    for (const [name, binding] of Object.entries(DEFAULT_BINDINGS)) {
        const idx = binding.btn;
        const pressed = gp.buttons[idx]?.pressed || false;

        if (gpPressed(idx, pressed)) {
            if (binding.press === "toggle_slow") {
                slowMode = !slowMode;
                document.getElementById("btn-slow")?.classList.toggle("active", slowMode);
                sendCommand("drivetrain", "slow_mode", slowMode ? 1 : 0);
            } else if (binding.press === "estop") {
                estop();
            } else if (binding.press === "preset_up") {
                if (currentPresetIdx < presets.length - 1) currentPresetIdx++;
                sendCommand("elevator", "preset", presets[currentPresetIdx]);
                updatePresetUI(presets[currentPresetIdx]);
            } else if (binding.press === "preset_down") {
                if (currentPresetIdx > 0) currentPresetIdx--;
                sendCommand("elevator", "preset", presets[currentPresetIdx]);
                updatePresetUI(presets[currentPresetIdx]);
            } else if (Array.isArray(binding.press)) {
                sendCommand(binding.press[0], binding.press[1]);
            }
        }
        if (binding.release && gpReleased(idx, pressed)) {
            if (Array.isArray(binding.release)) {
                sendCommand(binding.release[0], binding.release[1]);
            }
        }
    }

    requestAnimationFrame(pollGamepad);
}

function updatePresetUI(val) {
    document.querySelectorAll(".btn-preset").forEach(b => {
        b.classList.toggle("active", parseFloat(b.dataset.preset) === val);
    });
    const car = document.getElementById("elevator-car");
    if (car) car.style.bottom = Math.min(val / 110 * 100, 100) + "%";
}

requestAnimationFrame(pollGamepad);
renderBindings();

// ========== TOOLS TAB: NETWORK CHECK ==========

clickBtn("btn-net-check", () => {
    const el = document.getElementById("net-status");
    el.textContent = "Checking...";
    el.className = "net-status";
    fetch("/api/network_check")
        .then(r => r.json())
        .then(data => {
            if (data.reachable) {
                el.textContent = "Robot reachable at " + data.robot_ip +
                    (data.nt_connected ? " (NT connected)" : " (NT not connected yet)");
                el.className = "net-status net-ok";
            } else {
                el.textContent = "Cannot reach robot at " + data.robot_ip +
                    ". Make sure you are on the robot's WiFi network.";
                el.className = "net-status net-fail";
            }
        })
        .catch(() => {
            el.textContent = "Check failed — server error.";
            el.className = "net-status net-fail";
        });
});

// ========== TOOLS TAB: VISUAL TASK RUNNER ==========

// Step detection patterns for each task type
const stepPatterns = {
    setup: [
        { step: "python",   match: ["--- Python ---"], progress: 10 },
        { step: "packages", match: ["--- Required Packages ---"], progress: 30 },
        { step: "files",    match: ["--- Project Files ---"], progress: 50 },
        { step: "tests",    match: ["--- Running Tests ---"], progress: 70 },
        { step: "download", match: ["--- Robot Deploy Packages ---"], progress: 85 },
    ],
    test: [
        { step: "collect",  match: ["collecting", "collected"], progress: 15 },
        { step: "running",  match: ["PASSED", "FAILED", "tests/"], progress: 50 },
        { step: "results",  match: ["passed", "failed", "error"], progress: 90 },
    ],
    deploy: [
        { step: "network",  match: ["Robot reachable", "Check network", "PASS"], progress: 10 },
        { step: "connect",  match: ["ssh", "paramiko", "connecting", "Team number", "Connect to roboRIO", "Deploying to team"], progress: 25 },
        { step: "install",  match: ["Installing", "pip_cache", "Downloading", "Collecting", "Install packages"], progress: 50 },
        { step: "upload",   match: ["->", "make /home", "sftp", "Upload code"], progress: 75 },
        { step: "start",    match: ["Starting robot", "SUCCESS", "Deploy was", "SUCCESS!"], progress: 95 },
    ],
};

function setStep(task, stepName, status) {
    const stepEl = document.querySelector(`#${task}-steps .step-item[data-step="${stepName}"]`);
    if (!stepEl) return;
    stepEl.classList.remove("step-active", "step-pass", "step-fail");
    if (status === "active") {
        stepEl.classList.add("step-active");
        stepEl.querySelector(".step-icon").innerHTML = "";
    } else if (status === "pass") {
        stepEl.classList.add("step-pass");
        stepEl.querySelector(".step-icon").innerHTML = "&#9745;";
    } else if (status === "fail") {
        stepEl.classList.add("step-fail");
        stepEl.querySelector(".step-icon").innerHTML = "&#9746;";
    } else {
        stepEl.querySelector(".step-icon").innerHTML = "&#9744;";
    }
}

function setProgress(task, pct, label) {
    const fill = document.getElementById(task + "-progress-fill");
    const lbl = document.getElementById(task + "-progress-label");
    if (fill) {
        fill.classList.remove("indeterminate", "done-ok", "done-fail");
        fill.style.width = pct + "%";
    }
    if (lbl) lbl.innerHTML = '<span class="spinner"></span> ' + label;
}

function finishTask(task, success) {
    const fill = document.getElementById(task + "-progress-fill");
    const lbl = document.getElementById(task + "-progress-label");
    const panel = document.getElementById("panel-" + task);

    if (fill) {
        fill.classList.remove("indeterminate");
        fill.style.width = "100%";
        fill.classList.add(success ? "done-ok" : "done-fail");
    }
    if (lbl) {
        lbl.innerHTML = success ? "Done" : "Failed";
    }
    if (panel) {
        panel.classList.remove("task-running");
        panel.classList.add(success ? "task-done-ok" : "task-done-fail");
    }
}

// Track which steps have been activated per task
const activatedSteps = {};

function parseOutputForSteps(task, allText) {
    const patterns = stepPatterns[task];
    if (!patterns) return;
    if (!activatedSteps[task]) activatedSteps[task] = new Set();

    let latestIdx = -1;
    const lower = allText.toLowerCase();

    for (let i = 0; i < patterns.length; i++) {
        const p = patterns[i];
        const found = p.match.some(m => lower.includes(m.toLowerCase()));
        if (found && !activatedSteps[task].has(p.step)) {
            activatedSteps[task].add(p.step);
        }
        if (found) latestIdx = i;
    }

    // Update step visuals
    for (let i = 0; i < patterns.length; i++) {
        const p = patterns[i];
        if (i < latestIdx) {
            // Check if this step had a FAIL
            const hasFail = allText.includes("FAIL") && i === latestIdx - 1;
            setStep(task, p.step, "pass");
        } else if (i === latestIdx) {
            setStep(task, p.step, "active");
            setProgress(task, p.progress, p.step.charAt(0).toUpperCase() + p.step.slice(1) + "...");
        }
    }
}

function runTask(task, outputId, btnId) {
    const output = document.getElementById(outputId);
    const btn = document.getElementById(btnId);
    const panel = document.getElementById("panel-" + task);
    const progressWrap = document.getElementById(task + "-progress-wrap");
    const steps = document.getElementById(task + "-steps");
    const termDetails = document.getElementById(task + "-terminal-details");
    const fill = document.getElementById(task + "-progress-fill");

    // Reset state
    output.textContent = "";
    output.classList.remove("task-success", "task-fail");
    if (panel) {
        panel.classList.remove("task-done-ok", "task-done-fail");
        panel.classList.add("task-running");
    }
    if (progressWrap) progressWrap.style.display = "block";
    if (steps) {
        steps.style.display = "flex";
        steps.querySelectorAll(".step-item").forEach(el => {
            el.classList.remove("step-active", "step-pass", "step-fail");
            el.querySelector(".step-icon").innerHTML = "&#9744;";
        });
    }
    if (termDetails) termDetails.style.display = "block";
    if (fill) {
        fill.className = "progress-fill indeterminate";
        fill.style.width = "30%";
    }
    activatedSteps[task] = new Set();

    setProgress(task, 0, "Starting...");
    btn.disabled = true;
    btn.textContent = "RUNNING...";

    fetch("/api/run_task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task }),
    }).then(r => r.json()).then(data => {
        if (data.error) {
            output.textContent += "ERROR: " + data.error + "\n";
            btn.disabled = false;
            btn.textContent = btn.dataset.label;
            finishTask(task, false);
            return;
        }
        pollTaskOutput(task, outputId, btnId, 0);
    }).catch(err => {
        output.textContent += "Failed to start: " + err + "\n";
        btn.disabled = false;
        btn.textContent = btn.dataset.label;
        finishTask(task, false);
    });
}

function pollTaskOutput(task, outputId, btnId, since) {
    fetch("/api/task_output?task=" + task + "&since=" + since)
        .then(r => r.json())
        .then(data => {
            const output = document.getElementById(outputId);
            if (data.lines.length > 0) {
                output.textContent += data.lines.join("\n") + "\n";
                output.scrollTop = output.scrollHeight;
                // Parse for step progress
                parseOutputForSteps(task, output.textContent);
            }
            if (data.running) {
                setTimeout(() => pollTaskOutput(task, outputId, btnId, data.total), 400);
            } else {
                const btn = document.getElementById(btnId);
                btn.disabled = false;
                btn.textContent = btn.dataset.label;

                const text = output.textContent;
                let success = text.includes("exit code 0");
                if (task === "deploy") {
                    success = text.includes("SUCCESS") && text.includes("exit code 0");
                } else if (task === "test") {
                    success = text.includes("passed") && !text.match(/\d+ failed/);
                }

                // Mark steps based on actual output
                const patterns = stepPatterns[task] || [];
                for (const p of patterns) {
                    if (activatedSteps[task]?.has(p.step)) {
                        if (p === patterns[patterns.length - 1] && !success) {
                            setStep(task, p.step, "fail");
                        } else {
                            setStep(task, p.step, "pass");
                        }
                    }
                }

                output.classList.add(success ? "task-success" : "task-fail");
                finishTask(task, success);
            }
        })
        .catch(() => {
            setTimeout(() => pollTaskOutput(task, outputId, btnId, since), 1000);
        });
}

// Store original labels
document.querySelectorAll("#btn-run-setup, #btn-run-tests, #btn-run-deploy").forEach(btn => {
    btn.dataset.label = btn.textContent;
});

clickBtn("btn-run-setup", () => runTask("setup", "setup-output", "btn-run-setup"));
clickBtn("btn-run-tests", () => runTask("test", "test-output", "btn-run-tests"));
clickBtn("btn-run-deploy", () => {
    const output = document.getElementById("deploy-output");
    const panel = document.getElementById("panel-deploy");
    const progressWrap = document.getElementById("deploy-progress-wrap");
    const steps = document.getElementById("deploy-steps");
    const termDetails = document.getElementById("deploy-terminal-details");

    // Show progress UI immediately for network check
    if (progressWrap) progressWrap.style.display = "block";
    if (steps) steps.style.display = "flex";
    if (termDetails) termDetails.style.display = "block";
    output.textContent = "";
    output.classList.remove("task-success", "task-fail");
    if (panel) {
        panel.classList.remove("task-done-ok", "task-done-fail");
        panel.classList.add("task-running");
    }

    setStep("deploy", "network", "active");
    setProgress("deploy", 5, "Checking network...");

    fetch("/api/network_check")
        .then(r => r.json())
        .then(data => {
            if (!data.reachable) {
                setStep("deploy", "network", "fail");
                output.textContent = "Cannot reach robot at " + data.robot_ip + "\n" +
                    "Make sure you are connected to the robot's WiFi network.\n\n" +
                    "Deploy aborted.\n";
                output.classList.add("task-fail");
                finishTask("deploy", false);
                return;
            }
            setStep("deploy", "network", "pass");
            output.textContent = "Robot reachable at " + data.robot_ip + "\n\n";
            runTask("deploy", "deploy-output", "btn-run-deploy");
        })
        .catch(() => {
            setStep("deploy", "network", "pass");
            output.textContent = "Network check skipped. Deploying...\n\n";
            runTask("deploy", "deploy-output", "btn-run-deploy");
        });
});

// ========== DEBUG TAB ==========

let debugAutoRefresh = true;

function refreshDebugLog() {
    fetch("/api/debug")
        .then(r => r.json())
        .then(entries => {
            const log = document.getElementById("debug-log");
            const showSend = document.querySelector('.debug-filter[data-dir="SEND"]').checked;
            const showRecv = document.querySelector('.debug-filter[data-dir="RECV"]').checked;
            const search = document.getElementById("debug-search").value.toLowerCase();

            let html = "";
            for (const e of entries) {
                if (e.dir === "SEND" && !showSend) continue;
                if (e.dir === "RECV" && !showRecv) continue;
                if (search && !e.key.toLowerCase().includes(search)) continue;

                const dirClass = e.dir === "SEND" ? "dir-send" : "dir-recv";
                html += `<div class="debug-entry">` +
                    `<span class="de-time">${e.time}.${String(e.ms).padStart(5, "0").slice(0, 3)}</span>` +
                    `<span class="de-dir ${dirClass}">${e.dir}</span>` +
                    `<span class="de-key">${e.key}</span>` +
                    `<span class="de-val">${e.value}</span>` +
                    `</div>`;
            }
            log.innerHTML = html || '<div class="debug-empty">No entries yet. Connect to the robot and send commands.</div>';
            log.scrollTop = log.scrollHeight;
        })
        .catch(() => {});
}

clickBtn("btn-debug-refresh", refreshDebugLog);
clickBtn("btn-debug-clear", () => {
    document.getElementById("debug-log").innerHTML = '<div class="debug-empty">Log cleared.</div>';
});

document.getElementById("debug-auto").addEventListener("change", e => {
    debugAutoRefresh = e.target.checked;
});

document.querySelectorAll(".debug-filter").forEach(cb => {
    cb.addEventListener("change", refreshDebugLog);
});
document.getElementById("debug-search").addEventListener("input", refreshDebugLog);

setInterval(() => {
    if (debugAutoRefresh && document.getElementById("tab-debug").classList.contains("active")) {
        refreshDebugLog();
    }
}, 1000);

fetch("/api/network_check").then(r => r.json()).then(data => {
    const diIp = document.getElementById("di-ip");
    if (diIp) diIp.textContent = data.robot_ip;
}).catch(() => {});
