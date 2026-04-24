/* Immaculata Robotics - Team 1279 Cold Fusion
   Robot Simulator - Three.js 3D + Full Ball Physics
   Accurate robot model: swerve drive, dual-wheel feeder intake,
   conveyor, kicker, dual shooter wheels, tilting hood, elevator */

const socket = io();

let state = null;
const activeKeys = new Set();
let kbDrive = { vx: 0, vy: 0, omega: 0 };
let prevButtons = [];

const container = document.getElementById("viewport");
const canvas = document.getElementById("three-canvas");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xe0e4ea);

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputEncoding = THREE.sRGBEncoding;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.2;

const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100);
camera.position.set(0, 12, 10);
camera.lookAt(0, 0, 0);

function resize() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
resize();

// ===== LIGHTING =====
scene.add(new THREE.AmbientLight(0xffffff, 0.55));

const dirLight = new THREE.DirectionalLight(0xffffff, 0.85);
dirLight.position.set(8, 18, 10);
dirLight.castShadow = true;
dirLight.shadow.mapSize.set(2048, 2048);
dirLight.shadow.camera.left = -12;
dirLight.shadow.camera.right = 12;
dirLight.shadow.camera.top = 8;
dirLight.shadow.camera.bottom = -8;
scene.add(dirLight);

scene.add(new THREE.HemisphereLight(0xddeeff, 0x8899aa, 0.35));

// ===== FIELD =====
const FW = 16.46;
const FH = 8.23;

const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(FW, FH),
    new THREE.MeshStandardMaterial({ color: 0x6b7d6b, roughness: 0.85 })
);
floor.rotation.x = -Math.PI / 2;
floor.receiveShadow = true;
scene.add(floor);

// Subtle field lines
const gridHelper = new THREE.GridHelper(Math.max(FW, FH), 20, 0x7a8a7a, 0x7a8a7a);
gridHelper.position.y = 0.005;
gridHelper.material.opacity = 0.12;
gridHelper.material.transparent = true;
scene.add(gridHelper);

// Walls
const wallMat = new THREE.MeshStandardMaterial({ color: 0xc8d0d8, roughness: 0.6 });
function makeWall(w, h, x, z, ry) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, 0.08), wallMat);
    m.position.set(x, h / 2, z);
    m.rotation.y = ry || 0;
    m.castShadow = true;
    m.receiveShadow = true;
    scene.add(m);
}
makeWall(FW, 0.35, 0, -FH / 2, 0);
makeWall(FW, 0.35, 0, FH / 2, 0);
makeWall(FH, 0.35, -FW / 2, 0, Math.PI / 2);
makeWall(FH, 0.35, FW / 2, 0, Math.PI / 2);

// Alliance zones
scene.add((() => {
    const m = new THREE.Mesh(
        new THREE.PlaneGeometry(1.5, FH),
        new THREE.MeshStandardMaterial({ color: 0x003da5, transparent: true, opacity: 0.1 })
    );
    m.rotation.x = -Math.PI / 2;
    m.position.set(-FW / 2 + 0.75, 0.01, 0);
    return m;
})());
scene.add((() => {
    const m = new THREE.Mesh(
        new THREE.PlaneGeometry(1.5, FH),
        new THREE.MeshStandardMaterial({ color: 0xcf222e, transparent: true, opacity: 0.1 })
    );
    m.rotation.x = -Math.PI / 2;
    m.position.set(FW / 2 - 0.75, 0.01, 0);
    return m;
})());

// Center line
const cl = new THREE.Mesh(
    new THREE.PlaneGeometry(0.05, FH),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.15 })
);
cl.rotation.x = -Math.PI / 2;
cl.position.y = 0.01;
scene.add(cl);

// ===== MATERIALS =====
const matBlue = new THREE.MeshStandardMaterial({ color: 0x003da5, roughness: 0.4, metalness: 0.1 });
const matBlueDark = new THREE.MeshStandardMaterial({ color: 0x002266, roughness: 0.5 });
const matGold = new THREE.MeshStandardMaterial({ color: 0xc5a030, roughness: 0.3, metalness: 0.4 });
const matMetal = new THREE.MeshStandardMaterial({ color: 0x888888, roughness: 0.3, metalness: 0.6 });
const matDarkMetal = new THREE.MeshStandardMaterial({ color: 0x555555, roughness: 0.4, metalness: 0.5 });
const matBlack = new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.7 });
const matRed = new THREE.MeshStandardMaterial({ color: 0xbb2222, roughness: 0.5 });
const matGreen = new THREE.MeshStandardMaterial({ color: 0x22aa44, roughness: 0.5 });
const matOrange = new THREE.MeshStandardMaterial({ color: 0xff8800, roughness: 0.4 });
const matDarkPlate = new THREE.MeshStandardMaterial({ color: 0x1a1a2e, roughness: 0.3, metalness: 0.2 });

// ===== ROBOT MODEL =====
const robotGroup = new THREE.Group();
scene.add(robotGroup);

const BS = 0.762; // 30 inches = 0.762m
const BH = 0.15;  // body height

// --- Chassis frame (aluminum frame visible) ---
const chassisGeo = new THREE.BoxGeometry(BS - 0.05, 0.04, BS - 0.05);
const chassis = new THREE.Mesh(chassisGeo, matMetal);
chassis.position.y = 0.04;
chassis.receiveShadow = true;
robotGroup.add(chassis);

// --- Belly pan ---
const bellyGeo = new THREE.BoxGeometry(BS - 0.08, 0.01, BS - 0.08);
const belly = new THREE.Mesh(bellyGeo, matDarkPlate);
belly.position.y = 0.02;
robotGroup.add(belly);

// --- Bumpers (blue with gold trim) ---
// Front bumper
const bumpFGeo = new THREE.BoxGeometry(BS + 0.06, 0.1, 0.06);
const bumpF = new THREE.Mesh(bumpFGeo, matBlue);
bumpF.position.set(0, 0.07, -BS / 2 - 0.01);
bumpF.castShadow = true;
robotGroup.add(bumpF);
// Front bumper gold stripe
const bumpFStripe = new THREE.Mesh(new THREE.BoxGeometry(BS + 0.07, 0.02, 0.065), matGold);
bumpFStripe.position.set(0, 0.10, -BS / 2 - 0.01);
robotGroup.add(bumpFStripe);

// Back bumper
const bumpB = new THREE.Mesh(bumpFGeo, matBlue);
bumpB.position.set(0, 0.07, BS / 2 + 0.01);
bumpB.castShadow = true;
robotGroup.add(bumpB);
const bumpBStripe = new THREE.Mesh(new THREE.BoxGeometry(BS + 0.07, 0.02, 0.065), matGold);
bumpBStripe.position.set(0, 0.10, BS / 2 + 0.01);
robotGroup.add(bumpBStripe);

// Side bumpers
const bumpSGeo = new THREE.BoxGeometry(0.06, 0.1, BS - 0.02);
const bumpL = new THREE.Mesh(bumpSGeo, matBlue);
bumpL.position.set(-BS / 2 - 0.01, 0.07, 0);
bumpL.castShadow = true;
robotGroup.add(bumpL);
const bumpR = new THREE.Mesh(bumpSGeo, matBlue);
bumpR.position.set(BS / 2 + 0.01, 0.07, 0);
bumpR.castShadow = true;
robotGroup.add(bumpR);

// --- Team number plate (gold, front center) ---
const teamPlate = new THREE.Mesh(
    new THREE.BoxGeometry(0.22, 0.06, 0.015),
    matGold
);
teamPlate.position.set(0, 0.07, -BS / 2 - 0.04);
robotGroup.add(teamPlate);

// --- Direction arrow (gold triangle on top) ---
const arrowShape = new THREE.Shape();
arrowShape.moveTo(0, 0);
arrowShape.lineTo(-0.07, -0.12);
arrowShape.lineTo(0.07, -0.12);
arrowShape.closePath();
const arrow = new THREE.Mesh(
    new THREE.ExtrudeGeometry(arrowShape, { depth: 0.015, bevelEnabled: false }),
    matGold
);
arrow.rotation.x = -Math.PI / 2;
arrow.position.set(0, 0.135, -BS / 2 + 0.08);
robotGroup.add(arrow);

// --- Swerve modules (4 corners) ---
const wheelGeo = new THREE.CylinderGeometry(0.05, 0.05, 0.035, 16);
const moduleGeo = new THREE.BoxGeometry(0.09, 0.06, 0.09);
const wheels = [];
const swervePositions = [
    [-BS / 2 + 0.09, -BS / 2 + 0.09], // FL
    [BS / 2 - 0.09, -BS / 2 + 0.09],  // FR
    [-BS / 2 + 0.09, BS / 2 - 0.09],  // RL
    [BS / 2 - 0.09, BS / 2 - 0.09],   // RR
];
for (const [sx, sz] of swervePositions) {
    const wGroup = new THREE.Group();
    wGroup.position.set(sx, 0.05, sz);

    // Module housing
    const mod = new THREE.Mesh(moduleGeo, matDarkMetal);
    mod.position.y = 0.01;
    wGroup.add(mod);

    // Wheel
    const wheel = new THREE.Mesh(wheelGeo, matBlack);
    wheel.rotation.z = Math.PI / 2;
    wheel.position.y = -0.01;
    wGroup.add(wheel);

    // Wheel tread marks (gold accent)
    const treadGeo = new THREE.CylinderGeometry(0.052, 0.052, 0.005, 16);
    const tread = new THREE.Mesh(treadGeo, matGold);
    tread.rotation.z = Math.PI / 2;
    tread.position.y = -0.01;
    wGroup.add(tread);

    robotGroup.add(wGroup);
    wheels.push(wGroup);
}

// --- Top plate / electronics board ---
const topPlate = new THREE.Mesh(
    new THREE.BoxGeometry(BS - 0.15, 0.015, BS - 0.15),
    matDarkPlate
);
topPlate.position.y = 0.13;
robotGroup.add(topPlate);

// --- FEEDER / INTAKE (back of robot, +Z local) ---
// Two counter-rotating wheels at the back that grab balls
const feederGroup = new THREE.Group();
feederGroup.position.set(0, 0.08, BS / 2 - 0.06);
robotGroup.add(feederGroup);

// Feeder housing
const feederHousing = new THREE.Mesh(
    new THREE.BoxGeometry(0.3, 0.06, 0.08),
    matDarkMetal
);
feederGroup.add(feederHousing);

// Left feeder wheel (green = intake color)
const fWheelGeo = new THREE.CylinderGeometry(0.04, 0.04, 0.06, 12);
const feederWheelL = new THREE.Mesh(fWheelGeo, matGreen);
feederWheelL.rotation.z = Math.PI / 2;
feederWheelL.position.set(-0.1, -0.01, 0.02);
feederGroup.add(feederWheelL);

// Right feeder wheel
const feederWheelR = new THREE.Mesh(fWheelGeo, matGreen);
feederWheelR.rotation.z = Math.PI / 2;
feederWheelR.position.set(0.1, -0.01, 0.02);
feederGroup.add(feederWheelR);

// Intake indicator bar (glows when active)
const intakeBarMat = new THREE.MeshStandardMaterial({ color: 0x22cc55, transparent: true, opacity: 0 });
const intakeBar = new THREE.Mesh(
    new THREE.BoxGeometry(0.35, 0.02, 0.02),
    intakeBarMat
);
intakeBar.position.set(0, 0.04, 0.04);
feederGroup.add(intakeBar);

// --- CONVEYOR (runs through middle of robot, back to front) ---
const conveyorGeo = new THREE.BoxGeometry(0.12, 0.02, BS - 0.25);
const conveyorMat = new THREE.MeshStandardMaterial({ color: 0x333333, roughness: 0.9 });
const conveyor = new THREE.Mesh(conveyorGeo, conveyorMat);
conveyor.position.set(0, 0.10, 0);
robotGroup.add(conveyor);

// Conveyor side rails
const cRailGeo = new THREE.BoxGeometry(0.015, 0.04, BS - 0.25);
const cRailL = new THREE.Mesh(cRailGeo, matMetal);
cRailL.position.set(-0.07, 0.11, 0);
robotGroup.add(cRailL);
const cRailR = new THREE.Mesh(cRailGeo, matMetal);
cRailR.position.set(0.07, 0.11, 0);
robotGroup.add(cRailR);

// --- KICKER (small wheel between conveyor and shooter) ---
const kickerGeo = new THREE.CylinderGeometry(0.03, 0.03, 0.05, 12);
const kicker = new THREE.Mesh(kickerGeo, matRed);
kicker.rotation.z = Math.PI / 2;
kicker.position.set(0, 0.12, -BS / 2 + 0.2);
robotGroup.add(kicker);

// --- SHOOTER (front of robot, -Z local) ---
const shooterGroup = new THREE.Group();
shooterGroup.position.set(0, 0.14, -BS / 2 + 0.08);
robotGroup.add(shooterGroup);

// Shooter frame
const shooterFrame = new THREE.Mesh(
    new THREE.BoxGeometry(0.28, 0.07, 0.1),
    matDarkMetal
);
shooterGroup.add(shooterFrame);

// Left shooter wheel (red = power)
const sWheelGeo = new THREE.CylinderGeometry(0.05, 0.05, 0.04, 16);
const sWheelL = new THREE.Mesh(sWheelGeo, matRed);
sWheelL.rotation.z = Math.PI / 2;
sWheelL.position.set(-0.11, 0.01, 0);
shooterGroup.add(sWheelL);

// Right shooter wheel
const sWheelR = new THREE.Mesh(sWheelGeo, matRed);
sWheelR.rotation.z = Math.PI / 2;
sWheelR.position.set(0.11, 0.01, 0);
shooterGroup.add(sWheelR);

// Shooter barrel / exit channel
const barrelGeo = new THREE.BoxGeometry(0.14, 0.04, 0.06);
const barrel = new THREE.Mesh(barrelGeo, matMetal);
barrel.position.set(0, 0.04, -0.04);
shooterGroup.add(barrel);

// Shooter glow ring (RPM indicator)
const glowMat = new THREE.MeshBasicMaterial({
    color: 0xff3333, transparent: true, opacity: 0, side: THREE.DoubleSide
});
const shooterGlow = new THREE.Mesh(new THREE.RingGeometry(0.07, 0.12, 16), glowMat);
shooterGlow.position.set(0, 0.02, -0.07);
shooterGlow.rotation.x = Math.PI / 2;
shooterGroup.add(shooterGlow);

// --- HOOD (tilting plate above shooter to aim) ---
const hoodGeo = new THREE.BoxGeometry(0.22, 0.015, 0.1);
const hoodMat = new THREE.MeshStandardMaterial({ color: 0x666677, roughness: 0.4, metalness: 0.3 });
const hood = new THREE.Mesh(hoodGeo, hoodMat);
hood.position.set(0, 0.055, -0.01);
shooterGroup.add(hood);

// Hood hinge indicators
const hingeGeo = new THREE.CylinderGeometry(0.008, 0.008, 0.24, 8);
const hinge = new THREE.Mesh(hingeGeo, matMetal);
hinge.rotation.z = Math.PI / 2;
hinge.position.set(0, 0.05, 0.04);
shooterGroup.add(hinge);

// --- Ball loaded indicator ---
const ballGeo = new THREE.SphereGeometry(0.04, 16, 16);
const loadedBall = new THREE.Mesh(ballGeo, matOrange);
loadedBall.position.set(0, 0.05, 0.03);
loadedBall.visible = false;
shooterGroup.add(loadedBall);

// --- ELEVATOR (vertical, center-back area) ---
const elevGroup = new THREE.Group();
elevGroup.position.set(0, 0.13, 0.12);
robotGroup.add(elevGroup);

// Elevator rails (two vertical aluminum bars)
const railGeo = new THREE.BoxGeometry(0.025, 0.6, 0.025);
const elevRailL = new THREE.Mesh(railGeo, matMetal);
elevRailL.position.set(-0.1, 0.3, 0);
elevGroup.add(elevRailL);
const elevRailR = new THREE.Mesh(railGeo, matMetal);
elevRailR.position.set(0.1, 0.3, 0);
elevGroup.add(elevRailR);

// Rail cross braces
for (let i = 0; i < 4; i++) {
    const braceGeo = new THREE.BoxGeometry(0.18, 0.008, 0.02);
    const brace = new THREE.Mesh(braceGeo, matMetal);
    brace.position.set(0, 0.1 + i * 0.15, 0);
    elevGroup.add(brace);
}

// Elevator car / carriage
const elevCarGeo = new THREE.BoxGeometry(0.2, 0.05, 0.05);
const elevCar = new THREE.Mesh(elevCarGeo, matBlue);
elevCar.position.y = 0.03;
elevCar.castShadow = true;
elevGroup.add(elevCar);

// Car accent
const carAccent = new THREE.Mesh(
    new THREE.BoxGeometry(0.21, 0.01, 0.055),
    matGold
);
carAccent.position.y = 0.055;
elevCar.add(carAccent);

// ===== FIELD BALLS =====
const fieldBallMeshes = new Map();
const fieldBallGeo = new THREE.SphereGeometry(0.06, 16, 16);
const fieldBallMat = new THREE.MeshStandardMaterial({ color: 0xffaa00, roughness: 0.3, metalness: 0.1 });

function syncFieldBalls(balls) {
    const currentIds = new Set(balls.map(b => b.id));
    for (const [id, mesh] of fieldBallMeshes) {
        if (!currentIds.has(id)) {
            scene.remove(mesh);
            fieldBallMeshes.delete(id);
        }
    }
    for (const b of balls) {
        let mesh = fieldBallMeshes.get(b.id);
        if (!mesh) {
            mesh = new THREE.Mesh(fieldBallGeo, fieldBallMat);
            mesh.castShadow = true;
            scene.add(mesh);
            fieldBallMeshes.set(b.id, mesh);
        }
        mesh.position.set(b.x - FW / 2, 0.06, -(b.y - FH / 2));
    }
}

// ===== PROJECTILES =====
const projectileMeshes = [];
const projGeo = new THREE.SphereGeometry(0.05, 12, 12);
const projMat = new THREE.MeshStandardMaterial({
    color: 0xff8800, roughness: 0.3, emissive: 0xff4400, emissiveIntensity: 0.2
});
const shadowGeo = new THREE.CircleGeometry(0.04, 12);
const shadowMat = new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.2 });
const projShadows = [];

for (let i = 0; i < 20; i++) {
    const pm = new THREE.Mesh(projGeo, projMat);
    pm.visible = false;
    pm.castShadow = true;
    scene.add(pm);
    projectileMeshes.push(pm);

    const s = new THREE.Mesh(shadowGeo, shadowMat);
    s.rotation.x = -Math.PI / 2;
    s.position.y = 0.005;
    s.visible = false;
    scene.add(s);
    projShadows.push(s);
}

function syncProjectiles(projs) {
    for (let i = 0; i < projectileMeshes.length; i++) {
        if (projs && i < projs.length) {
            const p = projs[i];
            const px = p.x - FW / 2;
            const pz = -(p.y - FH / 2);
            projectileMeshes[i].visible = true;
            projectileMeshes[i].position.set(px, Math.max(0.05, p.z), pz);
            projShadows[i].visible = p.z > 0.1;
            projShadows[i].position.set(px, 0.005, pz);
            const sc = Math.max(0.3, 1 - p.z * 0.15);
            projShadows[i].scale.set(sc, sc, sc);
        } else {
            projectileMeshes[i].visible = false;
            projShadows[i].visible = false;
        }
    }
}

// ===== CAMERA =====
let cameraMode = "follow";
let freeCamAngle = 0;
let freeCamDist = 12;
let freeCamHeight = 8;
let isDragging = false;
let lastMouse = { x: 0, y: 0 };

document.getElementById("cam-follow").onclick = () => setCameraMode("follow");
document.getElementById("cam-top").onclick = () => setCameraMode("top");
document.getElementById("cam-free").onclick = () => setCameraMode("free");

function setCameraMode(mode) {
    cameraMode = mode;
    document.querySelectorAll(".cam-btn").forEach(b => b.classList.remove("active"));
    document.getElementById("cam-" + mode).classList.add("active");
}

canvas.addEventListener("mousedown", (e) => {
    if (cameraMode === "free") { isDragging = true; lastMouse = { x: e.clientX, y: e.clientY }; }
});
canvas.addEventListener("mousemove", (e) => {
    if (isDragging && cameraMode === "free") {
        freeCamAngle += (e.clientX - lastMouse.x) * 0.01;
        freeCamHeight = Math.max(2, Math.min(20, freeCamHeight + (e.clientY - lastMouse.y) * 0.05));
        lastMouse = { x: e.clientX, y: e.clientY };
    }
});
canvas.addEventListener("mouseup", () => isDragging = false);
canvas.addEventListener("wheel", (e) => {
    if (cameraMode === "free") {
        freeCamDist = Math.max(4, Math.min(25, freeCamDist + e.deltaY * 0.01));
    }
});

function updateCamera() {
    if (!state) return;
    const rx = state.x - FW / 2;
    const rz = -(state.y - FH / 2);

    if (cameraMode === "follow") {
        camera.position.set(
            rx - Math.cos(state.heading) * 5,
            3.5,
            rz + Math.sin(state.heading) * 5
        );
        camera.lookAt(rx, 0.3, rz);
    } else if (cameraMode === "top") {
        camera.position.set(0, 14, 0.01);
        camera.lookAt(0, 0, 0);
    } else if (cameraMode === "free") {
        camera.position.set(
            Math.cos(freeCamAngle) * freeCamDist,
            freeCamHeight,
            Math.sin(freeCamAngle) * freeCamDist
        );
        camera.lookAt(rx, 0, rz);
    }
}

// ===== UPDATE SCENE =====
function updateScene() {
    if (!state) return;

    const rx = state.x - FW / 2;
    const rz = -(state.y - FH / 2);
    robotGroup.position.set(rx, 0, rz);
    robotGroup.rotation.y = state.heading - Math.PI / 2;

    // Swerve wheel steering
    for (let i = 0; i < 4; i++) {
        wheels[i].rotation.y = -(state.wheel_angles[i] || 0);
    }

    // Elevator car position
    const elevPct = state.elevator_position / 110;
    elevCar.position.y = 0.03 + elevPct * 0.5;

    // Hood tilt
    hood.rotation.x = ((state.hood_angle - 45) / 25) * 0.35;

    // Ball loaded indicator
    loadedBall.visible = state.ball_loaded;

    // Shooter wheel spin + glow
    const rpmPct = Math.min(Math.abs(state.shooter_rpm) / 3600, 1);
    glowMat.opacity = rpmPct * 0.5;
    if (rpmPct > 0.05) {
        sWheelL.rotation.x += rpmPct * 0.6;
        sWheelR.rotation.x += rpmPct * 0.6;
        kicker.rotation.x += rpmPct * 0.3;
    }

    // Feeder wheel spin when intaking
    if (state.feeder_state === "intake") {
        feederWheelL.rotation.x += 0.15;
        feederWheelR.rotation.x -= 0.15;
        intakeBarMat.opacity = 0.6;
    } else {
        intakeBarMat.opacity = 0;
    }

    // Conveyor visual
    if (state.conveyor_state === "forward") {
        conveyor.position.z -= 0.002;
        if (conveyor.position.z < -0.01) conveyor.position.z = 0;
    } else if (state.conveyor_state === "reverse") {
        conveyor.position.z += 0.002;
        if (conveyor.position.z > 0.01) conveyor.position.z = 0;
    }

    syncFieldBalls(state.field_balls || []);
    syncProjectiles(state.projectiles || []);
    updateCamera();
}

// ===== RENDER LOOP =====
function animate() {
    requestAnimationFrame(animate);
    updateScene();
    renderer.render(scene, camera);
}
animate();

// ===== STATE =====
socket.on("state_update", (s) => {
    state = s;
    updateUI(s);
});

function updateUI(s) {
    const speed = Math.sqrt(s.vx * s.vx + s.vy * s.vy);
    document.getElementById("stat-speed").textContent = (speed * 4.5).toFixed(1) + " m/s";
    document.getElementById("stat-rpm").textContent = Math.abs(Math.round(s.shooter_rpm));
    document.getElementById("stat-elev").textContent = s.elevator_position.toFixed(1);
    document.getElementById("stat-shots").textContent = s.balls_shot;
    document.getElementById("stat-field-balls").textContent = (s.field_balls || []).length;

    document.getElementById("hud-coords").textContent = s.x.toFixed(1) + ", " + s.y.toFixed(1) + "m";
    document.getElementById("hud-heading").textContent = (s.heading * 180 / Math.PI).toFixed(0) + "\u00B0";

    const shooterEl = document.getElementById("s-shooter");
    shooterEl.textContent = s.shooter_state;
    shooterEl.className = "sv" + (s.shooter_state === "firing" ? " firing" :
        s.shooter_state === "spinning" ? " spinning" : "");

    document.getElementById("s-feeder").textContent = s.feeder_state;
    document.getElementById("s-feeder").className = "sv" + (s.feeder_state === "intake" ? " active" : "");

    document.getElementById("s-hood").textContent = s.hood_angle.toFixed(1) + "\u00B0";
    document.getElementById("hood-badge").textContent = s.hood_angle.toFixed(1) + "\u00B0";
    document.getElementById("rpm-badge").textContent = Math.abs(Math.round(s.shooter_rpm)) + " RPM";

    document.getElementById("s-conveyor").textContent = s.conveyor_state;

    const ballEl = document.getElementById("s-ball");
    ballEl.textContent = s.ball_loaded ? "Loaded" : "Empty";
    ballEl.className = "sv" + (s.ball_loaded ? " loaded" : " empty");

    document.getElementById("s-drive").textContent = s.slow_mode ? "Slow" : "Normal";
    document.getElementById("s-drive").className = "sv" + (s.slow_mode ? " warning" : "");

    document.getElementById("elev-fill").style.height = (s.elevator_position / 110 * 100) + "%";
    document.getElementById("ball-count-badge").textContent = (s.field_balls || []).length;
}

// ===== GAMEPAD =====
let gpConnected = false;

window.addEventListener("gamepadconnected", (e) => {
    gpConnected = true;
    document.getElementById("gp-dot").classList.add("connected");
    document.getElementById("gp-label").textContent = e.gamepad.id.split("(")[0].trim() || "Gamepad";
});
window.addEventListener("gamepaddisconnected", () => {
    gpConnected = false;
    document.getElementById("gp-dot").classList.remove("connected");
    document.getElementById("gp-label").textContent = "No Gamepad";
});

function deadzone(val, dz) {
    dz = dz || 0.12;
    return Math.abs(val) < dz ? 0 : (val - Math.sign(val) * dz) / (1 - dz);
}

function pollGamepad() {
    requestAnimationFrame(pollGamepad);
    if (!gpConnected) return;
    const gp = navigator.getGamepads()[0];
    if (!gp) return;

    const b = gp.buttons;
    socket.emit("drive", {
        vx: -deadzone(gp.axes[0]),
        vy: -deadzone(gp.axes[1]),
        omega: -deadzone(gp.axes[2])
    });

    function edge(idx) { return b[idx] && b[idx].pressed && !prevButtons[idx]; }
    function release(idx) { return b[idx] && !b[idx].pressed && prevButtons[idx]; }

    if (edge(5)) socket.emit("command", { command: "slow_mode", value: 1 });
    if (release(5)) socket.emit("command", { command: "slow_mode", value: 0 });
    if (edge(4)) { socket.emit("command", { command: "fire" }); setPressed("btn-fire", true); }
    if (release(4)) { socket.emit("command", { command: "cease_fire" }); setPressed("btn-fire", false); }
    if (edge(10)) { socket.emit("command", { command: "launch" }); setPressed("btn-launch", true); }
    if (release(10)) { socket.emit("command", { command: "cease_fire" }); setPressed("btn-launch", false); }
    if (edge(11)) { socket.emit("command", { command: "intake" }); setPressed("btn-intake", true); }
    if (release(11)) { socket.emit("command", { command: "stop_feeder" }); setPressed("btn-intake", false); }
    if (edge(1)) socket.emit("command", { command: "hood_up" });
    if (release(1)) socket.emit("command", { command: "stop_hood" });
    if (edge(13)) socket.emit("command", { command: "hood_down" });
    if (release(13)) socket.emit("command", { command: "stop_hood" });
    if (edge(3)) socket.emit("command", { command: "elevator_up" });
    if (release(3)) socket.emit("command", { command: "stop_elevator" });
    if (edge(0)) socket.emit("command", { command: "elevator_down" });
    if (release(0)) socket.emit("command", { command: "stop_elevator" });
    if (edge(9)) socket.emit("command", { command: "conveyor_fwd" });
    if (release(9)) socket.emit("command", { command: "stop_conveyor" });
    if (edge(8)) socket.emit("command", { command: "conveyor_rev" });
    if (release(8)) socket.emit("command", { command: "stop_conveyor" });
    if (edge(12)) socket.emit("command", { command: "clear" });
    if (release(12)) socket.emit("command", { command: "cease_fire" });
    if (b[2] && b[2].pressed) socket.emit("command", { command: "brake" });

    prevButtons = Array.from(b).map(btn => btn && btn.pressed);
}
requestAnimationFrame(pollGamepad);

function setPressed(id, pressed) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle("pressed", pressed);
}

// ===== KEYBOARD =====
document.addEventListener("keydown", (ev) => {
    if (activeKeys.has(ev.key)) return;
    activeKeys.add(ev.key);
    const k = ev.key.toLowerCase();

    if (k === "w") { kbDrive.vy = 1; socket.emit("drive", kbDrive); ev.preventDefault(); }
    else if (k === "s") { kbDrive.vy = -1; socket.emit("drive", kbDrive); ev.preventDefault(); }
    else if (k === "a") { kbDrive.vx = -1; socket.emit("drive", kbDrive); ev.preventDefault(); }
    else if (k === "d") { kbDrive.vx = 1; socket.emit("drive", kbDrive); ev.preventDefault(); }
    else if (k === "q") { kbDrive.omega = -0.7; socket.emit("drive", kbDrive); ev.preventDefault(); }
    else if (k === "e") { kbDrive.omega = 0.7; socket.emit("drive", kbDrive); ev.preventDefault(); }
    else if (k === "shift") socket.emit("command", { command: "slow_mode", value: 1 });
    else if (k === "f") { socket.emit("command", { command: "fire" }); setPressed("btn-fire", true); ev.preventDefault(); }
    else if (k === "g") { socket.emit("command", { command: "launch" }); setPressed("btn-launch", true); ev.preventDefault(); }
    else if (k === "r") { socket.emit("command", { command: "intake" }); setPressed("btn-intake", true); ev.preventDefault(); }
    else if (k === "t") { socket.emit("command", { command: "hood_up" }); ev.preventDefault(); }
    else if (k === "y") { socket.emit("command", { command: "hood_down" }); ev.preventDefault(); }
    else if (ev.key === "ArrowUp") { socket.emit("command", { command: "elevator_up" }); ev.preventDefault(); }
    else if (ev.key === "ArrowDown") { socket.emit("command", { command: "elevator_down" }); ev.preventDefault(); }
    else if (k === " ") { socket.emit("command", { command: "estop" }); kbDrive = { vx: 0, vy: 0, omega: 0 }; ev.preventDefault(); }
    else if (k === "b") { socket.emit("command", { command: "spawn_ball" }); ev.preventDefault(); }
});

document.addEventListener("keyup", (ev) => {
    activeKeys.delete(ev.key);
    const k = ev.key.toLowerCase();

    if (k === "w" || k === "s") { kbDrive.vy = 0; socket.emit("drive", kbDrive); }
    else if (k === "a" || k === "d") { kbDrive.vx = 0; socket.emit("drive", kbDrive); }
    else if (k === "q" || k === "e") { kbDrive.omega = 0; socket.emit("drive", kbDrive); }
    else if (k === "shift") socket.emit("command", { command: "slow_mode", value: 0 });
    else if (k === "f" || k === "g") { socket.emit("command", { command: "cease_fire" }); setPressed("btn-fire", false); setPressed("btn-launch", false); }
    else if (k === "r") { socket.emit("command", { command: "stop_feeder" }); setPressed("btn-intake", false); }
    else if (k === "t" || k === "y") socket.emit("command", { command: "stop_hood" });
    else if (ev.key === "ArrowUp" || ev.key === "ArrowDown") socket.emit("command", { command: "stop_elevator" });
});

// ===== UI BUTTONS =====
function setupHold(btnId, startCmd, stopCmd) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    const start = (e) => { e.preventDefault(); btn.classList.add("pressed"); socket.emit("command", { command: startCmd }); };
    const stop = (e) => { e.preventDefault(); btn.classList.remove("pressed"); socket.emit("command", { command: stopCmd }); };
    btn.addEventListener("mousedown", start);
    btn.addEventListener("touchstart", start, { passive: false });
    btn.addEventListener("mouseup", stop);
    btn.addEventListener("mouseleave", stop);
    btn.addEventListener("touchend", stop, { passive: false });
}

setupHold("btn-fire", "fire", "cease_fire");
setupHold("btn-launch", "launch", "cease_fire");
setupHold("btn-clear", "clear", "cease_fire");
setupHold("btn-intake", "intake", "stop_feeder");
setupHold("btn-conv-fwd", "conveyor_fwd", "stop_conveyor");
setupHold("btn-conv-rev", "conveyor_rev", "stop_conveyor");
setupHold("btn-hood-up", "hood_up", "stop_hood");
setupHold("btn-hood-down", "hood_down", "stop_hood");

document.querySelectorAll("[data-preset]").forEach((btn) => {
    btn.addEventListener("click", () => {
        socket.emit("command", { command: "elevator_preset", value: parseFloat(btn.dataset.preset) });
        document.querySelectorAll("[data-preset]").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
    });
});

document.getElementById("btn-spawn-1").addEventListener("click", () => {
    socket.emit("command", { command: "spawn_ball" });
});
document.getElementById("btn-spawn-5").addEventListener("click", () => {
    socket.emit("command", { command: "spawn_balls", value: 5 });
});
document.getElementById("btn-clear-balls").addEventListener("click", () => {
    socket.emit("command", { command: "clear_balls" });
});

document.getElementById("btn-estop").addEventListener("click", () => {
    socket.emit("command", { command: "estop" });
    kbDrive = { vx: 0, vy: 0, omega: 0 };
});
