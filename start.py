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
import subprocess
import sys
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    HAS_TK = True
except ImportError:
    HAS_TK = False

import firewall


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
    root.geometry("520x520")
    root.minsize(440, 360)

    # ----- header -----
    header = tk.Frame(root, bg=PANEL)
    header.pack(fill="x", side="top")
    hinner = tk.Frame(header, bg=PANEL, padx=20, pady=12)
    hinner.pack(fill="x")
    tk.Label(
        hinner,
        text="COLD FUSION ROBOTICS",
        bg=PANEL,
        fg=ACCENT,
        font=("Helvetica", 14, "bold"),
    ).pack(anchor="w")
    tk.Label(
        hinner,
        text="Team 1279 — Robot Code Control Panel",
        bg=PANEL,
        fg=DIM,
        font=("Helvetica", 10),
    ).pack(anchor="w", pady=(1, 0))
    tk.Frame(root, bg=BORDER, height=1).pack(fill="x")

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

    def _firewall_on_clicked() -> None:
        if not firewall.is_windows():
            messagebox.showinfo(
                "Cold Fusion Robotics",
                "This button only does something on Windows. "
                "Your firewall (if any) is unchanged.",
                parent=root,
            )
            return
        # set_firewall blocks while UAC is up; the panel freezes for a
        # second or two and that's fine — UAC is the user's signal that
        # the request was heard.
        ok_, msg = firewall.set_firewall(True)
        if ok_:
            messagebox.showinfo("Cold Fusion Robotics", msg, parent=root)
        else:
            messagebox.showwarning("Cold Fusion Robotics", msg, parent=root)

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
        ("Tools", [
            (
                "Documentation",
                "Read the team's guides and dashboard reference.",
                lambda: _launch(["docs.py"]),
            ),
            (
                "Turn Firewall Back On",
                "Re-enable Windows Firewall (deploy turns it off for the DS).",
                _firewall_on_clicked,
            ),
        ]),
    ]
    for i, (section_title, section_cards) in enumerate(sections):
        tk.Label(
            body,
            text=section_title.upper(),
            bg=BG,
            fg=DIM,
            font=("Helvetica", 9, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0 if i == 0 else 10, 4))
        for title, subtitle, cmd in section_cards:
            Card(body, title, subtitle, cmd).pack(fill="x", pady=3)

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
