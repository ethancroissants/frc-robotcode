# Next steps — what to verify before shipping

Most of the engineering plan from `PRODUCT_PLAN.md` is now in code.
This page is the explicit "what's left, in order" list — the things
that need a real laptop / Pi / signing cert to validate, that I
can't do from a code-editing session.

## 1. Re-run install.sh on a Pi to land the rename

The `cfsight-*` → `acuity-*` rename touched a lot of files. To verify
nothing's broken, on your existing dev Pi:

```sh
cd /tmp && sudo rm -rf acuity-src
GH_TOKEN=ghp_yourtoken
git clone "https://${GH_TOKEN}@github.com/ethancroissants/frc-robotcode.git" acuity-src
sudo bash acuity-src/acuity/firmware/install.sh
sudo reboot
```

Expected after reboot:

* `systemctl is-active acuity-firstboot acuity-dashboard` → both `active`.
* `systemctl is-active cfsight-firstboot cold-fusion-sight` → both
  `inactive` or `not-found` (install.sh removes them).
* `ls /usr/local/bin/acuity-*.sh` → both present.
* `ls /etc/systemd/system/acuity-*.service` → three units.
* `cat /etc/avahi/services/acuity.service` → exists.
* `cat /etc/sudoers.d/acuity-dashboard` → exists, mode 0440.
* `cat /boot/firmware/acuity.conf` → migrated from cfsight.conf if
  one was there.
* Browse to `http://<pi>:8080/` → see the new four-tab dashboard.

If anything's missing, check `journalctl -u acuity-firstboot -b` and
`journalctl -u acuity-dashboard -b`.

## 2. First Manager run

Needs Node + npm on your laptop:

```sh
cd acuity/manager
npm install
npm run dev
```

The window should open with the Acuity wordmark, the Devices grid,
and the four tabs. With a Pi on the same network advertising
`_acuity._tcp.local`, a tile should appear within a few seconds.

Click each action on the tile and confirm:

* **Open dashboard** → opens `http://<pi>:8080/` in the system browser.
* **Update firmware** → streams install.sh output into the log pane.
* **Open terminal** → switches to Terminal tab, gives you an
  interactive SSH shell.
* **Reboot** → device restarts, tile briefly drops + reappears.
* **Forget WiFi** → device drops, comes back as `Acuity-Setup-XXXX`
  AP. (Test only when you can re-enter team WiFi via the captive
  portal.)
* **Download diagnostics** → produces `/tmp/acuity-diag.tgz` on the
  device. (Saving locally TODO.)

Library installer:

* Click **Libraries** tab → click **Java** card → pick a real
  WPILib Java project folder. Verify `<project>/vendordeps/Acuity.json`
  appears.
* Same for **C++** with a C++ WPILib project.
* For **Python**, pick a robotpy project. Verify pyproject.toml has
  `acuity-vision>=0.1` added under `[tool.robotpy].requires`.

## 3. Library publishing

Before any external team can `pip install acuity-vision` or paste a
working vendordep URL, we need to actually publish:

* **Java + C++ (vendordep):** Push a build to
  `https://maven.pkg.github.com/ethancroissants/frc-robotcode` via
  `./gradlew publish` in `acuity/libraries/java/`. Update
  `acuity/libraries/Acuity.json`'s `mavenUrls` if we move host.
* **Python:** `python -m build` + `twine upload` to PyPI.
  `acuity-vision` is the chosen name — claim it before someone else
  does.
* **Vendordep JSON URL:** The `jsonUrl` in `Acuity.json` points at
  `raw.githubusercontent.com/.../master/acuity/libraries/Acuity.json`
  for now. Once we have a real domain (acuity.tech), repoint it.

## 4. Cut your first Manager release

Build pipeline lives at
[`.github/workflows/manager-release.yml`](../../.github/workflows/manager-release.yml).
To ship the first installable EXE:

```sh
# Make sure version + lockfile are in source.
cd acuity/manager
npm install      # produces package-lock.json the workflow needs

# Commit the lockfile (if you don't have one yet).
git add acuity/manager/package-lock.json acuity/manager/package.json
git commit -m "manager: lock deps"

# Tag + push. CI builds the unsigned EXE and uploads to GitHub Releases.
git tag manager-v0.1.0
git push origin master --tags
```

When the workflow finishes, grab the `Acuity Manager Setup 0.1.0.exe`
from the Release page and run it on a Windows machine. From then on,
every subsequent `manager-vX.Y.Z` tag triggers a new release and the
running Manager will detect it on launch and offer a one-click update.

> Code signing is **deferred** — Windows SmartScreen and macOS
> Gatekeeper warn on unsigned binaries. Click "More info" → "Run
> anyway" on Windows, or right-click → Open on macOS. We add a real
> cert when volume justifies $200/yr.

## 5. Test plan — simulated device

Before shipping, write an in-repo simulated Acuity that publishes the
NT4 schema with synthetic AprilTag data. Use it to:

* Verify each library binding (Java / Python / C++) reads every field.
* Stress-test the dashboard's WS reconnection.
* Verify the Manager's mDNS discovery picks it up.

Tooling: a small Python script using `acuity/dashboard/nt4_client.py`
that publishes fake snapshots at a configurable FPS. Live under
`acuity/dashboard/sim/` so it ships alongside the real thing.

## 6. First beta team

Once steps 1–4 are done, recruit a friendly team that doesn't already
have a coprocessor. Ship them:

* One assembled device.
* The Manager binary.
* A printed quick-start card.

Watch them go through the entire flow. Take notes. The first 30
minutes of unboxing are the most important data we'll ever get.
