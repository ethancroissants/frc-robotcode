#!/usr/bin/env python3
"""Cold Fusion Robotics — Vision Pi updater.

Same as `setup_orangepi.py` but skips the apt-install / first-time
provisioning steps. Use this for routine "I changed app.js, push it":

    python update_orangepi.py --ui

It rsyncs the orangepi/ folder and `systemctl restart`s the service.
Falls back to a full install run if the service isn't installed yet.
"""

from __future__ import annotations

import shlex
import sys

import setup_orangepi as base
import ui_mode


def _logic() -> int:
    if ui_mode.is_active():
        ui_mode.get_app().banner("Vision Pi Update", "push code changes to the Pi")

    cfg = base.load_cfg()
    if not cfg.get("host"):
        base._info("No saved Pi config — running first-time setup instead.")
        return base._logic()

    if not base.check_reachable(cfg):
        return 1

    # If key auth ever broke (Pi got re-flashed, keys cleared, etc.) the
    # update path would silently hang on the first ssh call. Detect that
    # and bounce back into the full setup, which knows how to reprompt
    # for a password and re-bootstrap.
    if not base._ssh_key_auth_works(cfg):
        base._info("SSH key auth no longer works — running full setup to fix it.")
        return base._logic()

    if not base.push_files(cfg):
        return 1

    base._step("Restarting the Pi service")
    target = base.ssh_target(cfg)
    rc = base._stream([
        "ssh", "-t", target,
        "sudo systemctl restart cold-fusion-sight && "
        "systemctl --no-pager status cold-fusion-sight | sed -n '1,5p'",
    ])
    if rc != 0:
        base._fail("Service restart failed — falling back to full install.")
        return base.run_remote_install(cfg) and 0 or 1

    url = f"http://{cfg['host']}:8080/"
    base._ok(f"Update complete. UI: {url}")
    if ui_mode.is_active():
        ui_mode.get_app().set_followup(
            "Open Sight UI",
            lambda: base._open_browser(url),
            prompt=f"Pi updated. UI is at {url}.",
        )
    return 0


def main() -> int:
    if "--ui" in sys.argv[1:]:
        sys.argv = [a for a in sys.argv if a != "--ui"]
        if ui_mode.HAS_TK:
            app = ui_mode.activate("Vision Pi Update", "push changes to the Pi")
            return app.run(_logic)
    return _logic()


if __name__ == "__main__":
    sys.exit(main())
