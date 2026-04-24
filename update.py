#!/usr/bin/env python3
"""Pull the latest changes from the git remote and refresh Python deps."""
import os
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def main() -> int:
    repo = Path(__file__).resolve().parent
    os.chdir(repo)

    remote = os.environ.get("REMOTE", "orgin")
    branch = os.environ.get(
        "BRANCH",
        subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip(),
    )

    print(f"Fetching from {remote}...")
    run(["git", "fetch", remote, branch])

    print(f"Pulling latest changes on {branch}...")
    run(["git", "pull", "--ff-only", remote, branch])

    if (repo / "pyproject.toml").exists() or (repo / "setup.py").exists():
        print("Installing/updating Python dependencies...")
        run([sys.executable, "-m", "pip", "install", "-e", ".", "--upgrade"])

    print("Update complete.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}", file=sys.stderr)
        sys.exit(e.returncode)
