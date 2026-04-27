"""Cold Fusion Robotics UI mode for setup/deploy scripts.

Activated by `--ui` on the host script's command line. Opens a branded Tk
window with live log output and modal dialogs for y/n prompts and pauses.

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
    from tkinter import messagebox, scrolledtext
    HAS_TK = True
except ImportError:
    HAS_TK = False


# Cold Fusion brand palette — deep navy with cold cyan accent.
BG = "#0a0e1a"
PANEL = "#10182a"
FG = "#e8f4ff"
DIM = "#6e8aab"
ACCENT = "#00d4ff"
OK = "#3cf07a"
FAIL = "#ff5470"
WARN = "#ffb454"
STEP = "#6eb6ff"


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
        self.root.geometry("960x640")
        self.root.minsize(720, 480)

        # Header with brand mark.
        header = tk.Frame(self.root, bg=PANEL)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=PANEL, padx=22, pady=16)
        inner.pack(fill="x")
        tk.Label(
            inner,
            text="◆ COLD FUSION ROBOTICS",
            bg=PANEL,
            fg=ACCENT,
            font=("Helvetica", 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            inner,
            text=subtitle or title,
            bg=PANEL,
            fg=DIM,
            font=("Helvetica", 11),
        ).pack(anchor="w", pady=(2, 0))
        tk.Frame(self.root, bg=ACCENT, height=2).pack(fill="x")

        # Log area.
        self.log_widget = scrolledtext.ScrolledText(
            self.root,
            bg=BG,
            fg=FG,
            insertbackground=FG,
            font=("Menlo", 10),
            borderwidth=0,
            highlightthickness=0,
            padx=14,
            pady=10,
            wrap="word",
            state="disabled",
        )
        self.log_widget.pack(fill="both", expand=True)
        self.log_widget.tag_config("ok", foreground=OK)
        self.log_widget.tag_config("fail", foreground=FAIL)
        self.log_widget.tag_config("warn", foreground=WARN)
        self.log_widget.tag_config(
            "step", foreground=STEP, font=("Menlo", 10, "bold")
        )
        self.log_widget.tag_config("info", foreground=DIM)
        self.log_widget.tag_config(
            "banner", foreground=ACCENT, font=("Menlo", 12, "bold")
        )
        self.log_widget.tag_config("dim", foreground=DIM)

        # Status bar.
        self._status_var = tk.StringVar(value="Working...")
        status = tk.Frame(self.root, bg=PANEL)
        status.pack(fill="x", side="bottom")
        tk.Label(
            status,
            textvariable=self._status_var,
            bg=PANEL,
            fg=DIM,
            anchor="w",
            font=("Helvetica", 10),
            padx=14,
            pady=8,
        ).pack(fill="x")

        self._exit_code = 0
        self._closed = False
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        self._closed = True
        self.root.destroy()

    def run(self, worker_fn: Callable[[], int]) -> int:
        """Run worker_fn in a thread; enter Tk mainloop; return its rc."""

        def runner() -> None:
            try:
                rc = worker_fn() or 0
            except SystemExit as e:
                rc = int(e.code) if e.code is not None else 0
            except Exception as e:
                self.fail(f"Unhandled error: {e}")
                rc = 1
            self._exit_code = rc
            # Schedule status update; leave window open so user can read output.
            self.root.after(0, self._on_worker_done)

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        self.root.mainloop()
        return self._exit_code

    def _on_worker_done(self) -> None:
        rc = self._exit_code
        if rc == 0:
            self._status_var.set("Done. Close this window when ready.")
        else:
            self._status_var.set(
                f"Finished with exit code {rc}. Close this window when ready."
            )

    # ---- thread-safe log writers (callable from worker thread) ----

    def _append(self, text: str, *tags: str) -> None:
        def do() -> None:
            if self._closed:
                return
            self.log_widget.configure(state="normal")
            self.log_widget.insert("end", text, tags)
            self.log_widget.see("end")
            self.log_widget.configure(state="disabled")

        self.root.after(0, do)

    def banner(self, title: str, subtitle: str = "") -> None:
        self._append("\n")
        self._append("━" * 64 + "\n", "dim")
        self._append(f"  {title}\n", "banner")
        if subtitle:
            self._append(f"  {subtitle}\n", "info")
        self._append("━" * 64 + "\n\n", "dim")

    def step(self, msg: str) -> None:
        self._append(f"\n▶ {msg}\n", "step")
        self._set_status(msg)

    def ok(self, msg: str) -> None:
        self._append(f"  ✓ {msg}\n", "ok")

    def fail(self, msg: str) -> None:
        self._append(f"  ✗ {msg}\n", "fail")

    def warn(self, msg: str) -> None:
        self._append(f"  ! {msg}\n", "warn")

    def info(self, msg: str) -> None:
        self._append(f"  · {msg}\n", "info")

    def log_raw(self, text: str) -> None:
        self._append(text)

    def _set_status(self, msg: str) -> None:
        def do() -> None:
            if self._closed:
                return
            self._status_var.set(msg)

        self.root.after(0, do)

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
        self._append(
            f"  ? {prompt} → {'yes' if ans else 'no'}\n", "info"
        )
        return ans

    def pause(self, msg: str = "Press OK to continue...") -> None:
        reply = _Reply()

        def show() -> None:
            if self._closed:
                reply.put(True)
                return
            messagebox.showinfo(
                "Cold Fusion Robotics", msg, parent=self.root
            )
            reply.put(True)

        self.root.after(0, show)
        reply.get()
        self._append(f"  · {msg} (acknowledged)\n", "info")

    # ---- subprocess streaming (worker thread reads pipe directly) ----

    def stream_subprocess(self, cmd: list[str]) -> int:
        self._append(f"  $ {' '.join(cmd)}\n", "dim")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            self.fail(f"Failed to launch: {e}")
            return 1
        assert proc.stdout is not None
        for line in proc.stdout:
            self._append(line)
        return proc.wait()
