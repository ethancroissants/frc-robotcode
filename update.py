#!/usr/bin/env python3
"""Reset the local repo to match its GitHub remote.

Pass --ui to show the friendly Cold Fusion loading-bar window.
"""
import subprocess
import sys
from pathlib import Path

import ui_mode

REPO_DIR = Path(__file__).resolve().parent


def _git_capture(*args: str) -> str:
    cmd = ["git", "-C", str(REPO_DIR), *args]
    return subprocess.check_output(cmd, text=True).strip()


def _git(*args: str) -> None:
    cmd = ["git", "-C", str(REPO_DIR), *args]
    if ui_mode.is_active():
        rc = ui_mode.get_app().stream_subprocess(cmd)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, cmd)
        return
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, text=True)


def _default_branch() -> str:
    try:
        ref = _git_capture(
            "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"
        )
        return ref.rsplit("/", 1)[-1]
    except subprocess.CalledProcessError:
        return "main"


def _logic() -> int:
    if ui_mode.is_active():
        ui_mode.get_app().banner("Update", "syncing with GitHub")
        ui_mode.get_app().step("Fetching the latest code")
    _git("fetch", "origin", "--prune")

    if ui_mode.is_active():
        ui_mode.get_app().step("Resetting local changes")
    _git("reset", "--hard", "HEAD")
    _git("clean", "-fdx")

    if ui_mode.is_active():
        ui_mode.get_app().step("Switching to the latest branch")
    branch = _default_branch()
    _git("checkout", "-B", branch, f"origin/{branch}")

    if ui_mode.is_active():
        ui_mode.get_app().ok(f"Updated to origin/{branch}")
    else:
        print("Update complete.")
    return 0


def main() -> int:
    if "--ui" in sys.argv[1:]:
        sys.argv = [a for a in sys.argv if a != "--ui"]
        if ui_mode.HAS_TK:
            app = ui_mode.activate("Update", "sync with GitHub")
            return app.run(_logic)
    return _logic()


if __name__ == "__main__":
    try:
        rc = main()
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit {e.returncode}", file=sys.stderr)
        rc = e.returncode or 1
    except FileNotFoundError:
        print("git not found. Install Git and ensure it is on PATH.",
              file=sys.stderr)
        rc = 1
    if sys.platform == "win32" and not ui_mode.is_active():
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass
    sys.exit(rc)
