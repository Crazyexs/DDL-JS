#!/bin/bash
set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_USER="${SUDO_USER:-$(whoami)}"

echo "================================================="
echo "   Daedalus Ground Station - Raspberry Pi Setup"
echo "   Repo: $REPO_DIR"
echo "   User: $INSTALL_USER"
echo "================================================="

# 1. Update and install system dependencies
echo ">>> Installing required system packages..."
sudo apt update
sudo apt install -y python3-venv python3-pip xdotool unclutter speech-dispatcher espeak-ng firefox-esr

# 2. Setup Python virtual environment
echo ">>> Setting up Python virtual environment..."
cd "$REPO_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Create startup script (uses dynamic repo path, no hardcoded /home/admin)
echo ">>> Creating startup script..."
mkdir -p "$REPO_DIR/scripts"
cat > "$REPO_DIR/scripts/start-gcs.sh" << EOF
#!/bin/bash
cd "$REPO_DIR"
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8080 &
sleep 10
export DISPLAY=:0
firefox-esr --kiosk http://127.0.0.1:8080
EOF
chmod +x "$REPO_DIR/scripts/start-gcs.sh"

# 4. Setup auto-start (XDG global autostart — works on X11 and Wayland)
echo ">>> Configuring auto-start..."
sudo mkdir -p /etc/xdg/autostart
sudo tee /etc/xdg/autostart/daedalus-gcs.desktop > /dev/null << EOF
[Desktop Entry]
Type=Application
Name=DaedalusGCS
Exec=bash -c "$REPO_DIR/scripts/start-gcs.sh"
X-GNOME-Autostart-enabled=true
EOF

# 5. Add user to dialout group for serial port access (XBee radio)
echo ">>> Granting serial port access to $INSTALL_USER..."
sudo usermod -aG dialout "$INSTALL_USER"

echo "================================================="
echo " Setup complete! Reboot to activate auto-start."
echo " Serial port access requires a logout/login or reboot."
echo "================================================="
