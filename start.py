#!/usr/bin/env python3
"""Cold Fusion Robotics — Control Panel.

A light-themed launcher window that opens the right script for each task:
install, deploy, update, push, or run the simulator. Each button spawns
the matching script as a separate subprocess (with --ui where available),
so each task runs in its own friendly loading-bar window.

Run me directly with:

    python start.py

…or use the start.bash wrapper.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox
    HAS_TK = True
except ImportError:
    HAS_TK = False


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


def _launch(args: list[str]) -> None:
    """Spawn a subprocess for a task; do not block the dashboard."""
    cmd = [sys.executable, *args]
    try:
        # On Windows, open in a new console so the child has its own window
        # group; everywhere else, just spawn detached.
        kwargs = {"cwd": str(REPO)}
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

        inner = tk.Frame(self, bg=PANEL, padx=18, pady=14)
        inner.pack(fill="x")
        self._inner = inner

        self._title = tk.Label(
            inner,
            text=title,
            bg=PANEL,
            fg=FG,
            font=("Helvetica", 13, "bold"),
            anchor="w",
        )
        self._title.pack(anchor="w")
        self._subtitle = tk.Label(
            inner,
            text=subtitle,
            bg=PANEL,
            fg=DIM,
            font=("Helvetica", 10),
            anchor="w",
        )
        self._subtitle.pack(anchor="w", pady=(2, 0))

        for w in (self, inner, self._title, self._subtitle):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def _set_bg(self, color: str) -> None:
        self.configure(bg=color)
        self._inner.configure(bg=color)
        self._title.configure(bg=color)
        self._subtitle.configure(bg=color)

    def _click(self, _event=None) -> None:
        self._command()

    def _enter(self, _event=None) -> None:
        self._set_bg(self._hover_bg)
        self.configure(highlightbackground=HOVER_BORDER)

    def _leave(self, _event=None) -> None:
        self._set_bg(self._normal_bg)
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
    root.geometry("580x600")
    root.minsize(500, 540)

    # ----- header -----
    header = tk.Frame(root, bg=PANEL)
    header.pack(fill="x", side="top")
    hinner = tk.Frame(header, bg=PANEL, padx=24, pady=20)
    hinner.pack(fill="x")
    tk.Label(
        hinner,
        text="COLD FUSION ROBOTICS",
        bg=PANEL,
        fg=ACCENT,
        font=("Helvetica", 16, "bold"),
    ).pack(anchor="w")
    tk.Label(
        hinner,
        text="Team 1279 — Robot Code Control Panel",
        bg=PANEL,
        fg=DIM,
        font=("Helvetica", 11),
    ).pack(anchor="w", pady=(2, 0))
    tk.Frame(root, bg=BORDER, height=1).pack(fill="x")

    # ----- body -----
    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True, padx=22, pady=18)

    cards = [
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
            "Update from GitHub",
            "Sync this folder with the latest team code.",
            lambda: _launch(["update.py", "--ui"]),
        ),
        (
            "Push Changes",
            "Commit your edits and push them to GitHub.",
            lambda: _launch(["push.py", "--ui"]),
        ),
        (
            "Run Simulator",
            "Test the robot code on your computer.",
            lambda: _launch(["-m", "robotpy", "sim"]),
        ),
    ]
    for title, subtitle, cmd in cards:
        Card(body, title, subtitle, cmd).pack(fill="x", pady=6)

    # ----- footer -----
    footer = tk.Frame(root, bg=PANEL)
    footer.pack(fill="x", side="bottom")
    tk.Frame(footer, bg=BORDER, height=1).pack(fill="x", side="top")
    finner = tk.Frame(footer, bg=PANEL, padx=14, pady=10)
    finner.pack(fill="x")
    tk.Label(
        finner,
        text=f"Working in: {REPO}",
        bg=PANEL,
        fg=DIM,
        font=("Helvetica", 9),
        anchor="w",
    ).pack(side="left")
    tk.Button(
        finner,
        text="Quit",
        bg=PANEL,
        fg=FG,
        relief="flat",
        borderwidth=0,
        font=("Helvetica", 10),
        activebackground=PANEL,
        activeforeground=ACCENT,
        cursor="hand2",
        command=root.destroy,
    ).pack(side="right")

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
