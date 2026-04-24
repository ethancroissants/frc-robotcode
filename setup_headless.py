#!/usr/bin/env python3
"""
Non-interactive setup checker for use from the web panel.
Same checks as setup.py but no prompts, just output.
"""
import sys
import os
import subprocess

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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0, result.stdout.strip()
    except Exception:
        return False, ""


print()
print("=" * 55)
print("  Team 1279 Robot Code -- Setup Checker")
print("=" * 55)
print()

print("--- Python ---")
major, minor = sys.version_info[:2]
check(f"Python version is 3.12+ (you have {major}.{minor})",
      major == 3 and minor >= 12,
      "Download Python 3.12+ from https://python.org/downloads")

pip_ok, _ = run_quiet([sys.executable, "-m", "pip", "--version"])
check("pip is installed", pip_ok, "Run: python -m ensurepip --upgrade")
print()

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
            check(f"{module_name} is installed", False,
                  f"Auto-install failed: {install_result.stderr.strip()[:200]}")
print()

print("--- Project Files ---")
script_dir = os.path.dirname(os.path.abspath(__file__))
required_files = [
    "robot.py", "robotcontainer.py", "constants.py",
    "subsystems/__init__.py", "subsystems/drivetrain.py",
    "subsystems/shooter.py", "subsystems/feeder.py",
    "subsystems/hood.py", "subsystems/elevator.py",
]
for filepath in required_files:
    full_path = os.path.join(script_dir, filepath)
    check(f"{filepath} exists", os.path.isfile(full_path),
          "Missing file! Make sure you have the complete project.")
print()

print("--- Running Tests ---")
test_result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    capture_output=True, text=True, cwd=script_dir, timeout=30,
)
if test_result.returncode == 0:
    for line in test_result.stdout.splitlines():
        if "passed" in line:
            check(f"All tests pass ({line.strip()})", True)
            break
    else:
        check("All tests pass", True)
else:
    check("All tests pass", False,
          "Some tests failed. Run 'python -m pytest tests/ -v' to see details.")
    for line in test_result.stdout.splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            print(f"         -> {line.strip()}")
print()

print("--- Robot Deploy Packages ---")
print("  Downloading Python + packages for the roboRIO...")
print("  (This requires internet -- only needed once.)")
print()

dl_python = subprocess.run(
    [sys.executable, "-m", "robotpy", "installer", "download-python"],
    capture_output=True, text=True, cwd=script_dir, timeout=300,
)
check("roboRIO Python runtime downloaded",
      dl_python.returncode == 0,
      "Run: python -m robotpy installer download-python")

dl_sync = subprocess.run(
    [sys.executable, "-m", "robotpy", "sync", "--no-install"],
    capture_output=True, text=True, cwd=script_dir, timeout=300,
)
check("Robot project requirements downloaded",
      dl_sync.returncode == 0,
      "Run: python -m robotpy sync --no-install")
print()

print("=" * 55)
total = passed + failed
if failed == 0:
    print(f"  All {passed} checks passed! You're ready to go.")
else:
    print(f"  {passed}/{total} checks passed, {failed} failed.")
if warned > 0:
    print(f"  {warned} optional warnings.")
print("=" * 55)
sys.exit(0 if failed == 0 else 1)
