# Daedalus Ground Station (Team #1043)

![Daedalus Logo](ui/assets/daedalus.png)

![Project Status](https://img.shields.io/badge/status-active-success)
![Python](https://img.shields.io/badge/python-3.8+-blue.svg)

**Daedalus Ground Station** is a comprehensive mission control interface designed for **CanSat Team #1043**. It provides real-time telemetry visualization, command uplink capabilities, and GPS tracking to monitor the payload during flight operations.

The system is built with a robust **Python FastAPI** backend for hardware communication and data logging, paired with a responsive **web-based frontend** for data visualization.

---

## Features

*   **Real-time Telemetry Dashboard:** Live monitoring of Altitude, Temperature, Pressure, Voltage, Current, and IMU data (Gyro/Accel).
*   **GPS Tracking:** Interactive map integration using Leaflet.js to track the payload's location.
*   **Command Uplink:** Send commands (e.g., `CX,ON`, `SIM,ENABLE`) directly to the CanSat via serial connection.
*   **Data Logging:**
    *   **Flight Data:** Automatically saves telemetry to CSV format (`data/Flight_1043.csv`).
    *   **System Logs:** Records operational events to JSONL (`logs/ground.jsonl`).
*   **Dynamic Configuration:** Flexible telemetry parsing defined in `telemetry_config.json`.
*   **Simulation Mode:** Built-in tools to replay flight data or generate dummy telemetry for testing and practice.

---

## Tech Stack

### Backend
*   **Language:** Python 3.8+
*   **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (with Uvicorn)
*   **Communication:** `pyserial`, `websockets`

### Frontend
*   **Core:** HTML5, CSS3, Vanilla JavaScript
*   **Visualization:**
    *   [ECharts](https://echarts.apache.org/) (Real-time charts)
    *   [Leaflet](https://leafletjs.com/) (Maps)

---

## Installation

To avoid common "command not found" errors, we run the commands using direct paths to the virtual environment (`venv`).

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Crazyexs/DDL-JS.git
    cd DDL-JS
    ```

2.  **Set up a Virtual Environment:**
    ```bash
    # Windows
    python -m venv venv

    # macOS/Linux
    python3 -m venv venv
    ```

3.  **Install Dependencies:**
    We recommend using the absolute path to the virtual environment's pip:
    ```bash
    # Windows
    .\venv\Scripts\pip install -r requirements.txt

    # macOS/Linux
    ./venv/bin/pip install -r requirements.txt
    ```

---

## Usage

1.  **Connect the Radio Transceiver:**
    Plug your LoRa/XBee radio into the USB port.

2.  **Start the Server:**
    Run the server using the absolute path to the virtual environment's uvicorn to prevent errors.
    ```bash
    # Windows
    .\venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8080
    
    # macOS/Linux
    ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
    ```

3.  **Access the Dashboard:**
    Open your web browser (Firefox recommended) and navigate to:
    > **http://localhost:8080**

4.  **Hardware & Serial Port Setup:**
    1. Look at the **Configuration Panel** on the left side of the screen.
    2. Select the correct **COM Port** (Windows) or `/dev/` port (Mac/Linux) from the dropdown list.
    3. Ensure the **Baud Rate** is set to `115200` (or whatever matches your XBee configuration).
    4. Click **Connect**.

5.  **Remote Access (Optional) with ngrok:**
    To make your Ground Station accessible over the internet, you can use [ngrok](https://ngrok.com/).

    *   **Run ngrok:** In a **new terminal window**, run:
        ```bash
        ngrok http 8080
        ```
    *   ngrok will provide a public URL (e.g., `https://xxxx-xxxx-xxxx-xxxx.ngrok-free.app`) that you can use to access your dashboard remotely.

6.  **Simulation (Optional):**
    If you don't have hardware connected, click the **Run Sim** button in the UI or use the `/dummy.on` command in the quick commands list to generate fake telemetry.

---

## Project Structure

```text
DDL-JS/
├── main.py                 # Core backend logic (Server, Serial, Logging)
├── requirements.txt        # Python dependencies
├── telemetry_config.json   # Telemetry parsing configuration
├── data/                   # Stores flight CSV data
├── logs/                   # Stores system operation logs
└── ui/                     # Web frontend source code
    ├── index.html          # Main dashboard layout
    ├── app.js              # Frontend logic
    ├── styles.css          # Styling
    └── assets/             # Images and icons
```

## API Endpoints

The backend exposes several endpoints for control and integration:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/command` | Queue a command for uplink to the CanSat. |
| `GET` | `/api/logs` | Retrieve the latest system logs. |
| `POST` | `/api/sim/start` | Start the pressure data simulation. |
| `POST` | `/api/dummy/start` | Enable internal dummy data generation. |
| `GET` | `/api/health` | Check system status (Serial connection, RX count). |

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

---

## Raspberry Pi Setup

This section covers deploying the GCS on a Raspberry Pi with full auto-start on boot.

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

---

## Data Logging

The GCS saves every single byte received from the CanSat to a CSV file the moment it arrives, before any parsing or validation. This means no data is ever lost, even if a packet is malformed or incomplete.

- **Main log file:** `data/Flight_1043.csv`

The CSV file is created automatically when the server starts. Each row in the file is exactly the raw string received from the CanSat over the radio, in the order it was received.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## Commercial Off-The-Shelf (COTS) Software

This project utilizes the following third-party software packages and libraries:

### Backend (Python)
*   **[FastAPI](https://fastapi.tiangolo.com/):** High-performance web framework for building APIs.
*   **[Uvicorn](https://www.uvicorn.org/):** Lightning-fast ASGI server implementation.
*   **[PySerial](https://pyserial.readthedocs.io/):** Python serial port access library for hardware communication.
*   **[Pydantic](https://docs.pydantic.dev/):** Data validation and settings management using Python type hints.
*   **[Aiofiles](https://github.com/Tinche/aiofiles):** File support for asyncio.
*   **[Python-Multipart](https://github.com/Kludex/python-multipart):** Streaming multipart parser for Python.

### Frontend (JavaScript)
*   **[ECharts](https://echarts.apache.org/):** A powerful, interactive charting and visualization library.
*   **[Leaflet.js](https://leafletjs.com/):** An open-source JavaScript library for mobile-friendly interactive maps.

### External Tools
*   **[ngrok](https://ngrok.com/):** A tool to expose a local web server to the internet (used for remote access).
