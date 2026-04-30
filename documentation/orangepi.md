# Vision Pi (Orange Pi 5) — Setup Guide

The Orange Pi 5 hosts the camera + the click-to-aim web UI. It talks to
the roboRIO over the robot's network. This is the **first-time setup**;
once it's done, the **Set up Vision Pi** and **Update Vision Pi** buttons
in the Cold Fusion control panel handle everything from the laptop.

---

## What you need

- Orange Pi 5 (or 5B) — 4 GB RAM is plenty
- microSD card, 32 GB or larger (Class 10 / A2)
- USB-C 5 V / 3 A power supply (Pi 5 won't reliably boot at 2 A)
- USB webcam (any UVC camera that supports MJPEG — most do)
- Ethernet cable (Pi → robot radio's spare LAN port)
- microSD reader for your laptop

You don't need a monitor or keyboard for the Pi. Setup is "headless" —
flash the SD card, plug the Pi in, then drive it from the laptop over
SSH. (You'll need a monitor + keyboard only if something goes sideways.)

---

## Step 1 — flash the SD card

1. Download **Armbian** for Orange Pi 5 (Bookworm minimal):
   <https://www.armbian.com/orange-pi-5/>
2. Download **balenaEtcher**: <https://etcher.balena.io/>
3. Plug the SD card into your laptop, open Etcher, pick the Armbian
   `.img.xz` you downloaded, pick the SD card, click **Flash**.
4. When Etcher finishes, **eject the card**.

> Why Armbian: it has the best Orange Pi 5 kernel support and ships
> with `apt`. Stock Orange Pi OS works too — instructions below should
> still match. Avoid Ubuntu Server images that aren't tuned for the
> RK3588S, they tend to drop USB devices under load.

## Step 2 — first boot

1. Put the SD card in the Pi.
2. Plug the **USB camera** into one of the USB-A ports.
3. Plug an **Ethernet cable** from the Pi into a spare LAN port on the
   robot's radio (or any switch that can reach the rio).
4. Plug in **power**. The blue LED blinks for ~30 seconds, then settles.

The Pi gets an IP from the radio's DHCP. Default Armbian login is
`root` / `1234` — first login forces you to change the password and
create a regular user. **Use the username `orangepi`** (the rest of
this project assumes that name; you can change it later in
`.orangepi_cfg`).

## Step 3 — find the Pi from your laptop

You have two options:

- **mDNS (easiest):** the Pi advertises itself as `orangepi.local`.
  Try `ping orangepi.local`. If that resolves, skip to Step 4.
- **DHCP table:** log into the radio's web UI (default
  `http://10.TE.AM.1`) and look under **Status → DHCP Leases**. Note
  the Pi's IP.

If neither works, plug a monitor and USB keyboard into the Pi briefly
and run `ip a` to read off its address.

## Step 4 — first SSH

From the laptop, open a terminal:

```bash
ssh orangepi@orangepi.local       # or orangepi@<ip>
```

You'll be asked to accept the host key (type `yes`) and enter the
password you set in step 2. You should see the Armbian welcome banner.

> If SSH refuses the connection: SSH is enabled by default on Armbian,
> but some images ship with it off. From the Pi's console:
>
> ```bash
> sudo systemctl enable --now ssh
> ```

Log out (`exit`) — you're done with manual SSH for now.

## Step 5 — install Cold Fusion Sight

This is the **only step you'll repeat** for future Pi reflashes.

1. On the laptop, open the Cold Fusion control panel:
   ```bash
   python start.py
   ```
2. Click **Set up Vision Pi**.
3. When it asks for the host, type the same name/IP you used in Step 4
   (e.g. `orangepi.local`) and accept the default user (`orangepi`).
4. The installer will:
   - rsync the `orangepi/` folder onto the Pi
   - `apt install` ffmpeg + python3-venv + v4l-utils (you'll be prompted
     for the Pi's password the first time — store it in your SSH agent
     or accept the prompts)
   - create a Python venv, install FastAPI + uvicorn + pyntcore
   - drop a systemd unit and start the service
   - generate SSH keys on both the Pi and the rio so they can SSH each
     other without passwords (if the rio is reachable)

When it finishes, click **Open Sight UI**. Your browser should land on
`http://orangepi.local:8080/` and show the live camera + the team-yellow
control panel.

## Step 6 — verify

On the camera page you should see:

- **CONNECTED** pill (green) in the top-left = Pi is talking to the rio
- Live camera feed filling most of the page
- Distance / RPS / dial readouts populating from the rio
- The OPERATOR D-pad lights up when you press the operator gamepad

If **CONNECTED** stays red, the Pi can't reach NetworkTables. Check:

```bash
ssh orangepi@orangepi.local
cat /home/orangepi/cold-fusion-sight/sight.env       # is TEAM=1279?
sudo journalctl -u cold-fusion-sight -n 60           # last 60 log lines
ping 10.12.79.2                                      # rio reachable from Pi?
```

---

## Day-to-day use

- **Drive the robot:** open the control panel, hit **Connect** (puts you
  on the robot WiFi and launches DriverStation).
- **Push code:** **Deploy to Robot**. Deploy now sends rio code AND
  updates the Pi in one click — you don't need to remember which one
  changed.
- **Aim & shoot:** open the Sight UI, click anywhere on the camera. The
  rio rotates, dials in distance from the LaserCAN, and fires.
- **Update just the Pi:** **Update Vision Pi**. Faster than full
  Deploy when you only edited HTML/JS/CSS.

## Cross-host SSH

After **Set up Vision Pi**, the Pi and rio can SSH each other without
passwords:

```bash
# from the Pi:
ssh admin@10.12.79.2

# from the rio (`ssh admin@10.12.79.2` from the laptop, then):
ssh orangepi@<pi-ip>
```

This is mostly for debugging — pulling logs, copying a one-off file
between them. The control panel doesn't depend on it.

## Troubleshooting

| Symptom                                 | Try                                                              |
|-----------------------------------------|------------------------------------------------------------------|
| Can't `ping orangepi.local`             | Check Ethernet light, reboot the radio, use the IP from DHCP    |
| **Set up Vision Pi** "Permission denied"| Re-enter Pi password, or `ssh-copy-id orangepi@orangepi.local`  |
| Web UI loads but says **DISCONNECTED**  | `journalctl -u cold-fusion-sight -f` while you watch            |
| Camera frame is black                   | `v4l2-ctl --list-devices` on the Pi; reseat USB                 |
| LaserCAN reads "NO READING"             | Check CAN ID matches `constants.CANIDs.LASERCAN` (default 36)   |
| Pi UI laggy                             | Lower `CAMERA_FPS` in `sight.env` and `systemctl restart cold-fusion-sight` |

## When the rio is broken

The Pi keeps streaming the camera even when the rio is down — useful
for visually checking the field/camera health independent of the robot
code. Click-to-aim won't do anything until the rio is back, but the
video and the (stale) HUD readouts stay up.
