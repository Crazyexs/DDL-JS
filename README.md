# Daedalus Ground Station — Team #1043

Real-time telemetry dashboard for CanSat Team #1043. FastAPI backend + browser-based frontend.

---

## Deep Installation Guide

Follow these step-by-step instructions to download, install, and run the Ground Control Station (GCS) on your computer.

### Prerequisites

Before you begin, you must have **Python 3.9** (or newer) installed on your computer. 
- **Windows**: Download Python from [python.org/downloads](https://www.python.org/downloads/). *Crucial Step:* During installation, make sure you check the box that says **"Add Python to PATH"** before clicking Install.
- **macOS**: Install via Homebrew (`brew install python`) or download from python.org.
- **Linux**: Usually pre-installed, or install via `sudo apt install python3 python3-venv`.

You also need **Git** installed to download the code. Download from [git-scm.com](https://git-scm.com/downloads).

---

### Step-by-Step: Windows

**1. Open Command Prompt**
Press `Win + R`, type `cmd`, and press Enter.

**2. Download the Code**
Run the following command to clone the repository to your computer:
```bat
git clone https://github.com/Crazyexs/DDL-JS.git
```

**3. Enter the Project Folder**
```bat
cd DDL-JS
```

**4. Create a Virtual Environment**
This creates an isolated environment so the project's dependencies don't mess with your system Python:
```bat
python -m venv venv
```

**5. Activate the Virtual Environment**
You must run this command *every time* you open a new terminal to run the GCS:
```bat
venv\Scripts\activate
```
*(You will know it worked if you see `(venv)` at the start of your command prompt).*

**6. Install the Dependencies**
Download all the required libraries (like FastAPI and PySerial) automatically:
```bat
pip install -r requirements.txt
```

**7. Start the Server**
Run the FastAPI backend server:
```bat
python -m uvicorn main:app --host 0.0.0.0 --port 8080
```
The server is now running! Leave this Command Prompt window open.

---

### Step-by-Step: macOS & Linux

**1. Open Terminal**
Open your Terminal application.

**2. Download the Code**
Run the following command to clone the repository:
```bash
git clone https://github.com/Crazyexs/DDL-JS.git
```

**3. Enter the Project Folder**
```bash
cd DDL-JS
```

**4. Create a Virtual Environment**
```bash
python3 -m venv venv
```

**5. Activate the Virtual Environment**
You must run this command *every time* you open a new terminal to run the GCS:
```bash
source venv/bin/activate
```
*(You will know it worked if you see `(venv)` at the start of your command prompt).*

**6. Install the Dependencies**
```bash
pip install -r requirements.txt
```

**7. Start the Server**
Run the FastAPI backend server:
```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```
The server is now running! Leave this Terminal window open.

---

## Opening the Dashboard

Once the server is running (Step 7 above), open your preferred web browser (Google Chrome or Microsoft Edge recommended) and go to:

**[http://localhost:8080](http://localhost:8080)**

---

## Hardware & Serial Port Setup

You no longer need to edit the code to connect to your XBee radio! 

1. Plug your XBee USB radio adapter into your computer.
2. Open the dashboard in your browser (`http://localhost:8080`).
3. Look at the **Configuration Panel** on the left side of the screen.
4. Select the correct **COM Port** (Windows) or `/dev/` port (Mac/Linux) from the dropdown list.
5. Ensure the **Baud Rate** is set to `115200` (or whatever matches your XBee configuration).
6. Click **Connect**.

If you do not have a radio plugged in but still want to test the dashboard, you can click **Run Sim** or use the `/dummy.on` command in the quick commands list to generate fake telemetry.

---

## Project Structure

```
DDL-JS/
├── main.py                  # Backend server (FastAPI + serial)
├── requirements.txt         # Python dependencies
├── telemetry_config.json    # Telemetry field definitions (CSV column order)
├── cansat_2023_simp.txt     # Simulation pressure data
└── ui/
    ├── index.html           # Main dashboard
    ├── cmd.html             # Standalone command panel (/cmd)
    ├── app.js               # Dashboard logic
    ├── styles.css           # Styles
    └── sw.js                # Service worker (offline tile cache)
```

---

## Commands Reference

All commands are sent via the Quick Command dropdown or the manual input box in the dashboard.

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

---

## Raspberry Pi Setup

This section covers deploying the GCS on a Raspberry Pi with the KMR-1.44 SPI V2 (ST7735) status display and full auto-start on boot.

### Wiring the KMR-1.44 SPI V2 Screen

Connect the screen to the Raspberry Pi GPIO header as follows:

| Screen Pin | Raspberry Pi Pin | Description |
|---|---|---|
| VCC | Pin 2 or 4 (5V) | Power (use 5V for full brightness) |
| GND | Pin 6 (GND) | Ground |
| CS | Pin 24 (GPIO 8 / CE0) | SPI Chip Select |
| RESET | Pin 22 (GPIO 25) | Reset |
| A0 / DC | Pin 18 (GPIO 24) | Data / Command |
| SDA | Pin 19 (GPIO 10 / MOSI) | SPI Data |
| SCK | Pin 23 (GPIO 11 / SCLK) | SPI Clock |
| LED | Pin 12 (GPIO 18) | Backlight (software-controlled) |

If you connect LED directly to 3.3V instead of GPIO 18, open `oled/oled_daemon.py` and change `BACKLIGHT = 18` to `BACKLIGHT = None`.

### Enable SPI on the Pi

SPI must be enabled before the screen will work. Run this once:

```bash
sudo raspi-config
```

Go to: **3 Interface Options** → **I4 SPI** → **Yes** → Finish → Reboot.

### Pi Installation — One Command

After cloning the repository, run the setup script once. It handles everything automatically:

```bash
chmod +x scripts/setup-pi.sh
bash scripts/setup-pi.sh
```

Then reboot:

```bash
sudo reboot
```

After the reboot:
- The GCS server starts automatically in the background.
- Firefox opens `http://localhost:8080` automatically on desktop login.
- Your XBee radio is detected and connected automatically.
- The ST7735 screen starts displaying Pi stats automatically.

### What the Setup Script Does

The `scripts/setup-pi.sh` script performs four steps automatically:

1. Installs all Python dependencies into the virtual environment.
2. Enables the SPI interface in `/boot/firmware/config.txt` for the ST7735 screen.
3. Installs and enables `scripts/daedalus.service` as a systemd service so the GCS server starts on every boot.
4. Creates `~/.config/autostart/daedalus-browser.desktop` so Firefox opens the dashboard automatically on desktop login (with a 5-second delay to let the server start first).

### Managing the Service

| Command | What it does |
|---|---|
| `sudo systemctl status daedalus` | Check if the GCS is running |
| `journalctl -u daedalus -f` | Watch live logs |
| `sudo systemctl restart daedalus` | Restart the GCS |
| `sudo systemctl stop daedalus` | Stop the GCS |
| `sudo systemctl disable daedalus` | Disable auto-start on boot |

### Accessing the Dashboard from Another Device

Once the service is running, find the Pi's IP address:

```bash
hostname -I
```

Then open a browser on any device on the same Wi-Fi network and go to:

**http://<Pi-IP-address>:8080**

For example: `http://192.168.1.42:8080`

---

## Data Logging

The GCS saves every single byte received from the CanSat to a CSV file the moment it arrives, before any parsing or validation. This means no data is ever lost, even if a packet is malformed or incomplete.

- **Main log file:** `data/Flight_1043.csv`
- **Display control page:** `http://localhost:8080/display`

The CSV file is created automatically when the server starts. Each row in the file is exactly the raw string received from the CanSat over the radio, in the order it was received.

