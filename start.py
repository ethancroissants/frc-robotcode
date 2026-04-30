#!/usr/bin/env python3
"""Cold Fusion Robotics — Control Panel.

A light-themed launcher window that opens the right script for each task:
install, deploy, update, push, or run the simulator. Each button spawns
the matching script as a separate subprocess (with --ui where available),
so each task runs in its own friendly loading-bar window.

Run me directly with:

    python start.py

…or double-click START.bat on Windows.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    HAS_TK = True
except ImportError:
    HAS_TK = False

import firewall
# Reuse the deploy module's ping + team-number helpers so we have one source
# of truth for "how do we find the rio". Importing it is side-effect-free
# beyond enabling ANSI on Windows stdout.
from deploy import ping, read_team_number


REPO = Path(__file__).resolve().parent

# Light theme palette (matches ui_mode.py).
BG = "#f4f5f7"
PANEL = "#ffffff"
FG = "#1a1f2e"
DIM = "#6b7280"
ACCENT = "#0066cc"
BORDER = "#e2e6ec"
CARD_HOVER = "#f0f6ff"
HOVER_BORDER = "#9cc4ee"
OK_COLOR = "#16a34a"
FAIL_COLOR = "#dc2626"
DISABLED_FG = "#9ca3af"
DISABLED_BG = "#f1f3f6"

DEFAULT_TEAM = "1279"
ROBOT_SSID = "FRC-1279"
STATUS_POLL_MS = 5000

# roboRIO ships with these SSH accounts; `admin` has no password by default.
SSH_USER = "admin"

# Standard FRC DS install locations. We probe in order; first one wins.
DRIVER_STATION_PATHS = [
    r"C:\Program Files (x86)\FRC Driver Station\DriverStation.exe",
    r"C:\Program Files\FRC Driver Station\DriverStation.exe",
]


def _driver_station_path() -> str | None:
    if platform.system() != "Windows":
        return None
    for p in DRIVER_STATION_PATHS:
        if os.path.exists(p):
            return p
    return None


def _run_elevated(file: str, args: list[str], *, wait: bool, timeout: int = 30) -> tuple[int, str]:
    """Run a program elevated via PowerShell `Start-Process -Verb RunAs`.

    UAC pops automatically. Returns (exit_code, stderr_or_stdout). Use
    wait=True to block until the elevated child exits (e.g. taskkill);
    wait=False fires-and-forgets (e.g. DriverStation, which we want to
    leave running).
    """
    arg_list = ",".join(f"'{a}'" for a in args) if args else ""
    body = (
        f"Start-Process -FilePath '{file}' "
        + (f"-ArgumentList {arg_list} " if arg_list else "")
        + "-Verb RunAs -PassThru -WindowStyle Hidden -ErrorAction Stop"
    )
    if wait:
        ps = (
            "$ErrorActionPreference='Stop'; try { "
            f"$p = {body}; $p.WaitForExit(); exit $p.ExitCode "
            "} catch { Write-Error $_.Exception.Message; exit 2 }"
        )
    else:
        ps = (
            "$ErrorActionPreference='Stop'; try { "
            f"$null = {body}; exit 0 "
            "} catch { Write-Error $_.Exception.Message; exit 2 }"
        )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return 127, "PowerShell not found."
    except subprocess.TimeoutExpired:
        return 124, "Timed out waiting for the UAC prompt."
    err = (result.stderr or result.stdout or "").strip()
    return result.returncode, err


def _open_driver_station() -> tuple[bool, str]:
    if platform.system() != "Windows":
        return True, "Skipped Driver Station (not on Windows)."
    path = _driver_station_path()
    if not path:
        return False, (
            "Couldn't find DriverStation.exe in the standard FRC install path."
        )
    # DS requires admin (it manages joystick HID and high-priority sockets),
    # so we elevate via UAC. Fire-and-forget: we don't want to wait for the
    # user to close DS.
    rc, err = _run_elevated(path, [], wait=False)
    if rc == 0:
        return True, "Launched Driver Station."
    low = err.lower()
    if "canceled" in low or "cancelled" in low:
        return False, "Admin permission denied — Driver Station not launched."
    return False, f"Failed to launch Driver Station: {err.splitlines()[0] if err else 'unknown error'}"


def _close_driver_station() -> tuple[bool, str]:
    if platform.system() != "Windows":
        return True, "Skipped Driver Station (not on Windows)."
    # DS runs elevated so killing it needs admin too. Wait for taskkill to
    # finish so the exit code tells us whether it actually killed something.
    rc, err = _run_elevated(
        "taskkill", ["/IM", "DriverStation.exe", "/F"], wait=True,
    )
    if rc == 0:
        return True, "Closed Driver Station."
    if rc == 128:
        return True, "Driver Station wasn't running."
    low = err.lower()
    if "canceled" in low or "cancelled" in low:
        return False, "Admin permission denied — Driver Station not closed."
    if "not found" in low or "no tasks" in low:
        return True, "Driver Station wasn't running."
    return False, f"Couldn't close Driver Station: {err.splitlines()[0] if err else 'unknown error'}"


def _current_wifi_ssid() -> str | None:
    """Return the SSID currently associated with the WiFi adapter, or None.
    Windows-only — uses `netsh wlan show interfaces`."""
    if platform.system() != "Windows":
        return None
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for raw in result.stdout.splitlines():
        line = raw.strip()
        # Match "SSID" but not "BSSID". netsh's localized output makes this
        # fragile in non-English Windows, but for now we trust English.
        if line.startswith("SSID") and not line.startswith("BSSID"):
            _, _, value = line.partition(":")
            value = value.strip()
            return value or None
    return None


def _disconnect_robot_wifi(ssid: str = ROBOT_SSID) -> tuple[bool, str]:
    """Disconnect the WiFi adapter. The user pressed an explicit
    Disconnect button, so we honor it unconditionally — no SSID
    detection that could falsely report "not connected" and skip the
    action while we're actually still on the robot network.

    Reports the previously-associated SSID when we can detect it, just
    so the user has feedback about what got dropped.
    """
    if platform.system() != "Windows":
        return True, "Skipped WiFi disconnect (not on Windows)."
    current = _current_wifi_ssid()  # best-effort; may return None
    try:
        result = subprocess.run(
            ["netsh", "wlan", "disconnect"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        return False, "netsh not found — can't manage WiFi."
    except subprocess.TimeoutExpired:
        return False, "WiFi disconnect timed out."
    if result.returncode == 0:
        if current:
            return True, f"Disconnected from {current}."
        return True, "WiFi disconnected."
    err = (result.stderr or result.stdout or "").strip().splitlines()
    return False, f"Couldn't disconnect: {err[0] if err else 'unknown error'}"


def _connect_robot_wifi(ssid: str = ROBOT_SSID) -> tuple[bool, str]:
    """Try to associate with the robot's WiFi network.

    Uses `netsh wlan connect`, which needs an existing saved profile for
    the SSID — Windows' WiFi UI creates that the first time you connect
    by hand. If there's no profile, the user has to connect once
    manually (entering the password) and from then on this works.

    Returns (success, message). Non-Windows is a friendly no-op.
    """
    if platform.system() != "Windows":
        return False, "Skipped WiFi connect (not on Windows)."
    current = _current_wifi_ssid()
    if current == ssid:
        return True, f"Already connected to {ssid}."
    try:
        result = subprocess.run(
            ["netsh", "wlan", "connect", f"name={ssid}", f"ssid={ssid}"],
            capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError:
        return False, "netsh not found — can't manage WiFi."
    except subprocess.TimeoutExpired:
        return False, "WiFi connect timed out."
    if result.returncode == 0:
        return True, f"Connecting to {ssid}…"
    err = (result.stderr or result.stdout or "").strip().splitlines()
    msg = err[0] if err else "unknown error"
    if "no such wireless" in msg.lower() or "profile" in msg.lower():
        msg = (
            f"No saved profile for {ssid}. "
            "Connect to it once manually so Windows remembers it."
        )
    return False, f"Couldn't connect to {ssid}: {msg}"


def _open_ssh_terminal(host: str) -> tuple[bool, str]:
    """Spawn a new terminal window running `ssh admin@host`.

    Each platform needs a different invocation: Windows Terminal if present
    (else cmd /k), Terminal.app via osascript on macOS, and the first
    available terminal emulator on Linux.
    """
    target = f"{SSH_USER}@{host}"
    system = platform.system()
    try:
        if system == "Windows":
            # Windows Terminal preferred — it's the modern one and ships
            # with Win11 by default. cmd /k keeps the window open after
            # ssh exits so the user can read errors.
            wt = shutil.which("wt.exe") or shutil.which("wt")
            if wt:
                subprocess.Popen([wt, "ssh", target])
            else:
                # Use shell=True so cmd's `start` builtin opens a new window.
                subprocess.Popen(
                    f'start "" cmd /k ssh {target}', shell=True,
                )
        elif system == "Darwin":
            script = (
                f'tell application "Terminal" to do script "ssh {target}"\n'
                'tell application "Terminal" to activate'
            )
            subprocess.Popen(["osascript", "-e", script])
        else:
            for term, args in (
                ("gnome-terminal", ["--", "ssh", target]),
                ("konsole", ["-e", "ssh", target]),
                ("xfce4-terminal", ["-e", f"ssh {target}"]),
                ("kitty", ["ssh", target]),
                ("alacritty", ["-e", "ssh", target]),
                ("xterm", ["-e", f"ssh {target}"]),
            ):
                if shutil.which(term):
                    subprocess.Popen([term, *args])
                    break
            else:
                return False, "No supported terminal emulator found on PATH."
    except Exception as e:
        return False, f"Failed to open terminal: {e}"
    return True, f"Opened SSH to {target}"


def _rio_addresses(team: str | None, *, include_mdns: bool = False) -> list[str]:
    """Candidate addresses for the rio. mDNS is slow when it fails, so it's
    off by default — we use it only for the explicit Prep Bot button."""
    t = team or DEFAULT_TEAM
    if not t.isdigit():
        t = DEFAULT_TEAM
    n = int(t)
    addrs = [f"10.{n // 100}.{n % 100}.2", "172.22.11.2"]
    if include_mdns:
        addrs.insert(0, f"roborio-{t}-FRC.local")
    return addrs


def _check_bot_status(*, include_mdns: bool = False, timeout_s: float = 0.6) -> tuple[bool, str | None]:
    """Try each candidate IP; return (reachable, host_that_worked)."""
    team = read_team_number() or DEFAULT_TEAM
    for host in _rio_addresses(team, include_mdns=include_mdns):
        if ping(host, timeout_s=timeout_s):
            return True, host
    return False, None


def _launch(args: list[str], *, restart_panel: bool = False) -> None:
    """Spawn a subprocess for a task; do not block the dashboard.

    If restart_panel is set, the child gets CFR_RESTART_AFTER_UPDATE=1 so it
    knows to reopen the panel for us when it finishes.
    """
    cmd = [sys.executable, *args]
    try:
        env = dict(os.environ)
        if restart_panel:
            env["CFR_RESTART_AFTER_UPDATE"] = "1"
        # On Windows, open in a new console so the child has its own window
        # group; everywhere else, just spawn detached.
        kwargs = {"cwd": str(REPO), "env": env}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x00000010  # CREATE_NEW_CONSOLE
        subprocess.Popen(cmd, **kwargs)
    except Exception as e:
        messagebox.showerror(
            "Cold Fusion Robotics", f"Failed to launch:\n{e}"
        )


class Card(tk.Frame):
    """A clickable rectangle with a title and a one-line subtitle."""

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        subtitle: str,
        command,
        *,
        enabled: bool = True,
    ) -> None:
        super().__init__(
            parent,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
            cursor="hand2",
        )
        self._command = command
        self._normal_bg = PANEL
        self._hover_bg = CARD_HOVER
        self._enabled = enabled

        inner = tk.Frame(self, bg=PANEL, padx=14, pady=9)
        inner.pack(fill="x")
        self._inner = inner

        self._title = tk.Label(
            inner,
            text=title,
            bg=PANEL,
            fg=FG,
            font=("Helvetica", 11, "bold"),
            anchor="w",
        )
        self._title.pack(anchor="w")
        self._subtitle = tk.Label(
            inner,
            text=subtitle,
            bg=PANEL,
            fg=DIM,
            font=("Helvetica", 9),
            anchor="w",
        )
        self._subtitle.pack(anchor="w", pady=(1, 0))

        for w in (self, inner, self._title, self._subtitle):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

        self._apply_enabled()

    def _set_bg(self, color: str) -> None:
        self.configure(bg=color)
        self._inner.configure(bg=color)
        self._title.configure(bg=color)
        self._subtitle.configure(bg=color)

    def _apply_enabled(self) -> None:
        if self._enabled:
            self._normal_bg = PANEL
            self._title.configure(fg=FG)
            self._subtitle.configure(fg=DIM)
            self.configure(cursor="hand2", highlightbackground=BORDER)
        else:
            self._normal_bg = DISABLED_BG
            self._title.configure(fg=DISABLED_FG)
            self._subtitle.configure(fg=DISABLED_FG)
            self.configure(cursor="arrow", highlightbackground=BORDER)
        self._set_bg(self._normal_bg)

    def set_enabled(self, value: bool) -> None:
        if self._enabled == value:
            return
        self._enabled = value
        self._apply_enabled()

    def _click(self, _event=None) -> None:
        if not self._enabled:
            return
        self._command()

    def _enter(self, _event=None) -> None:
        if not self._enabled:
            return
        self._set_bg(self._hover_bg)
        self.configure(highlightbackground=HOVER_BORDER)

    def _leave(self, _event=None) -> None:
        self._set_bg(self._normal_bg)
        if self._enabled:
            self.configure(highlightbackground=BORDER)


def main() -> int:
    if not HAS_TK:
        print(
            "Tkinter is not installed, so the control panel can't open.\n"
            "Install python3-tk (Linux) or reinstall Python with the "
            "tcl/tk option (Windows / mac).",
            file=sys.stderr,
        )
        return 1

    root = tk.Tk()
    root.title("Cold Fusion Robotics — Control Panel")
    root.configure(bg=BG)
    root.geometry("520x520")
    root.minsize(440, 360)

    # ----- header -----
    header = tk.Frame(root, bg=PANEL)
    header.pack(fill="x", side="top")
    hinner = tk.Frame(header, bg=PANEL, padx=20, pady=12)
    hinner.pack(fill="x")

    htitles = tk.Frame(hinner, bg=PANEL)
    htitles.pack(side="left", fill="x", expand=True)
    tk.Label(
        htitles,
        text="COLD FUSION ROBOTICS",
        bg=PANEL,
        fg=ACCENT,
        font=("Helvetica", 14, "bold"),
    ).pack(anchor="w")
    tk.Label(
        htitles,
        text="Team 1279 — Robot Code Control Panel",
        bg=PANEL,
        fg=DIM,
        font=("Helvetica", 10),
    ).pack(anchor="w", pady=(1, 0))

    # Live connection indicator. The dot recolors as we re-poll every
    # STATUS_POLL_MS milliseconds. Pinging happens on a background thread
    # so the UI stays responsive while ICMP times out.
    hstatus = tk.Frame(hinner, bg=PANEL)
    hstatus.pack(side="right", padx=(12, 0))
    status_dot = tk.Label(
        hstatus, text="●", bg=PANEL, fg=DIM, font=("Helvetica", 14)
    )
    status_dot.pack(side="left")
    status_text = tk.Label(
        hstatus,
        text="Checking…",
        bg=PANEL,
        fg=DIM,
        font=("Helvetica", 10),
    )
    status_text.pack(side="left", padx=(4, 0))

    tk.Frame(root, bg=BORDER, height=1).pack(fill="x")

    alive = {"v": True}
    # Latest reachable host from the status poller. The SSH button reads
    # this so it always targets the address that just answered a ping,
    # rather than re-probing on click.
    current_host: dict[str, str | None] = {"v": None}
    card_refs: dict[str, "Card"] = {}

    def _set_status(reachable: bool | None, host: str | None) -> None:
        if not alive["v"]:
            return
        if reachable is None:
            status_dot.configure(fg=DIM)
            status_text.configure(text="Checking…", fg=DIM)
        elif reachable:
            status_dot.configure(fg=OK_COLOR)
            status_text.configure(text=f"Connected ({host})", fg=FG)
        else:
            status_dot.configure(fg=FAIL_COLOR)
            status_text.configure(text="No bot connection", fg=FG)
        # Track the host so SSH knows where to dial; only the True branch
        # has a real host. None reverts the SSH button to disabled.
        current_host["v"] = host if reachable else None
        for cid in ("ssh", "wipe"):
            card = card_refs.get(cid)
            if card is not None:
                card.set_enabled(bool(reachable))

    def _poll_status() -> None:
        if not alive["v"]:
            return

        def worker() -> None:
            ok_, host = _check_bot_status()
            if alive["v"]:
                root.after(0, lambda: _set_status(ok_, host))

        threading.Thread(target=worker, daemon=True).start()
        root.after(STATUS_POLL_MS, _poll_status)

    def _on_close() -> None:
        alive["v"] = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    # First check fires immediately, then every STATUS_POLL_MS thereafter.
    root.after(100, _poll_status)

    # ----- scrollable body -----
    # Tk has no native scrollable frame, so we wrap a Frame inside a Canvas
    # and keep them in sync via <Configure>. Mousewheel binds use bind_all
    # but only while the cursor is over our canvas (Enter/Leave).
    body_outer = tk.Frame(root, bg=BG)
    body_outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(body_outer, bg=BG, highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(body_outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    body = tk.Frame(canvas, bg=BG)
    inner_id = canvas.create_window((0, 0), window=body, anchor="nw")

    def _on_canvas_resize(event: "tk.Event") -> None:
        canvas.itemconfigure(inner_id, width=event.width)

    def _on_body_resize(_event=None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    canvas.bind("<Configure>", _on_canvas_resize)
    body.bind("<Configure>", _on_body_resize)

    def _on_mousewheel(event: "tk.Event") -> None:
        # On Windows/macOS event.delta is +/-120 per notch; on X11 we get
        # Button-4/Button-5 events instead (handled below).
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind_wheel(_e=None) -> None:
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

    def _unbind_wheel(_e=None) -> None:
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

    canvas.bind("<Enter>", _bind_wheel)
    canvas.bind("<Leave>", _unbind_wheel)

    # Pad inside the scrollable area, not on the canvas, so the scrollbar
    # hugs the right edge of the window.
    body_padded = tk.Frame(body, bg=BG)
    body_padded.pack(fill="both", expand=True, padx=18, pady=12)
    body = body_padded

    def _update_clicked() -> None:
        # Close the panel so only the update window stays on screen; the
        # update process will reopen a fresh panel when it finishes (so the
        # menu picks up any code changes from the pull).
        _launch(["update.py", "--ui"], restart_panel=True)
        root.destroy()

    def _disconnect_clicked() -> None:
        # "Disconnect" is the inverse of Connect: re-enable the firewall,
        # drop the robot WiFi (only if we're actually on it — see
        # _disconnect_robot_wifi), and close the Driver Station.
        if firewall.is_windows():
            fw_ok, fw_msg = firewall.set_firewall(True)
        else:
            fw_ok, fw_msg = True, "Skipped firewall (not on Windows)."
        wifi_ok, wifi_msg = _disconnect_robot_wifi(ROBOT_SSID)
        ds_ok, ds_msg = _close_driver_station()
        # Refresh the header dot — we just kicked the WiFi, so cached
        # state is stale.
        _set_status(None, None)

        body_text = (
            f"Firewall: {fw_msg}\n\n"
            f"WiFi: {wifi_msg}\n\n"
            f"Driver Station: {ds_msg}"
        )
        if fw_ok and wifi_ok and ds_ok:
            messagebox.showinfo("Disconnect", body_text, parent=root)
        else:
            messagebox.showwarning("Disconnect", body_text, parent=root)

    def _ssh_clicked() -> None:
        host = current_host["v"]
        if not host:
            messagebox.showwarning(
                "SSH",
                "Not connected to the robot. Press Connect first.",
                parent=root,
            )
            return
        ok_, msg = _open_ssh_terminal(host)
        if not ok_:
            messagebox.showerror("SSH", msg, parent=root)

    def _orangepi_target() -> tuple[str, str] | None:
        """Resolve the saved Pi user/host from .orangepi_cfg."""
        cfg_path = REPO / ".orangepi_cfg"
        if not cfg_path.exists():
            return None
        try:
            import json
            data = json.loads(cfg_path.read_text())
        except Exception:
            return None
        host = data.get("host")
        user = data.get("user", "orangepi")
        if not host:
            return None
        return user, host

    def _open_sight_ui_clicked() -> None:
        target = _orangepi_target()
        if target is None:
            messagebox.showinfo(
                "Sight UI",
                "Vision Pi isn't set up yet. Click \"Set up Vision Pi\" first.",
                parent=root,
            )
            return
        _, host = target
        url = f"http://{host}:8080/"
        import webbrowser
        webbrowser.open(url)

    def _ssh_pi_clicked() -> None:
        target = _orangepi_target()
        if target is None:
            messagebox.showinfo(
                "SSH",
                "Vision Pi isn't set up yet. Click \"Set up Vision Pi\" first.",
                parent=root,
            )
            return
        user, host = target
        # _open_ssh_terminal hardcodes admin@host for the rio; Pi uses orangepi.
        # Build the same per-platform spawning logic but with the right user.
        target_str = f"{user}@{host}"
        try:
            if platform.system() == "Windows":
                wt = shutil.which("wt.exe") or shutil.which("wt")
                if wt:
                    subprocess.Popen([wt, "ssh", target_str])
                else:
                    subprocess.Popen(f'start "" cmd /k ssh {target_str}', shell=True)
            elif platform.system() == "Darwin":
                script = (
                    f'tell application "Terminal" to do script "ssh {target_str}"\n'
                    'tell application "Terminal" to activate'
                )
                subprocess.Popen(["osascript", "-e", script])
            else:
                for term, args in (
                    ("gnome-terminal", ["--", "ssh", target_str]),
                    ("konsole", ["-e", "ssh", target_str]),
                    ("xfce4-terminal", ["-e", f"ssh {target_str}"]),
                    ("kitty", ["ssh", target_str]),
                    ("alacritty", ["-e", "ssh", target_str]),
                    ("xterm", ["-e", f"ssh {target_str}"]),
                ):
                    if shutil.which(term):
                        subprocess.Popen([term, *args])
                        break
                else:
                    messagebox.showerror(
                        "SSH", "No supported terminal emulator found.", parent=root,
                    )
        except Exception as e:
            messagebox.showerror("SSH", f"Failed to open terminal: {e}", parent=root)

    prep_running = {"v": False}

    def _prep_bot_clicked() -> None:
        # Guard against double-clicks while a prep is in flight. Each step
        # blocks (UAC, netsh, sleep, ping) so we run on a worker thread and
        # bounce the result dialog back to the UI thread.
        if prep_running["v"]:
            return
        prep_running["v"] = True
        _set_status(None, None)

        def worker() -> None:
            try:
                # 1) Drop the firewall so the DS can talk to the rio.
                if firewall.is_windows():
                    fw_ok, fw_msg = firewall.set_firewall(False)
                else:
                    fw_ok, fw_msg = True, "Skipped firewall (not on Windows)."

                # 2) Associate with the robot WiFi (FRC-1279).
                wifi_ok, wifi_msg = _connect_robot_wifi(ROBOT_SSID)

                # 3) Give the adapter a few seconds to associate + DHCP
                #    before pinging. We retry the ping each second so we
                #    don't wait the full window when association is fast.
                bot_ok, host = False, None
                deadline = time.monotonic() + (8.0 if wifi_ok else 1.0)
                while time.monotonic() < deadline:
                    bot_ok, host = _check_bot_status(
                        include_mdns=True, timeout_s=0.8
                    )
                    if bot_ok:
                        break
                    time.sleep(1.0)

                if bot_ok:
                    bot_msg = f"Connected to the robot at {host}."
                else:
                    bot_msg = (
                        "Couldn't reach the robot on any known address.\n"
                        "Check that the rio is powered, fully booted, and "
                        "that you're on its WiFi (or USB tethered)."
                    )

                # 4) Launch the Driver Station so the user has it ready.
                ds_ok, ds_msg = _open_driver_station()
            except Exception as e:  # never lose the lock on a crash
                fw_ok = wifi_ok = bot_ok = ds_ok = False
                fw_msg = wifi_msg = bot_msg = ds_msg = ""
                _err = f"Connect crashed: {e}"
                root.after(0, lambda: messagebox.showerror(
                    "Connect", _err, parent=root,
                ))
                prep_running["v"] = False
                return

            def show() -> None:
                _set_status(bot_ok, host)
                body_text = (
                    f"Firewall: {fw_msg}\n\n"
                    f"WiFi: {wifi_msg}\n\n"
                    f"Robot: {bot_msg}\n\n"
                    f"Driver Station: {ds_msg}"
                )
                if bot_ok and fw_ok and wifi_ok and ds_ok:
                    messagebox.showinfo("Connect", body_text, parent=root)
                else:
                    messagebox.showwarning("Connect", body_text, parent=root)
                prep_running["v"] = False

            root.after(0, show)

        threading.Thread(target=worker, daemon=True).start()

    sections = [
        ("Robot Code", [
            (
                "Install / Setup",
                "Install RobotPy and project dependencies.",
                lambda: _launch(["setup.py", "--ui"]),
            ),
            (
                "Deploy to Robot",
                "Push the latest code onto the roboRIO.",
                lambda: _launch(["deploy.py", "--ui"]),
            ),
            (
                "Wipe RoboRIO",
                "Fresh-install Python on the rio when a deploy left it broken.",
                lambda: _launch(["wipe_rio.py", "--ui"]),
                "wipe",
            ),
            (
                "Update from GitHub",
                "Sync this folder with the latest team code.",
                _update_clicked,
            ),
            (
                "Run Simulator",
                "Test the robot code on your computer.",
                lambda: _launch(["-m", "robotpy", "sim"]),
            ),
        ]),
        ("Connection", [
            (
                "Connect",
                "Disable firewall, join FRC-1279 WiFi, and ping the robot.",
                _prep_bot_clicked,
            ),
            (
                "Disconnect",
                "Re-enable firewall and leave the robot WiFi.",
                _disconnect_clicked,
            ),
            (
                "SSH to Robot",
                "Open a terminal connected to the rio over SSH.",
                _ssh_clicked,
                "ssh",
            ),
        ]),
        ("Vision Pi", [
            (
                "Set up Vision Pi",
                "Install the camera + sight web UI on the Orange Pi 5.",
                lambda: _launch(["setup_orangepi.py", "--ui"]),
            ),
            (
                "Update Vision Pi",
                "Push the latest sight code to the Pi and restart.",
                lambda: _launch(["update_orangepi.py", "--ui"]),
            ),
            (
                "Open Sight UI",
                "Open the Pi's camera/control web page in your browser.",
                _open_sight_ui_clicked,
            ),
            (
                "SSH to Vision Pi",
                "Open a terminal connected to the Pi over SSH.",
                _ssh_pi_clicked,
            ),
        ]),
        ("Tools", [
            (
                "Documentation",
                "Read the team's guides and dashboard reference.",
                lambda: _launch(["docs.py"]),
            ),
        ]),
    ]
    # Two-column grid per section. Cards have uniform width via grid_columnconfigure
    # with weight=1 + uniform="cards", so they stay the same size as the window grows.
    for i, (section_title, section_cards) in enumerate(sections):
        tk.Label(
            body,
            text=section_title.upper(),
            bg=BG,
            fg=DIM,
            font=("Helvetica", 9, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0 if i == 0 else 12, 4))
        grid = tk.Frame(body, bg=BG)
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1, uniform="cards")
        grid.grid_columnconfigure(1, weight=1, uniform="cards")
        for j, item in enumerate(section_cards):
            # 4th tuple element (optional) is a stable id used to look the
            # card up later — needed for the SSH card whose enabled state
            # tracks bot reachability.
            title, subtitle, cmd = item[0], item[1], item[2]
            card_id = item[3] if len(item) > 3 else None
            # SSH and Wipe start disabled; the status poller flips them on
            # once the rio answers a ping (both need a live SSH connection).
            initial_enabled = card_id not in ("ssh", "wipe")
            card = Card(grid, title, subtitle, cmd, enabled=initial_enabled)
            card.grid(row=j // 2, column=j % 2, sticky="nsew", padx=4, pady=4)
            if card_id:
                card_refs[card_id] = card

    # ----- footer -----
    footer = tk.Frame(root, bg=PANEL)
    footer.pack(fill="x", side="bottom")
    tk.Frame(footer, bg=BORDER, height=1).pack(fill="x", side="top")
    finner = tk.Frame(footer, bg=PANEL, padx=12, pady=6)
    finner.pack(fill="x")
    left = tk.Frame(finner, bg=PANEL)
    left.pack(side="left", fill="x", expand=True)
    tk.Label(
        left,
        text=f"Working in: {REPO}",
        bg=PANEL,
        fg=DIM,
        font=("Helvetica", 8),
        anchor="w",
    ).pack(anchor="w")
    tk.Label(
        left,
        text="Code & GUI by Ethan Canterbury",
        bg=PANEL,
        fg=DIM,
        font=("Helvetica", 8),
        anchor="w",
    ).pack(anchor="w", pady=(1, 0))
    tk.Button(
        finner,
        text="Quit",
        bg=PANEL,
        fg=FG,
        relief="flat",
        borderwidth=0,
        font=("Helvetica", 9),
        activebackground=PANEL,
        activeforeground=ACCENT,
        cursor="hand2",
        command=root.destroy,
    ).pack(side="right")

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
