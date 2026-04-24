#!/usr/bin/env python3
"""Nuke the local repo and re-clone fresh from GitHub."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_URL = os.environ.get(
    "REPO_URL", "https://github.com/ethancroissants/frc-robotcode"
)


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> int:
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
    shutil.rmtree(repo)

    print(f"Cloning {REPO_URL} into {name}...")
    run(["git", "clone", REPO_URL, name])

    new_repo = parent / name
    os.chdir(new_repo)
    print(f"Now in {new_repo}")

    print(f"Deleting moved update script {stash}...")
    stash.unlink()
    stash_dir.rmdir()

    print("Update complete.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}", file=sys.stderr)
        sys.exit(e.returncode)
