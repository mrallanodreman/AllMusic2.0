# AllMusic 2.0

Desktop companion app for AllMusic.

This repository contains the native Linux mini-app, not the public website. The web platform lives separately and the app connects to it through a configurable API base URL.

## What it does

- Native GTK desktop mini player
- Search tracks through the AllMusic API
- Stream audio directly from the remote service
- Download the current track as MP3
- Keep local window position and user config
- Toggle the app open or hidden with a lightweight launcher

## Project files

```text
allmusic2.py          Main GTK application
allmusic2.svg         App icon
install.sh            User-local installer for Linux desktops
config.example.json   Example runtime config
requirements.txt      Python package requirements
```

## Runtime requirements

System packages are required for GTK and audio playback.

### Debian / Ubuntu / Linux Mint

```bash
sudo apt update
sudo apt install -y python3 python3-gi gir1.2-gtk-3.0 gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-libav python3-requests
```

If you prefer pip for the Python-only dependency:

```bash
pip install -r requirements.txt
```

## Install

```bash
chmod +x install.sh
./install.sh
```

That creates:

- `~/.local/bin/allmusic2`
- `~/.local/bin/allmusic2-toggle`
- `~/.local/share/applications/allmusic2.desktop`
- `~/.config/allmusic2/config.json`

## Run

```bash
allmusic2
```

Toggle hidden/visible state:

```bash
allmusic2-toggle
```

## Configuration

The app reads config from:

```text
~/.config/allmusic2/config.json
```

Example:

```json
{
  "api_base": "https://edgemarketing.art/allmusic",
  "dl_dir": "/home/your-user/Downloads"
}
```

You can also override the API at runtime with:

```bash
ALLMUSIC_API_BASE="https://example.com/allmusic" allmusic2
```

## Notes

- This repo is for the desktop app only.
- The website and backend service are separate sister projects.
- The default API target points to the live AllMusic service, but it is configurable.
