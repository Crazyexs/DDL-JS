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

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Crazyexs/DDL-JS.git
    cd DDL-JS
    ```

2.  **Set up a Virtual Environment (Recommended):**
    ```bash
    # Windows
    python -m venv venv
    venv\Scripts\activate

    # macOS/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

---

## Usage

1.  **Connect the Radio Transceiver:**
    Plug your LoRa/Serial radio into the USB port. Update the `DEFAULT_PORT` in `main.py` if necessary (default is `COM3` for Windows).

2.  **Start the Server:**
    ```bash
    # Windows
    .\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8080
    
    # Linux/Mac
    ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8080
    ```

3.  **Access the Dashboard:**
    Open your web browser and navigate to:
    > **http://localhost:8080**

4.  **Remote Access (Optional) with ngrok:**
    To make your Ground Station accessible over the internet, you can use [ngrok](https://ngrok.com/).

    *   **Installation:** Download ngrok from their [official website](https://ngrok.com/download) or install it via a package manager (e.g., Chocolatey on Windows: `choco install ngrok`).
    *   **Setup:** Follow ngrok's instructions to authenticate your client with your auth token.
    *   **Run ngrok:** In a **new terminal window**, run:
        ```bash
        ngrok http 8080
        ```
    *   ngrok will provide a public URL (e.g., `https://xxxx-xxxx-xxxx-xxxx.ngrok-free.app`) that you can use to access your dashboard remotely.

5.  **Simulation (Optional):**
    If you don't have hardware connected, click the **Run Sim** button in the UI or use the API to start the dummy data generator.

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