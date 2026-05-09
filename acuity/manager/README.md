# Acuity Manager

Driver-station companion app for the Acuity vision coprocessor.
Discovers devices on the team WiFi, opens their dashboards, runs
firmware updates, exposes a built-in SSH terminal, and walks teams
through installing the robot-side libraries for their language.

This is a thin Electron shell. The dashboard already lives at
`http://10.TE.AM.11:8080/` on the device — Manager just embeds it,
adds out-of-band control buttons, and hides all the SSH plumbing.

## Quickstart (dev)

```sh
cd acuity/manager
npm install
npm run dev
```

## Building locally (unsigned)

```sh
npm run build:win      # → dist/Acuity Manager Setup *.exe + portable .exe
npm run build:mac      # → dist/*.dmg + dist/*.zip
npm run build:linux    # → dist/*.AppImage
```

Outputs land under `acuity/manager/dist/`. We deliberately ship
**unsigned** binaries for now — Windows SmartScreen will warn on
first run, macOS Gatekeeper will require right-click → Open. Saves
us a $200/yr cert until volume justifies it.

## Releasing via GitHub Actions

`.github/workflows/manager-release.yml` builds the Windows EXE on
every tag matching `manager-v*` and uploads the binaries to a
GitHub Release. To cut a release:

```sh
# 1. Bump the version in package.json (and in the libraries' Acuity.json
#    if the schema changed).
# 2. Commit + tag:
git add acuity/manager/package.json
git commit -m "manager: 0.2.0"
git tag manager-v0.2.0
git push origin master --tags
```

CI builds the unsigned `Acuity Manager Setup 0.2.0.exe` (NSIS) plus a
portable single-file `.exe`, plus the `latest.yml` electron-updater
needs. Download from the GitHub Releases page and ship the link.

## Auto-update

The running app checks GitHub Releases on launch (3 s after main
window opens). If a newer `manager-v*` release is found, the topbar
lights up an **Update** pill and a banner offers a manual download.
Once downloaded, a **Restart & install** button replaces the binary
and relaunches.

We **don't auto-download** — at competition the field WiFi might
charge per byte and a forced 80 MB download is hostile. Users opt in.

**Important:** electron-updater talks to the GitHub Releases API
anonymously. If `ethancroissants/frc-robotcode` is **private**,
end-user installs will silently fail to find updates (the API
returns 404 without auth). Two fixes when that becomes a problem:

1. **Make the repo public.** The Manager binary is OSS by design
   anyway — anyone reverse-engineering it learns nothing they
   couldn't read in this repo.
2. **Mirror releases to a public repo.** Set up a stub
   `acuity-releases` public repo that the workflow `gh release
   create`s into, and point the package.json `publish.repo` at
   that. Code stays private; binaries are public.

## First-launch onboarding

A four-step wizard walks new users through:

1. Welcome screen.
2. Pick a path — new device / existing device / install library.
3. Per-path instructions (captive-portal walkthrough, scan,
   library install).
4. Done.

Re-openable any time via the **?** button in the topbar.

## Layout

```
manager/
├── package.json        # Electron + electron-builder + deps
├── src/
│   ├── main.js         # Electron main process
│   ├── preload.js      # contextBridge: safely exposes Node APIs to renderer
│   ├── ipc/
│   │   ├── discovery.js  # mDNS scan for _acuity._tcp.local
│   │   ├── ssh.js        # ssh2-based remote exec for update/reboot/diagnose
│   │   └── pty.js        # node-pty terminal session, piped through ssh
│   └── renderer/
│       ├── index.html
│       ├── style.css     # Acuity light theme (matches dashboard)
│       └── app.js        # UI state + button wiring
└── assets/
    └── icon.png
```

## Features (target)

- **Auto-discovery.** mDNS scan finds every `acuity-NNNN.local` on
  the network, shows them as tiles with name, IP, version, status dot.
- **Open dashboard.** Click a tile → opens an embedded webview at
  `:8080` with the live camera feed and AprilTag overlays.
- **Update firmware.** Pulls the latest `install.sh` and re-runs it
  via SSH with a streaming log pane.
- **Reboot / forget WiFi.** One-click; forget WiFi puts the device
  back into AP-mode setup wizard.
- **Open SSH terminal.** xterm.js + node-pty + ssh2 — full interactive
  shell to the device, no separate ssh client required.
- **Install vision libraries.** A wizard that:
  1. Asks for the team's language (Java / Python / C++).
  2. Detects their robot project (looks for `build.gradle`,
     `pyproject.toml`, etc.).
  3. Adds the Acuity vendordep / pip dependency.
  4. Drops a starter snippet into their `Robot.java` or `robot.py`.
- **Diagnostics bundle.** One click → device journal, configs,
  hostapd log, latest screenshot — zipped + saved locally.

## Status

Foundation only. See [../docs/PRODUCT_PLAN.md](../docs/PRODUCT_PLAN.md)
for what's built vs. what's pending.
