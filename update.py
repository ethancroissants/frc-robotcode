#!/usr/bin/env python3
"""Reset the local repo to match its GitHub remote.

Pass --ui to show the friendly Cold Fusion loading-bar window.

When launched from start.py with CFR_RESTART_AFTER_UPDATE=1 in the env, the
success screen offers an "Open Control Panel" button that respawns start.py
with the freshly-pulled code. (If the user closes the window without
clicking, we respawn anyway so they're never left stranded.)
"""
import os
import shlex
import subprocess
import sys
from pathlib import Path

import ui_mode

REPO_DIR = Path(__file__).resolve().parent

# Set when the success-screen button fires, so we don't double-spawn.
_followup_state = {"fired": False}


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


def _spawn_start() -> None:
    """Open a fresh control panel; called from the followup button or as
    a fallback if the user closes the window manually."""
    _followup_state["fired"] = True
    start_py = REPO_DIR / "start.py"
    if not start_py.exists():
        return
    try:
        # Strip the restart flag so the new panel doesn't propagate it.
        env = dict(os.environ)
        env.pop("CFR_RESTART_AFTER_UPDATE", None)
        if sys.platform == "darwin":
            # On macOS a plain Popen of the Tk launcher gets hidden by the
            # window server (no LaunchServices/dock activation context) and
            # the panel silently never appears. Routing through Terminal.app
            # via osascript gives the relaunched python a real shell parent,
            # so its Tk window actually shows up. The shell command matches
            # the standard "run in Terminal" pattern: cd, run, echo exit,
            # exit so the Terminal tab can close itself.
            shell_cmd = (
                f"cd {shlex.quote(str(REPO_DIR))} && "
                f"{shlex.quote(sys.executable)} {shlex.quote(str(start_py))} && "
                f"echo Exit status: $? && exit 1"
            )
            # AppleScript double-quoted string: escape backslashes and quotes.
            safe = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
            osa = (
                f'tell application "Terminal" to do script "{safe}"\n'
                'tell application "Terminal" to activate'
            )
            subprocess.Popen(["osascript", "-e", osa])
        else:
            subprocess.Popen(
                [sys.executable, str(start_py)], cwd=str(REPO_DIR), env=env,
            )
    except Exception:
        pass


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
        if os.environ.get("CFR_RESTART_AFTER_UPDATE"):
            ui_mode.get_app().set_followup(
                label="Open Control Panel",
                on_click=_spawn_start,
                prompt="The menu will reopen with the new code.",
            )
    else:
        print("Update complete.")
    return 0


def main() -> int:
    if "--ui" in sys.argv[1:]:
        sys.argv = [a for a in sys.argv if a != "--ui"]
        if ui_mode.HAS_TK:
            app = ui_mode.activate("Update", "sync with GitHub")
            rc = app.run(_logic)
            # If start.py asked us to take over the panel and the user
            # didn't click the followup button (closed the window or hit X
            # after a failure), still bring the panel back.
            if (os.environ.get("CFR_RESTART_AFTER_UPDATE")
                    and not _followup_state["fired"]):
                _spawn_start()
            return rc
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
