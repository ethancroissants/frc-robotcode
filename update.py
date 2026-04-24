#!/usr/bin/env python3
"""Nuke the local repo and re-clone fresh from GitHub."""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_URL = os.environ.get(
    "REPO_URL", "https://github.com/ethancroissants/frc-robotcode"
)


def find_git() -> str:
    git = shutil.which("git")
    if git:
        return git
    # Admin processes inherit system PATH, which often lacks Git for Windows.
    if os.name == "nt":
        for candidate in (
            r"C:\Program Files\Git\cmd\git.exe",
            r"C:\Program Files (x86)\Git\cmd\git.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
        ):
            if Path(candidate).exists():
                return candidate
    raise FileNotFoundError(
        "git executable not found. Install Git and ensure it is on PATH."
    )


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def is_admin() -> bool:
    if os.name != "nt":
        return True
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def relaunch_as_admin() -> int:
    import ctypes
    script = str(Path(__file__).resolve())
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
    # ShellExecuteW with "runas" triggers the UAC elevation prompt.
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, f'"{script}" {params}', None, 1
    )
    if rc <= 32:
        print("Elevation was declined or failed.", file=sys.stderr)
        return 1
    return 0


def force_remove(func, path, _exc):
    # Git marks pack .idx files read-only; clear the bit and retry.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def main() -> int:
    if os.name == "nt" and not is_admin():
        print("Requesting administrator privileges...")
        return relaunch_as_admin()

    script = Path(__file__).resolve()
    repo = script.parent
    parent = repo.parent
    name = repo.name

    stash_dir = Path(tempfile.mkdtemp(prefix="frc-update-"))
    stash = stash_dir / script.name
    print(f"Moving update script to {stash}...")
    shutil.move(str(script), str(stash))

    os.chdir(parent)

    print(f"Deleting {repo}...")
    shutil.rmtree(repo, onexc=force_remove)

    git = find_git()
    print(f"Cloning {REPO_URL} into {name}...")
    run([git, "clone", REPO_URL, name])

    new_repo = parent / name
    os.chdir(new_repo)
    print(f"Now in {new_repo}")

    print(f"Deleting moved update script {stash}...")
    stash.unlink()
    stash_dir.rmdir()

    print("Update complete.")
    return 0


if __name__ == "__main__":
    # If we were relaunched as admin, Windows will close this console on exit.
    # Pause so the user can read any output (success or failure).
    elevated = os.name == "nt" and is_admin() and sys.argv[-1:] != ["--no-pause"]
    code = 0
    try:
        code = main()
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}", file=sys.stderr)
        code = e.returncode
    except Exception as e:
        import traceback
        traceback.print_exc()
        code = 1
    if elevated:
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass
    sys.exit(code)
