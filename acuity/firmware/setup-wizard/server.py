"""Acuity — first-boot captive-portal setup wizard.

Runs in AP mode only (started by acuity-wifi-mode.sh after hostapd /
dnsmasq are up). Serves a single HTML form on every URL — that's the
captive-portal trick: dnsmasq points all DNS lookups at us, the OS's
captive-portal probe (connectivitycheck.gstatic.com / captive.apple.com)
hits us, and the OS pops the form automatically.

Once the user submits, we:
  1. Validate the input (team number is a positive int, SSID isn't empty).
  2. Write KEY=VALUE pairs to /boot/firmware/acuity.conf — atomic
     rename so a power-loss mid-write can't corrupt it.
  3. Show a "Got it, rebooting..." page.
  4. Reboot the Pi 2 s later.

After reboot, acuity-firstboot.sh reads the new config, drops AP
mode, joins the team WiFi, and starts the dashboard.

Why FastAPI for what could be 30 lines of Flask:
  * The main dashboard already uses FastAPI/uvicorn — same venv, no
    new dependency surface.
  * Async file I/O via aiofiles isn't strictly necessary at this
    scale, but the small overhead is negligible and the framework's
    request validation makes the multipart parsing trivially safe.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse

log = logging.getLogger("acuity-setup")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CFG_PATH = Path("/boot/firmware/acuity.conf")
CFG_TMP = Path("/boot/firmware/acuity.conf.tmp")

app = FastAPI(title="Acuity Setup")


# ---------- Captive-portal probe handlers ----------
#
# Each OS hits a specific URL on first WiFi-connect to test for
# internet:
#   * iOS / macOS expects 200 OK with body literally containing
#     "Success" — anything else (200 OK with non-Success body, or
#     a 302) triggers the captive-portal sheet.
#   * Android expects HTTP 204 No Content. ANY other status (200 OK,
#     302) triggers CaptivePortalLogin.
#   * Windows expects body "Microsoft Connect Test" on /connecttest.txt.
#     Anything else triggers their captive UI.
#
# Earlier we returned 302 → "/", but iOS's captive sheet sometimes
# silently closes on a redirect chain instead of rendering the
# destination. Returning the form HTML *directly* with status 200 is
# the reliable answer for all three OSes — they each detect "this
# isn't internet" and pop their captive UI showing exactly the body
# we returned, which is the wizard form.

_PROBE_PATHS = (
    "/generate_204",          # Android
    "/gen_204",               # Android (older)
    "/hotspot-detect.html",   # iOS / macOS
    "/library/test/success.html",  # iOS
    "/connecttest.txt",       # Windows
    "/ncsi.txt",              # Windows (older)
    "/redirect",              # generic
)


def _attach_probe_handlers() -> None:
    """Register a handler for every captive-portal probe path that
    returns the wizard form directly with HTTP 200 + HTML, so the OS's
    captive sheet renders the form immediately."""
    async def probe_handler(_request: Request) -> HTMLResponse:
        cur = _read_conf()
        return _render_form(
            team=str(cur.get("TEAM", "")),
            ssid=str(cur.get("SSID", "")),
            country=str(cur.get("COUNTRY", "US")) or "US",
        )
    for p in _PROBE_PATHS:
        app.add_api_route(p, probe_handler, methods=["GET"])


_attach_probe_handlers()


# ---------- Form ----------

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="theme-color" content="#eef0f3" />
  <title>Acuity — setup</title>
  <style>
    /* Mirrors the dashboard tokens (orangepi/static/style.css) so the
       wizard reads as the same product. Light theme, yellow accent,
       sans for labels (uppercase, tracked), mono for data. */
    :root {
      --bg: #eef0f3;
      --panel: #ffffff;
      --panel-2: #f6f7f9;
      --border: #d8dce3;
      --border-strong: #c1c7d0;
      --text: #1a1d24;
      --text-dim: #5b6371;
      --text-soft: #8b93a3;
      --accent: #f5b400;
      --accent-strong: #c98e00;
      --accent-soft: rgba(245, 180, 0, 0.16);
      --good: #16a34a;
      --good-soft: rgba(22, 163, 74, 0.10);
      --bad: #dc2626;
      --bad-soft: rgba(220, 38, 38, 0.10);
      --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.06);
      --shadow: 0 2px 6px rgba(15, 23, 42, 0.08), 0 1px 2px rgba(15, 23, 42, 0.04);
      --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", Helvetica, Arial, sans-serif;
      --mono: ui-monospace, "SF Mono", Menlo, Consolas, "Roboto Mono", monospace;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      min-height: 100vh;
      min-height: 100dvh;
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      font-size: 14px;
      -webkit-font-smoothing: antialiased;
      -webkit-text-size-adjust: 100%;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      padding: 16px;
      padding-top: max(16px, env(safe-area-inset-top));
      padding-bottom: max(24px, env(safe-area-inset-bottom));
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border-strong);
      border-radius: 8px;
      box-shadow: var(--shadow);
      width: 100%;
      max-width: 440px;
      padding: 18px 18px 20px;
    }
    @media (min-width: 480px) {
      .card { padding: 24px 26px 24px; }
    }
    .brand {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.10em;
      text-transform: uppercase;
      color: var(--text);
      margin: 0 0 4px;
    }
    h1 {
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin: 6px 0 14px;
      color: var(--text);
    }
    p.lead {
      color: var(--text-dim);
      font-size: 13px;
      line-height: 1.5;
      margin: 0 0 18px;
    }
    code {
      font-family: var(--mono);
      font-size: 0.92em;
      background: var(--panel-2);
      border: 1px solid var(--border);
      padding: 1px 5px;
      border-radius: 3px;
      color: var(--text);
    }
    .field { margin: 14px 0; }
    label {
      display: block;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--text-soft);
      margin: 0 0 5px;
    }
    input[type="text"],
    input[type="password"],
    input[type="number"] {
      width: 100%;
      background: var(--panel);
      color: var(--text);
      border: 1px solid var(--border-strong);
      border-radius: 4px;
      padding: 11px 12px;
      font-family: var(--mono);
      font-size: 16px; /* >=16px on iOS prevents zoom-on-focus */
      outline: none;
      transition: border-color 0.1s, box-shadow 0.1s;
      -webkit-appearance: none;
      appearance: none;
    }
    input:focus {
      border-color: var(--accent-strong);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }
    input::placeholder { color: var(--text-soft); }
    .hint {
      font-size: 11px;
      color: var(--text-dim);
      margin-top: 5px;
      line-height: 1.4;
    }
    .msg {
      font-size: 12px;
      font-family: var(--mono);
      padding: 8px 10px;
      border-radius: 4px;
      margin-bottom: 14px;
      border: 1px solid transparent;
    }
    .msg.err {
      color: var(--bad);
      background: var(--bad-soft);
      border-color: rgba(220, 38, 38, 0.3);
    }
    .msg.ok {
      color: var(--good);
      background: var(--good-soft);
      border-color: rgba(22, 163, 74, 0.3);
    }
    button {
      width: 100%;
      background: var(--accent);
      border: 1px solid var(--accent);
      color: #1f1500;
      font-family: var(--sans);
      font-weight: 700;
      font-size: 13px;
      letter-spacing: 0.10em;
      text-transform: uppercase;
      padding: 13px;
      border-radius: 4px;
      cursor: pointer;
      margin-top: 18px;
      min-height: 48px;
      transition: background 0.08s, border-color 0.08s;
    }
    button:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
    button:active { transform: translateY(1px); }
    footer {
      margin-top: 18px;
      padding-top: 14px;
      border-top: 1px solid var(--border);
      color: var(--text-dim);
      font-size: 11px;
      line-height: 1.55;
    }
    footer .pill {
      display: inline-block;
      font-size: 9px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 2px 8px;
      border-radius: 999px;
      border: 1px solid rgba(245, 180, 0, 0.4);
      background: var(--accent-soft);
      color: var(--accent-strong);
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">Acuity</div>
    <h1>First-boot setup</h1>
    <p class="lead">
      Connect this Vision Pi to your robot's WiFi. It'll reboot once
      and come back at <code>acuity-NNNN.local:8080</code>.
    </p>

    {message_html}

    <form method="post" action="/save" autocomplete="off" novalidate>
      <div class="field">
        <label for="team">Team number</label>
        <input id="team" name="team" type="number" min="1" max="99999"
               required inputmode="numeric"
               value="{team}" placeholder="e.g. 1279" />
        <div class="hint">Drives the hostname <code>acuity-NNNN.local</code>.</div>
      </div>

      <div class="field">
        <label for="ssid">Robot WiFi SSID</label>
        <input id="ssid" name="ssid" type="text" required maxlength="32"
               autocapitalize="off" autocorrect="off" spellcheck="false"
               value="{ssid}" placeholder="e.g. 1279" />
        <div class="hint">For most FRC teams this is just the team number.</div>
      </div>

      <div class="field">
        <label for="psk">Password</label>
        <input id="psk" name="psk" type="password" maxlength="63"
               autocapitalize="off" autocorrect="off" spellcheck="false"
               value="" placeholder="(leave blank for an open network)" />
        <div class="hint">Stored on this Pi only.</div>
      </div>

      <div class="field">
        <label for="country">Country code</label>
        <input id="country" name="country" type="text" maxlength="2"
               autocapitalize="characters" autocorrect="off" spellcheck="false"
               value="{country}" placeholder="US" />
      </div>

      <button type="submit">Save &amp; reboot</button>
    </form>

    <footer>
      Currently in <span class="pill">AP mode</span>.
      Plug a USB camera in before saving — the dashboard will be live at
      <code>acuity-NNNN.local:8080</code> within about 30 seconds of reboot.
    </footer>
  </div>
</body>
</html>
"""


def _esc(s: str) -> str:
    """Minimal HTML escape for form pre-fills."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_form(message: str = "", team: str = "", ssid: str = "", country: str = "US",
                 ok: bool = False) -> HTMLResponse:
    msg_html = ""
    if message:
        cls = "ok" if ok else "err"
        msg_html = f'<div class="msg {cls}">{_esc(message)}</div>'
    # Use .replace() instead of .format() because INDEX_HTML contains a
    # full CSS <style> block with literal `{` / `}`. str.format() tries
    # to parse those CSS braces as format placeholders and dies with
    # `KeyError: '\\n  --bg'` on the very first :root rule.
    body = (
        INDEX_HTML
        .replace("{message_html}", msg_html)
        .replace("{team}", _esc(team))
        .replace("{ssid}", _esc(ssid))
        .replace("{country}", _esc(country))
    )
    return HTMLResponse(body)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Show the form, pre-populated with whatever's currently in
    acuity.conf so the operator can edit a typo without re-typing
    everything."""
    cur = _read_conf()
    return _render_form(
        team=str(cur.get("TEAM", "")),
        ssid=str(cur.get("SSID", "")),
        country=str(cur.get("COUNTRY", "US")) or "US",
    )


# ---------- Save ----------

# SSID can be 1..32 octets per 802.11. Allow most printable chars; strict
# enough that we won't accidentally write a control char into hostapd
# config. (We never feed PSK into a config file directly — NetworkManager
# does its own escaping when we hand it via nmcli.)
_SSID_RE = re.compile(r"^[\x20-\x7e]{1,32}$")
_TEAM_RE = re.compile(r"^\d{1,5}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _read_conf() -> dict[str, str]:
    """Best-effort parse of the existing acuity.conf. Missing file or
    parse error → empty dict; we don't want first-boot setup to fail
    just because someone hand-edited the file weirdly."""
    out: dict[str, str] = {}
    try:
        for line in CFG_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("read acuity.conf failed: %s", e)
    return out


def _write_conf(team: str, ssid: str, psk: str, country: str) -> None:
    """Write acuity.conf atomically. The boot partition is FAT32 so
    rename-over is not strictly POSIX-atomic — but it's close enough for
    our case; either the new file is fully there or the rename failed.
    """
    body = (
        "# Generated by the first-boot setup wizard.\n"
        "# Edit by hand to change settings. Delete to re-trigger AP mode.\n"
        f"TEAM={team}\n"
        f"SSID={ssid}\n"
        f"PSK={psk}\n"
        f"COUNTRY={country}\n"
    )
    CFG_TMP.write_text(body)
    os.replace(CFG_TMP, CFG_PATH)


def _schedule_reboot(delay_s: float = 2.5) -> None:
    """Reboot via a daemon thread so we can return the response first.
    `systemctl reboot` over D-Bus is the canonical way; the service runs
    as root so this just works."""
    def _go() -> None:
        time.sleep(delay_s)
        log.info("rebooting now")
        try:
            subprocess.run(["systemctl", "reboot"], check=False)
        except Exception as e:
            log.exception("reboot failed: %s", e)
    threading.Thread(target=_go, daemon=True).start()


@app.post("/save", response_class=HTMLResponse)
async def save(
    team: str = Form(...),
    ssid: str = Form(...),
    psk: str = Form(""),
    country: str = Form("US"),
) -> HTMLResponse:
    team = team.strip()
    ssid = ssid.strip()
    psk = psk  # don't strip the password — leading/trailing whitespace is rare but legal
    country = (country or "US").strip().upper()

    if not _TEAM_RE.match(team):
        return _render_form("Team number must be 1-5 digits.",
                            team=team, ssid=ssid, country=country)
    if not ssid:
        return _render_form("SSID can't be blank.",
                            team=team, ssid=ssid, country=country)
    if not _SSID_RE.match(ssid):
        return _render_form("SSID has unsupported characters.",
                            team=team, ssid=ssid, country=country)
    if len(psk) > 63:
        return _render_form("Password too long (max 63 chars).",
                            team=team, ssid=ssid, country=country)
    if not _COUNTRY_RE.match(country):
        return _render_form("Country code must be 2 letters (e.g. US).",
                            team=team, ssid=ssid, country=country)

    try:
        _write_conf(team, ssid, psk, country)
    except Exception as e:
        log.exception("write conf failed")
        return _render_form(f"Couldn't write config: {e}",
                            team=team, ssid=ssid, country=country)

    log.info("config saved: team=%s ssid=%s — rebooting", team, ssid)
    _schedule_reboot()

    return HTMLResponse(
        _RESULT_HTML
        .replace("{team}", _esc(team))
        .replace("{ssid}", _esc(ssid))
    )


_RESULT_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="theme-color" content="#eef0f3" />
  <meta http-equiv="refresh" content="30; url=http://acuity-{team}.local:8080/" />
  <title>Saved — rebooting</title>
  <style>
    :root {
      --bg: #eef0f3;
      --panel: #ffffff;
      --panel-2: #f6f7f9;
      --border: #d8dce3;
      --border-strong: #c1c7d0;
      --text: #1a1d24;
      --text-dim: #5b6371;
      --text-soft: #8b93a3;
      --good: #16a34a;
      --good-soft: rgba(22, 163, 74, 0.10);
      --shadow: 0 2px 6px rgba(15, 23, 42, 0.08), 0 1px 2px rgba(15, 23, 42, 0.04);
      --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", Helvetica, Arial, sans-serif;
      --mono: ui-monospace, "SF Mono", Menlo, Consolas, "Roboto Mono", monospace;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      min-height: 100vh;
      min-height: 100dvh;
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      font-size: 14px;
      -webkit-font-smoothing: antialiased;
      -webkit-text-size-adjust: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border-strong);
      border-radius: 8px;
      box-shadow: var(--shadow);
      width: 100%;
      max-width: 440px;
      padding: 22px 22px 20px;
      text-align: left;
    }
    @media (min-width: 480px) {
      .card { padding: 28px 28px 24px; }
    }
    .brand {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.10em;
      text-transform: uppercase;
      color: var(--text);
      margin: 0 0 12px;
    }
    .status {
      display: inline-block;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 3px 10px;
      border-radius: 999px;
      border: 1px solid rgba(22, 163, 74, 0.4);
      background: var(--good-soft);
      color: var(--good);
      margin-bottom: 10px;
    }
    h1 {
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin: 4px 0 14px;
      color: var(--text);
    }
    p {
      color: var(--text-dim);
      line-height: 1.55;
      font-size: 13px;
      margin: 0 0 12px;
    }
    p strong { color: var(--text); font-weight: 600; }
    code {
      font-family: var(--mono);
      font-size: 0.92em;
      background: var(--panel-2);
      border: 1px solid var(--border);
      padding: 1px 5px;
      border-radius: 3px;
      color: var(--text);
      word-break: break-all;
    }
    footer {
      margin-top: 18px;
      padding-top: 14px;
      border-top: 1px solid var(--border);
      color: var(--text-soft);
      font-size: 11px;
      line-height: 1.55;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">Acuity</div>
    <span class="status">Saved</span>
    <h1>Rebooting</h1>
    <p>The Pi is rebooting and will join <strong>{ssid}</strong>.</p>
    <p>In about 30 seconds, your dashboard will be at
       <br><code>http://acuity-{team}.local:8080/</code></p>
    <footer>
      You can disconnect from <code>Acuity-Setup-*</code> and rejoin
      your normal WiFi.
    </footer>
  </div>
</body>
</html>
"""


# Catch-all for any other path the captive-portal probe hits (Android in
# particular tries a few different URLs). Bouncing them to "/" is what
# triggers the auto-popup.
@app.get("/{full_path:path}")
async def catch_all(full_path: str) -> RedirectResponse:
    return RedirectResponse(url="/", status_code=302)


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz() -> str:
    return "ok"
