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

DEFAULT_USER = "orangepi"
DEFAULT_HOST = "orangepi.local"
INSTALL_DIR = "/home/orangepi/cold-fusion-sight"

# rio SSH details. The roboRIO ships with `admin` (no password) on port 22.
RIO_USER = "admin"


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

def gather_config(cfg: dict) -> dict | None:
    """Ask for / confirm the Pi's user@host. Saved to .orangepi_cfg."""
    host = _ask_string(
        "Pi hostname or IP", default=cfg.get("host", DEFAULT_HOST)
    )
    if not host:
        return None
    user = _ask_string("Pi SSH user", default=cfg.get("user", DEFAULT_USER))
    if not user:
        return None
    cfg = dict(cfg)
    cfg["user"] = user
    cfg["host"] = host
    save_cfg(cfg)
    return cfg


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
            "rsync", "-az", "--delete", "--exclude=.venv", "--exclude=__pycache__",
            f"{ORANGEPI_DIR}/", f"{target}:{INSTALL_DIR}/",
        ])
    else:
        # Fall back to scp -r. Requires the install dir to exist first.
        if _stream([
            "ssh", target, f"mkdir -p {shlex.quote(INSTALL_DIR)}",
        ]) != 0:
            _fail("Couldn't create install directory on the Pi.")
            return False
        rc = _stream([
            "scp", "-r",
            *(str(p) for p in ORANGEPI_DIR.iterdir() if p.name != ".venv"),
            f"{target}:{INSTALL_DIR}/",
        ])
    if rc != 0:
        _fail("File transfer failed.")
        return False
    _ok("Files copied.")
    return True


def run_remote_install(cfg: dict) -> bool:
    _step("Installing on the Pi (apt + venv + systemd)")
    target = ssh_target(cfg)
    rc = _stream([
        "ssh", "-t", target,
        f"cd {shlex.quote(INSTALL_DIR)} && bash install.sh",
    ])
    if rc != 0:
        _fail("Remote install failed; check the details panel.")
        return False
    _ok("Service installed and started.")
    return True


def setup_cross_ssh(cfg: dict) -> None:
    """Install passwordless SSH between the Pi and the rio (both directions).

    The laptop already trusts both hosts (the user typed Pi's password
    earlier in this run; the rio's `admin` account has no password by
    default). We use that trust to:
      1. Generate an ed25519 keypair on the Pi if one doesn't exist.
      2. Read the Pi's public key and append it to the rio's
         /home/admin/.ssh/authorized_keys.
      3. Generate an ed25519 keypair on the rio if one doesn't exist.
      4. Read the rio's public key and append it to the Pi's
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

    pi_pub = _ensure_ssh_key_remote(pi_target, key_path="~/.ssh/id_ed25519")
    if pi_pub:
        _push_authorized_key(rio_target, pi_pub, label="Pi key on rio")

    rio_pub = _ensure_ssh_key_remote(rio_target, key_path="/home/admin/.ssh/id_ed25519")
    if rio_pub:
        _push_authorized_key(pi_target, rio_pub, label="rio key on Pi")


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
    # Replace any existing TEAM= line atomically; create if missing.
    cmd = (
        f"sudo sed -i.bak '/^TEAM=/d' {INSTALL_DIR}/sight.env && "
        f"echo {shlex.quote(env_line)} | sudo tee -a {INSTALL_DIR}/sight.env >/dev/null && "
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
    cfg = gather_config(cfg)
    if cfg is None:
        _fail("Setup cancelled.")
        return 1

    if not check_reachable(cfg):
        return 1

    if not push_files(cfg):
        return 1

    if not run_remote_install(cfg):
        return 1

    write_team(cfg)
    setup_cross_ssh(cfg)

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
