#!/usr/bin/env python3
# ============================================================
# SETUP CHECKER
# ============================================================
# Run this script to make sure your computer is ready to work
# on the robot code. It checks each requirement and tells you
# what to fix if something is missing.
#
# Usage:  python setup.py
# ============================================================

import sys
import os
import subprocess
import shutil

# ---------- HELPERS ----------

PASS = "  PASS"
FAIL = "  FAIL"
WARN = "  WARN"

passed = 0
failed = 0
warned = 0


def check(name, ok, fix_hint=""):
    global passed, failed
    if ok:
        print(f"{PASS}  {name}")
        passed += 1
    else:
        print(f"{FAIL}  {name}")
        if fix_hint:
            print(f"         -> Fix: {fix_hint}")
        failed += 1


def warn(name, message):
    global warned
    print(f"{WARN}  {name}")
    print(f"         -> {message}")
    warned += 1


def run_quiet(cmd):
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0, result.stdout.strip()
    except Exception:
        return False, ""


# ---------- CHECKS ----------

print()
print("=" * 55)
print("  Team 1279 Robot Code -- Setup Checker")
print("=" * 55)
print()

# 1. Python version
print("--- Python ---")
major, minor = sys.version_info[:2]
check(
    f"Python version is 3.12+ (you have {major}.{minor})",
    major == 3 and minor >= 12,
    "Download Python 3.12+ from https://python.org/downloads"
)

# 2. pip available
pip_ok, _ = run_quiet([sys.executable, "-m", "pip", "--version"])
check(
    "pip is installed",
    pip_ok,
    "Run: python -m ensurepip --upgrade"
)
print()

# 3. Required packages -- auto-install if missing
print("--- Required Packages ---")

packages_to_check = {
    "wpilib": "robotpy",
    "commands2": "robotpy[commands2]",
    "phoenix6": "phoenix6",
    "pyfrc": "pyfrc",
    "pytest": "pytest",
    "flask": "flask>=3.0",
    "ntcore": "pyntcore",
}

missing_packages = []
for module_name, pip_name in packages_to_check.items():
    try:
        __import__(module_name)
        check(f"{module_name} is installed", True)
    except ImportError:
        missing_packages.append((module_name, pip_name))

if missing_packages:
    print()
    print("  Installing missing packages...")
    pip_names = [pip_name for _, pip_name in missing_packages]
    install_result = subprocess.run(
        [sys.executable, "-m", "pip", "install"] + pip_names,
        capture_output=True, text=True, timeout=120,
    )
    if install_result.returncode == 0:
        for module_name, pip_name in missing_packages:
            try:
                __import__(module_name)
                check(f"{module_name} is installed (just installed)", True)
            except ImportError:
                check(f"{module_name} is installed", False, f"pip install {pip_name} failed")
    else:
        for module_name, pip_name in missing_packages:
            check(f"{module_name} is installed", False, f"Auto-install failed: {install_result.stderr.strip()[:200]}")
print()

# 4. Project files
print("--- Project Files ---")
script_dir = os.path.dirname(os.path.abspath(__file__))

required_files = [
    "robot.py",
    "robotcontainer.py",
    "constants.py",
    "subsystems/__init__.py",
    "subsystems/drivetrain.py",
    "subsystems/shooter.py",
    "subsystems/feeder.py",
    "subsystems/hood.py",
    "subsystems/elevator.py",
]

for filepath in required_files:
    full_path = os.path.join(script_dir, filepath)
    check(
        f"{filepath} exists",
        os.path.isfile(full_path),
        f"Missing file! Make sure you have the complete project."
    )
print()

# 5. Test files
print("--- Test Files ---")
test_files = [
    "tests/__init__.py",
    "tests/conftest.py",
    "tests/test_constants.py",
    "tests/test_drivetrain.py",
    "tests/test_shooter.py",
    "tests/test_feeder.py",
    "tests/test_elevator.py",
    "tests/test_hood.py",
]

for filepath in test_files:
    full_path = os.path.join(script_dir, filepath)
    check(
        f"{filepath} exists",
        os.path.isfile(full_path),
        f"Missing test file!"
    )
print()

# 6. Run the tests
print("--- Running Tests ---")
test_result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    capture_output=True,
    text=True,
    cwd=script_dir,
    timeout=30,
)

if test_result.returncode == 0:
    # Count passed tests from output
    for line in test_result.stdout.splitlines():
        if "passed" in line:
            check(f"All tests pass ({line.strip()})", True)
            break
    else:
        check("All tests pass", True)
else:
    check(
        "All tests pass",
        False,
        "Some tests failed. Run 'python -m pytest tests/ -v' to see details."
    )
    # Show the summary line
    for line in test_result.stdout.splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            print(f"         -> {line.strip()}")
print()

# 7. Optional tools
print("--- Optional Tools ---")

# Phoenix Tuner (can't really check, just remind)
warn(
    "Phoenix Tuner X",
    "Install from https://pro.docs.ctr-electronics.com -- needed to configure motors and scan the CAN bus."
)

# FRC Driver Station
if sys.platform == "win32":
    warn(
        "FRC Driver Station",
        "Install from https://docs.wpilib.org -- needed to enable/disable the robot."
    )
else:
    warn(
        "FRC Driver Station",
        "Only runs on Windows. You'll need a Windows laptop to drive the robot."
    )

# FRC Game Tools
warn(
    "FRC Game Tools",
    "Install from https://docs.wpilib.org -- includes Driver Station and roboRIO imaging tool."
)
print()

# 8. Download robot packages for offline deploy
print("--- Robot Deploy Packages ---")
print("  Downloading Python + packages for the roboRIO...")
print("  (This requires internet -- only needed once.)")
print()

dl_python = subprocess.run(
    [sys.executable, "-m", "robotpy", "installer", "download-python"],
    capture_output=True, text=True, cwd=script_dir, timeout=300,
)
if dl_python.returncode == 0:
    check("roboRIO Python runtime downloaded", True)
else:
    check(
        "roboRIO Python runtime downloaded",
        False,
        "Run: python -m robotpy installer download-python"
    )

dl_sync = subprocess.run(
    [sys.executable, "-m", "robotpy", "sync", "--no-install"],
    capture_output=True, text=True, cwd=script_dir, timeout=300,
)
if dl_sync.returncode == 0:
    check("Robot project requirements downloaded", True)
else:
    check(
        "Robot project requirements downloaded",
        False,
        "Run: python -m robotpy sync --no-install"
    )
print()

# ---------- SUMMARY ----------

print("=" * 55)
total = passed + failed
if failed == 0:
    print(f"  All {passed} checks passed! You're ready to go.")
else:
    print(f"  {passed}/{total} checks passed, {failed} failed.")
    print(f"  Fix the failures above before deploying to the robot.")

if warned > 0:
    print(f"  {warned} optional warnings -- review when you can.")

print("=" * 55)
print()

if failed > 0:
    input("Press Enter to exit...")
    sys.exit(1)

print("  What would you like to do next?")
print()
print("  [1] Open the Web Panel (setup, deploy, and control -- all in one)")
print("  [2] Deploy to robot now (command line)")
print("  [3] Exit")
print()

while True:
    choice = input("  Enter 1, 2, or 3: ").strip()
    if choice == "1":
        web_panel_dir = os.path.join(script_dir, "web_panel")
        print()
        print("  Starting Web Panel...")
        print("  Open http://localhost:5279 in your browser.")
        print("  Press Ctrl+C to stop.")
        print()
        try:
            subprocess.run(
                [sys.executable, "server.py", "--port", "5279"],
                cwd=web_panel_dir,
            )
        except KeyboardInterrupt:
            print("\n  Web panel stopped.")
        break
    elif choice == "2":
        print()
        subprocess.run([sys.executable, os.path.join(script_dir, "deploy.py")])
        break
    elif choice == "3":
        break
    else:
        print("  Please enter 1, 2, or 3.")
