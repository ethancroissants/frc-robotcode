#!/usr/bin/env python3
"""Forcibly reinstall RobotPy + project deps on the roboRIO.

Use this when a previous deploy left the rio in a broken state — e.g. the
`robotpy-native-wpihal` package has version `None` so `import wpilib` fails
with "libwpiHal.so: cannot open shared object file".

The flow mirrors what `robotpy deploy` does internally when packages
mismatch (see robotpy_installer.cli_deploy._ensure_requirements):

  1. Kill the running robot program.
  2. Run `ensurepip` over SSH — defensive recovery in case a prior wipe
     deleted pip itself. ensurepip is in stdlib so it always works.
  3. `python -m robotpy installer install --force-reinstall --ignore-installed`
     pushes wheels from the local cache (populated by setup.py's
     `robotpy sync`) and overwrites any corrupt/half-installed packages.

We deliberately do NOT `rm -rf` site-packages anymore — that wiped pip
itself and made future `installer install` calls fail with
"No module named pip". `pip --force-reinstall` handles corrupt installs
cleanly without ever needing to bootstrap pip from scratch.

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
RIO_PYTHON = "/usr/local/bin/python3"
RIO_KILL_ROBOT = "/usr/local/frc/bin/frcKillRobot.sh"


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


def ssh_run(host: str, command: str, *, timeout: int = 180) -> tuple[int, str]:
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
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        combined = (out + err).strip()
        return rc, combined
    finally:
        client.close()


# Run on the rio over SSH. We use absolute paths because non-interactive
# SSH sessions on the rio don't get /usr/local/bin in PATH (login-shell
# profile.d scripts don't run), so plain `python3` is "command not found".
#
# We don't try to bootstrap pip here — the rio's Python is a slimmed-down
# build that omits `ensurepip`, so pip can only be (re)installed via opkg.
# That's done by the install-python step below.
_PREP_SCRIPT = (
    f"{RIO_KILL_ROBOT} -t 2>/dev/null || true; "
    "rm -rf /home/lvuser/py /home/lvuser/.cache 2>/dev/null || true; "
    "echo prep_done"
)


def _read_rio_packages() -> list[str]:
    """Return the list of packages to push to the rio.

    Includes a pinned `robotpy==<version>` (from `[tool.robotpy].robotpy_version`)
    plus everything in `[tool.robotpy].requires`. Reading pyproject.toml directly
    means we never have to call out to pypi to learn what to install.
    """
    try:
        import tomllib  # py3.11+
    except ImportError:
        import tomli as tomllib  # type: ignore

    pyproject = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pyproject.toml")
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    rp = data.get("tool", {}).get("robotpy", {})
    pkgs: list[str] = []
    version = rp.get("robotpy_version")
    pkgs.append(f"robotpy=={version}" if version else "robotpy")
    pkgs.extend(rp.get("requires", []))
    return pkgs


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
        "force-reinstall robotpy + project deps",
        color=_d.red,
    )

    team = _d.read_team_number()
    if team:
        _d.info(f"Detected team number: {_d.bold(team)}")
    else:
        _d.fail("No team number configured. Run Install/Setup first.")
        return 1

    _d.warn("This will force-reinstall every Python package on the roboRIO,")
    _d.warn("overwriting any corrupt or half-installed packages from a prior deploy.")
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

    _d.step("Preparing the rio")
    _d.info("(killing robot, clearing /home/lvuser/py, ensuring pip is alive)")
    try:
        rc, out = ssh_run(host, _PREP_SCRIPT)
    except Exception as e:
        _d.fail(f"SSH failed: {e}")
        return 1
    if out:
        for line in out.splitlines():
            _d.info(line)
    if rc != 0:
        _d.fail(f"Prep script exited {rc}")
        return rc
    _d.ok("Rio prepped.")

    # The rio's pip is shipped inside the python opkg package. If a previous
    # bad wipe deleted pip itself (No module named pip), the only way to
    # restore it is to opkg-uninstall and reinstall Python. uninstall-python
    # is idempotent (won't error if already gone), and install-python pulls
    # the .ipk from the laptop cache, so this works offline.
    _d.step("Reinstalling Python on the rio (restores pip)")
    rc = run_local([
        sys.executable, "-m", "robotpy", "installer", "uninstall-python",
    ])
    if rc != 0:
        # Don't fail hard here — uninstall may legitimately error if Python
        # was already gone, and install-python below will surface real issues.
        _d.warn(f"uninstall-python exited {rc} (continuing anyway)")
    rc = run_local([
        sys.executable, "-m", "robotpy", "installer", "install-python",
    ])
    if rc != 0:
        _d.fail(f"install-python exited {rc}")
        _d.info("If 'python ipk not downloaded', run Install/Setup once")
        _d.info("on a machine with internet to populate the cache.")
        return rc

    _d.step("Force-reinstalling packages on the rio")
    pkgs = _read_rio_packages()
    if not pkgs:
        _d.fail("No packages found in pyproject.toml [tool.robotpy]")
        return 1
    for p in pkgs:
        _d.info(f"- {p}")
    # --force-reinstall: pip wipes each package's existing files before
    #   writing the new ones, fixing any half-installed metadata.
    # --ignore-installed: don't trust metadata that says a package is up to
    #   date; reinstall regardless.
    # No pypi calls — wheels come from the local cache that setup.py
    # populates via `robotpy sync`.
    rc = run_local([
        sys.executable, "-m", "robotpy", "installer", "install",
        "--force-reinstall", "--ignore-installed",
        *pkgs,
    ])
    if rc != 0:
        _d.fail(f"installer install exited {rc}")
        _d.info("If this is a 'no matching distribution' error, run")
        _d.info("Install/Setup once on a machine with internet to populate the cache.")
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
