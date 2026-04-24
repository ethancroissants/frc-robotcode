#!/usr/bin/env python3
import sys
import os
import subprocess
import socket

TEAM = "1279"
ROBOT_IP = "10.12.79.2"
WEB_PANEL_PORT = 5279

script_dir = os.path.dirname(os.path.abspath(__file__))


def check_robot_network():
    """Check if we can reach the robot on the network."""
    print("  Checking robot network connection...")
    try:
        sock = socket.create_connection((ROBOT_IP, 22), timeout=3)
        sock.close()
        print(f"  Connected to robot at {ROBOT_IP}")
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        pass
    # Fallback: try ping
    try:
        ping_cmd = ["ping", "-n", "1", "-w", "2000", ROBOT_IP] if sys.platform == "win32" else ["ping", "-c", "1", "-W", "2", ROBOT_IP]
        result = subprocess.run(ping_cmd, capture_output=True, timeout=5)
        if result.returncode == 0:
            print(f"  Robot reachable at {ROBOT_IP}")
            return True
    except Exception:
        pass
    return False


print()
print("=" * 55)
print("  Team 1279 -- Deploy to Robot")
print("=" * 55)
print()

# Check robot network first
if not check_robot_network():
    print()
    print("  WARNING: Cannot reach the robot at " + ROBOT_IP)
    print()
    print("  Make sure you are connected to the robot's WiFi network")
    print("  (usually named something like '1279' or 'FRC-1279').")
    print()
    resp = input("  Try deploying anyway? (y/n): ").strip().lower()
    if resp != "y":
        print("  Cancelled. Connect to the robot network and try again.")
        input("\nPress Enter to exit...")
        sys.exit(1)
    print()

# Run tests
print("Running tests...")
test_result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
    cwd=script_dir,
)

if test_result.returncode != 0:
    print()
    print("  Tests failed! Fix them before deploying.")
    print("  (Or press Enter to deploy anyway)")
    try:
        input()
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        sys.exit(1)

print()
print(f"Deploying to robot (team {TEAM})...")
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

if deploy_result.returncode != 0:
    print()
    print("  Deploy failed. Check the errors above.")
    print()
    print("  Common fixes:")
    print("    - Make sure you're on the robot's network")
    print(f"    - Try: ping {ROBOT_IP}")
    print("    - Run python setup.py first (downloads packages)")
    print()
    input("Press Enter to exit...")
    sys.exit(1)

print()
print("=" * 55)
print("  Deployed! Your code is now running on the robot.")
print("=" * 55)
print()
print("  What would you like to do?")
print()
print("  [1] Open the Web Control Panel (control robot from your browser)")
print("  [2] Just exit (use Driver Station + controllers instead)")
print()

while True:
    choice = input("  Enter 1 or 2: ").strip()
    if choice == "1":
        print()
        print(f"  Starting Web Control Panel...")
        print(f"  Open http://localhost:{WEB_PANEL_PORT} in your browser.")
        print(f"  Press Ctrl+C to stop.")
        print()
        web_panel_dir = os.path.join(script_dir, "web_panel")
        try:
            subprocess.run(
                [sys.executable, "server.py",
                 "--port", str(WEB_PANEL_PORT),
                 "--robot-ip", ROBOT_IP],
                cwd=web_panel_dir,
            )
        except KeyboardInterrupt:
            print("\n  Web panel stopped.")
        break
    elif choice == "2":
        print()
        print("  To drive with controllers:")
        print("    1. Plug Xbox controllers into the Driver Station laptop")
        print("    2. Open FRC Driver Station")
        print("    3. Click Enable")
        print()
        print(f"  You can also start the web panel later:")
        print(f"    cd web_panel")
        print(f"    python server.py")
        print()
        input("Press Enter to exit...")
        break
    else:
        print("  Please enter 1 or 2.")
