# Daedalus Ground Station — Team #1043

Real-time telemetry dashboard for CanSat Team #1043. FastAPI backend + browser-based frontend.

---

## Quick Start (Mac / Linux)

```bash
git clone https://github.com/Crazyexs/DDL-JS.git
cd DDL-JS
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```

Open **http://localhost:8080** in your browser.

## Quick Start (Windows)

```bat
git clone https://github.com/Crazyexs/DDL-JS.git
cd DDL-JS
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## Requirements

- Python 3.9 or newer
- No other system dependencies needed (all libraries in `requirements.txt`)

---

## Serial Port Setup

Edit `DEFAULT_PORT` at the top of `main.py` to match your XBee radio:

| OS | Example |
|---|---|
| macOS | `/dev/cu.usbserial-XXXXXXXX` |
| Linux / Pi | `/dev/ttyUSB0` |
| Windows | `COM3` |

If no radio is connected, click **Run Sim** in the UI to stream the simulation pressure file.

---

## 🍓 Raspberry Pi Setup (Deep Guide)

This section provides a step-by-step walkthrough to turn a Raspberry Pi into a dedicated, autonomous Ground Control Station.

### Step 1: Hardware Preparation
1. **Radio:** Plug in your XBee USB adapter.
2. **GPS:** Plug in your Ground Station USB GPS (e.g. VK-172 u-blox 7).

### Step 2: Download the Ground Station
Open a terminal on the Raspberry Pi and clone this repository, making sure to switch to the `raspberry-pi` branch:
```bash
git clone https://github.com/Crazyexs/DDL-JS.git
cd DDL-JS
git checkout raspberry-pi
```

### Step 3: Run the Setup Script
The provided script will automatically install all required packages (like Chromium), create a Python virtual environment, install dependencies, and configure the Pi to boot directly into the dashboard.
```bash
sudo bash scripts/setup-pi.sh
```

### Step 4: Reboot
Once the script finishes, you **must reboot** the Raspberry Pi to apply the user group changes (giving you permission to read the USB radio) and to start the auto-boot services.
```bash
sudo reboot
```

After rebooting:
- The backend server will automatically start silently in the background (via systemd).
- The Raspberry Pi desktop will load, and a Chromium browser will automatically open in fullscreen (kiosk) mode, displaying the dashboard.

---

### 🌐 Accessing the Dashboard Remotely (via Ngrok)

If you need to view the Ground Station from a different network (e.g. sharing the live dashboard with judges or team members far away), you can use `ngrok` to create a secure public URL.

#### 1. Install Ngrok
Open a new terminal on the Pi and install ngrok via apt:
```bash
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
  | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" \
  | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update
sudo apt install ngrok
```

#### 2. Authenticate
Sign up for a free account at [ngrok.com](https://ngrok.com/) and find your Authtoken on the dashboard. Add it to your Pi:
```bash
ngrok config add-authtoken YOUR_AUTHTOKEN_HERE
```

#### 3. Expose the Server
Because the Daedalus server runs on port `8080`, simply run:
```bash
ngrok http 8080
```
Ngrok will display a screen with a "Forwarding" URL (e.g., `https://a1b2c3d4.ngrok-free.app`). Send this link to anyone, and they will be able to view the live dashboard directly from their phones or laptops!

*(Note: Ngrok will stop if you close the terminal. Keep it running during the mission if remote viewing is needed).*

---

### ⚙️ Managing the Background Service

The setup script creates a shortcut tool called `gcs` to easily control the background server:

```bash
gcs start      # Start the backend manually
gcs stop       # Stop the backend
gcs restart    # Restart the backend (useful after a git pull)
gcs status     # Check if the backend is running
gcs logs       # View the live system logs for the backend
gcs open       # Open the dashboard in a browser window manually
```

### Re-running setup
The setup script is safe to run multiple times. If you download new code changes, apply them easily:
```bash
git pull
sudo bash scripts/setup-pi.sh
gcs restart
```

---

## Project Structure

```
DDL-JS/
├── main.py                  # Backend server (FastAPI + serial)
├── requirements.txt         # Python dependencies
├── telemetry_config.json    # Telemetry field definitions (CSV column order)
├── cansat_2023_simp.csv     # Simulation pressure data
├── scripts/
│   ├── setup-pi.sh          # Raspberry Pi one-command installer
│   └── start-kiosk.sh       # Kiosk browser launcher (called by autostart)
└── ui/
    ├── index.html           # Main dashboard
    ├── cmd.html             # Standalone command panel (/cmd)
    ├── app.js               # Dashboard logic
    ├── styles.css           # Styles
    └── sw.js                # Service worker (offline tile cache)
```

---

## Commands Reference

All commands are sent via the Quick Command dropdown or the manual input box.

| Command | Description |
|---|---|
| `CX,ON` / `CX,OFF` | Enable / disable telemetry transmission |
| `CAL` | Calibrate altimeter (zero reference at current altitude) |
| `RESET` | Software reset the payload |
| `SIM,ENABLE` | Arm simulation mode |
| `SIM,ACTIVATE` | Start simulation (requires ENABLE first) |
| `SIM,DISABLE` | Exit simulation mode |
| `SIMP,<pa>` | Feed simulated pressure value (Pa) |
| `SET,MAIN_ALT,<m>` | Set main chute deployment altitude (m) |
| `SET,APOGEE_ALT,<m>` | Set apogee detection altitude (m) |
| `SET,TX_RATE,<hz>` | Set telemetry transmit rate |
| `MEC,PL,ON` / `OFF` | Payload release servo open / close |
| `MEC,INS,ON` / `OFF` | Instrument bay servo open / close |
| `MEC,PAR,CW` / `ACW` / `OFF` | Parachute spin motor CW / CCW / stop |
| `SERVO,A,<0-180>` | Direct servo A angle |
| `SERVO,B,<0-180>` | Direct servo B angle |
| `CAL,TOF,<mm>` | Calibrate VL53L1X ToF sensor (distance in mm) |
| `CAL,MAG,RESET` | Reset magnetometer calibration |
