# Nanobot Deployment Guide

## Running as a systemd Service (Auto-start on boot)

### 1. Create the service file

```bash
sudo nano /etc/systemd/system/nanobot.service
```

Paste the following:

```ini
[Unit]
Description=Nanobot AI Gateway
After=network.target

[Service]
Type=simple
User=root
ExecStart=/root/.local/bin/nanobot gateway
Restart=on-failure
RestartSec=5
StandardOutput=append:/root/.nanobot/gateway.log
StandardError=append:/root/.nanobot/gateway.log

[Install]
WantedBy=multi-user.target
```

### 2. Enable and start the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable nanobot      # auto-start on boot
sudo systemctl start nanobot       # start now
```

---

## Start / Stop / Restart

| Action | Command |
|--------|---------|
| Start | `sudo systemctl start nanobot` |
| Stop | `sudo systemctl stop nanobot` |
| Restart | `sudo systemctl restart nanobot` |
| Enable on boot | `sudo systemctl enable nanobot` |
| Disable on boot | `sudo systemctl disable nanobot` |

---

## View Logs

### Live logs (real-time)
```bash
tail -f /root/.nanobot/gateway.log
```

### Via systemd (last 100 lines + live)
```bash
journalctl -u nanobot -n 100 -f
```

### Check service status
```bash
sudo systemctl status nanobot
```

---

## Deploying Code Changes

> The service runs the **installed** binary (`/root/.local/bin/nanobot`), not the project source.
> Editing files under `/root/projects/nanobot` has **no effect** until you reinstall.

### After editing source code

```bash
uv tool install --reinstall /root/projects/nanobot
sudo systemctl restart nanobot
```

### After editing config only (`~/.nanobot/config.json`)

No reinstall needed — just restart:

```bash
sudo systemctl restart nanobot
```

---

## Notes

- Config file: `~/.nanobot/config.json`
- Log file: `~/.nanobot/gateway.log`
