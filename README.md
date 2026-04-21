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

Then open **http://localhost:8080** in your browser.

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
| Linux | `/dev/ttyUSB0` |
| Windows | `COM3` |

If no radio is connected, click **Run Sim** in the UI to generate dummy telemetry.

---

## Raspberry Pi Setup

```bash
cd DDL-JS
bash scripts/setup-pi.sh
```

Then reboot. The ground station auto-starts in Firefox kiosk mode on boot.

---

## Project Structure

```
DDL-JS/
├── main.py                 # Backend server (FastAPI + serial)
├── requirements.txt        # Python dependencies
├── telemetry_config.json   # Telemetry field definitions
├── scripts/
│   └── setup-pi.sh         # Raspberry Pi auto-install script
└── ui/
    ├── index.html
    ├── app.js
    └── styles.css
```

---

## Commands Reference

All commands are sent via the **Quick Command** dropdown or the manual input box.

| Command | Description |
|---|---|
| `CX,ON` / `CX,OFF` | Enable / disable telemetry transmission |
| `CAL` | Calibrate altimeter (sets current altitude as ground reference) |
| `RESET` | Software reset the payload |
| `SIM,ENABLE` | Arm simulation mode |
| `SIM,ACTIVATE` | Start simulation (requires ENABLE first) |
| `SIM,DISABLE` | Exit simulation mode |
| `SIMP,<pa>` | Feed simulated pressure value (Pa) |
| `SET,MAIN_ALT,<m>` | Set main chute deployment altitude (m) |
| `MEC,PL,ON` / `OFF` | Payload release servo open / close |
| `MEC,INS,ON` / `OFF` | Instrument bay servo open / close |
| `MEC,PAR,CW` / `ACW` / `OFF` | Parachute spin motor CW / CCW / stop |
| `SERVO,A,<0-180>` | Direct servo A angle |
| `SERVO,B,<0-180>` | Direct servo B angle |
| `/dummy.on` / `/dummy.off` | Start / stop local dummy data (GCS only) |
