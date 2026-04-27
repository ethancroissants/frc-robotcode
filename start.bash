#!/usr/bin/env bash
# Open the Cold Fusion Robotics control panel.
# Double-click this file (or run ./start.bash) to launch start.py.

set -e

# Move into the repo dir so relative paths in start.py work.
cd "$(dirname "$0")"

# Prefer python3, fall back to python.
if command -v python3 >/dev/null 2>&1; then
    exec python3 start.py "$@"
elif command -v python >/dev/null 2>&1; then
    exec python start.py "$@"
else
    echo "Python 3 is not installed or not on your PATH." >&2
    echo "Install Python 3 from https://www.python.org/downloads/" >&2
    exit 1
fi
