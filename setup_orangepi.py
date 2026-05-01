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
            *(str(p) for p in ORANGEPI_DIR.iterdir()
              if p.name not in (".venv", "__pycache__")),
            f"{target}:{INSTALL_DIR}/",
        ])
    if rc != 0:
        _fail("File transfer failed.")
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


def run_remote_install(cfg: dict) -> bool:
    _step("Installing on the Pi (apt + venv + systemd + static IP)")
    target = ssh_target(cfg)
    team = _read_team_number() or "1279"
    # install.sh reads $TEAM and pins the static IP at 10.TE.AM.11.
    install_cmd = (
        f"cd {shlex.quote(INSTALL_DIR)} && "
        f"TEAM={shlex.quote(team)} bash install.sh"
    )
    rc = _stream(["ssh", "-t", target, install_cmd])
    if rc != 0:
        _fail("Remote install failed; check the details panel.")
        return False
    _ok("Service installed and started.")
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
    # Drop the password from memory now that keys are in place.
    password = None  # noqa: F841

    if not push_files(cfg):
        return 1

    if not run_remote_install(cfg):
        return 1

    write_team(cfg)
    write_target_file(cfg)
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
