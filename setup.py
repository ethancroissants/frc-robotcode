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
from typing import Callable

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

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


# -------- setup logic --------

def run(label: str, cmd: list[str]) -> None:
    if ui_mode.is_active():
        rc = ui_mode.get_app().stream_subprocess(cmd)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, cmd)
        return
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


DRIVER_STATION_PATHS = [
    r"C:\Program Files (x86)\FRC Driver Station\DriverStation.exe",
    r"C:\Program Files\FRC Driver Station\DriverStation.exe",
]
DRIVER_STATION_URL = (
    "https://www.ni.com/en/support/downloads/drivers/download.frc-game-tools.html"
)
MIN_PY = (3, 9)


def ensure_internet() -> bool:
    """Verify the laptop can actually reach PyPI before we try to install.

    The robot's WiFi has no internet, and `pip install` against it just
    times out with cryptic "ReadTimeoutError" stacks. Catching it here
    lets us tell the user *why* and what to do instead.

    Probes pypi.org first (where pip will go), with python.org as a
    fallback in case PyPI is the one that's down rather than the user.
    """
    step("Checking internet connectivity")
    import urllib.request, urllib.error
    targets = [
        ("https://pypi.org/simple/", "pypi.org"),
        ("https://www.python.org/", "python.org"),
    ]
    last_err = ""
    for url, label in targets:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cold-fusion-setup"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                if 200 <= resp.status < 400:
                    ok(f"reachable: {label}")
                    return True
        except urllib.error.URLError as e:
            last_err = f"{label}: {e.reason}"
        except Exception as e:
            last_err = f"{label}: {e}"
    fail("No internet — can't reach PyPI to install dependencies.")
    if last_err:
        info(last_err)
    info("If you're on the ROBOT'S WiFi, switch to your normal home/school WiFi")
    info("(robot radio has no internet). Run setup.py once with internet, then")
    info("you can re-join the robot WiFi to deploy.")
    return False


def ensure_python_version() -> bool:
    step("Checking Python version")
    have = sys.version_info[:3]
    if have >= MIN_PY:
        ok(f"Python {have[0]}.{have[1]}.{have[2]}  {dim(sys.executable)}")
        return True
    fail(
        f"Python {have[0]}.{have[1]} is too old — need "
        f"{MIN_PY[0]}.{MIN_PY[1]}+."
    )
    info("Reinstall a newer Python from https://www.python.org/downloads/")
    return False


def _git_install_cmd() -> list[str] | None:
    """Return a best-guess install command for the host's package manager.

    Returns None when we don't have a confident automated path — the caller
    falls back to a manual-install hint.
    """
    if sys.platform.startswith("win"):
        if shutil.which("winget"):
            return [
                "winget", "install", "-e", "--id", "Git.Git",
                "--accept-source-agreements", "--accept-package-agreements",
                "--silent",
            ]
        return None
    if sys.platform == "darwin":
        if shutil.which("brew"):
            return ["brew", "install", "git"]
        return None
    if shutil.which("apt-get"):
        return ["sudo", "apt-get", "install", "-y", "git"]
    if shutil.which("dnf"):
        return ["sudo", "dnf", "install", "-y", "git"]
    if shutil.which("yum"):
        return ["sudo", "yum", "install", "-y", "git"]
    if shutil.which("pacman"):
        return ["sudo", "pacman", "-S", "--noconfirm", "git"]
    if shutil.which("zypper"):
        return ["sudo", "zypper", "--non-interactive", "install", "git"]
    return None


def ensure_git() -> bool:
    """Verify git is installed and on PATH; offer to install it if not."""
    step("Checking git")
    if shutil.which("git"):
        return check("git", ["git", "--version"])[0]
    warn("git is not installed (or not on PATH).")

    cmd = _git_install_cmd()
    if cmd is not None:
        info(f"Would run: {' '.join(cmd)}")
        if ask_yn("Install git now?", default=True):
            try:
                subprocess.check_call(cmd)
            except subprocess.CalledProcessError as e:
                fail(f"Install command exited {e.returncode}; install manually.")
                return False
            if shutil.which("git"):
                ok("git installed")
                return True
            warn("git installed but not yet on PATH — open a new terminal.")
            return False
        info("Skipped. Install git when you're ready.")
        return False
    info("Install git from https://git-scm.com/downloads")
    return False


def _driver_station_path() -> str | None:
    if not sys.platform.startswith("win"):
        return None
    for p in DRIVER_STATION_PATHS:
        if os.path.exists(p):
            return p
    return None


def ensure_driver_station() -> bool:
    """Windows-only: check FRC Driver Station and prompt to install if missing.

    Driver Station ships in NI's FRC Game Tools bundle; there's no winget
    package, so we just point at the download page (and offer to open it).
    """
    if not sys.platform.startswith("win"):
        step("Checking FRC Driver Station")
        info("Skipping (Driver Station only runs on Windows).")
        return True
    step("Checking FRC Driver Station")
    path = _driver_station_path()
    if path:
        ok(f"Driver Station installed  {dim(path)}")
        return True
    warn("FRC Driver Station is not installed.")
    info(f"Download FRC Game Tools from: {DRIVER_STATION_URL}")
    info("After installing, re-run setup.")
    if ask_yn("Open the download page in your browser?", default=True):
        try:
            import webbrowser
            webbrowser.open(DRIVER_STATION_URL)
            ok("Opened in browser.")
        except Exception as e:
            warn(f"Couldn't open browser: {e}")
    return False


def _tkinter_install_hint() -> tuple[str | None, list[str] | None]:
    """Return (human hint, auto-runnable cmd) for installing tkinter on this OS.

    Auto-runnable cmd is None unless we're confident enough to offer running it
    on the user's behalf (Linux with a known package manager).
    """
    if sys.platform == "darwin":
        # Homebrew Python ships without Tk; the python.org installer includes it.
        return ("brew install python-tk", None)
    if sys.platform.startswith("win"):
        return (
            "reinstall Python from python.org with the "
            "'tcl/tk and IDLE' option checked",
            None,
        )
    # Linux — detect a package manager and suggest the matching package.
    if shutil.which("apt-get"):
        cmd = ["sudo", "apt-get", "install", "-y", "python3-tk"]
        return (" ".join(cmd), cmd)
    if shutil.which("dnf"):
        cmd = ["sudo", "dnf", "install", "-y", "python3-tkinter"]
        return (" ".join(cmd), cmd)
    if shutil.which("yum"):
        cmd = ["sudo", "yum", "install", "-y", "python3-tkinter"]
        return (" ".join(cmd), cmd)
    if shutil.which("pacman"):
        cmd = ["sudo", "pacman", "-S", "--noconfirm", "tk"]
        return (" ".join(cmd), cmd)
    if shutil.which("zypper"):
        cmd = ["sudo", "zypper", "--non-interactive", "install", "python3-tk"]
        return (" ".join(cmd), cmd)
    return (None, None)


def ensure_tkinter() -> bool:
    """Verify tkinter is importable so `--ui` mode works on later runs.

    tkinter is a Python stdlib module but ships separately at the OS level on
    Homebrew macOS and most Linux distros — it's not pip-installable, which is
    why it can't go in pyproject.toml.
    """
    step("Checking tkinter (powers --ui mode)")
    try:
        import tkinter  # noqa: F401
        ok(f"tkinter available (Tk {tkinter.TkVersion})")
        return True
    except ImportError:
        warn("tkinter is missing — `python setup.py --ui` won't work without it.")

    hint, cmd = _tkinter_install_hint()
    if cmd is not None:
        info(f"Detected installable package; would run: {hint}")
        if ask_yn("Install tkinter now?", default=True):
            try:
                subprocess.check_call(cmd)
            except subprocess.CalledProcessError as e:
                fail(f"Install command exited {e.returncode}; install manually.")
                return False
            try:
                import tkinter  # noqa: F401
                ok(f"tkinter installed (Tk {tkinter.TkVersion})")
                return True
            except ImportError:
                fail("Still can't import tkinter after install.")
                info("Try restarting your shell / re-running setup.py.")
                return False
        info("Skipped. Run the command above when you're ready for --ui.")
        return False

    if hint:
        info(f"Install manually: {hint}")
    else:
        info("Install Python's tkinter module via your OS package manager.")
    return False


def stage_pi_wheels(repo: Path) -> bool:
    """Pre-download Pi-compatible wheels on the laptop into orangepi/vendor/wheels/.

    The Orange Pi / Raspberry Pi 5 lives on the robot's WiFi (no internet),
    so it can't `pip install` from PyPI. setup_orangepi.py later pushes this
    cache to the Pi and runs `pip install --no-index --find-links vendor/wheels`.

    Cached by hash of (requirements.txt + py + arch). Re-runs that don't
    change inputs are a no-op.

    Skipped silently if there's no orangepi/requirements.txt — teams that
    don't use the Pi don't need this.
    """
    op_dir = repo / "orangepi"
    req = op_dir / "requirements.txt"
    if not req.exists():
        return True  # not a failure — team just doesn't use a Pi

    step("Staging Pi (orangepi) wheels for offline install")
    wheels_dir = op_dir / "vendor" / "wheels"
    wheels_dir.mkdir(parents=True, exist_ok=True)
    stamp = wheels_dir / ".cache-stamp"

    # Pi target. Default to Pi 5 + Pi OS Trixie (aarch64, Python 3.13). If a
    # previous run of setup_orangepi.py probed a different Pi, it stashed the
    # actual values in .orangepi_cfg — prefer those when present.
    py, arch = "3.13", "aarch64"
    cfg_path = repo / ".orangepi_cfg"
    if cfg_path.exists():
        import json
        try:
            cfg = json.loads(cfg_path.read_text())
            pi_env = cfg.get("pi_env") or {}
            py = str(pi_env.get("py") or py)
            arch = str(pi_env.get("arch") or arch)
        except Exception:
            pass

    cache_key = _pi_wheel_cache_key(req, py, arch)
    if stamp.exists() and stamp.read_text().strip() == cache_key:
        n = len(list(wheels_dir.glob("*.whl"))) + len(list(wheels_dir.glob("*.tar.gz")))
        if n > 0:
            ok(f"wheel cache valid for Python {py}/{arch} ({n} wheels) — skipping")
            return True

    plat_tags = {
        "aarch64": ["manylinux_2_28_aarch64", "manylinux2014_aarch64", "linux_aarch64"],
        "arm64":   ["manylinux_2_28_aarch64", "manylinux2014_aarch64", "linux_aarch64"],
        "armv7l":  ["manylinux2014_armv7l", "linux_armv7l"],
        "x86_64":  ["manylinux_2_28_x86_64", "manylinux2014_x86_64", "linux_x86_64"],
    }.get(arch)
    if not plat_tags:
        warn(f"Unknown Pi arch '{arch}' — skipping wheel staging.")
        return False

    info(f"Target: Python {py}, {arch}")

    # Wipe stale wheels so we don't ship mismatched versions if requirements
    # changed since the last successful stage.
    for old in wheels_dir.glob("*.whl"):
        old.unlink()
    for old in wheels_dir.glob("*.tar.gz"):
        old.unlink()
    if stamp.exists():
        stamp.unlink()

    base_cmd = [
        sys.executable, "-m", "pip", "download",
        "--only-binary", ":all:",
        "--python-version", py,
        "--implementation", "cp",
        *sum((["--platform", t] for t in plat_tags), []),
        "-r", str(req),
        "-d", str(wheels_dir),
    ]
    abi_cmd = base_cmd + ["--abi", f"cp{py.replace('.', '')}"]

    try:
        run("pip download (Pi wheels, strict ABI)", abi_cmd)
    except subprocess.CalledProcessError:
        info("Strict ABI failed — retrying with looser matching for pure-python deps.")
        try:
            run("pip download (Pi wheels, loose)", base_cmd)
        except subprocess.CalledProcessError as e:
            fail(f"Pi wheel download failed (exit {e.returncode}).")
            info(
                "If a specific package has no aarch64 wheel, you may need to "
                "build it on the Pi during a one-time online session, or "
                "remove it from orangepi/requirements.txt."
            )
            return False

    n = len(list(wheels_dir.glob("*.whl"))) + len(list(wheels_dir.glob("*.tar.gz")))
    stamp.write_text(cache_key + "\n")
    ok(f"staged {n} wheel(s) in orangepi/vendor/wheels/ (cached for next run)")
    return True


def _pi_wheel_cache_key(req_path: Path, py: str, arch: str) -> str:
    """Hash of inputs that, when changed, invalidate the staged Pi wheel cache."""
    import hashlib
    h = hashlib.sha256()
    h.update(req_path.read_bytes())
    h.update(f"|py={py}|arch={arch}".encode())
    return h.hexdigest()


def _verify_requires_installed(requires: list[str]) -> list[str]:
    """Return the list of pyproject `requires` whose dist isn't installed.

    Mirrors `robotpy deploy`'s pre-flight check: it uses
    importlib.metadata.distribution() against each requirement name. Any
    package it can't find is what trips the "Locally installed packages
    do not match requirements" abort.
    """
    if not requires:
        return []
    # Use the laptop's own Python to query — same env that pip just installed
    # into. Spawning a subprocess avoids stale importlib caches.
    code = (
        "import sys\n"
        "from importlib.metadata import distribution, PackageNotFoundError\n"
        "missing = []\n"
        "for name in sys.argv[1:]:\n"
        "    try:\n"
        "        distribution(name)\n"
        "    except PackageNotFoundError:\n"
        "        missing.append(name)\n"
        "print('\\n'.join(missing))\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", code, *requires],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def read_robot_requires(repo: Path) -> list[str]:
    """Read [tool.robotpy].requires from pyproject.toml.

    `robotpy sync` stages these for the roboRIO but doesn't always install them
    in the local Python environment, so `robotpy sim` can fail with
    ModuleNotFoundError. We pip-install them explicitly to guarantee local sim works.
    """
    pyproject = repo / "pyproject.toml"
    if not pyproject.exists():
        return []
    with pyproject.open("rb") as f:
        data = tomllib.load(f)
    return list(data.get("tool", {}).get("robotpy", {}).get("requires", []))


def offer_deploy(repo: Path) -> int:
    """Terminal-mode follow-up: asks via prompt, runs deploy.py inline."""
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


def _spawn_deploy_ui(repo: Path) -> Callable[[], None]:
    """Build a callback that launches `deploy.py --ui` in a fresh process."""

    def fire() -> None:
        deploy_script = repo / "deploy.py"
        if not deploy_script.exists():
            return
        cmd = [sys.executable, str(deploy_script), "--ui"]
        try:
            subprocess.Popen(cmd, cwd=str(repo))
        except Exception:
            # Best-effort; the setup window is about to close regardless.
            pass

    return fire


def main() -> int:
    if "--ui" in sys.argv[1:]:
        sys.argv = [a for a in sys.argv if a != "--ui"]
        if not ui_mode.HAS_TK:
            print("UI mode requested but tkinter is unavailable; using terminal.")
        else:
            app = ui_mode.activate(
                "Setup", "install, sync, and verify your robot code"
            )
            return app.run(_main_logic)
    return _main_logic()


def _main_logic() -> int:
    repo = Path(__file__).resolve().parent
    os.chdir(repo)

    banner("RobotPy Setup", "install, sync, and verify your robot code", color=cyan)

    # Prereq checks. These are reported in the final summary; only the Python
    # version gate is fatal — git/DS/tkinter just warn so the user can keep
    # going if they only need part of the toolchain.
    py_ok = ensure_python_version()
    if not py_ok:
        return 1
    # Internet must come before pip/robotpy steps — installing offline produces
    # confusing partial states (deploy later fails with "package not found").
    if not ensure_internet():
        print()
        banner(
            "Setup Aborted", "no internet — connect to a real WiFi and retry",
            color=red,
        )
        return 1
    git_ok = ensure_git()
    ds_ok = ensure_driver_station()
    # tkinter is optional (only used by --ui mode), so check but don't fail setup.
    ensure_tkinter()

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

    # Safety net for older robotpy versions: sync installs locally now (in its
    # own elevated pip window), but historically didn't, leaving `robotpy sim`
    # to fail on `import commands2`. We pip-install without --upgrade so we
    # don't race the sync subprocess for already-installed packages — and we
    # downgrade hard failures to warnings, since by the time we're here sync
    # has typically covered everything.
    requires = read_robot_requires(repo)
    local_install_ok = True
    if requires:
        step("Installing project requirements locally (for sim + deploy check)")
        # Give sync's spawned pip window a head start before we touch site-packages,
        # so we don't race it for cscore/__init__.py and trip WinError 32 on Windows.
        time.sleep(3)
        try:
            run(
                f"pip install {' '.join(requires)}",
                [sys.executable, "-m", "pip", "install", *requires],
            )
            ok(f"{len(requires)} project requirement(s) installed locally")
        except subprocess.CalledProcessError as e:
            local_install_ok = False
            warn(
                "Local pip install failed (likely a Windows file lock from the "
                "sync subprocess). Retrying once after a longer pause… "
                f"(exit {e.returncode})"
            )
            time.sleep(8)
            try:
                run(
                    f"pip install {' '.join(requires)} (retry)",
                    [sys.executable, "-m", "pip", "install", *requires],
                )
                local_install_ok = True
                ok("retry succeeded")
            except subprocess.CalledProcessError as e2:
                fail(
                    "Local pip install still failing — `robotpy deploy` will "
                    "refuse to run later because the laptop's packages won't "
                    f"match pyproject.toml. (exit {e2.returncode})"
                )

        # Verify each requirement actually landed. `robotpy deploy` checks the
        # exact same thing before uploading and aborts hard ("Locally installed
        # packages do not match requirements") if anything's missing — catching
        # it here means we fail while the user is still on real internet, not
        # later when they're already on the robot's WiFi.
        if local_install_ok:
            missing = _verify_requires_installed(requires)
            if missing:
                fail(
                    "Installed but importable check found missing packages: "
                    + ", ".join(missing)
                )
                info(
                    "Run `python -m robotpy sync` while on internet, then "
                    "re-run setup.py."
                )
                local_install_ok = False
            else:
                ok("all project requirements verified installed")

    # Stage Pi (orangepi/) wheels on the laptop while we still have internet.
    # The Pi lives on the robot's WiFi (no internet), so setup_orangepi.py
    # later just pushes these pre-downloaded wheels to the Pi and pip-installs
    # them offline. Cached by hash of requirements.txt + py + arch — only
    # re-downloads when one of those changes.
    pi_wheels_ok = stage_pi_wheels(repo)

    step("Running checks")
    results: dict[str, bool] = {
        "git installed": git_ok,
        "project requirements installed": local_install_ok,
        "Pi wheel cache staged": pi_wheels_ok,
    }
    if sys.platform.startswith("win"):
        results["FRC Driver Station installed"] = ds_ok
    results |= {
        "robotpy CLI available": check(
            "robotpy CLI",
            [sys.executable, "-c",
             "from importlib.metadata import version; print(version('robotpy'))"],
        )[0],
        "wpilib importable": check(
            "import wpilib",
            [sys.executable, "-c", "import wpilib; print(wpilib.__version__)"],
        )[0],
        "commands2 importable": check(
            "import commands2",
            [sys.executable, "-c", "import commands2; print(commands2.__name__)"],
        )[0],
        # cscore + numpy are required by vision.py (USB camera sight). Catch a
        # broken wheel here rather than at robotInit on the field. We deliberately
        # do *not* depend on cv2 — WPILib's 2026 mirror ships no OpenCV wheel for
        # cp314 linux_roborio, so vision.py draws overlays in pure numpy.
        "cscore importable": check(
            "import cscore",
            [sys.executable, "-c", "import cscore; print(cscore.__name__)"],
        )[0],
        "numpy importable": check(
            "import numpy",
            [sys.executable, "-c", "import numpy; print(numpy.__version__)"],
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

    if ui_mode.is_active():
        # Replace the success "you can close this" copy with a Deploy button.
        # Clicking it spawns deploy.py --ui in a fresh window and closes this
        # one — no second confirmation popup needed.
        ui_mode.get_app().set_followup(
            label="Deploy now",
            on_click=_spawn_deploy_ui(repo),
            prompt="Push code to the robot now?",
        )
        return 0

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
        if not ui_mode.is_active():
            try:
                input(f"\n{dim('Press Enter to close...')}")
            except EOFError:
                pass
