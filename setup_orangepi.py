#!/usr/bin/env python3
"""Cold Fusion Robotics — Vision Pi installer.

Mirrors deploy.py / setup.py for the rio: provides a friendly UI (when run
with --ui) that walks through:

  1. Ask for the Pi's hostname/user (saved to .orangepi_cfg next to this file).
  2. SCP the orangepi/ folder to the Pi.
  3. Run install.sh on the Pi to apt-install ffmpeg/venv, create the
     virtualenv, drop the systemd unit, and start the service.
  4. Print the URL the driver should bookmark.

Re-running is safe — install.sh is idempotent.

The Pi setup is decoupled from the rio deploy pipeline on purpose: rio code
(robot.py / commands / etc) is what robotpy deploys; the Pi just runs a
network-attached camera + web UI talking to the rio over NetworkTables.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import ui_mode

REPO = Path(__file__).resolve().parent
ORANGEPI_DIR = REPO / "orangepi"
CFG_PATH = REPO / ".orangepi_cfg"
# pi_target.json gets included in `robotpy deploy` (no leading dot) so the
# rio's orangepi_pusher.py can find the Pi after deploy.
TARGET_PATH = REPO / "pi_target.json"

DEFAULT_USER = "orangepi"
DEFAULT_HOST = "orangepi.local"
INSTALL_DIR = "/home/orangepi/cold-fusion-sight"

# rio SSH details. The roboRIO ships with `admin` (no password) on port 22.
RIO_USER = "admin"
# Robot code runs as `lvuser`; that's the account whose key needs to be on
# the Pi so orangepi_pusher.py can push without a password prompt.
RIO_ROBOT_USER = "lvuser"


# ----- ui-or-print helpers -----

def _step(msg: str) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().step(msg)
    else:
        print(f"\n▶ {msg}")


def _ok(msg: str) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().ok(msg)
    else:
        print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().fail(msg)
    else:
        print(f"  ✗ {msg}")


def _info(msg: str) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().info(msg)
    else:
        print(f"  · {msg}")


def _ask_string(prompt: str, default: str = "") -> str | None:
    if ui_mode.is_active():
        return ui_mode.get_app().ask_string(prompt, default=default, title="Vision Pi")
    try:
        ans = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        return None
    return ans or default


def _ask_password(prompt: str) -> str | None:
    """Prompt for the Pi user's password.

    Used only on first run to bootstrap SSH key auth — after the laptop's
    pubkey is on the Pi, every subsequent setup step uses key auth and
    this prompt is skipped silently. Empty/cancelled means "I already
    have key auth set up, don't bother me".
    """
    if ui_mode.is_active():
        return ui_mode.get_app().ask_password(prompt, title="Vision Pi")
    import getpass
    try:
        return getpass.getpass(f"{prompt}: ") or None
    except (EOFError, KeyboardInterrupt):
        return None


def _stream(cmd: list[str]) -> int:
    """Run a subprocess; in UI mode the output goes to the details pane."""
    if ui_mode.is_active():
        return ui_mode.get_app().stream_subprocess(cmd)
    print(f"  $ {' '.join(shlex.quote(a) for a in cmd)}")
    return subprocess.run(cmd).returncode


# ----- config persistence -----

def load_cfg() -> dict:
    if not CFG_PATH.exists():
        return {}
    try:
        return json.loads(CFG_PATH.read_text())
    except Exception:
        return {}


def save_cfg(cfg: dict) -> None:
    CFG_PATH.write_text(json.dumps(cfg, indent=2))


# ----- network helpers -----

def ssh_target(cfg: dict) -> str:
    user = cfg.get("user", DEFAULT_USER)
    host = cfg.get("host", DEFAULT_HOST)
    return f"{user}@{host}"


def ping(host: str) -> bool:
    """Cross-platform single-shot ping."""
    if sys.platform.startswith("win"):
        cmd = ["ping", "-n", "1", "-w", "1500", host]
    else:
        cmd = ["ping", "-c", "1", "-W", "2", host]
    return subprocess.run(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def have(tool: str) -> bool:
    from shutil import which
    return which(tool) is not None


# ----- installer steps -----

def gather_config(cfg: dict) -> tuple[dict, str | None] | None:
    """Ask for / confirm the Pi's user@host (saved) + password (not saved).

    Returns (cfg, password) where password may be None if the user left
    it blank — we'll skip the SSH-key bootstrap and assume key auth is
    already in place. The password is *only* held in memory long enough
    to set up keys; it's never written to disk.
    """
    host = _ask_string(
        "Pi hostname or IP", default=cfg.get("host", DEFAULT_HOST)
    )
    if not host:
        return None
    user = _ask_string("Pi SSH user", default=cfg.get("user", DEFAULT_USER))
    if not user:
        return None
    password = _ask_password(
        f"Password for {user}@{host}\n"
        "(leave blank if SSH key auth is already set up)"
    )
    cfg = dict(cfg)
    cfg["user"] = user
    cfg["host"] = host
    save_cfg(cfg)
    return cfg, password


def _ssh_key_auth_works(cfg: dict, attempts: int = 1) -> bool:
    """Returns True if `ssh user@host true` succeeds without a password.

    BatchMode=yes refuses to prompt for a password, so the call returns
    quickly with non-zero rc on a fresh Pi rather than hanging waiting
    for input we can't supply (stdin is piped by stream_subprocess).

    On Windows a fresh Pi reachable only via mDNS/IPv6 link-local can flake
    the first probe even when key auth is fine — `attempts` lets the caller
    retry a couple of times with a short delay.
    """
    import time
    target = ssh_target(cfg)
    for i in range(max(1, attempts)):
        try:
            result = subprocess.run(
                [
                    "ssh",
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=5",
                    "-o", "StrictHostKeyChecking=accept-new",
                    target,
                    "true",
                ],
                capture_output=True, timeout=15,
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass
        if i + 1 < attempts:
            time.sleep(1.0)
    return False


def _ensure_local_ssh_key() -> Path | None:
    """Make sure the laptop has ~/.ssh/id_ed25519(.pub); generate if missing.
    Returns the path to the public key file, or None on failure."""
    home = Path.home()
    ssh_dir = home / ".ssh"
    key_path = ssh_dir / "id_ed25519"
    pub_path = ssh_dir / "id_ed25519.pub"
    if pub_path.exists():
        return pub_path
    # Try a fallback to RSA if the user already has one (older laptops).
    rsa_pub = ssh_dir / "id_rsa.pub"
    if rsa_pub.exists():
        return rsa_pub
    _info("Generating laptop SSH key (~/.ssh/id_ed25519)…")
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    try:
        rc = subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path), "-q"],
            capture_output=True, timeout=15,
        ).returncode
    except Exception as e:
        _fail(f"ssh-keygen failed: {e}")
        return None
    if rc != 0 or not pub_path.exists():
        _fail("Couldn't generate local SSH key.")
        return None
    return pub_path


def _ensure_paramiko():
    """Lazy import paramiko, auto-installing it on first use.

    Paramiko is a pure-python SSH client — we only use it for the
    one-time pubkey-install step, since system `ssh` can't accept a
    password through the piped stdin our UI uses. After bootstrap, every
    other call goes back through system ssh + key auth.
    """
    try:
        import paramiko  # type: ignore
        return paramiko
    except ImportError:
        pass
    _info("Installing paramiko (one-time, for SSH password bootstrap)…")
    rc = _stream([sys.executable, "-m", "pip", "install", "--user", "paramiko"])
    if rc != 0:
        _fail("Couldn't install paramiko.")
        _info("Run manually:  " + sys.executable + " -m pip install paramiko")
        return None
    try:
        import paramiko  # type: ignore
        return paramiko
    except ImportError:
        _fail("paramiko installed but import still fails — try restarting setup.")
        return None


def bootstrap_ssh_key(cfg: dict, password: str | None) -> bool:
    """Make sure passwordless SSH from laptop → Pi works.

    Flow:
      1. Try BatchMode key auth. If it works, we're already set up — skip.
      2. If not, and a password was provided, ssh in with paramiko using
         the password and append the laptop's pubkey to the Pi's
         authorized_keys.
      3. Verify by retrying step 1.

    Returns True on success. The password is never logged or saved.
    """
    _step("Setting up passwordless SSH to the Pi")

    if _ssh_key_auth_works(cfg):
        _ok("SSH key auth already works — no password needed.")
        return True

    if not password:
        _fail("SSH key auth doesn't work yet, and you didn't enter a password.")
        _info("Re-run setup and type the Pi's password when asked.")
        _info(
            "(That's the password you set on first boot of the Pi — "
            "the one for the `" + cfg.get("user", DEFAULT_USER) + "` user.)"
        )
        return False

    pub_path = _ensure_local_ssh_key()
    if pub_path is None:
        return False
    pubkey = pub_path.read_text().strip()
    if not pubkey.startswith("ssh-"):
        _fail(f"Public key at {pub_path} looks malformed.")
        return False

    paramiko = _ensure_paramiko()
    if paramiko is None:
        return False

    host = cfg["host"]
    user = cfg.get("user", DEFAULT_USER)
    _info(f"Connecting to {user}@{host} with the password (one-time bootstrap)…")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host,
            username=user,
            password=password,
            timeout=10,
            # Don't let paramiko try the laptop's existing keys first —
            # if one of them happened to work we'd have skipped this path
            # back at step 1. Forcing password keeps the failure mode
            # honest ("password didn't work" vs "some key happened to").
            allow_agent=False,
            look_for_keys=False,
        )
    except paramiko.AuthenticationException:
        _fail("Password rejected by the Pi.")
        _info("Double-check the password you set on first boot.")
        return False
    except Exception as e:
        _fail(f"Couldn't connect to {host}: {e}")
        return False

    # Append our pubkey to ~/.ssh/authorized_keys idempotently. mkdir + chmod
    # cover a fresh user that's never SSH'd anywhere before.
    quoted = shlex.quote(pubkey)
    install_cmd = (
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        "touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && "
        f"grep -qxF {quoted} ~/.ssh/authorized_keys || "
        f"echo {quoted} >> ~/.ssh/authorized_keys"
    )
    try:
        _, stdout, stderr = client.exec_command(install_cmd, timeout=15)
        rc = stdout.channel.recv_exit_status()
        err = stderr.read().decode(errors="replace").strip()
    except Exception as e:
        client.close()
        _fail(f"Failed to run install command on Pi: {e}")
        return False
    finally:
        client.close()

    if rc != 0:
        _fail(f"Installing key on Pi failed (rc={rc}): {err}")
        return False

    # mDNS / IPv6 link-local resolution can flake the first probe on Windows
    # even when key auth is genuinely fine. Retry a few times before giving up.
    if not _ssh_key_auth_works(cfg, attempts=4):
        # Don't hard-fail: paramiko reported success appending the key, and
        # our follow-up rsync/ssh will exercise the real path. Warn loudly
        # so the user knows what to look for if push_files then errors.
        _info(
            "Heads-up: post-install key probe didn't succeed, but the key "
            "was uploaded — continuing anyway."
        )
        _info(
            "If the next step fails on auth, run "
            "`ssh -v " + ssh_target(cfg) + "` in a terminal to debug."
        )
        return True

    _ok("SSH key installed on the Pi — passwordless from now on.")
    return True


def detect_pi_env(cfg: dict) -> dict | None:
    """Probe the Pi for Python version, arch, and apt packages we'll need.

    Returns a dict like {"py": "3.11", "arch": "aarch64", "apt_missing": [...]}
    or None on failure. Run before staging wheels so the laptop downloads
    matching artifacts (a Pi 5 wants `linux_aarch64` wheels for Python 3.11
    or 3.13; a Pi 4 32-bit would want `armv7l`).
    """
    _step("Probing the Pi")
    target = ssh_target(cfg)
    # Probe each requirement as a list of alternatives separated by '|'.
    # If ANY alternative is installed, the dep is satisfied (handles the
    # libglib2.0-0 → libglib2.0-0t64 rename in Debian Trixie's t64
    # transition). We emit NEED only if every alternative is missing.
    # Use Python's own arch reporting (sysconfig.get_platform) instead of
    # `uname -m`. On Raspberry Pi OS with a 64-bit kernel + 32-bit userspace,
    # `uname -m` returns 'aarch64' but Python is 'armv7l' — pip wheels are
    # tagged by the userspace arch, so keying off the kernel arch makes the
    # staged wheel cache silently install the wrong artifacts.
    probe = r"""
echo PY:$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
echo ARCH:$(python3 -c 'import sysconfig;print(sysconfig.get_platform().rsplit("-",1)[-1])')
for spec in 'python3-venv' 'python3-pip' 'libgl1' 'libglib2.0-0t64|libglib2.0-0'; do
  ok=0
  IFS='|'
  for pkg in $spec; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then ok=1; echo HAVE:$pkg; fi
  done
  unset IFS
  if [ $ok -eq 0 ]; then echo "NEED:${spec%%|*}"; fi
done
"""
    try:
        result = subprocess.run(
            ["ssh", target, probe],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:
        _fail(f"Couldn't probe Pi: {e}")
        return None
    if result.returncode != 0:
        _fail(f"Pi probe failed: {result.stderr.strip()}")
        return None

    info: dict = {"apt_missing": [], "apt_have": []}
    for line in result.stdout.splitlines():
        if line.startswith("PY:"):
            info["py"] = line[3:].strip()
        elif line.startswith("ARCH:"):
            info["arch"] = line[5:].strip()
        elif line.startswith("NEED:"):
            info["apt_missing"].append(line[5:].strip())
        elif line.startswith("HAVE:"):
            info["apt_have"].append(line[5:].strip())
    if "py" not in info or "arch" not in info:
        _fail(f"Couldn't parse probe output: {result.stdout!r}")
        return None
    _ok(f"Pi: Python {info['py']}, arch {info['arch']}")

    # Persist into .orangepi_cfg so the next run can stage wheels without
    # being able to reach the Pi (e.g. when the laptop is on home WiFi for
    # the download step but the Pi is on the robot's network).
    cfg["pi_env"] = info
    save_cfg(cfg)
    return info


def bridge_internet_for_apt(cfg: dict, apt_missing: list[str]) -> bool:
    """Briefly connect the Pi's wlan0 to a user-supplied WiFi to run apt.

    This solves the chicken-and-egg of `python3-pip`/`libgl1`/etc. on a
    fresh Pi that lives on the FRC robot network (no internet). The Pi's
    ethernet to the robot stays untouched; we only toggle wlan0.

    Flow on the Pi (one ssh round-trip):
      1. nmcli adds a temporary connection profile `cf-temp-install`.
      2. Brings it up on wlan0; DHCP/DNS settle.
      3. apt-get update + apt-get install -y <missing>.
      4. Down + delete the profile (trap EXIT — runs even on failure).

    Returns True on success. False if the user skipped, the WiFi connect
    failed, or apt install failed. The caller handles aborting setup.
    """
    if not apt_missing:
        return True

    _step("Installing missing apt packages on the Pi (one-time internet bridge)")
    _info(f"Missing: {' '.join(apt_missing)}")
    _info(
        "We'll briefly connect the Pi's WiFi (wlan0) to a network with "
        "internet, install the packages, then disconnect. The Pi's robot "
        "ethernet stays connected the whole time."
    )

    ssid = _ask_string("WiFi network name (SSID)", default="")
    if not ssid:
        _fail("No SSID provided — skipping apt install.")
        _info(
            "Re-run setup with the SSID/password, or install on the Pi "
            "manually with: sudo apt-get install -y " + " ".join(apt_missing)
        )
        return False
    wifi_pass = _ask_password(
        f"Password for '{ssid}' (leave blank for open network)"
    ) or ""

    target = ssh_target(cfg)
    ssid_q = shlex.quote(ssid)
    psk_q = shlex.quote(wifi_pass)
    pkgs_q = " ".join(shlex.quote(p) for p in apt_missing)

    # Build the remote script. trap EXIT guarantees the temp connection is
    # cleaned up even if `set -e` aborts midway. Hard-coded con-name so we
    # don't have to deal with weird SSID characters in connection lookup.
    script_lines = [
        "set -e",
        "cleanup() {",
        "  sudo nmcli connection down cf-temp-install >/dev/null 2>&1 || true",
        "  sudo nmcli connection delete cf-temp-install >/dev/null 2>&1 || true",
        "}",
        "trap cleanup EXIT",
        "if ! command -v nmcli >/dev/null; then",
        "  echo 'nmcli not installed — Pi OS Bookworm/Trixie should have it; aborting' >&2",
        "  exit 2",
        "fi",
        # If wifi was previously toggled off (nmcli radio wifi off, or a
        # soft rfkill), wlan0 shows up as 'unavailable' and `connection up`
        # fails with a confusing "No suitable device" error. Force it on.
        "if command -v rfkill >/dev/null; then sudo rfkill unblock wifi || true; fi",
        "sudo nmcli radio wifi on || true",
        "sleep 1",
        f"sudo nmcli connection add type wifi con-name cf-temp-install "
        f"ifname wlan0 ssid {ssid_q} >/dev/null",
    ]
    if wifi_pass:
        script_lines.append(
            f"sudo nmcli connection modify cf-temp-install "
            f"wifi-sec.key-mgmt wpa-psk wifi-sec.psk {psk_q}"
        )
    script_lines += [
        "sudo nmcli connection modify cf-temp-install connection.autoconnect no",
        # The robot ethernet has no internet. Force wlan0's default route to win
        # over eth0's by giving it a lower (better) route-metric than the
        # default ethernet metric (100). Otherwise apt traffic goes out eth0
        # and dies with "No route to host".
        "sudo nmcli connection modify cf-temp-install "
        "ipv4.route-metric 50 ipv6.route-metric 50",
        "echo '[bridge] connecting wlan0 to the temp WiFi…'",
        "sudo nmcli connection up cf-temp-install",
        "sleep 5",  # let DHCP / DNS / route table settle
        "echo '[bridge] verifying internet via wlan0…'",
        # Quick reachability + route check so we fail fast with a clear message
        # rather than letting apt produce a wall of errors.
        "if ! curl -s --max-time 8 --interface wlan0 -o /dev/null "
        "http://archive.raspberrypi.com/debian/dists/trixie/InRelease; then",
        "  echo '[bridge] wlan0 cannot reach the package mirror.' >&2",
        "  echo '[bridge] route table:' >&2",
        "  ip route >&2 || true",
        "  exit 3",
        "fi",
        # Sync clock from an HTTPS Date header. If the Pi has no RTC battery
        # or has been off the network, its wall clock can drift into the past.
        # apt's signature verifier (sqv) rejects 'not yet live' signatures, so
        # apt-get update silently keeps stale package lists that point at dead
        # mirror URLs — which then 404/timeout during install. One-shot fix.
        "echo '[bridge] syncing system clock from HTTPS Date header…'",
        "http_date=$(curl -sI --max-time 8 --interface wlan0 "
        "https://archive.raspberrypi.com/ "
        "| awk -F': ' 'tolower($1)==\"date\"{print $2}' | tr -d '\\r')",
        "if [ -n \"$http_date\" ]; then",
        "  sudo date -u -s \"$http_date\" >/dev/null && "
        "echo \"[bridge] clock set to $(date -u)\"",
        "else",
        "  echo '[bridge] could not read Date header — continuing anyway' >&2",
        "fi",
        "echo '[bridge] running apt-get update'",
        "sudo apt-get update",
        f"echo '[bridge] installing: {' '.join(apt_missing)}'",
        f"sudo apt-get install -y {pkgs_q}",
        # Top up the wheel cache from PyPI while we're online. Laptop-side
        # `pip download --platform/--abi` can miss wheels for extras like
        # `uvicorn[standard]` (uvloop, httptools) due to strict tag filters;
        # running pip on the Pi itself avoids that — it picks the exact
        # tags Python here can use. Idempotent: pip skips wheels already
        # present in the destination dir.
        f"if [ -f {shlex.quote(INSTALL_DIR)}/requirements.txt ]; then",
        "  echo '[bridge] topping up Pi wheel cache from PyPI…'",
        f"  mkdir -p {shlex.quote(INSTALL_DIR)}/vendor/wheels",
        f"  python3 -m pip download --only-binary=:all: "
        f"-r {shlex.quote(INSTALL_DIR)}/requirements.txt "
        f"-d {shlex.quote(INSTALL_DIR)}/vendor/wheels "
        "|| echo '[bridge] wheel top-up had errors; continuing — '"
        "'install.sh will surface anything still missing' >&2",
        "fi",
        "echo '[bridge] done — disconnecting'",
    ]
    script = "\n".join(script_lines) + "\n"

    rc = _stream(["ssh", "-t", target, f"bash -c {shlex.quote(script)}"])
    if rc != 0:
        _fail("Internet bridge / apt install failed (rc={}).".format(rc))
        _info(
            "Common causes: wrong WiFi password, SSID typo, weak signal, "
            "or the Pi has no wlan0 (e.g. wired-only model)."
        )
        return False
    _ok("apt packages installed; temp WiFi disconnected.")
    return True


def check_pi_wheel_cache(pi_env: dict) -> bool:
    """Verify the laptop has staged Pi wheels (created by setup.py).

    setup_orangepi.py never downloads — wheel staging happens in setup.py
    while the laptop is on real internet. This function just verifies the
    cache is present and matches the Pi's Python/arch. If it doesn't, we
    point the user at setup.py (which they should run on home WiFi).
    """
    _step("Checking Pi wheel cache")
    wheels_dir = ORANGEPI_DIR / "vendor" / "wheels"
    stamp = wheels_dir / ".cache-stamp"
    req = ORANGEPI_DIR / "requirements.txt"

    n_wheels = len(list(wheels_dir.glob("*.whl"))) if wheels_dir.exists() else 0
    if n_wheels == 0 or not stamp.exists():
        _fail("No Pi wheels staged on the laptop.")
        _info(
            "Run `python setup.py` while on a WiFi with internet — it "
            "downloads Pi-compatible wheels into orangepi/vendor/wheels/. "
            "Then come back to the robot's WiFi and re-run Vision Pi setup."
        )
        return False

    py = pi_env.get("py", "?")
    arch = pi_env.get("arch", "?")
    expected = _wheel_cache_key(req, py, arch)
    if stamp.read_text().strip() != expected:
        _fail(
            f"Pi wheel cache is stale or built for the wrong Python/arch "
            f"(this Pi is Python {py} on {arch})."
        )
        _info(
            "Re-run `python setup.py` on internet to refresh the cache — "
            "it picks up the Pi's actual specs from .orangepi_cfg."
        )
        return False

    _ok(f"Pi wheel cache OK ({n_wheels} wheels for Python {py}/{arch}).")
    return True


def _wheel_cache_key(req_path: Path, py: str, arch: str) -> str:
    """Hash of inputs that, when changed, invalidate the staged wheel cache.
    Mirrors _pi_wheel_cache_key in setup.py — keep them in sync."""
    import hashlib
    h = hashlib.sha256()
    h.update(req_path.read_bytes())
    h.update(f"|py={py}|arch={arch}".encode())
    return h.hexdigest()


def check_reachable(cfg: dict) -> bool:
    _step("Checking Pi connectivity")
    host = cfg["host"]
    if ping(host):
        _ok(f"{host} reachable")
        return True
    _fail(f"Couldn't ping {host}.")
    _info("Make sure the Pi is on the network and reachable from this laptop.")
    _info("Try `ssh " + ssh_target(cfg) + "` manually first.")
    return False


def push_files(cfg: dict) -> bool:
    _step("Sending files to the Pi")
    target = ssh_target(cfg)

    rsync_avail = have("rsync") and not sys.platform.startswith("win")
    if rsync_avail:
        # Trailing slash on the source = "copy contents into INSTALL_DIR".
        rc = _stream([
            "rsync", "-az", "--info=progress2",
            "--delete", "--exclude=.venv", "--exclude=__pycache__",
            f"{ORANGEPI_DIR}/", f"{target}:{INSTALL_DIR}/",
        ])
        if rc != 0:
            _fail("File transfer failed (rsync).")
            return False
    else:
        # No rsync available (Windows default). `scp -r` is unbearably slow
        # when shipping the wheel cache (~100MB across 22 files) because it
        # opens a fresh SSH channel per file. Use a single `tar | ssh tar`
        # pipe instead — one SSH session, pipelined, no per-file overhead.
        if not _push_via_tar(target):
            return False

    # Strip CRLF line endings on shell scripts. Windows checkouts often save
    # *.sh with \r\n, and bash chokes with `$'\r': command not found` on the
    # very first line. Fixing it here means we don't have to police
    # .gitattributes / line-ending settings on every contributor's laptop.
    _info("Normalizing line endings on shell scripts…")
    fix_cmd = (
        f"find {shlex.quote(INSTALL_DIR)} -type f "
        f"\\( -name '*.sh' -o -name 'install.sh' \\) "
        f"-exec sed -i 's/\\r$//' {{}} +"
    )
    _stream(["ssh", target, fix_cmd])

    _ok("Files copied.")
    return True


def _push_via_tar(target: str) -> bool:
    """Stream orangepi/ to the Pi as one tar archive over a single SSH session.

    Faster than `scp -r` for the wheel cache because it's one TCP stream and
    one SSH auth; scp does per-file negotiation and falls off a cliff on slow
    links. We feed Python's tarfile output through `ssh ... tar xf -` so the
    Pi extracts as we transfer (no temp file on either end).

    Excludes .venv/ and __pycache__/ matches the rsync filter above. Wheels
    are already zip-compressed, so we don't bother gzipping the tar.
    """
    import io
    import tarfile
    import time

    skip_names = {".venv", "__pycache__"}

    # Total expected size for the progress UI. Skips the same paths the
    # tar walk will skip — counters disagree slightly on dir entries, but
    # the byte total is what matters.
    total_bytes = 0
    file_count = 0
    for p in ORANGEPI_DIR.rglob("*"):
        if any(part in skip_names for part in p.parts):
            continue
        if p.is_file():
            try:
                total_bytes += p.stat().st_size
                file_count += 1
            except OSError:
                pass
    _info(f"  packaging {file_count} file(s), ~{total_bytes // (1024 * 1024)} MB")

    remote_cmd = (
        f"mkdir -p {shlex.quote(INSTALL_DIR)} && "
        f"cd {shlex.quote(INSTALL_DIR)} && tar xf -"
    )
    proc = subprocess.Popen(
        ["ssh", target, remote_cmd],
        stdin=subprocess.PIPE,
    )
    if proc.stdin is None:
        _fail("Couldn't open ssh stdin pipe.")
        return False

    sent_bytes = 0
    last_report = time.monotonic()

    class _ProgressWriter:
        """Wraps proc.stdin to count bytes for the progress UI."""
        def __init__(self, inner):
            self._inner = inner
        def write(self, data):
            nonlocal sent_bytes, last_report
            self._inner.write(data)
            sent_bytes += len(data)
            now = time.monotonic()
            if now - last_report > 1.0:
                last_report = now
                pct = (sent_bytes / total_bytes * 100) if total_bytes else 0
                mb = sent_bytes // (1024 * 1024)
                _info(f"  pushed {mb} MB ({pct:.0f}%)")
            return len(data)
        def flush(self):
            self._inner.flush()
        def close(self):
            self._inner.close()

    def _filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # Drop excluded paths. arcname is relative — split on / works on both
        # platforms because tar normalizes separators internally.
        for part in info.name.split("/"):
            if part in skip_names:
                return None
        return info

    try:
        with tarfile.open(fileobj=_ProgressWriter(proc.stdin), mode="w|") as tar:
            tar.add(str(ORANGEPI_DIR), arcname=".", filter=_filter)
    except Exception as e:
        _fail(f"tar stream failed: {e}")
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.wait(timeout=5)
        return False

    try:
        proc.stdin.close()
    except Exception:
        pass
    rc = proc.wait()
    if rc != 0:
        _fail(f"Remote tar extraction failed (rc={rc}).")
        return False
    _info(f"  pushed {sent_bytes // (1024 * 1024)} MB total")
    return True


def run_remote_install(
    cfg: dict, password: str | None = None, pi_env: dict | None = None,
) -> bool:
    _step("Installing on the Pi (apt + venv + systemd + static IP)")
    target = ssh_target(cfg)
    team = _read_team_number() or "1279"

    # install.sh runs `sudo apt-get`, `sudo systemctl`, etc. — and most Pi
    # default users (pi/orangepi) require a password for sudo. The SSH
    # subprocess has piped stdin (no tty), so sudo can't prompt; we need to
    # arrange passwordless sudo for the duration of the setup. The matching
    # _remove_temp_nopasswd() call runs once *all* setup steps that need
    # sudo are done (write_team, setup_cross_ssh).
    if not _try_install_temp_nopasswd(cfg, password) and password is None:
        _info(
            "Tip: if install.sh fails on 'sudo: a password is required', "
            "re-run setup and type the Pi user's password."
        )

    # Tell install.sh which apt deps are missing (vs. already installed) so
    # it can skip the apt step when everything's already present — the Pi
    # is offline and apt would fail otherwise.
    apt_missing = " ".join(pi_env["apt_missing"]) if pi_env else ""

    # install.sh reads these env vars:
    #   TEAM         — sets static IP (10.TE.AM.11)
    #   APT_MISSING  — space-separated apt packages to install (empty = skip)
    #   USE_LOCAL_WHEELS=1 — install pip deps from vendor/wheels offline
    install_cmd = (
        f"cd {shlex.quote(INSTALL_DIR)} && "
        f"TEAM={shlex.quote(team)} "
        f"APT_MISSING={shlex.quote(apt_missing)} "
        f"USE_LOCAL_WHEELS=1 "
        f"bash install.sh"
    )
    rc = _stream(["ssh", "-t", target, install_cmd])
    if rc != 0:
        _fail("Remote install failed; check the details panel.")
        return False
    _ok("Service installed and started.")
    return True


def _remove_temp_nopasswd(cfg: dict) -> None:
    """Remove the temp sudoers rule we created in _try_install_temp_nopasswd.

    Idempotent — does nothing if the file isn't there. Safe to call even if
    we never installed a rule (the `sudo rm -f` either succeeds against an
    existing file, or no-ops because the file's missing).
    """
    user = cfg.get("user", DEFAULT_USER)
    target = ssh_target(cfg)
    _info("Removing temporary sudoers rule…")
    _stream([
        "ssh", target,
        f"sudo rm -f /etc/sudoers.d/cf-install-{user}",
    ])


def _try_install_temp_nopasswd(cfg: dict, password: str | None) -> bool:
    """Install a temporary `NOPASSWD: ALL` sudoers entry for the install user.

    install.sh will sudo many times (apt, systemctl, tee /etc/...). We don't
    want to plumb the password through every shell prompt, and the user's
    default sudo config almost always requires a password. Solution: use the
    password ONCE via paramiko (so it doesn't leak into shell logs) to drop
    a sudoers.d snippet that grants this user passwordless sudo for the rest
    of the run. The caller is responsible for removing it after install.sh
    finishes — we wire that into the cleanup tail of the install command.

    Returns True if the rule was installed, False otherwise (e.g. no password
    provided, paramiko unavailable, or sudo refused). On False the caller
    falls back to running install.sh straight; sudo will prompt and likely
    fail, but the user gets a clear error.
    """
    user = cfg.get("user", DEFAULT_USER)
    host = cfg["host"]

    if password is None:
        _info(
            "No password on hand — install.sh will need passwordless sudo "
            "configured on the Pi, or it'll fail. (Re-run setup with the "
            "password if it does.)"
        )
        return False

    paramiko = _ensure_paramiko()
    if paramiko is None:
        return False

    _info("Granting temporary passwordless sudo for the install…")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        # Use key auth (already bootstrapped) so we don't have to re-send the
        # password over the wire — but the *target* command does need it once,
        # to authenticate the initial sudo. We pipe it via stdin to `sudo -S`,
        # which keeps it out of any process listing.
        client.connect(
            hostname=host, username=user, timeout=10,
            allow_agent=True, look_for_keys=True,
        )
    except Exception as e:
        _fail(f"Couldn't connect to {host} to set up sudo: {e}")
        return False

    # Bake the rule into the bash -c argument so stdin is reserved purely
    # for the password. (Earlier version piped the rule through stdin to
    # `tee`, but sudo only consumes the first stdin line as its password —
    # everything after that gets written to the file along with the rule,
    # which trips a sudoers syntax error like `:2:9: syntax error`.)
    rule_line = f"{user} ALL=(ALL) NOPASSWD:ALL"
    sudoers_path = f"/etc/sudoers.d/cf-install-{user}"
    inner = (
        f"printf '%s\\n' {shlex.quote(rule_line)} > {sudoers_path} "
        f"&& chmod 0440 {sudoers_path}"
    )
    sudo_cmd = f"sudo -S -p '' bash -c {shlex.quote(inner)}"
    try:
        stdin, stdout, stderr = client.exec_command(sudo_cmd, timeout=15)
        stdin.write(password + "\n")
        stdin.flush()
        stdin.channel.shutdown_write()
        rc = stdout.channel.recv_exit_status()
        err = stderr.read().decode(errors="replace").strip()
    except Exception as e:
        client.close()
        _fail(f"Failed to install temp sudoers rule: {e}")
        return False
    finally:
        client.close()

    if rc != 0:
        _fail(f"Couldn't install temp sudoers rule (rc={rc}): {err}")
        return False
    _ok("Temporary passwordless sudo installed (will be removed after install).")
    return True


def write_target_file(cfg: dict) -> None:
    """Write pi_target.json for the rio's orangepi_pusher to read post-deploy.

    The rio doesn't know the Pi's user/IP/install dir — we write them into
    a file at the repo root that gets shipped with the rest of the project
    on the next `robotpy deploy`.
    """
    team = _read_team_number() or "1279"
    n = int(team)
    static_ip = f"10.{n // 100}.{n % 100}.11"
    payload = {
        "host": static_ip,
        "user": cfg.get("user", DEFAULT_USER),
        "install_dir": INSTALL_DIR,
        # The hostname the user originally typed during setup, so the rio can
        # fall back to mDNS if static IP routing breaks for some reason.
        "fallback_host": cfg.get("host", DEFAULT_HOST),
    }
    TARGET_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    _ok(f"Wrote pi_target.json (rio will reach Pi at {static_ip}).")


def setup_cross_ssh(cfg: dict) -> None:
    """Install passwordless SSH between the Pi and the rio (both directions).

    The laptop already trusts both hosts (the user typed Pi's password
    earlier in this run; the rio's `admin` account has no password by
    default). We use that trust to:
      1. Generate an ed25519 keypair on the Pi if one doesn't exist.
      2. Read the Pi's public key and append it to the rio's
         /home/admin/.ssh/authorized_keys (so Pi → rio works as admin).
      3. Generate keypairs on the rio for *both* admin and lvuser. lvuser
         is the account robot code runs as — without its key on the Pi,
         the rio's orangepi_pusher.py would prompt for a password and
         hang the daemon thread. Admin's key is for human SSH from the Pi.
      4. Read each rio public key and append it to the Pi's
         /home/orangepi/.ssh/authorized_keys.

    Idempotent — uses `grep -qxF || echo` so re-running doesn't dupe
    entries. Skips silently if the rio isn't reachable; the Pi side
    still works without rio trust, and the user can rerun later.
    """
    _step("Setting up Pi ↔ rio passwordless SSH")

    rio_host = _find_rio_host()
    if rio_host is None:
        _info("rio not reachable — skipping cross-host SSH for now.")
        _info("Run setup again once you're on the robot's WiFi to finish.")
        return

    pi_target = ssh_target(cfg)
    rio_target = f"{RIO_USER}@{rio_host}"

    # ---- Pi → rio (admin) ----
    pi_pub = _ensure_ssh_key_remote(pi_target, key_path="~/.ssh/id_ed25519")
    if pi_pub:
        _push_authorized_key(rio_target, pi_pub, label="Pi key on rio")

    # ---- rio admin → Pi ----
    rio_admin_pub = _ensure_ssh_key_remote(
        rio_target, key_path="/home/admin/.ssh/id_ed25519"
    )
    if rio_admin_pub:
        _push_authorized_key(pi_target, rio_admin_pub, label="rio-admin key on Pi")

    # ---- rio lvuser → Pi (the important one for auto-push) ----
    # admin has passwordless sudo on the rio; we use it to manage lvuser's
    # ssh dir without asking for lvuser's password (which the rio doesn't have).
    rio_lvuser_pub = _ensure_ssh_key_remote_as_other_user(
        rio_target, target_user=RIO_ROBOT_USER, key_path="/home/lvuser/.ssh/id_ed25519",
    )
    if rio_lvuser_pub:
        _push_authorized_key(pi_target, rio_lvuser_pub, label="rio-lvuser key on Pi")


def _find_rio_host() -> str | None:
    """Reuse deploy.py's address candidates to locate a reachable rio."""
    try:
        from deploy import _rio_addresses_for_team_setup  # type: ignore
    except Exception:
        _rio_addresses_for_team_setup = None  # noqa
    team = _read_team_number() or "1279"
    candidates = [
        f"roborio-{team}-FRC.local",
        f"10.{int(team) // 100}.{int(team) % 100}.2",
        "172.22.11.2",
    ]
    for host in candidates:
        if ping(host):
            return host
    return None


def _ensure_ssh_key_remote(ssh_target_str: str, key_path: str) -> str | None:
    """SSH to host, generate a key if missing, return the public key string."""
    pub_path = f"{key_path}.pub"
    cmd = (
        f'[ -f {pub_path} ] || ssh-keygen -t ed25519 -N "" -f {key_path} -q; '
        f"cat {pub_path}"
    )
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new",
             ssh_target_str, cmd],
            capture_output=True, text=True, timeout=20,
        )
    except Exception as e:
        _fail(f"Couldn't read SSH key from {ssh_target_str}: {e}")
        return None
    if result.returncode != 0:
        _fail(f"SSH key generation on {ssh_target_str} failed: {result.stderr.strip()}")
        return None
    pub = result.stdout.strip()
    if not pub.startswith("ssh-"):
        _fail(f"Unexpected key output from {ssh_target_str}: {pub[:80]!r}")
        return None
    _ok(f"Got SSH key from {ssh_target_str}")
    return pub


def _ensure_ssh_key_remote_as_other_user(
    ssh_target_str: str, target_user: str, key_path: str,
) -> str | None:
    """SSH as the login user, sudo to `target_user`, generate/read its key.

    Used to bootstrap an SSH key for `lvuser` on the rio: we log in as
    `admin` (which has passwordless sudo) and run ssh-keygen / cat as
    `lvuser` so the resulting files end up owned by lvuser, in
    /home/lvuser/.ssh. Without this, robot code (which runs as lvuser)
    couldn't SSH the Pi.
    """
    pub_path = f"{key_path}.pub"
    # `sudo -u lvuser` runs the command as lvuser. The shell expansion of
    # `~` happens after sudo, so it resolves to lvuser's home, not admin's.
    # We chain mkdir → keygen-if-missing → cat. install -d gives us a
    # 700-mode .ssh dir with the right ownership without futzing with chown.
    cmd = (
        f'sudo install -d -o {target_user} -g {target_user} -m 700 '
        f'/home/{target_user}/.ssh && '
        f'sudo -u {target_user} sh -c \''
        f'[ -f {pub_path} ] || ssh-keygen -t ed25519 -N "" -f {key_path} -q\' && '
        f'sudo cat {pub_path}'
    )
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new",
             ssh_target_str, cmd],
            capture_output=True, text=True, timeout=20,
        )
    except Exception as e:
        _fail(f"Couldn't read {target_user}'s SSH key: {e}")
        return None
    if result.returncode != 0:
        _fail(f"Generating {target_user}'s SSH key failed: {result.stderr.strip()}")
        return None
    pub = result.stdout.strip()
    if not pub.startswith("ssh-"):
        _fail(f"Unexpected key output for {target_user}: {pub[:80]!r}")
        return None
    _ok(f"Got SSH key for {target_user}@rio")
    return pub


def _push_authorized_key(dest_target: str, pubkey: str, label: str) -> None:
    """Append `pubkey` to ~/.ssh/authorized_keys on dest if not already there."""
    # Quote the key for the remote shell. The key never contains single quotes,
    # so single-quoting is enough; we still belt-and-braces with shlex.quote.
    quoted = shlex.quote(pubkey)
    # mkdir -p first; some images ship without ~/.ssh existing.
    cmd = (
        f'mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && '
        f'chmod 600 ~/.ssh/authorized_keys && '
        f'grep -qxF {quoted} ~/.ssh/authorized_keys || '
        f'echo {quoted} >> ~/.ssh/authorized_keys'
    )
    try:
        rc = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new",
             dest_target, cmd],
            capture_output=True, text=True, timeout=20,
        ).returncode
    except Exception as e:
        _fail(f"Failed to push {label}: {e}")
        return
    if rc == 0:
        _ok(f"Installed {label}")
    else:
        _fail(f"Failed to install {label} (rc={rc})")


def write_team(cfg: dict) -> None:
    """Push the rio team number into the Pi's sight.env so it auto-finds NT."""
    target = ssh_target(cfg)
    team = _read_team_number() or "1279"
    env_line = f"TEAM={team}"
    # sight.env is created by install.sh as the login user (`cat > ... <<EOF`),
    # so it's user-owned — no sudo needed for sed/tee. The `systemctl restart`
    # is the one privileged op, and install.sh installs a NOPASSWD sudoers
    # rule scoped to exactly that command, so it works without a password.
    cmd = (
        f"sed -i.bak '/^TEAM=/d' {INSTALL_DIR}/sight.env && "
        f"echo {shlex.quote(env_line)} >> {INSTALL_DIR}/sight.env && "
        f"sudo systemctl restart cold-fusion-sight"
    )
    _stream(["ssh", "-t", target, cmd])


def _read_team_number() -> str | None:
    """Reuse deploy.py's logic so the Pi gets the same team the rio uses."""
    try:
        from deploy import read_team_number
    except Exception:
        return None
    return read_team_number()


# ----- main flow -----

def _logic() -> int:
    if ui_mode.is_active():
        ui_mode.get_app().banner("Vision Pi", "set up the Orange Pi sight system")

    cfg = load_cfg()
    gathered = gather_config(cfg)
    if gathered is None:
        _fail("Setup cancelled.")
        return 1
    cfg, password = gathered

    if not check_reachable(cfg):
        return 1

    # Get key auth working before anything that uses SSH (push_files,
    # remote_install, write_team, setup_cross_ssh) — those all rely on
    # passwordless ssh / rsync.
    if not bootstrap_ssh_key(cfg, password):
        return 1

    # Probe the Pi (Python version + arch + which apt deps are missing).
    # Saved into .orangepi_cfg so the next `python setup.py` run on home
    # WiFi knows what Python/arch to download wheels for.
    pi_env = detect_pi_env(cfg)
    if pi_env is None:
        return 1

    # Verify the wheel cache that setup.py was supposed to have staged
    # while on internet. If it's missing/stale, we tell the user to run
    # setup.py on home WiFi and stop here.
    if not check_pi_wheel_cache(pi_env):
        return 1

    if not push_files(cfg):
        return 1

    # If apt packages are missing, briefly bridge the Pi's wlan0 to a
    # user-supplied WiFi (laptop's robot-network connection stays put).
    # We need temp NOPASSWD set up first since the bridge uses sudo for
    # nmcli + apt-get. Set it up here so it's available across both
    # bridge_internet_for_apt and run_remote_install.
    if pi_env.get("apt_missing"):
        if not _try_install_temp_nopasswd(cfg, password):
            _fail("Couldn't grant temporary sudo — re-run setup and enter password.")
            return 1
        if not bridge_internet_for_apt(cfg, pi_env["apt_missing"]):
            _remove_temp_nopasswd(cfg)
            return 1
        # Apt deps are now installed — tell install.sh to skip the apt step.
        pi_env["apt_missing"] = []

    # Pass the password through to the install step so we can grant
    # temporary passwordless sudo for apt/systemctl. Drop it from memory
    # immediately afterwards — _remove_temp_nopasswd uses key auth, not
    # the password.
    install_ok = run_remote_install(cfg, password=password, pi_env=pi_env)
    password = None  # noqa: F841
    if not install_ok:
        # Best effort: still try to clean up the NOPASSWD rule even if
        # install.sh itself failed midway.
        _remove_temp_nopasswd(cfg)
        return 1

    write_team(cfg)
    write_target_file(cfg)
    setup_cross_ssh(cfg)

    # All sudo-using steps are done; revoke the temporary NOPASSWD rule.
    _remove_temp_nopasswd(cfg)

    url = f"http://{cfg['host']}:8080/"
    _ok(f"Pi running. Open {url} in a browser.")
    if ui_mode.is_active():
        ui_mode.get_app().set_followup(
            "Open Sight UI",
            lambda: _open_browser(url),
            prompt=f"The Pi is up at {url}.",
        )
    return 0


def _open_browser(url: str) -> None:
    import webbrowser
    webbrowser.open(url)


def main() -> int:
    if "--ui" in sys.argv[1:]:
        sys.argv = [a for a in sys.argv if a != "--ui"]
        if ui_mode.HAS_TK:
            app = ui_mode.activate("Vision Pi", "set up the Orange Pi sight system")
            return app.run(_logic)
    return _logic()


if __name__ == "__main__":
    sys.exit(main())
