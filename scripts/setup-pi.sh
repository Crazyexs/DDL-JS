#!/bin/bash
# =============================================================================
# Daedalus GCS — Raspberry Pi Auto-Setup Script
# Team #1043
#
# What this script does:
#   1. Installs Python dependencies into the venv
#   2. Enables the SPI interface for the ST7735 screen
#   3. Installs the systemd service (GCS server auto-starts on boot)
#   4. Creates a Firefox autostart entry (opens dashboard on desktop login)
#
# Run once on the Raspberry Pi:
#   bash scripts/setup-pi.sh
#   sudo reboot
# =============================================================================

# Do NOT use set -e here — we want the script to continue even if one
# optional step fails (e.g. if a package is not available on this OS).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/venv"
AUTOSTART_DIR="$HOME/.config/autostart"
GCS_URL="http://localhost:8080"
CURRENT_USER="$(whoami)"

echo ""
echo "=========================================="
echo "  Daedalus GCS Setup"
echo "  Repo : $PROJECT_DIR"
echo "  User : $CURRENT_USER"
echo "  Port : 8080"
echo "=========================================="
echo ""

# ── Step 1: Python virtual environment ────────────────────────────────────────
echo "[1/4] Installing Python dependencies..."
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --quiet
echo "      Done."

# ── Step 2: Enable SPI (for ST7735 screen) ────────────────────────────────────
echo "[2/4] Enabling SPI interface..."

SPI_ENABLED=false

# Method A: raspi-config noninteractive (most reliable on all Pi OS versions)
if command -v raspi-config &>/dev/null; then
    sudo raspi-config nonint do_spi 0 && SPI_ENABLED=true
fi

# Method B: manually add to config.txt as a fallback
if [ "$SPI_ENABLED" = false ]; then
    CONFIG_FILE=""
    if [ -f "/boot/firmware/config.txt" ]; then
        CONFIG_FILE="/boot/firmware/config.txt"   # Raspberry Pi OS Bookworm
    elif [ -f "/boot/config.txt" ]; then
        CONFIG_FILE="/boot/config.txt"             # Older Raspberry Pi OS
    fi

    if [ -n "$CONFIG_FILE" ]; then
        if ! grep -q "^dtparam=spi=on" "$CONFIG_FILE"; then
            echo "dtparam=spi=on" | sudo tee -a "$CONFIG_FILE" > /dev/null
            echo "      SPI line added to $CONFIG_FILE"
        else
            echo "      SPI already set in $CONFIG_FILE"
        fi
    else
        echo "      WARNING: Could not find boot config.txt — enable SPI manually via raspi-config"
    fi
fi

echo "      SPI step complete."

# ── Step 3: Install systemd service ───────────────────────────────────────────
echo "[3/4] Installing systemd service (GCS auto-start on boot)..."

sudo tee /etc/systemd/system/daedalus.service > /dev/null <<EOF
[Unit]
Description=Daedalus Ground Control Station (Team #1043)
After=network.target
Wants=network.target

[Service]
Type=simple
User=$CURRENT_USER
Group=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8080 --log-level info
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=daedalus
TimeoutStartSec=30
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable daedalus
echo "      Systemd service installed and enabled."

# ── Step 4: Firefox autostart on desktop login ────────────────────────────────
echo "[4/4] Setting up Firefox to open dashboard on login..."

mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_DIR/daedalus-browser.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Daedalus GCS Dashboard
Comment=Opens the Daedalus Ground Station in Firefox
Exec=bash -c 'sleep 8 && firefox --new-window $GCS_URL'
X-GNOME-Autostart-enabled=true
DESKTOP

echo "      Firefox autostart entry created at $AUTOSTART_DIR/daedalus-browser.desktop"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "  Reboot now to apply all changes:"
echo "    sudo reboot"
echo ""
echo "  After reboot:"
echo "    - GCS server starts automatically in the background"
echo "    - Firefox opens http://localhost:8080 automatically"
echo "    - XBee radio is detected and connected automatically"
echo "    - ST7735 screen starts automatically"
echo ""
echo "  Useful commands:"
echo "    journalctl -u daedalus -f          (live server logs)"
echo "    sudo systemctl restart daedalus    (restart server)"
echo "    sudo systemctl status daedalus     (check status)"
echo ""
