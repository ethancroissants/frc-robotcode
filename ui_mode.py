"""Cold Fusion Robotics UI mode for setup/deploy/update/push scripts.

Activated by `--ui` on the host script's command line. Opens a light-themed
window with a friendly title, a progress bar, and the current step. Raw
subprocess / log output is captured into a hidden "Show details" panel so
the main view stays clean.

Threading: the host's logic runs on a worker thread; UI updates marshal
back to the Tk main thread via root.after(). Worker-side ask_yn/pause
block on a queue until the dialog returns.
"""

from __future__ import annotations

import queue
import subprocess
import threading
from typing import Callable

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    HAS_TK = True
except ImportError:
    HAS_TK = False


# Light theme palette.
BG = "#f4f5f7"
PANEL = "#ffffff"
FG = "#1a1f2e"
DIM = "#6b7280"
ACCENT = "#0066cc"
OK_COLOR = "#16a34a"
FAIL_COLOR = "#dc2626"
WARN_COLOR = "#d97706"
BORDER = "#e2e6ec"
TROUGH = "#e8ecf2"
DETAILS_BG = "#fbfbfd"


_app: "App | None" = None


def is_active() -> bool:
    return _app is not None


def get_app() -> "App":
    assert _app is not None, "UI mode is not active"
    return _app


def activate(title: str, subtitle: str = "") -> "App":
    """Create the singleton App. Must be called from the main thread."""
    global _app
    if _app is None:
        _app = App(title, subtitle)
    return _app


class _Reply:
    """One-shot cross-thread mailbox for blocking UI dialogs."""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue(maxsize=1)

    def put(self, value) -> None:
        self._q.put(value)

    def get(self):
        return self._q.get()


class App:
    def __init__(self, title: str, subtitle: str = "") -> None:
        self.root = tk.Tk()
        self.root.title(f"Cold Fusion Robotics — {title}")
        self.root.configure(bg=BG)
        self.root.geometry("640x440")
        self.root.minsize(560, 400)

        # ----- header -----
        header = tk.Frame(self.root, bg=PANEL)
        header.pack(fill="x", side="top")
        hinner = tk.Frame(header, bg=PANEL, padx=24, pady=18)
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
            text=subtitle or title,
            bg=PANEL,
            fg=DIM,
            font=("Helvetica", 11),
        ).pack(anchor="w", pady=(2, 0))
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", side="top")

        # ----- footer -----
        footer = tk.Frame(self.root, bg=PANEL)
        footer.pack(fill="x", side="bottom")
        tk.Frame(footer, bg=BORDER, height=1).pack(fill="x", side="top")
        finner = tk.Frame(footer, bg=PANEL, padx=14, pady=10)
        finner.pack(fill="x")
        self._status_var = tk.StringVar(value="Working…")
        tk.Label(
            finner,
            textvariable=self._status_var,
            bg=PANEL,
            fg=DIM,
            font=("Helvetica", 10),
            anchor="w",
        ).pack(side="left")
        self._details_btn = tk.Button(
            finner,
            text="Show details",
            bg=PANEL,
            fg=DIM,
            relief="flat",
            borderwidth=0,
            font=("Helvetica", 9, "underline"),
            activebackground=PANEL,
            activeforeground=ACCENT,
            cursor="hand2",
            command=self._toggle_details,
        )
        self._details_btn.pack(side="right")

        # ----- content (body + lazy details pane) -----
        content = tk.Frame(self.root, bg=BG)
        content.pack(fill="both", expand=True)
        self._content = content

        body = tk.Frame(content, bg=BG)
        body.pack(fill="both", expand=True)
        self._body = body

        center = tk.Frame(body, bg=BG)
        center.place(relx=0.5, rely=0.5, anchor="center")

        self._icon_var = tk.StringVar(value="")
        self._icon_label = tk.Label(
            center,
            textvariable=self._icon_var,
            bg=BG,
            fg=ACCENT,
            font=("Helvetica", 28, "bold"),
        )
        self._icon_label.pack(pady=(0, 6))

        self._title_var = tk.StringVar(value="Getting ready…")
        tk.Label(
            center,
            textvariable=self._title_var,
            bg=BG,
            fg=FG,
            font=("Helvetica", 18, "bold"),
            wraplength=520,
            justify="center",
        ).pack()

        self._subtitle_var = tk.StringVar(value="This may take a moment.")
        tk.Label(
            center,
            textvariable=self._subtitle_var,
            bg=BG,
            fg=DIM,
            font=("Helvetica", 11),
            wraplength=520,
            justify="center",
        ).pack(pady=(6, 22))

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Light.Horizontal.TProgressbar",
            background=ACCENT,
            troughcolor=TROUGH,
            bordercolor=TROUGH,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=10,
        )
        self.progress = ttk.Progressbar(
            center,
            mode="indeterminate",
            style="Light.Horizontal.TProgressbar",
            length=440,
        )
        self.progress.pack()
        self.progress.start(12)

        self._hint_var = tk.StringVar(value="")
        tk.Label(
            center,
            textvariable=self._hint_var,
            bg=BG,
            fg=DIM,
            font=("Helvetica", 10),
        ).pack(pady=(12, 0))

        # Lazily created details pane.
        self._details_frame: tk.Frame | None = None
        self._details_text: tk.Text | None = None
        self._details_visible = False
        self._details_buf: list[str] = []

        self._exit_code = 0
        self._closed = False
        self._done = False
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        self._closed = True
        try:
            self.progress.stop()
        except Exception:
            pass
        self.root.destroy()

    # ---- worker thread integration ----

    def run(self, worker_fn: Callable[[], int]) -> int:
        """Run worker_fn on a thread; enter Tk mainloop; return its rc."""

        def runner() -> None:
            try:
                rc = worker_fn() or 0
            except SystemExit as e:
                rc = int(e.code) if e.code is not None else 0
            except Exception as e:
                self._buffer(f"Unhandled error: {e}\n")
                rc = 1
            self._exit_code = rc
            self.root.after(0, self._on_worker_done)

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        self.root.mainloop()
        return self._exit_code

    def _on_worker_done(self) -> None:
        if self._closed:
            return
        self._done = True
        try:
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=100, value=100)
        except Exception:
            pass
        rc = self._exit_code
        if rc == 0:
            self._icon_label.configure(fg=OK_COLOR)
            self._icon_var.set("✓")
            self._title_var.set("All done!")
            self._subtitle_var.set("You can close this window.")
            self._hint_var.set("")
            self._status_var.set("Done.")
        else:
            self._icon_label.configure(fg=FAIL_COLOR)
            self._icon_var.set("!")
            self._title_var.set("Something went wrong")
            self._subtitle_var.set(
                "Click “Show details” below to see what happened."
            )
            self._hint_var.set("")
            self._status_var.set(f"Failed (exit code {rc}).")
            if not self._details_visible:
                self._toggle_details()

    # ---- API used by host scripts (call from worker thread) ----

    def banner(self, title: str, subtitle: str = "") -> None:
        # Banners get filed into the details log; the live area is driven by
        # step() and the final result. (setup.py / deploy.py call banner()
        # twice — once at start, once at finish — but the start banner just
        # restates the script title we already show in the header.)
        self._buffer(f"\n=== {title} ===\n")
        if subtitle:
            self._buffer(f"  {subtitle}\n")

    def step(self, msg: str) -> None:
        self._set_title(msg, "Hang tight, this might take a minute.")
        self._set_status(msg)
        self._buffer(f"\n▶ {msg}\n")

    def ok(self, msg: str) -> None:
        self._buffer(f"  ✓ {msg}\n")

    def fail(self, msg: str) -> None:
        self._buffer(f"  ✗ {msg}\n")

    def warn(self, msg: str) -> None:
        self._buffer(f"  ! {msg}\n")

    def info(self, msg: str) -> None:
        self._buffer(f"  · {msg}\n")

    def log_raw(self, text: str) -> None:
        self._buffer(text)

    # ---- internal UI updates (always thread-safe via after) ----

    def _set_title(self, title: str, subtitle: str) -> None:
        def do() -> None:
            if self._closed or self._done:
                return
            self._title_var.set(title)
            self._subtitle_var.set(subtitle)
        self.root.after(0, do)

    def _set_status(self, msg: str) -> None:
        def do() -> None:
            if self._closed or self._done:
                return
            self._status_var.set(msg)
        self.root.after(0, do)

    def _buffer(self, text: str) -> None:
        # Append to the in-memory log and (if pane is built) the Text widget.
        self._details_buf.append(text)

        def do() -> None:
            if self._closed or self._details_text is None:
                return
            self._details_text.configure(state="normal")
            self._details_text.insert("end", text)
            self._details_text.see("end")
            self._details_text.configure(state="disabled")
        self.root.after(0, do)

    # ---- details panel ----

    def _ensure_details(self) -> None:
        if self._details_frame is not None:
            return
        frame = tk.Frame(self._content, bg=PANEL)
        tk.Frame(frame, bg=BORDER, height=1).pack(fill="x", side="top")
        text = tk.Text(
            frame,
            bg=DETAILS_BG,
            fg=FG,
            font=("Menlo", 9),
            height=10,
            borderwidth=0,
            padx=12,
            pady=10,
            wrap="word",
        )
        text.pack(fill="both", expand=True)
        text.insert("end", "".join(self._details_buf))
        text.configure(state="disabled")
        self._details_frame = frame
        self._details_text = text

    def _toggle_details(self) -> None:
        self._ensure_details()
        assert self._details_frame is not None
        if self._details_visible:
            self._details_frame.pack_forget()
            self._details_btn.configure(text="Show details")
            self._details_visible = False
        else:
            # Pack at the bottom of _content; _body keeps expanding above.
            self._details_frame.pack(fill="both", expand=False, side="bottom")
            self._details_btn.configure(text="Hide details")
            self._details_visible = True

    # ---- blocking dialogs (worker thread waits on Tk reply) ----

    def ask_yn(self, prompt: str, default: bool = False) -> bool:
        reply = _Reply()

        def show() -> None:
            if self._closed:
                reply.put(default)
                return
            result = messagebox.askyesno(
                "Cold Fusion Robotics",
                prompt,
                default=("yes" if default else "no"),
                parent=self.root,
            )
            reply.put(bool(result))

        self.root.after(0, show)
        ans = reply.get()
        self._buffer(f"  ? {prompt} → {'yes' if ans else 'no'}\n")
        return ans

    def pause(self, msg: str = "Press OK to continue…") -> None:
        reply = _Reply()

        def show() -> None:
            if self._closed:
                reply.put(True)
                return
            messagebox.showinfo("Cold Fusion Robotics", msg, parent=self.root)
            reply.put(True)

        self.root.after(0, show)
        reply.get()
        self._buffer(f"  · {msg} (acknowledged)\n")

    # ---- subprocess streaming (silent — output goes to details only) ----

    def stream_subprocess(self, cmd: list[str]) -> int:
        self._buffer(f"  $ {' '.join(cmd)}\n")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self._buffer(f"Failed to launch: {e}\n")
            return 1
        assert proc.stdout is not None
        for line in proc.stdout:
            self._buffer(line)
        return proc.wait()
