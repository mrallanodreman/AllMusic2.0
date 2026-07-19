#!/bin/bash
# AllMusic 2.0 - installer for Linux desktop environments
set -e

SRC="$(cd "$(dirname "$0")" && pwd)"
APP_SLUG="allmusic2"
APP_NAME="AllMusic 2.0"

DEST="${DEST:-$HOME/.local/share/$APP_SLUG}"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"

echo "Installing $APP_NAME to $DEST ..."
mkdir -p "$DEST" "$BIN" "$APPS" "$ICONS"

cp "$SRC/allmusic2.py" "$DEST/"
cp "$SRC/allmusic2.svg" "$ICONS/"

cat > "$BIN/$APP_SLUG" << 'SCRIPT'
#!/bin/bash
exec /usr/bin/python3 "$HOME/.local/share/allmusic2/allmusic2.py" "$@"
SCRIPT
chmod +x "$BIN/$APP_SLUG"

cat > "$BIN/${APP_SLUG}-toggle" << 'SCRIPT'
#!/bin/bash
PID_FILE="$HOME/.config/allmusic2/pid"
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" 2>/dev/null)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        kill -USR1 "$PID" 2>/dev/null && exit 0
    fi
fi
exec allmusic2 --hidden
SCRIPT
chmod +x "$BIN/${APP_SLUG}-toggle"

cat > "$APPS/${APP_SLUG}.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Desktop companion app for AllMusic
Exec=$BIN/$APP_SLUG
Icon=$ICONS/allmusic2.svg
Terminal=false
Categories=AudioVideo;Audio;Music;Player;
StartupNotify=true
StartupWMClass=$APP_SLUG
DESKTOP

# Config file — listo para usar
CFG="$HOME/.config/$APP_SLUG/config.json"
if [ ! -f "$CFG" ]; then
    mkdir -p "$HOME/.config/$APP_SLUG"
    cat > "$CFG" << CFG
{
    "api_base": "https://edgemarketing.art/allmusic",
    "dl_dir": "$HOME/Descargas"
}
CFG
fi

echo "Done. Log out/in or run:"
echo "  $APP_SLUG"
echo ""
echo "Config: $CFG"
