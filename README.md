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

If no radio is connected, click **Run Sim** in the UI to generate dummy telemetry.

---

## Raspberry Pi Setup

One command installs everything and configures auto-start:

```bash
git clone https://github.com/Crazyexs/DDL-JS.git
cd DDL-JS
git checkout raspberry-pi
sudo bash scripts/setup-pi.sh
sudo reboot
```

After reboot the backend starts automatically (systemd) and the browser opens
in kiosk mode when the desktop loads.

### What the setup script does

| Step | What happens |
|---|---|
| System packages | Installs `chromium-browser`, `python3-venv`, `unclutter`, `curl` |
| Python venv | Creates `venv/` and installs `requirements.txt` |
| systemd service | `daedalus-gcs.service` — starts backend at boot, restarts on crash |
| Kiosk autostart | XDG + LXDE autostart entries launch Chromium in kiosk mode after login |
| Serial access | Adds user to `dialout` group for XBee radio access |
| `gcs` tool | Installs `/usr/local/bin/gcs` for easy management |

### Managing the service

```bash
gcs start      # start the backend
gcs stop       # stop the backend
gcs restart    # restart the backend
gcs status     # show service status
gcs logs       # live log stream (Ctrl+C to exit)
gcs open       # open dashboard in browser
```

Or with systemctl directly:

```bash
sudo systemctl start  daedalus-gcs
sudo systemctl stop   daedalus-gcs
sudo systemctl status daedalus-gcs
journalctl -u daedalus-gcs -f
```

### Accessing the dashboard

| From | URL |
|---|---|
| On the Pi | `http://127.0.0.1:8080` |
| Another device on same network | `http://<pi-ip>:8080` |
| Remote (via ngrok) | Run `ngrok http 8080` in a terminal |

### Re-running setup

The setup script is idempotent — safe to run again after a `git pull`:

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
| `/dummy.on` / `/dummy.off` | Start / stop local dummy data (GCS only) |
