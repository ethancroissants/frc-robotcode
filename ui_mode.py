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
    from tkinter import messagebox, simpledialog, ttk
    HAS_TK = True
except ImportError:
    HAS_TK = False


# 2026-ish palette — kept in sync with start.py so every panel feels like
# the same product. Indigo accent, slate text hierarchy, gentle hairlines.
BG          = "#f6f7fb"
PANEL       = "#ffffff"
FG          = "#0f172a"   # primary
FG_STRONG   = "#020617"   # heading
DIM         = "#6b7280"   # secondary
DIM_SOFT    = "#9aa3b2"   # tertiary
ACCENT      = "#4f46e5"   # indigo-600
ACCENT_DARK = "#4338ca"   # indigo-700 — pressed/active button
ACCENT_SOFT = "#eef2ff"   # indigo-50 — hover surfaces
OK_COLOR    = "#10b981"
FAIL_COLOR  = "#ef4444"
WARN_COLOR  = "#f59e0b"
BORDER      = "#e5e7eb"
BORDER_SOFT = "#f1f3f7"
TROUGH      = "#eef0f4"
DETAILS_BG  = "#fbfbfd"


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


class Spinner(tk.Canvas):
    """A rotating-arc loading indicator drawn on a Canvas.

    Looks more like the MacOS / iOS / web app loading spinner than Tk's
    default linear Progressbar — which is the whole point of this rebuild.
    Animates by rotating a 110° arc around the center via after()-loop;
    the gap between start angle and 360 is what makes it read as
    "spinning" rather than "filling".

    Use Spinner.stop() to cancel the after-loop before the parent is
    destroyed, otherwise Tk will complain about callbacks on dead widgets.
    """

    _EXTENT_DEG = 110   # how much of the ring is drawn (the rest is gap)
    _STEP_DEG   = 14    # per-frame rotation
    _FRAME_MS   = 32    # ~31 fps — buttery on any laptop

    def __init__(
        self,
        parent: tk.Widget,
        size: int = 56,
        color: str = ACCENT,
        track: str = BORDER_SOFT,
        bg_color: str = BG,
        thickness: int = 4,
    ) -> None:
        super().__init__(
            parent,
            width=size,
            height=size,
            bg=bg_color,
            highlightthickness=0,
            borderwidth=0,
        )
        self._size = size
        self._color = color
        self._angle = 0
        self._after: str | None = None
        # Draw the static "track" first (full ring, soft color) so the
        # spinner reads as motion-on-a-circle, not a flailing arc. The
        # animated arc is drawn on top.
        pad = thickness + 2  # leave a hair of antialias margin
        self.create_oval(
            pad, pad, size - pad, size - pad,
            outline=track, width=thickness,
        )
        self._arc_id = self.create_arc(
            pad, pad, size - pad, size - pad,
            start=0, extent=self._EXTENT_DEG,
            outline=color, width=thickness,
            style="arc",
        )
        self._tick()

    def _tick(self) -> None:
        self._angle = (self._angle + self._STEP_DEG) % 360
        try:
            self.itemconfigure(self._arc_id, start=self._angle)
        except tk.TclError:
            return  # widget destroyed mid-frame
        self._after = self.after(self._FRAME_MS, self._tick)

    def stop(self) -> None:
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
            self._after = None


class App:
    def __init__(self, title: str, subtitle: str = "") -> None:
        self.root = tk.Tk()
        self.root.title(f"Cold Fusion Robotics — {title}")
        self.root.configure(bg=BG)
        self.root.geometry("680x480")
        self.root.minsize(580, 420)

        # ----- header (matches start.py: accent-dot + brand + subtitle) -----
        header = tk.Frame(self.root, bg=PANEL)
        header.pack(fill="x", side="top")
        hinner = tk.Frame(header, bg=PANEL, padx=26, pady=18)
        hinner.pack(fill="x")

        brand_row = tk.Frame(hinner, bg=PANEL)
        brand_row.pack(anchor="w")
        tk.Label(
            brand_row, text="●", bg=PANEL, fg=ACCENT, font=("Helvetica", 14),
        ).pack(side="left", padx=(0, 8))
        tk.Label(
            brand_row,
            text="COLD FUSION ROBOTICS",
            bg=PANEL,
            fg=FG_STRONG,
            font=("Helvetica", 14, "bold"),
        ).pack(side="left")
        tk.Label(
            hinner,
            text=subtitle or title,
            bg=PANEL,
            fg=DIM,
            font=("Helvetica", 11),
        ).pack(anchor="w", pady=(3, 0))
        tk.Frame(self.root, bg=BORDER_SOFT, height=1).pack(fill="x", side="top")

        # ----- footer -----
        footer = tk.Frame(self.root, bg=PANEL)
        footer.pack(fill="x", side="bottom")
        tk.Frame(footer, bg=BORDER_SOFT, height=1).pack(fill="x", side="top")
        finner = tk.Frame(footer, bg=PANEL, padx=18, pady=10)
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
        # Ghost-style "Show details" — no underline, just hover-color shift
        # to match the Quit button on the start panel. Less visually loud
        # than the old <button> + underline style.
        self._details_btn = tk.Label(
            finner,
            text="Show details",
            bg=PANEL,
            fg=DIM,
            font=("Helvetica", 9),
            cursor="hand2",
            padx=10,
            pady=4,
        )
        self._details_btn.pack(side="right")
        self._details_btn.bind("<Button-1>", lambda _e: self._toggle_details())
        self._details_btn.bind("<Enter>", lambda _e: self._details_btn.configure(fg=ACCENT))
        self._details_btn.bind("<Leave>", lambda _e: self._details_btn.configure(fg=DIM))

        # ----- content (body + lazy details pane) -----
        content = tk.Frame(self.root, bg=BG)
        content.pack(fill="both", expand=True)
        self._content = content

        body = tk.Frame(content, bg=BG)
        body.pack(fill="both", expand=True)
        self._body = body

        center = tk.Frame(body, bg=BG)
        center.place(relx=0.5, rely=0.5, anchor="center")

        # Spinner up top — leads the layout the same way the rotating
        # arc leads a Mac OS app loading screen. Replaced on success/fail
        # with the static ✓/✗ icon. The icon label takes the spinner's
        # spot, so the eye doesn't have to refocus when state changes.
        self.spinner = Spinner(center, size=56, color=ACCENT, bg_color=BG)
        self.spinner.pack(pady=(0, 14))

        self._icon_var = tk.StringVar(value="")
        self._icon_label = tk.Label(
            center,
            textvariable=self._icon_var,
            bg=BG,
            fg=ACCENT,
            font=("Helvetica", 32, "bold"),
        )
        # Built but not packed — packs in place of the spinner on done.

        self._title_var = tk.StringVar(value="Getting ready…")
        tk.Label(
            center,
            textvariable=self._title_var,
            bg=BG,
            fg=FG_STRONG,
            font=("Helvetica", 19, "bold"),
            wraplength=560,
            justify="center",
        ).pack()

        self._subtitle_var = tk.StringVar(value="This may take a moment.")
        tk.Label(
            center,
            textvariable=self._subtitle_var,
            bg=BG,
            fg=DIM,
            font=("Helvetica", 11),
            wraplength=560,
            justify="center",
        ).pack(pady=(8, 22))

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#ffffff",
            font=("Helvetica", 11, "bold"),
            padding=(24, 10),
            borderwidth=0,
            focusthickness=0,
        )
        style.map(
            "Accent.TButton",
            background=[
                ("active", ACCENT_DARK),
                ("pressed", ACCENT_DARK),
                ("disabled", BORDER),
            ],
            foreground=[("disabled", DIM)],
        )

        self._hint_var = tk.StringVar(value="")
        tk.Label(
            center,
            textvariable=self._hint_var,
            bg=BG,
            fg=DIM_SOFT,
            font=("Menlo", 9),
            wraplength=560,
            justify="center",
        ).pack(pady=(4, 0))

        # Built up-front, only packed on success when a follow-up is set.
        self._action_button = ttk.Button(
            center, text="Continue", style="Accent.TButton",
        )

        # Lazily created details pane.
        self._details_frame: tk.Frame | None = None
        self._details_text: tk.Text | None = None
        self._details_visible = False
        self._details_buf: list[str] = []

        self._followup_label: str | None = None
        self._followup_prompt: str = ""
        self._followup_on_click: Callable[[], None] | None = None

        self._exit_code = 0
        self._closed = False
        self._done = False
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        self._closed = True
        try:
            self.spinner.stop()
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
        # Stop the spinner and swap it for the static ✓ / ! icon in the
        # same spot, so the layout doesn't reflow when work completes.
        try:
            self.spinner.stop()
            self.spinner.pack_forget()
        except Exception:
            pass
        # `before=` keeps the icon at the top, where the spinner used to be.
        try:
            self._icon_label.pack(pady=(0, 14), before=self._action_button)
        except tk.TclError:
            self._icon_label.pack(pady=(0, 14))
        rc = self._exit_code
        if rc == 0:
            self._icon_label.configure(fg=OK_COLOR)
            self._icon_var.set("✓")
            self._title_var.set("All done")
            if self._followup_label and self._followup_on_click:
                self._subtitle_var.set(
                    self._followup_prompt or "Ready for the next step?"
                )
                self._action_button.configure(
                    text=self._followup_label, command=self._fire_followup
                )
                self._action_button.pack(pady=(4, 0))
            else:
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

    def _fire_followup(self) -> None:
        cb = self._followup_on_click
        self._followup_on_click = None
        try:
            if cb is not None:
                cb()
        finally:
            self._closed = True
            self.root.destroy()

    def set_followup(
        self,
        label: str,
        on_click: Callable[[], None],
        prompt: str = "",
    ) -> None:
        """Show a button on the success screen instead of "you can close…".

        on_click runs on the Tk main thread; the window closes after it
        returns so the host can spawn a follow-up subprocess and let this
        window go away.
        """
        self._followup_label = label
        self._followup_on_click = on_click
        self._followup_prompt = prompt

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

    def ask_string(
        self,
        prompt: str,
        default: str = "",
        title: str = "Cold Fusion Robotics",
    ) -> str | None:
        """Pop a modal asking for a single line of text.

        Returns the trimmed string, or None if the user cancelled / the
        window was closed.
        """
        reply = _Reply()

        def show() -> None:
            if self._closed:
                reply.put(None)
                return
            result = simpledialog.askstring(
                title, prompt, initialvalue=default, parent=self.root
            )
            reply.put(result)

        self.root.after(0, show)
        ans = reply.get()
        ans = ans.strip() if isinstance(ans, str) else None
        self._buffer(f"  ? {prompt} → {ans!r}\n")
        return ans

    def ask_password(
        self,
        prompt: str,
        title: str = "Cold Fusion Robotics",
    ) -> str | None:
        """Same as ask_string, but masks input and never logs the value.

        Returns the raw string (not stripped — passwords can have leading
        / trailing whitespace, however weird), or None if cancelled.
        """
        reply = _Reply()

        def show() -> None:
            if self._closed:
                reply.put(None)
                return
            # `show="*"` makes the entry render bullets instead of plaintext.
            result = simpledialog.askstring(
                title, prompt, parent=self.root, show="*"
            )
            reply.put(result)

        self.root.after(0, show)
        ans = reply.get()
        # Log only that *something* was entered, never the value.
        self._buffer(f"  ? {prompt} → {'(set)' if ans else '(blank)'}\n")
        return ans if isinstance(ans, str) else None

    def _set_hint(self, msg: str) -> None:
        def do() -> None:
            if self._closed or self._done:
                return
            self._hint_var.set(msg)
        self.root.after(0, do)

    # ---- subprocess streaming ----
    # stdout/stderr are captured into the hidden details log; the latest
    # non-empty line is also surfaced under the progress bar so long-running
    # commands like `robotpy deploy` show live activity. stdin is piped and
    # pre-fed 'y' answers so prompts like robotpy's "uninstall + install?"
    # don't EOF and crash the deploy.

    def stream_subprocess(
        self,
        cmd: list[str],
        capture: list[str] | None = None,
        *,
        env: dict[str, str] | None = None,
    ) -> int:
        """Run cmd, streaming stdout/stderr to the details panel.

        If `capture` is a list, each output line is also appended to it so
        callers can scan for known error strings after the process exits.
        `env` is forwarded to Popen unchanged — used by push.py to set
        GIT_ASKPASS without embedding tokens in argv.
        """
        self._buffer(f"  $ {' '.join(cmd)}\n")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                # Force UTF-8 so non-ASCII output from remote tools (em-dash,
                # progress glyphs, etc.) doesn't crash on Windows where the
                # default text-mode encoding is cp1252. errors="replace"
                # turns any genuinely undecodable bytes into '?' instead of
                # killing the stream mid-line.
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
        except Exception as e:
            self._buffer(f"Failed to launch: {e}\n")
            return 1
        assert proc.stdout is not None
        if proc.stdin is not None:
            try:
                proc.stdin.write("y\n" * 20)
                proc.stdin.flush()
            except (OSError, BrokenPipeError):
                pass
        for line in proc.stdout:
            self._buffer(line)
            if capture is not None:
                capture.append(line)
            trimmed = line.strip()
            if trimmed:
                # Truncate so a giant traceback line doesn't blow up the layout.
                self._set_hint(trimmed[:90])
        self._set_hint("")
        rc = proc.wait()
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
        return rc
