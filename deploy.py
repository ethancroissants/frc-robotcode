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


def read_team_number() -> str | None:
    for path in (".deploy_cfg", ".wpilib/wpilib_preferences.json"):
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            continue
        import re
        m = re.search(r'"?team(?:-number|Number)?"?\s*[:=]\s*"?(\d+)', text)
        if m:
            return m.group(1)
    env = os.environ.get("FRC_TEAM") or os.environ.get("TEAM")
    return env if env and env.isdigit() else None


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


def run_deploy(extra_args: list[str]) -> int:
    step("Running robotpy deploy")
    cmd = [sys.executable, "-m", "robotpy", "deploy", *extra_args]
    t0 = time.monotonic()
    if ui_mode.is_active():
        rc = ui_mode.get_app().stream_subprocess(cmd)
    else:
        info(f"$ {' '.join(cmd)}")
        rule("live output", color=dim)
        sys.stdout.flush()
        try:
            rc = subprocess.call(cmd)
        except KeyboardInterrupt:
            rule("", color=dim)
            print()
            warn("Interrupted by user.")
            return 130
        rule("", color=dim)
    elapsed = time.monotonic() - t0
    info(f"robotpy exited with code {rc} after {elapsed:.1f}s")
    return rc


def result_box(success: bool, rc: int) -> None:
    print()
    if success:
        banner("Deploy Successful", "code is running on the roboRIO", color=green)
    else:
        banner("Deploy Failed", f"robotpy exit code {rc}", color=red)
        print(bold("Troubleshooting:"))
        info("Connect to the robot's WiFi (or USB tether) and retry.")
        info("Power-cycle the roboRIO if it's been flaky.")
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
        info("No team number configured. robotpy will prompt if it needs one.")

    step("Network")
    info("Make sure your computer is on the robot's WiFi,")
    info("or tethered to the roboRIO over USB.")
    print()
    if not ask_yn("Connected to the robot?", default=True):
        print()
        warn("Aborted. Connect to the robot and try again.")
        return 1

    check_connectivity(team)

    rc = run_deploy(extra)
    result_box(rc == 0, rc)
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
