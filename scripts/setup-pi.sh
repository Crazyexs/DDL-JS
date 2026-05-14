#!/bin/bash
# Daedalus Ground Station — Raspberry Pi Setup
# Run with:  sudo bash scripts/setup-pi.sh
set -euo pipefail

# ─── Resolve identity ─────────────────────────────────────────────
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_USER="${SUDO_USER:-$(whoami)}"
INSTALL_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
GCS_PORT=8080
SERVICE_NAME="daedalus-gcs"

# ─── Must run as root (needs systemd + apt) ───────────────────────
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run with sudo."
    echo "  sudo bash scripts/setup-pi.sh"
    exit 1
fi

echo "================================================="
echo "  Daedalus Ground Station — Raspberry Pi Setup"
echo "  Repo : $REPO_DIR"
echo "  User : $INSTALL_USER"
echo "  Home : $INSTALL_HOME"
echo "  Port : $GCS_PORT"
echo "================================================="
echo ""

# ─── 1. System packages ───────────────────────────────────────────
echo ">>> [1/6] Installing system packages..."
apt-get update -qq

# Bookworm uses 'chromium', Bullseye uses 'chromium-browser'
CHROMIUM_PKG="chromium-browser"
if apt-cache show chromium &>/dev/null && ! apt-cache show chromium-browser &>/dev/null; then
    CHROMIUM_PKG="chromium"
fi

apt-get install -y --no-install-recommends \
    python3-venv python3-pip \
    "$CHROMIUM_PKG" \
    curl \
    unclutter \
    xdotool
echo "    Done (browser: $CHROMIUM_PKG)."

# ─── 2. Python virtual environment ────────────────────────────────
echo ""
echo ">>> [2/6] Setting up Python virtual environment..."
cd "$REPO_DIR"
if [ ! -d venv ]; then
    sudo -u "$INSTALL_USER" python3 -m venv venv
fi
sudo -u "$INSTALL_USER" venv/bin/pip install --upgrade pip -q
sudo -u "$INSTALL_USER" venv/bin/pip install -r requirements.txt -q
echo "    Done."

# ─── 3. systemd service for the backend ───────────────────────────
echo ""
echo ">>> [3/6] Installing systemd backend service..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << SERVICE
[Unit]
Description=Daedalus Ground Station Backend
Documentation=https://github.com/Crazyexs/DDL-JS
After=network.target

[Service]
Type=simple
User=${INSTALL_USER}
WorkingDirectory=${REPO_DIR}
ExecStart=${REPO_DIR}/venv/bin/uvicorn main:app --host 0.0.0.0 --port ${GCS_PORT}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
echo "    Service enabled: ${SERVICE_NAME}"

# ─── 4. Kiosk auto-start (browser) ────────────────────────────────
echo ""
echo ">>> [4/6] Configuring desktop kiosk auto-start..."

KIOSK_SCRIPT="$REPO_DIR/scripts/start-kiosk.sh"

# XDG autostart — universal: works on LXDE, GNOME, Wayfire, etc.
mkdir -p /etc/xdg/autostart
cat > /etc/xdg/autostart/daedalus-kiosk.desktop << DESKTOP
[Desktop Entry]
Type=Application
Name=Daedalus GCS Kiosk
Exec=bash ${KIOSK_SCRIPT}
X-GNOME-Autostart-enabled=true
NotShowIn=;
DESKTOP

# LXDE-pi autostart (Raspberry Pi OS Bullseye default desktop)
LXDE_AUTOSTART="${INSTALL_HOME}/.config/lxsession/LXDE-pi/autostart"
mkdir -p "$(dirname "$LXDE_AUTOSTART")"
KIOSK_ENTRY="@bash ${KIOSK_SCRIPT}"
if ! grep -qF "$KIOSK_ENTRY" "$LXDE_AUTOSTART" 2>/dev/null; then
    echo "$KIOSK_ENTRY" >> "$LXDE_AUTOSTART"
    chown "$INSTALL_USER:$INSTALL_USER" "$LXDE_AUTOSTART"
fi

echo "    XDG:  /etc/xdg/autostart/daedalus-kiosk.desktop"
echo "    LXDE: $LXDE_AUTOSTART"

# ─── 5. Serial port access ────────────────────────────────────────
echo ""
echo ">>> [5/6] Granting serial port access..."
usermod -aG dialout "$INSTALL_USER"
echo "    User $INSTALL_USER added to 'dialout' group."

# Grant access to ttyACM0 (USB GPS)
usermod -aG tty "$INSTALL_USER"
# udev rule so ttyACM0 is always accessible without sudo
cat > /etc/udev/rules.d/99-usb-gps.rules << 'UDEV'
SUBSYSTEM=="tty", ATTRS{idVendor}=="1546", ATTRS{idProduct}=="01a7", SYMLINK+="gps0", GROUP="dialout", MODE="0666"
SUBSYSTEM=="tty", KERNEL=="ttyACM*", GROUP="dialout", MODE="0666"
UDEV
udevadm control --reload-rules
echo "    GPS udev rules installed."

# ─── 6. Management tool ───────────────────────────────────────────
echo ""
echo ">>> [6/6] Installing 'gcs' management tool..."
cat > /usr/local/bin/gcs << 'GCSTOOL'
#!/bin/bash
SERVICE="daedalus-gcs"
CMD="${1:-help}"
case "$CMD" in
  start)   sudo systemctl start   "$SERVICE" && echo "Started."   ;;
  stop)    sudo systemctl stop    "$SERVICE" && echo "Stopped."   ;;
  restart) sudo systemctl restart "$SERVICE" && echo "Restarted." ;;
  status)  systemctl status       "$SERVICE" ;;
  logs)    journalctl -u          "$SERVICE" -f --no-pager ;;
  open)    DISPLAY=:0 xdg-open http://127.0.0.1:8080 ;;
  *)
    echo "Usage: gcs <command>"
    echo ""
    echo "  start    Start the backend"
    echo "  stop     Stop the backend"
    echo "  restart  Restart the backend"
    echo "  status   Show service status"
    echo "  logs     Live log stream (Ctrl+C to exit)"
    echo "  open     Open dashboard in browser"
    ;;
esac
GCSTOOL
chmod +x /usr/local/bin/gcs
echo "    Done. Run 'gcs help' for usage."

# ─── Summary ──────────────────────────────────────────────────────
echo ""
echo "================================================="
echo " Setup complete!"
echo ""
echo " Start now (no reboot needed for backend):"
echo "   sudo systemctl start ${SERVICE_NAME}"
echo "   gcs status"
echo ""
echo " Dashboard URL:  http://127.0.0.1:${GCS_PORT}"
echo " From another device:  http://<pi-ip>:${GCS_PORT}"
echo ""
echo " Auto-start on boot:  ENABLED (systemd)"
echo " Kiosk on login:      ENABLED (XDG + LXDE autostart)"
echo ""
echo " IMPORTANT: Reboot for serial port (dialout) access"
echo "   sudo reboot"
echo "================================================="
