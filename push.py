#!/usr/bin/env python3
"""Stage all changes, commit as "update", and push to GitHub.

Pass --ui to show the friendly Cold Fusion loading-bar window.

Token handling:
  We never embed the GitHub PAT in the remote URL anymore — the previous
  version did, and the URL got echoed to stdout by `_run`'s `print(...)`,
  leaking the token into shell history / pasted terminal output.

  Now the token comes from one of these sources, in priority order:
    1. $GH_TOKEN environment variable
    2. ~/.config/cfsight/gh-token (chmod 600)
    3. The user's existing git credential helper (`credential.helper`) —
       if neither of the above is set, we just call `git push` and trust
       whatever's already configured (git-credential-osxkeychain on Mac,
       libsecret on Linux, manager-core on Windows, etc.).

  When we *do* have a token, it's handed to git via GIT_ASKPASS — git
  asks our helper script for the credential and gets it on stdin, no
  argv echo, no log line. The script self-deletes when done.

  First-time setup (after revoking the leaked token from the GitHub UI):
    mkdir -p ~/.config/cfsight
    printf 'ghp_yourNewTokenHere' > ~/.config/cfsight/gh-token
    chmod 600 ~/.config/cfsight/gh-token
"""
from __future__ import annotations

import os
import shlex
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import ui_mode

GH_USER = "ethancroissants"
TOKEN_FILE = Path.home() / ".config" / "cfsight" / "gh-token"


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    """Run a subprocess. Prints a redacted command line so passwords /
    tokens that snuck into argv (shouldn't happen in this script
    anymore, but defence-in-depth) never reach stdout."""
    safe = " ".join(_redact_arg(a) for a in cmd)
    if ui_mode.is_active():
        ui_mode.get_app().info(f"$ {safe}")
        rc = ui_mode.get_app().stream_subprocess(cmd, env=env)
        if rc != 0:
            raise subprocess.CalledProcessError(rc, cmd)
        return
    print(f"$ {safe}")
    subprocess.run(cmd, check=True, env=env)


def _redact_arg(arg: str) -> str:
    # Nothing in this script's argv should ever contain a token, but if
    # something slips through (e.g. the user runs push.py with a custom
    # remote URL that has embedded creds), redact obvious patterns
    # before printing.
    if "ghp_" in arg or "github_pat_" in arg or "@github.com" in arg:
        return "<redacted>"
    return arg


def _step(msg: str) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().step(msg)
    else:
        print(msg)


def _info(msg: str) -> None:
    if ui_mode.is_active():
        ui_mode.get_app().info(msg)
    else:
        print(msg)


def _read_token() -> str | None:
    """Pick up the GitHub PAT from env var or ~/.config file. Returns
    None if no token is configured (in which case we let git's
    credential helper handle auth on its own)."""
    env_tok = os.environ.get("GH_TOKEN", "").strip()
    if env_tok:
        return env_tok
    if TOKEN_FILE.is_file():
        # Sanity-check perms: a token file readable by every user on the
        # box is a config bug we should at least warn about.
        try:
            mode = TOKEN_FILE.stat().st_mode & 0o777
            if mode & 0o077:
                _info(
                    f"warning: {TOKEN_FILE} is mode 0o{mode:o} (world/group readable). "
                    f"Run `chmod 600 {TOKEN_FILE}` to lock it down."
                )
        except OSError:
            pass
        token = TOKEN_FILE.read_text().strip()
        if token:
            return token
    return None


def _make_askpass_script(token: str) -> tuple[Path, dict[str, str]]:
    """Drop a one-shot GIT_ASKPASS helper into a temp file. The helper
    just echoes the username when git asks for "Username for ..." and
    the token when it asks for "Password for ...". The token never
    appears in the helper's argv, only on stdout (which git captures
    privately).

    Returns (script_path, env_overrides) — caller is responsible for
    deleting the script after the push completes."""
    fd, path = tempfile.mkstemp(prefix="cfsight-askpass-", suffix=".sh")
    os.close(fd)
    p = Path(path)
    p.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$1\" in\n"
        f"  *Username*) printf '%s' {shlex.quote(GH_USER)} ;;\n"
        # Token comes from the env we set in the parent. NEVER bake the
        # token into the script body — the file is mode 600 but it's
        # still nicer to keep it ephemeral via env.
        "  *Password*) printf '%s' \"$CFSIGHT_TOKEN\" ;;\n"
        "  *) printf '' ;;\n"
        "esac\n"
    )
    p.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)  # 0o700
    env = {
        "GIT_ASKPASS": str(p),
        "CFSIGHT_TOKEN": token,
        # GIT_TERMINAL_PROMPT=0 makes git fail loudly instead of hanging
        # for a tty prompt if the askpass somehow returns empty.
        "GIT_TERMINAL_PROMPT": "0",
    }
    return p, env


def _logic(force_mode: str = "off") -> int:
    """force_mode:
       "off"            — plain `git push`, fails on non-fast-forward (safe)
       "lease"          — `git push --force-with-lease`, only overwrites
                          remote if it matches what we last fetched
       "force"          — `git push --force`, the foot-gun. Requires explicit
                          --force on the CLI; --force-with-lease is the
                          default destructive option because it's safer.
    """
    repo = Path(__file__).resolve().parent
    os.chdir(repo)

    if ui_mode.is_active():
        ui_mode.get_app().banner("Push", "send your changes to GitHub")

    remote = os.environ.get("REMOTE", "orgin")
    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip()

    _step("Staging changes")
    _run(["git", "add", "-A"])

    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"]
    ).returncode
    if staged == 0:
        _info("No staged changes to commit.")
    else:
        _step("Committing")
        _run(["git", "commit", "-m", "update"])

    label = {"off": "", "lease": " (--force-with-lease)", "force": " (--force)"}[force_mode]
    _step(f"Pushing to {remote}/{branch}{label}")

    if force_mode == "force":
        _info(
            "WARNING: --force is the foot-gun version. It overwrites the "
            "remote even if someone else pushed concurrently. Prefer "
            "--force-with-lease unless you have a specific reason."
        )

    token = _read_token()
    askpass_path: Path | None = None
    push_env: dict[str, str] | None = None
    if token:
        askpass_path, env_overrides = _make_askpass_script(token)
        # Merge into the current env so PATH / etc. survive.
        push_env = {**os.environ, **env_overrides}
    else:
        _info(
            "no token in $GH_TOKEN or ~/.config/cfsight/gh-token — "
            "relying on your existing git credential helper."
        )

    push_cmd = ["git"]
    if token:
        # Override any system credential helper for this single push.
        # `-c credential.helper=` (empty value) tells git "ignore the
        # configured helper", which forces it to fall through to our
        # GIT_ASKPASS env var. Without this, on macOS the keychain
        # helper would intercept the auth request and serve a cached
        # (possibly stale) token before askpass ever runs — that's
        # the failure mode that wedged a "PAT lacks workflow scope"
        # error even after we gave the new token workflow scope.
        push_cmd += ["-c", "credential.helper="]
    push_cmd += ["push"]
    if force_mode == "lease":
        push_cmd.append("--force-with-lease")
    elif force_mode == "force":
        push_cmd.append("--force")
    push_cmd += [remote, branch]

    try:
        # Push to the configured remote name (no embedded creds in URL!).
        # Token, if any, is delivered via GIT_ASKPASS in push_env.
        _run(push_cmd, env=push_env)
    finally:
        # Always delete the askpass script, even on push failure.
        if askpass_path is not None:
            try:
                askpass_path.unlink()
            except OSError:
                pass

    if ui_mode.is_active():
        ui_mode.get_app().ok("Push complete.")
    else:
        print("Push complete.")
    return 0


def main() -> int:
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print(__doc__)
        print()
        print("Flags:")
        print("  --ui                  Show the friendly Tk progress window")
        print("  --force-with-lease    Overwrite remote, but only if it matches what we last fetched")
        print("  --force               Overwrite remote unconditionally (foot-gun)")
        return 0

    force_mode = "off"
    if "--force-with-lease" in args:
        force_mode = "lease"
        args = [a for a in args if a != "--force-with-lease"]
    elif "--force" in args:
        force_mode = "force"
        args = [a for a in args if a != "--force"]

    if "--ui" in args:
        args = [a for a in args if a != "--ui"]
        sys.argv = [sys.argv[0]] + args
        if ui_mode.HAS_TK:
            app = ui_mode.activate("Push", "send changes to GitHub")
            return app.run(lambda: _logic(force_mode=force_mode))

    sys.argv = [sys.argv[0]] + args
    return _logic(force_mode=force_mode)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}", file=sys.stderr)
        sys.exit(e.returncode)
