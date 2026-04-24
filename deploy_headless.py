#!/usr/bin/env python3
"""
Non-interactive deploy for use from the web panel.
Runs tests, then deploys to robot with full output.
"""
import sys
import os
import subprocess
import socket

TEAM = "1279"
ROBOT_IP = "10.12.79.2"

script_dir = os.path.dirname(os.path.abspath(__file__))

print()
print("=" * 55)
print("  Team 1279 -- Deploy to Robot")
print("=" * 55)
print()

# Step 1: Check network
print("[STEP] Check network")
reachable = False
try:
    sock = socket.create_connection((ROBOT_IP, 22), timeout=3)
    sock.close()
    reachable = True
    print(f"  PASS  Robot reachable at {ROBOT_IP}")
except (socket.timeout, ConnectionRefusedError, OSError):
    pass

if not reachable:
    try:
        ping_cmd = (["ping", "-n", "1", "-w", "2000", ROBOT_IP]
                    if sys.platform == "win32"
                    else ["ping", "-c", "1", "-W", "2", ROBOT_IP])
        result = subprocess.run(ping_cmd, capture_output=True, timeout=5)
        if result.returncode == 0:
            reachable = True
            print(f"  PASS  Robot reachable at {ROBOT_IP} (ping)")
    except Exception:
        pass

if not reachable:
    print(f"  FAIL  Cannot reach robot at {ROBOT_IP}")
    print("         Make sure you're on the robot network.")
    sys.exit(1)
print()

# Step 2: Run tests
print("[STEP] Run tests")
test_result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    cwd=script_dir,
)
print()

if test_result.returncode != 0:
    print("  WARN  Tests failed, continuing deploy anyway...")
    print()

# Step 3: Deploy
print("[STEP] Deploy to robot")
print(f"  Deploying to team {TEAM} ({ROBOT_IP})...")
print()

deploy_result = subprocess.run(
    [
        sys.executable, "-m", "robotpy", "deploy",
        "--skip-tests",
        "--no-resolve",
        "--team", TEAM,
    ],
    cwd=script_dir,
)

print()
if deploy_result.returncode == 0:
    print("=" * 55)
    print("  SUCCESS! Code deployed to robot.")
    print("=" * 55)
else:
    print("=" * 55)
    print("  FAIL  Deploy failed. Check errors above.")
    print("  Common fixes:")
    print("    - Make sure you're on the robot's network")
    print(f"    - Try: ping {ROBOT_IP}")
    print("    - Run setup first to download packages")
    print("=" * 55)
    sys.exit(1)
