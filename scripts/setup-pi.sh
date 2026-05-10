#!/bin/bash
# =============================================================================
# Daedalus GCS — Raspberry Pi Auto-Setup Script
# Team #1043
#
# What this script does:
#   1. Installs all Python dependencies into the venv
#   2. Enables the SPI interface for the ST7735 screen
#   3. Installs the systemd service so the GCS server starts on every boot
#   4. Creates an autostart entry so Firefox opens the dashboard on login
#
# Run once after cloning the repo:
#   chmod +x scripts/setup-pi.sh
#   bash scripts/setup-pi.sh
# =============================================================================

set -e  # Stop the script immediately if any command fails

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/venv"
USER_HOME="$HOME"
AUTOSTART_DIR="$USER_HOME/.config/autostart"
GCS_URL="http://localhost:8080"

echo ""
echo "=============================================="
echo "  Daedalus GCS — Raspberry Pi Setup"
echo "=============================================="
echo ""

# ── Step 1: Python virtual environment ────────────────────────────────────────
echo "[1/4] Installing Python dependencies..."
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --quiet
echo "      Done."

# ── Step 2: Enable SPI ────────────────────────────────────────────────────────
echo "[2/4] Enabling SPI interface for ST7735 screen..."
if ! grep -q "^dtparam=spi=on" /boot/config.txt 2>/dev/null && \
   ! grep -q "^dtparam=spi=on" /boot/firmware/config.txt 2>/dev/null; then
    # Raspberry Pi OS Bookworm uses /boot/firmware/config.txt
    if [ -f "/boot/firmware/config.txt" ]; then
        echo "dtparam=spi=on" | sudo tee -a /boot/firmware/config.txt > /dev/null
    else
        echo "dtparam=spi=on" | sudo tee -a /boot/config.txt > /dev/null
    fi
    echo "      SPI enabled. A reboot is required for it to take effect."
else
    echo "      SPI already enabled."
fi

# ── Step 3: Install systemd service ───────────────────────────────────────────
echo "[3/4] Installing systemd service (GCS auto-start on boot)..."

# Write the service file with the correct paths for this Pi
sudo tee /etc/systemd/system/daedalus.service > /dev/null <<EOF
[Unit]
Description=Daedalus Ground Control Station (Team #1043)
After=network.target
Wants=network.target

[Service]
Type=simple
User=$(whoami)
Group=$(whoami)
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
echo "[4/4] Setting up Firefox to open the dashboard on login..."

mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_DIR/daedalus-browser.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Daedalus GCS Dashboard
Comment=Opens the Daedalus Ground Station dashboard in Firefox
# Wait 5 seconds for the GCS server to fully start before opening the browser
Exec=bash -c 'sleep 5 && firefox --new-window $GCS_URL'
X-GNOME-Autostart-enabled=true
EOF

echo "      Firefox autostart entry created."

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=============================================="
echo "  Setup Complete!"
echo "=============================================="
echo ""
echo "  Next steps:"
echo ""
echo "  1. Reboot the Pi to apply all changes:"
echo "     sudo reboot"
echo ""
echo "  2. After reboot:"
echo "     - The GCS server will start automatically in the background."
echo "     - Firefox will open http://localhost:8080 automatically."
echo ""
echo "  To check the GCS server logs at any time:"
echo "     journalctl -u daedalus -f"
echo ""
echo "  To manually restart the server:"
echo "     sudo systemctl restart daedalus"
echo ""
