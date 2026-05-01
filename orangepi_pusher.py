"""Push the deployed orangepi/ folder from the rio to the Pi over SSH.

Why this exists
---------------
robotpy `deploy` uploads the *entire* project to /home/lvuser/py/ on the
rio, including the `orangepi/` subdirectory. We don't want the user to
have to ALSO run a "deploy to Pi" step from their laptop on every code
change — once the rio has the latest files it can hand them off itself.

So: every robot startup, this module checks whether the deployed
orangepi/ contents differ from what the Pi already has. If they do, it
ships a tarball over SSH and asks the Pi to restart its service.

How it works
------------
1. Hash the local /home/lvuser/py/orangepi/ directory.
2. SSH to the Pi (as `orangepi` using the lvuser key set up by
   setup_orangepi.py) and read /home/orangepi/cold-fusion-sight/.deploy_hash.
3. If it differs (or the Pi is fresh / unreachable / hash file is
   missing): tar | ssh "tar -x" the orangepi/ tree onto the Pi, write
   the new hash, and `sudo systemctl restart cold-fusion-sight`.

Everything is best-effort:
- runs in a daemon thread, never blocks robotInit.
- swallows all errors, logs them, never raises into robot code.
- skips silently in the simulator (no /home/lvuser/py/orangepi/).

The roboRIO's NI image has openssh-client (`ssh`, `scp`) and `tar`.
It does *not* have rsync, which is why we use the tar-pipe pattern.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

# Where robotpy unpacks the project on the rio. Same path on every NI image.
_DEPLOY_ROOT = Path("/home/lvuser/py")
_LOCAL_DIR = _DEPLOY_ROOT / "orangepi"
# Where the Pi keeps the running copy. Must match install.sh.
_REMOTE_DIR = "/home/orangepi/cold-fusion-sight"
_REMOTE_HASH_FILE = ".deploy_hash"
_REMOTE_SERVICE = "cold-fusion-sight"

# pi_target.json lives at the project root and is written by
# setup_orangepi.py. It survives `robotpy deploy` because robotpy ships
# every non-pyc file under the project (the leading dot is what gets
# excluded, so we don't use one).
_TARGET_FILE = _DEPLOY_ROOT / "pi_target.json"
# Fallback if the file is missing — assumes team 1279, default user/dir.
# The user-visible setup script writes the real values; this just keeps
# the rio from crashing when the file isn't there yet.
_DEFAULT_TARGET = {
    "host": "10.12.79.11",
    "user": "orangepi",
    "install_dir": _REMOTE_DIR,
}

# SSH options for unattended use. StrictHostKeyChecking=accept-new lets the
# first connection succeed and pin the key; later runs verify. We use a tight
# ConnectTimeout so a missing Pi doesn't stall robot startup for a minute.
_SSH_BASE = [
    "ssh",
    "-o", "BatchMode=yes",                    # never prompt
    "-o", "StrictHostKeyChecking=accept-new", # TOFU; pins key on first run
    "-o", "ConnectTimeout=5",
    "-o", "ServerAliveInterval=10",
    "-i", "/home/lvuser/.ssh/id_ed25519",     # the key Pi setup installed
]


def _log(msg: str) -> None:
    # Plain print — robotpy captures stdout into the rio log.
    print(f"[orangepi-pusher] {msg}", flush=True)


def _read_target() -> dict:
    """Read pi_target.json from the deploy, falling back to defaults."""
    try:
        with open(_TARGET_FILE) as f:
            data = json.load(f)
    except Exception as e:
        _log(f"no pi_target.json ({e}); using defaults")
        return dict(_DEFAULT_TARGET)
    return {**_DEFAULT_TARGET, **data}


def _hash_dir(root: Path) -> str:
    """Stable SHA-256 of every file under `root`. Sort-then-stream so two
    machines compute the same digest for the same tree."""
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        # Don't hash the venv or pycache from a previous local run.
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".venv/") or "__pycache__" in rel or rel.endswith(".pyc"):
            continue
        h.update(rel.encode())
        h.update(b"\0")
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    return h.hexdigest()


def _ssh(target: dict, remote_cmd: str, *, timeout: int = 30) -> tuple[int, str, str]:
    """Run `remote_cmd` on the Pi over SSH; return (rc, stdout, stderr)."""
    cmd = _SSH_BASE + [f"{target['user']}@{target['host']}", remote_cmd]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", f"ssh-launch-failed: {e}"
    return result.returncode, result.stdout, result.stderr


def _read_remote_hash(target: dict) -> str | None:
    rc, out, _ = _ssh(
        target,
        f"cat {target['install_dir']}/{_REMOTE_HASH_FILE} 2>/dev/null || true",
        timeout=15,
    )
    if rc != 0:
        return None
    h = out.strip()
    return h or None


def _push_tree(target: dict, local_dir: Path, new_hash: str) -> bool:
    """tar | ssh "tar -x" the local_dir contents into target's install_dir.

    Followed by writing the hash file and restarting the service. Excludes
    .venv and pycache since they're rio-specific noise.
    """
    # Build the tar locally and stream into a remote tar that extracts.
    tar_cmd = [
        "tar", "-czf", "-",
        "--exclude=.venv",
        "--exclude=__pycache__",
        "--exclude=*.pyc",
        "-C", str(local_dir),
        ".",
    ]
    remote_cmd = (
        f"set -e; "
        f"mkdir -p {target['install_dir']}; "
        f"tar -xzf - -C {target['install_dir']}; "
        # Hash file is the last write so an interrupted push doesn't look
        # complete. The Pi's next boot will see the old hash and re-pull.
        f"echo {new_hash} > {target['install_dir']}/{_REMOTE_HASH_FILE}; "
        f"sudo systemctl restart {_REMOTE_SERVICE}"
    )
    ssh_cmd = _SSH_BASE + [f"{target['user']}@{target['host']}", remote_cmd]
    try:
        tar_proc = subprocess.Popen(tar_cmd, stdout=subprocess.PIPE)
        ssh_proc = subprocess.Popen(ssh_cmd, stdin=tar_proc.stdout)
        tar_proc.stdout.close()  # let tar receive SIGPIPE if ssh dies
        rc = ssh_proc.wait(timeout=120)
        tar_rc = tar_proc.wait(timeout=10)
    except Exception as e:
        _log(f"push failed mid-stream: {e}")
        return False
    if rc != 0 or tar_rc != 0:
        _log(f"push failed (ssh rc={rc}, tar rc={tar_rc})")
        return False
    return True


def _push_once() -> None:
    if not _LOCAL_DIR.is_dir():
        _log(f"no orangepi/ at {_LOCAL_DIR} (sim or stripped deploy); skipping")
        return
    target = _read_target()
    _log(f"target: {target['user']}@{target['host']}:{target['install_dir']}")

    local_hash = _hash_dir(_LOCAL_DIR)
    _log(f"local hash:  {local_hash[:12]}…")

    remote_hash = _read_remote_hash(target)
    if remote_hash is None:
        _log("Pi unreachable or no hash on Pi — pushing fresh copy")
    elif remote_hash == local_hash:
        _log("Pi already up to date — skipping push")
        return
    else:
        _log(f"Pi hash:     {remote_hash[:12]}…  (differs; pushing)")

    if _push_tree(target, _LOCAL_DIR, local_hash):
        _log("push complete; service restarted on Pi")
    else:
        _log("push did not complete — UI may be stale until next deploy")


# Module-level guard so calling start() twice doesn't kick off two threads.
_started = False


def start() -> None:
    """Kick off the push in a daemon thread. Safe to call from robotInit."""
    global _started
    if _started:
        return
    _started = True
    # Skip in the simulator or any non-rio environment — there's no Pi to
    # push to and the SSH call would hang on a missing key.
    if not sys.platform.startswith("linux") or not _LOCAL_DIR.exists():
        _log("not on rio (no /home/lvuser/py/orangepi/); skipping pusher")
        return
    threading.Thread(
        target=_push_once, name="orangepi-pusher", daemon=True,
    ).start()
