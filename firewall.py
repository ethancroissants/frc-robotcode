#!/usr/bin/env python3
"""Toggle Windows Defender Firewall on/off (with a UAC prompt).

The FRC Driver Station can show "link-bad" / "DS radio bad" even when
the roboRIO is reachable, because Windows Firewall blocks the inbound
DS responses from the robot network. Turning the firewall off for
bench/practice testing is the fastest fix; turn it back on when you're
done.

On non-Windows hosts every operation is a friendly no-op.

Usage:
    python firewall.py off
    python firewall.py on
"""

from __future__ import annotations

import platform
import subprocess
import sys


def is_windows() -> bool:
    return platform.system() == "Windows"


def _ps_elevated_netsh(state: str) -> tuple[bool, str]:
    # Wrap netsh in PowerShell Start-Process -Verb RunAs so Windows shows
    # the UAC prompt. Wait for the elevated process and bubble its exit
    # code back. The try/catch turns "user denied UAC" into a clean exit 2
    # instead of a raw .NET exception.
    ps = (
        "$ErrorActionPreference='Stop'; "
        "try { "
        "  $p = Start-Process -FilePath 'netsh' "
        f"-ArgumentList 'advfirewall','set','allprofiles','state','{state}' "
        "-Verb RunAs -PassThru -WindowStyle Hidden -ErrorAction Stop; "
        "  $p.WaitForExit(); "
        "  exit $p.ExitCode "
        "} catch { "
        "  Write-Error $_.Exception.Message; "
        "  exit 2 "
        "}"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except FileNotFoundError:
        return False, "PowerShell isn't on PATH — can't elevate."
    except subprocess.TimeoutExpired:
        return False, "Timed out waiting for the UAC prompt."
    if result.returncode == 0:
        return True, f"Windows Firewall turned {state.upper()}."
    err = (result.stderr or result.stdout or "").strip()
    low = err.lower()
    if "canceled" in low or "cancelled" in low:
        return False, "Admin permission denied — firewall unchanged."
    return False, f"Couldn't change the firewall (exit {result.returncode}). {err}"


def set_firewall(enabled: bool) -> tuple[bool, str]:
    """Turn the Windows Firewall on (True) or off (False).

    Returns (success, human_message). Triggers a UAC prompt and blocks
    until the elevated child exits. On non-Windows, no-ops with a note.
    """
    if not is_windows():
        return False, "Firewall control is only available on Windows."
    return _ps_elevated_netsh("on" if enabled else "off")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1].lower() not in ("on", "off"):
        print("Usage: python firewall.py {on|off}", file=sys.stderr)
        return 64
    desired = argv[1].lower() == "on"
    ok, msg = set_firewall(desired)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
