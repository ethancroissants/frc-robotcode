#!/usr/bin/env python3
"""Install RobotPy and all robot dependencies listed in pyproject.toml."""

import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.check_call(cmd)


def check(label: str, cmd: list[str]) -> bool:
    print(f"\n[check] {label}")
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd)
    ok = result.returncode == 0
    print(f"  -> {'OK' if ok else 'FAILED'}")
    return ok


def main() -> int:
    repo = Path(__file__).resolve().parent

    print("=== Installing robotpy ===")
    run([sys.executable, "-m", "pip", "install", "robotpy", "certifi"])

    print("\n=== Syncing robot dependencies (pyproject.toml) ===")
    print("(robotpy will open a separate window to install packages -- "
          "wait for it to finish, then press enter there to close it)")
    run([sys.executable, "-m", "robotpy", "sync", "--use-certifi"])

    print("\n=== Running checks ===")
    results = {
        "robotpy CLI available":
            check("robotpy CLI",
                  [sys.executable, "-c",
                   "from importlib.metadata import version; print(version('robotpy'))"]),
        "wpilib importable":
            check("import wpilib",
                  [sys.executable, "-c", "import wpilib; print(wpilib.__version__)"]),
        "robot.py compiles":
            check("compile robot.py",
                  [sys.executable, "-m", "py_compile", str(repo / "robot.py")]),
        "project compiles":
            check("compile all sources",
                  [sys.executable, "-m", "compileall", "-q", str(repo)]),
    }

    print("\n=== Summary ===")
    for name, ok in results.items():
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}")

    if all(results.values()):
        print("\nSetup complete! You're ready to deploy or simulate.")
        return 0
    else:
        print("\nSetup finished, but some checks failed -- see above.",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"\nCommand failed: {e}", file=sys.stderr)
        sys.exit(e.returncode)
    finally:
        try:
            input("\nPress enter to close...")
        except EOFError:
            pass
