"""Generate installer banner art for the Acuity Manager NSIS installer.

Run from this directory:  python3 _make_assets.py

Produces, alongside this script:
  installer-sidebar.bmp     — 164x314 left rail on the welcome / finish pages
  uninstaller-sidebar.bmp   — same, used by the uninstaller
  installer-header.bmp      — 150x57 strip atop the inner pages

The .ico the installer + the app itself use is `acuity/img/AcuityAppIcon.ico`
— the canonical Acuity glyph, NOT regenerated here. We only own the wide
banner BMPs because they carry the wordmark + tagline, which a square icon
can't.

Re-runnable: overwrites in place. The script lives in the repo so the
banners can be regenerated whenever the brand text changes; committing the
BMPs is fine but the source-of-truth is *here*.
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent

# Acuity brand palette (mirrors :root in renderer/style.css)
INK        = (26, 29, 36)        # #1a1d24 — deep neutral
INK_DEEP   = (15, 17, 21)        # #0f1115 — even deeper for the sidebar gradient
PANEL      = (255, 255, 255)
ACCENT     = (245, 180, 0)       # #f5b400 — Acuity gold
ACCENT_DIM = (201, 142, 0)       # #c98e00
TEXT_DIM   = (139, 147, 163)     # #8b93a3
LINE       = (40, 44, 52)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """DejaVu is installed by default on the runner — and on most build
    machines — so we use it directly. If it ever isn't, Pillow's default
    bitmap font kicks in via the IOError path below; the assets will look
    a little rougher but the build doesn't break."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _vertical_gradient(size: tuple[int, int],
                       top: tuple[int, int, int],
                       bottom: tuple[int, int, int]) -> Image.Image:
    """Cheap vertical gradient. NSIS BMPs are 24-bit BI_RGB so we don't
    need alpha — just paint the whole canvas."""
    w, h = size
    img = Image.new("RGB", size, top)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def _centered(draw: ImageDraw.ImageDraw, xy: tuple[int, int],
              text: str, font: ImageFont.FreeTypeFont,
              fill: tuple[int, int, int]) -> None:
    """Pillow dropped textsize in 10.x; use textbbox for a portable size."""
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    w, h = r - l, b - t
    draw.text((xy[0] - w // 2 - l, xy[1] - h // 2 - t),
              text, font=font, fill=fill)


def make_sidebar(out: Path) -> None:
    """164x314 — the tall strip on the Welcome / Finish pages."""
    img = _vertical_gradient((164, 314), INK, INK_DEEP)
    d = ImageDraw.Draw(img)

    # Diagonal accent stripe near the bottom — gives the panel a hint of
    # branding without overwhelming the wordmark above it.
    d.polygon([(0, 235), (164, 215), (164, 222), (0, 242)], fill=ACCENT)

    # Wordmark, centered horizontally, sitting just above the middle.
    _centered(d, (82, 110), "ACUITY", _font(26, bold=True), PANEL)
    _centered(d, (82, 138), "MANAGER", _font(11, bold=True), TEXT_DIM)

    # Tagline near the bottom.
    _centered(d, (82, 280), "Vision coprocessor", _font(9), TEXT_DIM)
    _centered(d, (82, 294), "for FRC", _font(9), TEXT_DIM)

    img.save(out, "BMP")


def make_header(out: Path) -> None:
    """150x57 — the bar at the top of every inner page."""
    img = Image.new("RGB", (150, 57), PANEL)
    d = ImageDraw.Draw(img)

    # Left-aligned wordmark; subtle gold accent square stands in for an
    # icon without us shipping a full logo SVG.
    d.rectangle([8, 18, 22, 32], fill=ACCENT)
    d.rectangle([10, 20, 20, 30], fill=PANEL)
    d.rectangle([12, 22, 18, 28], fill=ACCENT)

    d.text((30, 17), "ACUITY", font=_font(13, bold=True), fill=INK)
    d.text((30, 33), "Manager Installer", font=_font(8), fill=TEXT_DIM)

    img.save(out, "BMP")


if __name__ == "__main__":
    make_sidebar(HERE / "installer-sidebar.bmp")
    make_sidebar(HERE / "uninstaller-sidebar.bmp")
    make_header (HERE / "installer-header.bmp")
    print("regenerated installer banners in", HERE)
