#!/bin/bash
# setup-pi.sh - One-time setup script for Raspberry Pi Ground Station
# Run this script once after cloning the repository on your Pi.
# Usage: sudo bash scripts/setup-pi.sh

set -e

echo "===================================="
echo "  DAEDALUS Ground Station - Pi Setup"
echo "===================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Please run as root (use sudo)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
USER_HOME="/home/pi"

echo "[1/6] Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv chromium-browser unclutter xdotool

echo "[2/6] Creating Python virtual environment..."
cd "$PROJECT_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

echo "[3/6] Installing systemd service for backend..."
cp "$PROJECT_DIR/scripts/autostart/groundstation.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable groundstation.service

echo "[4/6] Setting up kiosk autostart..."
chmod +x "$PROJECT_DIR/scripts/autostart/kiosk.sh"

# Create autostart directory if it doesn't exist
mkdir -p "$USER_HOME/.config/autostart"

# Create desktop entry for kiosk
cat > "$USER_HOME/.config/autostart/groundstation-kiosk.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Ground Station Kiosk
Exec=$PROJECT_DIR/scripts/autostart/kiosk.sh
X-GNOME-Autostart-enabled=true
EOF

chown -R pi:pi "$USER_HOME/.config/autostart"

echo "[5/6] Configuring display settings..."
# Add HDMI config for Waveshare 4.3" if not already present
if ! grep -q "hdmi_cvt=800 480" /boot/firmware/config.txt 2>/dev/null; then
    echo "" >> /boot/firmware/config.txt
    echo "# Waveshare 4.3 inch HDMI LCD (800x480)" >> /boot/firmware/config.txt
    echo "hdmi_group=2" >> /boot/firmware/config.txt
    echo "hdmi_mode=87" >> /boot/firmware/config.txt
    echo "hdmi_cvt=800 480 60 6 0 0 0" >> /boot/firmware/config.txt
    echo "Added HDMI settings for 800x480 display."
else
    echo "HDMI settings already configured."
fi

echo "[6/6] Setting permissions..."
chown -R pi:pi "$PROJECT_DIR"

echo ""
echo "===================================="
echo "  Setup Complete!"
echo "===================================="
echo ""
echo "NEXT STEPS:"
echo "  1. Reboot your Raspberry Pi: sudo reboot"
echo "  2. The ground station will start automatically."
echo "  3. Connect your radio via USB."
echo ""
echo "To manually start/stop the backend:"
echo "  sudo systemctl start groundstation"
echo "  sudo systemctl stop groundstation"
echo ""
