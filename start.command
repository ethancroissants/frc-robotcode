#!/usr/bin/env bash
# Cold Fusion Robotics - double-click launcher for macOS / Linux.
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
    python3 start.py
else
    python start.py
fi
