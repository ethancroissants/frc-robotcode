#!/usr/bin/env python3
"""Install RobotPy and all robot dependencies listed in pyproject.toml.

After the checks pass, offers to switch networks and run deploy.py.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


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
def magenta(t): return _c("35", t)
def cyan(t): return _c("36", t)


def _width() -> int:
    try:
        return min(shutil.get_terminal_size((80, 24)).columns, 78)
    except Exception:
        return 72


def banner(title: str, subtitle: str = "", color=cyan) -> None:
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
    w = _width()
    if not label:
        print(color("─" * w))
        return
    prefix = color("── ") + bold(label) + " "
    tail = w - len(label) - 4
    print(prefix + color("─" * max(3, tail)))


def step(msg: str) -> None:
    print(f"\n{cyan('▶')} {bold(msg)}")


def ok(msg: str) -> None:
    print(f"  {green('✓')} {msg}")


def fail(msg: str) -> None:
    print(f"  {red('✗')} {msg}")


def warn(msg: str) -> None:
    print(f"  {yellow('!')} {msg}")


def info(msg: str) -> None:
    print(f"  {dim('·')} {dim(msg)}")


def ask_yn(prompt: str, default: bool = False) -> bool:
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
    try:
        input(f"{yellow('⏸')}  {msg}")
    except EOFError:
        pass


# -------- setup logic --------

def run(label: str, cmd: list[str]) -> None:
    info(f"$ {' '.join(cmd)}")
    rule(label, color=dim)
    sys.stdout.flush()
    subprocess.check_call(cmd)
    rule("", color=dim)


def check(label: str, cmd: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
    except Exception as e:
        fail(f"{label} — {e}")
        return False, str(e)
    output = (result.stdout or result.stderr or "").strip().splitlines()
    detail = output[-1] if output else ""
    if result.returncode == 0:
        ok(f"{label}" + (f"  {dim(detail)}" if detail else ""))
        return True, detail
    else:
        fail(f"{label}" + (f"  {dim(detail)}" if detail else ""))
        return False, detail


def offer_deploy(repo: Path) -> int:
    print()
    rule("Next step", color=cyan)
    print()
    if not ask_yn("Deploy to the robot now?", default=False):
        info("Skipping deploy. Run `python deploy.py` when you're ready.")
        return 0

    print()
    step("Switch to the robot network")
    info("Disconnect from your current WiFi and connect to the robot's")
    info("network (or plug in a USB cable to the roboRIO).")
    print()
    pause("Press Enter once you're connected to the robot...")

    print()
    rule("Handing off to deploy.py", color=cyan)
    print()
    deploy_script = repo / "deploy.py"
    if not deploy_script.exists():
        fail(f"deploy.py not found at {deploy_script}")
        return 1
    return subprocess.call([sys.executable, str(deploy_script)])


def main() -> int:
    repo = Path(__file__).resolve().parent
    os.chdir(repo)

    banner("RobotPy Setup", "install, sync, and verify your robot code", color=cyan)

    step("Installing RobotPy")
    run("pip install robotpy certifi", [
        sys.executable, "-m", "pip", "install", "--upgrade", "robotpy", "certifi",
    ])
    ok("robotpy + certifi installed")

    step("Syncing robot dependencies (pyproject.toml)")
    info("robotpy may open a separate window to install roboRIO packages —")
    info("wait for it to finish, then close that window to continue.")
    run("robotpy sync", [sys.executable, "-m", "robotpy", "sync", "--use-certifi"])
    ok("dependencies synced")

    step("Running checks")
    results = {
        "robotpy CLI available": check(
            "robotpy CLI",
            [sys.executable, "-c",
             "from importlib.metadata import version; print(version('robotpy'))"],
        )[0],
        "wpilib importable": check(
            "import wpilib",
            [sys.executable, "-c", "import wpilib; print(wpilib.__version__)"],
        )[0],
        "robot.py compiles": check(
            "compile robot.py",
            [sys.executable, "-m", "py_compile", str(repo / "robot.py")],
        )[0],
        "project compiles": check(
            "compile all sources",
            [sys.executable, "-m", "compileall", "-q", str(repo)],
        )[0],
    }

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    print()
    rule("Summary", color=cyan)
    for name, good in results.items():
        (ok if good else fail)(name)

    print()
    if passed == total:
        banner(f"Setup Complete  ({passed}/{total})",
               "ready to simulate or deploy", color=green)
    else:
        banner(f"Setup Finished with Errors  ({passed}/{total})",
               "fix the failures above before deploying", color=red)
        return 1

    return offer_deploy(repo)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print()
        fail(f"Command failed: {' '.join(e.cmd) if isinstance(e.cmd, list) else e.cmd}")
        print()
        banner("Setup Failed", f"exit code {e.returncode}", color=red)
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    finally:
        try:
            input(f"\n{dim('Press Enter to close...')}")
        except EOFError:
            pass
