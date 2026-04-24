#!/usr/bin/env python3
"""Install RobotPy and all robot dependencies listed in pyproject.toml."""

import subprocess
import sys


if __name__ == "__main__":
    subprocess.check_call([sys.executable, "-m", "pip", "install", "robotpy"])
    subprocess.check_call([sys.executable, "-m", "robotpy", "sync"])
