#!/usr/bin/env python3
"""Deploy the robot code to the roboRIO with an interactive UI.

Any extra arguments are forwarded to `robotpy deploy`. Example:

    python deploy.py --skip-tests
    python deploy.py --nc
"""

import os
import platform
import shutil
import subprocess
import sys
import time

import firewall
import ui_mode


# -------- styling --------

def _enable_ansi() -> None:
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            pass


_enable_ansi()
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass
_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def bold(t): return _c("1", t)
def dim(t): return _c("2", t)
def red(t): return _c("31", t)
def green(t): return _c("32", t)
def yellow(t): return _c("33", t)
def blue(t): return _c("34", t)
def magenta(t): return _c("35", t)
def cyan(t): return _c("36", t)


def _width() -> int:
    try:
        return min(shutil.get_terminal_size((80, 24)).columns, 78)
    except Exception:
        return 72


def banner(title: str, subtitle: str = "", color=cyan) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().banner(title, subtitle)
        return
    w = _width()
    inner = w - 2
    top = "╔" + "═" * inner + "╗"
    bot = "╚" + "═" * inner + "╝"
    mid = "║" + " " * inner + "║"
    print(color(top))
    print(color(mid))
    pad = (inner - len(title)) // 2
    right = inner - len(title) - pad
    print(color("║") + " " * pad + bold(color(title)) + " " * right + color("║"))
    if subtitle:
        pad = (inner - len(subtitle)) // 2
        right = inner - len(subtitle) - pad
        print(color("║") + " " * pad + dim(subtitle) + " " * right + color("║"))
    print(color(mid))
    print(color(bot))
    print()


def rule(label: str = "", color=cyan) -> None:
    if ui_mode.is_active():
        return
    w = _width()
    if not label:
        print(color("─" * w))
        return
    prefix = color("── ") + bold(label) + " "
    tail = w - len(label) - 4
    print(prefix + color("─" * max(3, tail)))


def step(msg: str) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().step(msg)
        return
    print(f"\n{cyan('▶')} {bold(msg)}")


def ok(msg: str) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().ok(msg)
        return
    print(f"  {green('✓')} {msg}")


def fail(msg: str) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().fail(msg)
        return
    print(f"  {red('✗')} {msg}")


def warn(msg: str) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().warn(msg)
        return
    print(f"  {yellow('!')} {msg}")


def info(msg: str) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().info(msg)
        return
    print(f"  {dim('·')} {dim(msg)}")


def ask_yn(prompt: str, default: bool = False) -> bool:
    if ui_mode.is_active():
        return ui_mode.get_app().ask_yn(prompt, default)
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        ans = input(f"{magenta('?')} {bold(prompt)} {dim(suffix)} ").strip().lower()
    except EOFError:
        print()
        return default
    if not ans:
        return default
    return ans in ("y", "yes")


def pause(msg: str = "Press Enter to continue...") -> None:
    if ui_mode.is_active():
        ui_mode.get_app().pause(msg)
        return
    try:
        input(f"{yellow('⏸')}  {msg}")
    except EOFError:
        pass


# -------- deploy logic --------

def ping(host: str, timeout_s: float = 1.0) -> bool:
    if platform.system() == "Windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_s * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(timeout_s))), host]
    try:
        return subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode == 0
    except Exception:
        return False


DEFAULT_TEAM = "1279"


def read_team_number() -> str | None:
    for path in (
        ".deploy_cfg",
        ".wpilib/wpilib_preferences.json",
        "pyproject.toml",
    ):
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            continue
        import re
        m = re.search(r'"?team(?:[-_]?number|Number)?"?\s*[:=]\s*"?(\d+)', text)
        if m:
            return m.group(1)
    env = os.environ.get("FRC_TEAM") or os.environ.get("TEAM")
    if env and env.isdigit():
        return env
    # Fallback to team 1279 and persist it so robotpy's own deploy doesn't
    # prompt on stdin (which EOFs in our chained subprocess setup).
    try:
        save_team_number(DEFAULT_TEAM)
    except Exception:
        pass
    return DEFAULT_TEAM


def save_team_number(team: str) -> None:
    """Persist the team number to .wpilib/wpilib_preferences.json so robotpy
    (and other FRC tools) pick it up on the next run."""
    import json
    repo = os.path.dirname(os.path.abspath(__file__))
    prefs_dir = os.path.join(repo, ".wpilib")
    prefs_path = os.path.join(prefs_dir, "wpilib_preferences.json")
    os.makedirs(prefs_dir, exist_ok=True)
    data = {}
    if os.path.exists(prefs_path):
        try:
            with open(prefs_path) as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
    data["teamNumber"] = int(team)
    with open(prefs_path, "w") as f:
        json.dump(data, f, indent=2)


def ensure_team_number(team: str | None) -> str | None:
    """If we don't have a team number and we're in UI mode, ask the user.

    Without this, `robotpy deploy` would prompt on stdin — but in UI mode
    stdin is closed, so it would hang silently. Asking up front and saving
    the answer means robotpy never has to prompt at all.
    """
    if team or not ui_mode.is_active():
        return team
    answer = ui_mode.get_app().ask_string(
        "Enter your FRC team number:",
        default="",
        title="Team Number",
    )
    if not answer or not answer.isdigit():
        return None
    try:
        save_team_number(answer)
    except Exception as e:
        warn(f"Couldn't save team number: {e}")
    return answer


def check_connectivity(team: str | None) -> None:
    step("Checking robot connectivity")
    if not team:
        info("Team number unknown; robotpy will prompt if needed.")
        info("(set FRC_TEAM=#### to pre-configure)")
        return

    candidates = [
        f"roborio-{team}-FRC.local",
        f"roborio-{team}-FRC.lan",
        f"10.{int(team) // 100}.{int(team) % 100}.2",
        "172.22.11.2",  # USB tether
    ]
    info(f"Team {team} — trying {len(candidates)} addresses...")
    reached = None
    for host in candidates:
        if ping(host, timeout_s=1.0):
            reached = host
            break
    if reached:
        ok(f"Robot reachable at {bold(reached)}")
    else:
        warn("Could not reach the robot on any known address.")
        info("robotpy will still attempt to deploy and may succeed over a")
        info("slower / less-standard route. If deploy fails, check that:")
        info("  - You're on the robot's WiFi (or USB tethered)")
        info("  - The roboRIO is powered and fully booted (solid green 'RSL')")
        info("  - Firewall isn't blocking mDNS / port 22")


_LARGE_FILE_THRESHOLD = 250_000
# Mirrors robotpy_installer.cli_deploy._copy_to_tmpdir's filter, so the files
# we scan match the ones robotpy would upload.
_DEPLOY_IGNORE_DIRS = {"__pycache__", "ctre_sim", "venv"}
_DEPLOY_IGNORE_EXTS = frozenset({".pyc", ".whl", ".ipk", ".zip", ".gz", ".wpilog"})


def find_large_files(project_path: str) -> list[tuple[str, int]]:
    """Replicate robotpy's pre-deploy large-file scan so we can prompt the user
    ourselves. robotpy prompts on stdin, but in UI mode the subprocess has no
    stdin and the prompt EOFs — taking the answer up front avoids that."""
    found: list[tuple[str, int]] = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and d not in _DEPLOY_IGNORE_DIRS
        ]
        for filename in files:
            stem, ext = os.path.splitext(filename)
            if ext in _DEPLOY_IGNORE_EXTS or stem.startswith("."):
                continue
            full = os.path.join(root, filename)
            try:
                size = os.stat(full).st_size
            except OSError:
                continue
            if size > _LARGE_FILE_THRESHOLD:
                rel = os.path.relpath(full, project_path)
                found.append((rel, size))
    found.sort()
    return found


def handle_large_files(extra_args: list[str]) -> bool:
    """Returns False if the user declined to upload."""
    if "--large" in extra_args:
        return True
    project_path = os.path.dirname(os.path.abspath(__file__))
    large = find_large_files(project_path)
    if not large:
        return True
    warn(f"Found {len(large)} file(s) larger than {_LARGE_FILE_THRESHOLD} bytes:")
    for rel, sz in large[:10]:
        info(f"- {rel} ({sz} bytes)")
    if len(large) > 10:
        info(f"...and {len(large) - 10} more")
    if not ask_yn("Upload these large files anyway?", default=True):
        return False
    extra_args.append("--large")
    return True


def run_deploy(extra_args: list[str]) -> int:
    step("Sending code to the robot")
    info("This usually takes 30–90 seconds.")
    info("(any 'install/uninstall on roboRIO?' prompts auto-answered yes)")
    cmd = [sys.executable, "-m", "robotpy", "deploy", *extra_args]
    rc, output = _run_robotpy(cmd)

    # `robotpy deploy` aborts if the laptop's installed packages don't match
    # pyproject.toml — common after pulling a new requirement.
    # Auto-run `python -m robotpy sync` to install them, then retry the deploy
    # exactly once. The sync also updates the rio bundle robotpy will upload.
    if rc != 0 and _looks_like_sync_needed(output):
        info("")
        info("Local Python packages don't match pyproject.toml — running")
        info("`python -m robotpy sync` to install the missing ones, then retrying.")
        sync_rc = _run_robotpy_sync()
        if sync_rc == 0:
            info("Sync complete — re-running deploy.")
            rc, _ = _run_robotpy(cmd)
        else:
            info(f"`robotpy sync` exited with code {sync_rc}; not retrying.")
    return rc


def _run_robotpy(cmd: list[str]) -> tuple[int, str]:
    """Run robotpy in either UI or terminal mode, returning (rc, captured_output)."""
    t0 = time.monotonic()
    if ui_mode.is_active():
        captured: list[str] = []
        rc = ui_mode.get_app().stream_subprocess(cmd, capture=captured)
        output = "".join(captured)
    else:
        info(f"$ {' '.join(cmd)}")
        rule("live output", color=dim)
        sys.stdout.flush()
        try:
            rc, output = _spawn_with_yes_tee(cmd)
        except KeyboardInterrupt:
            rule("", color=dim)
            print()
            warn("Interrupted by user.")
            return 130, ""
        rule("", color=dim)
    elapsed = time.monotonic() - t0
    info(f"robotpy exited with code {rc} after {elapsed:.1f}s")
    return rc, output


def _looks_like_sync_needed(output: str) -> bool:
    return (
        "Locally installed packages do not match requirements" in output
        or "use\n  'python -m robotpy sync'" in output
        or "python -m robotpy sync" in output and "missing packages" in output
    )


def _run_robotpy_sync() -> int:
    """Run `python -m robotpy sync` to install pyproject.toml requirements.

    This is exactly what robotpy's own error message tells the user to do
    when the local install is out of date — running it ourselves saves the
    user a copy-paste round-trip.
    """
    sync_cmd = [sys.executable, "-m", "robotpy", "sync"]
    if ui_mode.is_active():
        return ui_mode.get_app().stream_subprocess(sync_cmd)
    info(f"$ {' '.join(sync_cmd)}")
    return _spawn_with_yes(sync_cmd)


def _spawn_with_yes(cmd: list[str]) -> int:
    """Run cmd while pre-feeding 'y' answers to its stdin.

    robotpy deploy prompts to uninstall+install rio packages whenever
    pyproject.toml's requires list changes (e.g. when we added robotpy-cscore).
    Its input() call EOFs when stdin is a non-interactive pipe in this chained
    setup.py → deploy.py → robotpy deploy flow, so we explicitly write 'y'
    lines into the pipe. Buffering means later input() calls consume them as
    needed; we close stdin only after the process exits.
    """
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        if proc.stdin is not None:
            try:
                proc.stdin.write(b"y\n" * 20)
                proc.stdin.flush()
            except (OSError, BrokenPipeError):
                # robotpy didn't read stdin at all — nothing to do.
                pass
        return proc.wait()
    finally:
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass


def _spawn_with_yes_tee(cmd: list[str]) -> tuple[int, str]:
    """Same as _spawn_with_yes but tees stdout/stderr to both the user's
    terminal and an in-memory buffer so the caller can scan for known errors.
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    captured: list[str] = []
    try:
        if proc.stdin is not None:
            try:
                proc.stdin.write("y\n" * 20)
                proc.stdin.flush()
            except (OSError, BrokenPipeError):
                pass
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            captured.append(line)
        rc = proc.wait()
    finally:
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
    return rc, "".join(captured)


def result_box(success: bool, rc: int) -> None:
    print()
    if success:
        banner("Deploy Successful", "code is running on the roboRIO", color=green)
    else:
        banner("Deploy Failed", f"robotpy exit code {rc}", color=red)
        print(bold("Troubleshooting:"))
        info("Connect to the robot's WiFi (or USB tether) and retry.")
        info("Power-cycle the roboRIO if it's been flaky.")
        info("If a package is missing locally: `python -m robotpy sync`.")
        info("Try `python deploy.py --skip-tests` to bypass unit tests.")
        info("Try `python deploy.py --nc` to stream console output while deploying.")
        info("Run `python -m robotpy deploy --help` for all flags.")
        print()


def main() -> int:
    extra = list(sys.argv[1:])
    if "--ui" in extra:
        extra.remove("--ui")
        if not ui_mode.HAS_TK:
            print("UI mode requested but tkinter is unavailable; using terminal.")
        else:
            app = ui_mode.activate("Deploy", "push code to the roboRIO")
            return app.run(lambda: _main_logic(extra))
    return _main_logic(extra)


def _main_logic(extra: list[str]) -> int:
    banner("Robot Deploy", "push code to the roboRIO", color=cyan)

    team = read_team_number()
    if team:
        info(f"Detected team number: {bold(team)}")
    else:
        # In UI mode, ask via dialog and save it. Otherwise let robotpy
        # prompt on the terminal as before.
        team = ensure_team_number(team)
        if team:
            info(f"Saved team number: {bold(team)}")
        elif ui_mode.is_active():
            fail("No team number provided — can't deploy without one.")
            return 1
        else:
            info("No team number configured. robotpy will prompt if needed.")

    step("Network")
    info("Make sure your computer is on the robot's WiFi,")
    info("or tethered to the roboRIO over USB.")
    print()
    if not ask_yn("Connected to the robot?", default=True):
        print()
        warn("Aborted. Connect to the robot and try again.")
        return 1

    check_connectivity(team)

    if not handle_large_files(extra):
        warn("Aborted: declined to upload large files.")
        info("Delete the offending files (e.g. clear out logs/) and retry,")
        info("or pass --large to skip this check next time.")
        return 1

    rc = run_deploy(extra)
    if rc == 0:
        disable_firewall_for_ds()
        deploy_to_orangepi()
    result_box(rc == 0, rc)
    return rc


def deploy_to_orangepi() -> None:
    """Note that the rio will push to the Pi itself on next robot startup.

    We used to rsync from the laptop here, but that meant Pi pushes only
    happened when *the laptop* deployed. Now the rio is the gateway:
      - laptop → rio (this is what `robotpy deploy` does)
      - rio → Pi  (orangepi_pusher.py runs in robotInit on every boot)
    So a Deploy press is enough to update both, even when the next boot
    is a power-cycle in the pit with the laptop unplugged.

    If the Pi was never configured we still nudge the user toward setup,
    but we don't try to push directly anymore.
    """
    repo = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(repo, "pi_target.json")
    if not os.path.exists(cfg_path):
        info("Vision Pi not configured yet.")
        info("(Run Set up Vision Pi from the control panel to provision it.)")
        return
    step("Vision Pi will sync on next robot boot")
    info("The rio's startup pusher will SSH the new orangepi/ files to the")
    info("Pi and restart cold-fusion-sight. No further action needed here.")
    info("Power-cycle the rio (or use `Update Vision Pi` to push from this")
    info("laptop directly) if you want it pushed *right now*.")


def disable_firewall_for_ds() -> None:
    """After a successful deploy, drop Windows Firewall so the Driver Station
    can talk to the rio. Triggers a UAC prompt; safe no-op on non-Windows.

    Why: the DS reports `link-bad` / `DS radio(.4)-bad` even when the rio is
    reachable from PowerShell, because the firewall blocks the DS's inbound
    discovery traffic. The user wants this off for bench testing and will
    re-enable it from the control panel when they're done.
    """
    if not firewall.is_windows():
        return
    step("Disabling Windows Firewall for the Driver Station")
    info("Windows will pop a UAC prompt — click Yes to allow.")
    ok_, msg = firewall.set_firewall(False)
    if ok_:
        ok(msg)
        info("Re-enable it from the control panel when you're done.")
    else:
        warn(msg)
        info("You can still try the DS; if it shows link-bad, run:")
        info("  python firewall.py off   (and approve the UAC prompt)")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
