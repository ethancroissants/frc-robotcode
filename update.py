#!/usr/bin/env python3
"""Reset the local repo to match its GitHub remote."""
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent


def git(*args: str, capture: bool = False) -> str:
    cmd = ["git", "-C", str(REPO_DIR), *args]
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, check=True, text=True, capture_output=capture)
    return (result.stdout or "").strip()


def default_branch() -> str:
    try:
        ref = git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", capture=True)
        return ref.rsplit("/", 1)[-1]
    except subprocess.CalledProcessError:
        return "main"


def main() -> int:
    git("fetch", "origin", "--prune")
    git("reset", "--hard", "HEAD")
    git("clean", "-fdx")
    branch = default_branch()
    git("checkout", "-B", branch, f"origin/{branch}")
    print("Update complete.")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit {e.returncode}", file=sys.stderr)
        rc = e.returncode or 1
    except FileNotFoundError:
        print("git not found. Install Git and ensure it is on PATH.", file=sys.stderr)
        rc = 1
    if sys.platform == "win32":
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass
    sys.exit(rc)
