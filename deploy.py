#!/usr/bin/env python3
"""Deploy the robot code to the roboRIO."""

import subprocess
import sys


if __name__ == "__main__":
    subprocess.check_call([sys.executable, "-m", "robotpy", "deploy", *sys.argv[1:]])
