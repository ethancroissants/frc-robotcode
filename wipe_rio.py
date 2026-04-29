#!/usr/bin/env python3
"""Wipe the roboRIO's Python install, then reinstall robotpy + project deps.

Use this when a previous deploy left the rio in a broken state — e.g. the
site-packages tree is half-populated and `import wpilib` fails with
"libwpiHal.so: cannot open shared object file". Wiping forces robotpy to
push fresh wheels for everything in pyproject.toml.

After this finishes, run Deploy to push the actual robot code.
"""

from __future__ import annotations

import os
import subprocess
import sys

import deploy as _d
import ui_mode


SSH_USER = "admin"
SSH_PASSWORD = ""  # default for the rio admin account


def find_rio(team: str | None) -> str | None:
    """Return the first rio address that answers a ping, or None."""
    if not team or not team.isdigit():
        return None
    candidates = [
        f"roborio-{team}-FRC.local",
        f"10.{int(team) // 100}.{int(team) % 100}.2",
        "172.22.11.2",  # USB tether
    ]
    for host in candidates:
        if _d.ping(host, timeout_s=1.0):
            return host
    return None


def ssh_run(host: str, command: str) -> tuple[int, str]:
    """Run a command on the rio over SSH; return (exit_code, combined_output).

    Uses paramiko (ships with robotpy) so we don't need an OpenSSH client on
    the host machine. The rio admin account has an empty password by default.
    """
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        username=SSH_USER,
        password=SSH_PASSWORD,
        look_for_keys=False,
        allow_agent=False,
        timeout=10,
    )
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=120)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        combined = (out + err).strip()
        return rc, combined
    finally:
        client.close()


_WIPE_SCRIPT = (
    # Stop the running user program first so we don't fight a live process.
    "/usr/local/frc/bin/frcKillRobot.sh -t 2>/dev/null || true; "
    # Nuke every site-packages on the rio (covers any python3.x version).
    # Busybox `find` on the rio has no -delete, so just rm -rf the whole
    # dir and recreate an empty one so pip can repopulate it.
    "for d in /usr/local/lib/python*/site-packages; do "
    "  [ -d \"$d\" ] && rm -rf \"$d\" && mkdir -p \"$d\"; "
    "done; "
    # Clear the deployed code dir + pip cache so the next deploy is clean.
    "rm -rf /home/lvuser/py /home/lvuser/.cache 2>/dev/null; "
    "echo done"
)


def run_local(cmd: list[str]) -> int:
    """Run a host-side command, streaming output to the UI or terminal."""
    if ui_mode.is_active():
        return ui_mode.get_app().stream_subprocess(cmd)
    _d.info(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd)


def main() -> int:
    extra = list(sys.argv[1:])
    if "--ui" in extra:
        extra.remove("--ui")
        if not ui_mode.HAS_TK:
            print("UI mode requested but tkinter is unavailable; using terminal.")
        else:
            app = ui_mode.activate("Wipe RoboRIO", "fresh-install python on the rio")
            return app.run(_logic)
    return _logic()


def _logic() -> int:
    _d.banner(
        "Wipe RoboRIO",
        "fresh-install python on the rio",
        color=_d.red,
    )

    team = _d.read_team_number()
    if team:
        _d.info(f"Detected team number: {_d.bold(team)}")
    else:
        _d.fail("No team number configured. Run Install/Setup first.")
        return 1

    _d.warn("This will UNINSTALL every Python package on the roboRIO,")
    _d.warn("then reinstall robotpy + your pyproject.toml requirements.")
    if not _d.ask_yn("Continue?", default=False):
        _d.info("Aborted.")
        return 1

    _d.step("Locating robot")
    host = find_rio(team)
    if not host:
        _d.fail("No rio reachable on the usual addresses.")
        _d.info("Connect to the robot's WiFi (or USB tether) and try again.")
        return 1
    _d.ok(f"Robot at {_d.bold(host)}")

    _d.step("Wiping Python on the rio")
    _d.info("(stopping robot program + clearing site-packages)")
    try:
        rc, out = ssh_run(host, _WIPE_SCRIPT)
    except Exception as e:
        _d.fail(f"SSH failed: {e}")
        return 1
    if out:
        for line in out.splitlines():
            _d.info(line)
    if rc != 0:
        _d.fail(f"Wipe command exited {rc}")
        return rc
    _d.ok("Rio Python tree cleared.")

    _d.step("Pushing wheels to the rio (robotpy sync)")
    _d.info("Uses the cache populated by setup.py — internet not required")
    _d.info("as long as you've run Install/Setup at least once.")
    # `robotpy sync` reads pyproject.toml itself (unlike `installer install -r`
    # which expects requirements.txt syntax). --no-install skips the local
    # pip step since setup.py already handled that. --use-certifi matches what
    # setup.py uses so SSL works on Windows.
    rc = run_local([
        sys.executable, "-m", "robotpy", "sync",
        "--use-certifi", "--no-install",
    ])
    if rc != 0:
        _d.fail(f"robotpy sync exited {rc}")
        _d.info("If this is a 'cannot download' error, run Install/Setup")
        _d.info("once on a machine with internet to populate the wheel cache.")
        return rc

    _d.banner(
        "Wipe Complete",
        "now click Deploy to push your code",
        color=_d.green,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
