#!/usr/bin/env python3
"""Cold Fusion Robotics — Documentation viewer.

A self-contained Markdown reader for the team's `documentation/` folder.
Most pit/driver laptops don't have a Markdown viewer installed, so we render
inline with stdlib Tk: bold, italic, inline & block code, headings, bullets,
numbered lists, blockquotes, tables, links, and horizontal rules.

Run me directly:

    python docs.py
"""

from __future__ import annotations

import re
import sys
import webbrowser
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox
    HAS_TK = True
except ImportError:
    HAS_TK = False


REPO = Path(__file__).resolve().parent
DOCS_DIR = REPO / "documentation"

# 2026-ish palette — kept in sync with start.py / ui_mode.py so all
# panels feel like the same product. If you change one, change all three.
BG           = "#f6f7fb"
PANEL        = "#ffffff"
FG           = "#0f172a"
FG_STRONG    = "#020617"
DIM          = "#6b7280"
DIM_SOFT     = "#9aa3b2"
ACCENT       = "#4f46e5"
ACCENT_SOFT  = "#eef2ff"
BORDER       = "#e5e7eb"
BORDER_SOFT  = "#f1f3f7"
HOVER_BORDER = "#c7d2fe"
CARD_HOVER   = ACCENT_SOFT
CODE_BG      = "#f1f3f7"
CODE_FG      = "#0f172a"
QUOTE_BORDER = "#c7d2fe"


# Friendly labels for the known docs. Anything else falls back to the filename.
NICE_TITLES: dict[str, str] = {
    "README.md": "Overview (README)",
    "guide.md": "Build / Deploy / Driver Station Guide",
    "elastic.md": "Elastic Dashboard & Tunables",
    "orangepi.md": "Vision Pi (Orange Pi 5) — Setup Guide",
}


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


class MarkdownRenderer:
    """Parse a Markdown string and stuff it into a Tk Text widget.

    Block-level: ATX headings, fenced code blocks, GitHub-style tables,
    blockquotes, bullet & numbered lists, horizontal rules, paragraphs.
    Inline: **bold**, *italic*, `code`, [link text](url).

    The renderer is intentionally small — we don't try to be CommonMark
    compliant. The team's docs use a fairly tame subset, and a simple
    renderer is easier to debug on a pit laptop than a full parser.
    """

    # Inline patterns are matched in priority order (bold before italic so
    # ** doesn't get eaten by single-* italic).
    _INLINE_RE = re.compile(
        r"(?P<bold>\*\*(?P<bold_in>[^*]+)\*\*)"
        r"|(?P<code>`(?P<code_in>[^`]+)`)"
        r"|(?P<link>\[(?P<link_text>[^\]]+)\]\((?P<link_url>[^)]+)\))"
        r"|(?P<italic>(?<!\*)\*(?!\*)(?P<italic_in>[^*\n]+)\*(?!\*))"
    )

    def __init__(self, text: tk.Text) -> None:
        self.text = text
        self._link_seq = 0
        self._configure_tags()

    def _configure_tags(self) -> None:
        t = self.text
        t.tag_configure("body", font=("Helvetica", 11), foreground=FG, spacing3=2)
        t.tag_configure(
            "h1",
            font=("Helvetica", 22, "bold"),
            foreground=FG,
            spacing1=14,
            spacing3=10,
        )
        t.tag_configure(
            "h2",
            font=("Helvetica", 17, "bold"),
            foreground=FG,
            spacing1=12,
            spacing3=8,
        )
        t.tag_configure(
            "h3",
            font=("Helvetica", 14, "bold"),
            foreground=FG,
            spacing1=10,
            spacing3=6,
        )
        t.tag_configure(
            "h4",
            font=("Helvetica", 12, "bold"),
            foreground=FG,
            spacing1=8,
            spacing3=4,
        )
        t.tag_configure("bold", font=("Helvetica", 11, "bold"))
        t.tag_configure("italic", font=("Helvetica", 11, "italic"))
        t.tag_configure(
            "code_inline",
            font=("Menlo", 10),
            background=CODE_BG,
            foreground=CODE_FG,
        )
        t.tag_configure(
            "code_block",
            font=("Menlo", 10),
            background=CODE_BG,
            foreground=CODE_FG,
            lmargin1=18,
            lmargin2=18,
            rmargin=18,
            spacing1=4,
            spacing3=4,
        )
        t.tag_configure(
            "blockquote",
            font=("Helvetica", 11, "italic"),
            foreground=DIM,
            lmargin1=22,
            lmargin2=22,
            spacing3=2,
        )
        t.tag_configure("bullet", lmargin1=24, lmargin2=44, spacing3=2)
        t.tag_configure("link", foreground=ACCENT, underline=1)
        t.tag_configure(
            "hr",
            foreground=BORDER,
            font=("Helvetica", 9),
            spacing1=8,
            spacing3=10,
            justify="center",
        )
        t.tag_configure(
            "table",
            font=("Menlo", 10),
            foreground=FG,
            lmargin1=10,
            lmargin2=10,
            spacing3=2,
        )
        t.tag_configure(
            "table_header",
            font=("Menlo", 10, "bold"),
            background=CODE_BG,
            foreground=FG,
            lmargin1=10,
            lmargin2=10,
            spacing3=2,
        )

    # ---- public entry point ----

    def render(self, content: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")

        lines = content.splitlines()
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]

            # Fenced code block — read until the closing fence so inline
            # markers inside source code don't get parsed.
            if line.lstrip().startswith("```"):
                i += 1
                buf: list[str] = []
                while i < n and not lines[i].lstrip().startswith("```"):
                    buf.append(lines[i])
                    i += 1
                i += 1  # consume closing fence (or run off end harmlessly)
                if buf:
                    self.text.insert("end", "\n".join(buf) + "\n", "code_block")
                self.text.insert("end", "\n")
                continue

            # GitHub table: "|...|" header followed by "|---|---|" separator.
            if (
                line.lstrip().startswith("|")
                and i + 1 < n
                and self._is_table_separator(lines[i + 1])
            ):
                table_lines = [line, lines[i + 1]]
                i += 2
                while i < n and lines[i].lstrip().startswith("|"):
                    table_lines.append(lines[i])
                    i += 1
                self._render_table(table_lines)
                continue

            # ATX heading
            m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
            if m:
                level = len(m.group(1))
                tag = f"h{min(level, 4)}"
                self._insert_inline(m.group(2), [tag])
                self.text.insert("end", "\n", tag)
                i += 1
                continue

            # Horizontal rule
            if re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", line):
                self.text.insert("end", "─" * 50 + "\n", "hr")
                i += 1
                continue

            # Blockquote (single-level; nested > > collapses to one)
            if line.lstrip().startswith(">"):
                stripped = line.lstrip()
                while stripped.startswith(">"):
                    stripped = stripped[1:].lstrip()
                self._insert_inline(stripped, ["blockquote"])
                self.text.insert("end", "\n", "blockquote")
                i += 1
                continue

            # Bullet list
            m = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
            if m:
                indent_spaces = len(m.group(1))
                prefix = "    " * (indent_spaces // 2) + "•  "
                self.text.insert("end", prefix, "bullet")
                self._insert_inline(m.group(2), ["bullet"])
                self.text.insert("end", "\n", "bullet")
                i += 1
                continue

            # Numbered list
            m = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)
            if m:
                indent_spaces = len(m.group(1))
                prefix = "    " * (indent_spaces // 2) + f"{m.group(2)}.  "
                self.text.insert("end", prefix, "bullet")
                self._insert_inline(m.group(3), ["bullet"])
                self.text.insert("end", "\n", "bullet")
                i += 1
                continue

            # Blank line
            if line.strip() == "":
                self.text.insert("end", "\n")
                i += 1
                continue

            # Plain paragraph
            self._insert_inline(line, ["body"])
            self.text.insert("end", "\n", "body")
            i += 1

        self.text.configure(state="disabled")
        self.text.yview_moveto(0.0)

    # ---- helpers ----

    @staticmethod
    def _is_table_separator(line: str) -> bool:
        # | --- | :---: | ---: |  — colons mark alignment, ignored.
        s = line.strip()
        if not s.startswith("|") or not s.endswith("|"):
            return False
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells:
            return False
        return all(re.match(r"^:?-{3,}:?$", c) for c in cells)

    def _render_table(self, rows: list[str]) -> None:
        if len(rows) < 2:
            return

        def split_row(r: str) -> list[str]:
            r = r.strip()
            if r.startswith("|"):
                r = r[1:]
            if r.endswith("|"):
                r = r[:-1]
            return [c.strip() for c in r.split("|")]

        header = split_row(rows[0])
        body = [split_row(r) for r in rows[2:]]

        # Pad short rows / clamp long ones to header width.
        ncols = len(header)
        norm_body: list[list[str]] = []
        for r in body:
            if len(r) < ncols:
                r = r + [""] * (ncols - len(r))
            else:
                r = r[:ncols]
            norm_body.append(r)

        widths = [len(c) for c in header]
        for r in norm_body:
            for j, cell in enumerate(r):
                widths[j] = max(widths[j], len(cell))

        def fmt_row(cells: list[str]) -> str:
            return "  " + "  │  ".join(c.ljust(widths[j]) for j, c in enumerate(cells)) + "  "

        sep = "──" + "──┼──".join("─" * w for w in widths) + "──"

        self.text.insert("end", fmt_row(header) + "\n", "table_header")
        self.text.insert("end", sep + "\n", "table")
        for r in norm_body:
            self.text.insert("end", fmt_row(r) + "\n", "table")
        self.text.insert("end", "\n")

    def _insert_inline(self, text: str, base_tags: list[str]) -> None:
        """Apply inline formatting tags while inserting `text`."""
        last = 0
        for m in self._INLINE_RE.finditer(text):
            if m.start() > last:
                self.text.insert("end", text[last:m.start()], tuple(base_tags))
            if m.group("bold"):
                self.text.insert(
                    "end", m.group("bold_in"), tuple(base_tags + ["bold"])
                )
            elif m.group("code"):
                self.text.insert(
                    "end", m.group("code_in"), tuple(base_tags + ["code_inline"])
                )
            elif m.group("link"):
                self._insert_link(
                    m.group("link_text"), m.group("link_url"), base_tags
                )
            elif m.group("italic"):
                self.text.insert(
                    "end", m.group("italic_in"), tuple(base_tags + ["italic"])
                )
            last = m.end()
        if last < len(text):
            self.text.insert("end", text[last:], tuple(base_tags))

    def _insert_link(self, label: str, url: str, base_tags: list[str]) -> None:
        # Each link gets its own dynamic tag so the binding closes over its url.
        self._link_seq += 1
        tag = f"link_{self._link_seq}"
        self.text.tag_configure(tag, foreground=ACCENT, underline=1)

        def open_url(_event: tk.Event, u: str = url) -> None:
            try:
                webbrowser.open(u)
            except Exception:
                pass

        self.text.tag_bind(tag, "<Button-1>", open_url)
        self.text.tag_bind(
            tag, "<Enter>", lambda _e: self.text.configure(cursor="hand2")
        )
        self.text.tag_bind(
            tag, "<Leave>", lambda _e: self.text.configure(cursor="")
        )
        self.text.insert("end", label, tuple(base_tags + [tag, "link"]))


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


class FileEntry(tk.Frame):
    """One clickable doc entry in the left sidebar."""

    def __init__(self, parent: tk.Widget, label: str, on_click) -> None:
        super().__init__(
            parent,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
            cursor="hand2",
        )
        self._on_click = on_click
        self._normal_bg = PANEL
        self._hover_bg = CARD_HOVER
        self._selected = False

        inner = tk.Frame(self, bg=PANEL, padx=14, pady=10)
        inner.pack(fill="x")
        self._inner = inner
        self._label = tk.Label(
            inner,
            text=label,
            bg=PANEL,
            fg=FG,
            font=("Helvetica", 11),
            anchor="w",
            justify="left",
        )
        self._label.pack(anchor="w", fill="x")

        for w in (self, inner, self._label):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def _set_bg(self, color: str) -> None:
        self.configure(bg=color)
        self._inner.configure(bg=color)
        self._label.configure(bg=color)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        if selected:
            self._set_bg(CARD_HOVER)
            self.configure(highlightbackground=ACCENT, highlightthickness=2)
            self._label.configure(fg=ACCENT, font=("Helvetica", 11, "bold"))
        else:
            self._set_bg(self._normal_bg)
            self.configure(highlightbackground=BORDER, highlightthickness=1)
            self._label.configure(fg=FG, font=("Helvetica", 11))

    def _click(self, _event=None) -> None:
        self._on_click()

    def _enter(self, _event=None) -> None:
        if not self._selected:
            self._set_bg(self._hover_bg)
            self.configure(highlightbackground=HOVER_BORDER)

    def _leave(self, _event=None) -> None:
        if not self._selected:
            self._set_bg(self._normal_bg)
            self.configure(highlightbackground=BORDER)


class DocsWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Cold Fusion Robotics — Documentation")
        self.root.configure(bg=BG)
        self.root.geometry("960x680")
        self.root.minsize(720, 480)

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
            text="Documentation",
            bg=PANEL,
            fg=DIM,
            font=("Helvetica", 11),
        ).pack(anchor="w", pady=(2, 0))
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        # ----- body: sidebar + viewer -----
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)

        sidebar = tk.Frame(body, bg=BG, width=240)
        sidebar.pack(side="left", fill="y", padx=(16, 8), pady=14)
        sidebar.pack_propagate(False)

        tk.Label(
            sidebar,
            text="Files",
            bg=BG,
            fg=DIM,
            font=("Helvetica", 9, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(0, 6))

        self._entries: list[FileEntry] = []
        self._current: Path | None = None

        # Right-side viewer card.
        viewer_card = tk.Frame(
            body,
            bg=PANEL,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        viewer_card.pack(side="left", fill="both", expand=True, padx=(8, 16), pady=14)

        self._title_var = tk.StringVar(value="Select a document on the left.")
        title_bar = tk.Frame(viewer_card, bg=PANEL)
        title_bar.pack(fill="x", padx=18, pady=(14, 6))
        tk.Label(
            title_bar,
            textvariable=self._title_var,
            bg=PANEL,
            fg=FG,
            font=("Helvetica", 13, "bold"),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        self._path_var = tk.StringVar(value="")
        tk.Label(
            title_bar,
            textvariable=self._path_var,
            bg=PANEL,
            fg=DIM,
            font=("Helvetica", 9),
        ).pack(side="right")
        tk.Frame(viewer_card, bg=BORDER, height=1).pack(fill="x", padx=18)

        text_holder = tk.Frame(viewer_card, bg=PANEL)
        text_holder.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        self._text = tk.Text(
            text_holder,
            bg=PANEL,
            fg=FG,
            relief="flat",
            borderwidth=0,
            padx=14,
            pady=10,
            wrap="word",
            font=("Helvetica", 11),
            cursor="",
        )
        scrollbar = tk.Scrollbar(text_holder, command=self._text.yview)
        self._text.configure(yscrollcommand=scrollbar.set, state="disabled")
        scrollbar.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)

        self._renderer = MarkdownRenderer(self._text)

        # Mousewheel — bind to the text so users don't have to grab the bar.
        self._text.bind(
            "<MouseWheel>",
            lambda e: self._text.yview_scroll(int(-e.delta / 120), "units"),
        )
        self._text.bind(
            "<Button-4>", lambda _e: self._text.yview_scroll(-3, "units")
        )
        self._text.bind(
            "<Button-5>", lambda _e: self._text.yview_scroll(3, "units")
        )

        # ----- footer -----
        footer = tk.Frame(self.root, bg=PANEL)
        footer.pack(fill="x", side="bottom")
        tk.Frame(footer, bg=BORDER, height=1).pack(fill="x", side="top")
        finner = tk.Frame(footer, bg=PANEL, padx=14, pady=10)
        finner.pack(fill="x")
        tk.Label(
            finner,
            text=f"Reading from: {DOCS_DIR}",
            bg=PANEL,
            fg=DIM,
            font=("Helvetica", 9),
            anchor="w",
        ).pack(side="left")
        tk.Button(
            finner,
            text="Close",
            bg=PANEL,
            fg=FG,
            relief="flat",
            borderwidth=0,
            font=("Helvetica", 10),
            activebackground=PANEL,
            activeforeground=ACCENT,
            cursor="hand2",
            command=self.root.destroy,
        ).pack(side="right")

        self._sidebar = sidebar
        self._populate_sidebar()

    # ---- behavior ----

    def _populate_sidebar(self) -> None:
        if not DOCS_DIR.is_dir():
            tk.Label(
                self._sidebar,
                text=f"No documentation/ folder\nat {DOCS_DIR}",
                bg=BG,
                fg=DIM,
                font=("Helvetica", 10),
                justify="left",
                anchor="w",
                wraplength=220,
            ).pack(anchor="w")
            return

        files = sorted(DOCS_DIR.glob("*.md"), key=lambda p: p.name.lower())
        if not files:
            tk.Label(
                self._sidebar,
                text="No .md files in documentation/",
                bg=BG,
                fg=DIM,
                font=("Helvetica", 10),
                anchor="w",
                wraplength=220,
            ).pack(anchor="w")
            return

        for path in files:
            label = NICE_TITLES.get(path.name, path.name)
            entry = FileEntry(
                self._sidebar,
                label,
                on_click=lambda p=path: self._select(p),
            )
            entry.pack(fill="x", pady=4)
            self._entries.append(entry)

        # Open the first file by default so the viewer isn't empty.
        first = next((p for p in files if p.name == "README.md"), files[0])
        self._select(first)

    def _select(self, path: Path) -> None:
        self._current = path
        for entry, p in zip(self._entries, sorted(DOCS_DIR.glob("*.md"), key=lambda x: x.name.lower())):
            entry.set_selected(p == path)

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            messagebox.showerror(
                "Cold Fusion Robotics", f"Could not open {path.name}:\n{e}"
            )
            return

        self._title_var.set(NICE_TITLES.get(path.name, path.name))
        try:
            rel = path.relative_to(REPO)
        except ValueError:
            rel = path
        self._path_var.set(str(rel))
        self._renderer.render(content)

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main() -> int:
    if not HAS_TK:
        print(
            "Tkinter is not installed, so the docs viewer can't open.\n"
            "Install python3-tk (Linux) or reinstall Python with the "
            "tcl/tk option (Windows / mac).",
            file=sys.stderr,
        )
        return 1
    return DocsWindow().run()


if __name__ == "__main__":
    sys.exit(main())
