import uvicorn
import socket
import random
import math

# main.py — DAEDALUS GS (Consolidated, clean)

import os
import sys
import json
import asyncio
import logging
import subprocess
from logging.handlers import RotatingFileHandler
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Optional, Set, List

import serial
from serial import SerialException
import serial.tools.list_ports
import serial_asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from datetime import datetime, timezone

# ===================== CONFIGURATION =====================
# This is the team ID number used for the competition.
TEAM_ID = 1043

# This is the default USB port the computer uses to talk to the radio.
# On Windows it is usually "COM3", "COM4", etc.
# On Linux/Mac it looks like "/dev/ttyUSB0".
DEFAULT_PORT = "COM3"

# This is the speed of the connection. Both the radio and computer must match this number.
DEFAULT_BAUD = 115200

# Setting this to True means this Python program handles the connection to the radio.
# If False, the web browser tries to handle it directly (not recommended here).
USE_SERVER_SERIAL = True

# These lines set up where the program looks for files.
# It creates folders for 'data' (CSV files), 'logs', and 'ui' (website files) if they don't exist.
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
UI_DIR = ROOT_DIR / "ui"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
UI_DIR.mkdir(parents=True, exist_ok=True)

# This is the name of the CSV file where we save flight data.
# It looks like: Flight_1043.csv
CSV_CURRENT = DATA_DIR / f"Flight_{TEAM_ID:04}.csv"

# A list of common connection speeds to choose from.
BAUD_PRESETS = [9600, 19200, 38400, 57600, 115200, 230400, 250000, 460800, 921600]

# ===================== TELEMETRY CONFIG (Dynamic Loading) =====================
# We load the structure of the CSV from 'telemetry_config.json'
# This allows you to change the order of columns without changing the code.
def load_telemetry_config():
    config_path = ROOT_DIR / "telemetry_config.json"
    if not config_path.exists():
        # Fallback default if file is missing
        print("Warning: telemetry_config.json not found, using default.")
        return [
            { "csv_header": "TEAM_ID", "internal_key": "team_id", "type": "int" },
            { "csv_header": "MISSION_TIME", "internal_key": "mission_time", "type": "str" },
            # ... (shortened fallback for safety, but ideally the file always exists)
        ]
    with open(config_path, "r") as f:
        return json.load(f)

TELEMETRY_CONFIG = load_telemetry_config()

# Build the CSV Header string dynamically from the config
# e.g. "TEAM_ID,MISSION_TIME,..."
CSV_HEADER = ",".join([item.get("csv_header", "") for item in TELEMETRY_CONFIG])

# ===================== LOGGING (Keeping records) =====================
# This sets up a system to save important messages to a file named 'ground.jsonl'.
# It also prints them to the screen so you can see what's happening.
logger = logging.getLogger("gs")
logger.setLevel(logging.INFO)
file_h = RotatingFileHandler(LOG_DIR / "ground.jsonl", maxBytes=5_000_000, backupCount=5)
file_h.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(file_h)
console = logging.StreamHandler()
console.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(message)s'))
logger.addHandler(console)

def log_json(**kw):
    """Helper function to save a log message as structured JSON data."""
    logger.info(json.dumps(kw, ensure_ascii=False))

# ===================== DATA MODELS (Structure of data) =====================
class SerialCfg(BaseModel):
    """Settings for the serial connection."""
    port: str = Field(default=DEFAULT_PORT)
    baud: int = Field(default=DEFAULT_BAUD)

class CommandBody(BaseModel):
    """Structure for a command sent from the website."""
    # The command string, like "CX,ON" or "ST,GPS".
    # The backend will automatically add "CMD,1043," to the front later.
    cmd: str

class IngestBody(BaseModel):
    """Structure for receiving raw data lines directly."""
    line: str

class Telemetry(BaseModel):
    """
    The structure of a single packet of data from the CanSat.
    NOTE: 'internal_key' in telemetry_config.json MUST match these field names.
    """
    team_id: int = 0
    mission_time: str = "00:00:00"
    packet_count: int = 0
    mode: str = "F"
    state: str = "BOOT"
    altitude_m: float = 0.0
    temperature_c: float = 0.0
    pressure_kpa: float = 0.0
    voltage_v: float = 0.0
    current_a: float = 0.0
    gyro_r_dps: float = 0.0
    gyro_p_dps: float = 0.0
    gyro_y_dps: float = 0.0
    accel_r_dps2: float = 0.0
    accel_p_dps2: float = 0.0
    accel_y_dps2: float = 0.0
    gps_time: str = "00:00:00"
    gps_altitude_m: float = 0.0
    gps_lat: float = 0.0
    gps_lon: float = 0.0
    gps_sats: int = 0
    cmd_echo: str = "—"
    
    # Optional extra data
    heading: Optional[float] = None
    
    # Extra info added by the Ground Station
    gs_ts_utc: str
    gs_rx_count: int
    gs_loss_total: int
    gs_raw_line: Optional[str] = None

# ===================== GLOBAL STATE (Program Memory) =====================
@dataclass
class GSState:
    """Stores the current status of the Ground Station."""
    cfg: SerialCfg = field(default_factory=SerialCfg) # Current connection settings
    rx_count: int = 0           # Total packets received
    loss_count: int = 0         # Total packets lost
    last_pkt: Optional[int] = None # The ID number of the last packet we saw
    csv_ready: bool = False     # Is the CSV file ready to be written to?
    last_cmd: str = "—"         # The last command we sent

state = GSState()
ring: Deque[str] = deque(maxlen=10_000)   # Keeps the last 10,000 log messages in memory
ws_clients: Set[WebSocket] = set()        # A list of all web browsers currently connected
uplink_q: asyncio.Queue[str] = asyncio.Queue() # A queue (line) of commands waiting to be sent

_serial_transport = None
_serial_writer_lock = asyncio.Lock()

def ensure_csv_header():
    """Checks if the CSV file exists. If not, creates it and adds the header row."""
    if not CSV_CURRENT.exists():
        CSV_CURRENT.write_text(CSV_HEADER + "\r\n", encoding="utf-8", newline="\r\n")
    state.csv_ready = True

ensure_csv_header()

# ===================== SERIAL COMMUNICATION (Talking to Hardware) =====================
import threading
import time

# These variables help share the serial connection safely between different parts of the program.
_serial_port: Optional[serial.Serial] = None
_serial_lock = threading.Lock()
_stop_event = threading.Event()

def serial_read_thread_target(loop):
    """
    This function runs in the background (a separate thread).
    Its job is to:
    1. Connect to the radio (serial port).
    2. Listen for incoming data constantly.
    3. Send any received data to the main program to be processed.
    """
    global _serial_port
    
    log_json(event="serial_thread_start")

    while not _stop_event.is_set():
        # 1. Try to Connect
        if _serial_port is None:
            try:
                # Check if the selected port actually exists
                available_ports = [p.device for p in serial.tools.list_ports.comports()]
                if state.cfg.port not in available_ports:
                    # If not found, log an error and wait 5 seconds before trying again
                    log_json(level="error", event="port_not_found", port=state.cfg.port, available=available_ports)
                    time.sleep(5)
                    continue

                log_json(event="serial_connecting", port=state.cfg.port, baud=state.cfg.baud)
                ser = serial.Serial(state.cfg.port, state.cfg.baud, timeout=1)
                
                # Safely save the connection object
                with _serial_lock:
                    _serial_port = ser
                log_json(event="serial_connected", port=state.cfg.port)
            except SerialException as e:
                msg = str(e)
                if "Access is denied" in msg:
                    print(f"\n[!!!] SERIAL ERROR: Access Denied on {state.cfg.port}. Close other apps (VSCode, CoolTerm)!\n")
                log_json(level="warn", event="serial_open_failed", port=state.cfg.port, error=msg)
                time.sleep(2)
                continue
            except Exception as e:
                log_json(level="warn", event="serial_open_failed", port=state.cfg.port, error=str(e))
                time.sleep(2)
                continue

        # 2. Read Loop (Listen for data)
        try:
            if _serial_port and _serial_port.is_open:
                # Read a line of text from the serial port
                # timeout=1 ensures we don't get stuck here forever if there is no data
                line_bytes = _serial_port.readline()
                if line_bytes:
                    try:
                        # Convert bytes to a string and remove whitespace
                        line = line_bytes.decode(errors="ignore").rstrip("\r\n")
                        if line:
                            # Send the line to the main program loop to be handled
                            asyncio.run_coroutine_threadsafe(handle_telemetry_line(line), loop)
                    except Exception:
                        pass
            else:
                # If connection is lost, clean up
                with _serial_lock:
                    _serial_port = None
                time.sleep(1)

        except Exception as e:
            # If any error happens during reading, log it and try to reconnect
            log_json(level="error", event="serial_read_error", error=str(e))
            with _serial_lock:
                if _serial_port:
                    try:
                        _serial_port.close()
                    except:
                        pass
                    _serial_port = None
            time.sleep(1)

    # Cleanup when the program stops
    with _serial_lock:
        if _serial_port:
            _serial_port.close()
    log_json(event="serial_thread_stop")

async def serial_writer_worker():
    """
    This function runs constantly in the background.
    Its job is to wait for commands in the queue and send them to the radio.
    """
    while True:
        # Wait for a command to appear in the queue
        cmd = await uplink_q.get()
        try:
            # Convert string to bytes and add a newline character
            data = (cmd + "\r\n").encode()
            
            wrote = False
            # Use the lock to make sure we don't conflict with the reading thread
            with _serial_lock:
                if _serial_port and _serial_port.is_open:
                    _serial_port.write(data)
                    _serial_port.flush() # Ensure data is sent immediately
                    wrote = True
            
            if wrote:
                log_json(subsystem="uplink", sent=cmd)
                ring.append(json.dumps({"uplink": cmd}))
            else:
                # If not connected, warn the user
                log_json(level="warn", event="uplink_dropped_no_serial", cmd=cmd)
                await broadcast_ws({"type": "error", "message": f"UPLINK FAILED: Serial not connected."})

        except Exception as e:
            log_json(level="error", event="uplink_error", error=str(e), cmd=cmd)
            await broadcast_ws({"type": "error", "message": f"UPLINK ERROR: {e}"})

# ===================== TELEMETRY PIPELINE (Processing Data) =====================
def now_utc_iso() -> str:
    """Returns the current time in UTC as a string."""
    return datetime.now(timezone.utc).isoformat()

async def broadcast_ws(payload: dict):
    """Sends a JSON message to all connected web browsers."""
    text = json.dumps(payload)
    dead = []
    
    # Create a list of connected clients for logging
    client_list = []
    for ws in ws_clients:
        c = ws.client
        if c:
            client_list.append(f"{c.host}:{c.port}")
        else:
            client_list.append("unknown")
            
    log_json(event="ws_broadcast", clients=client_list)
    
    # Send the message to each client
    for ws in list(ws_clients):
        try:
            await ws.send_text(text)
        except Exception:
            # If sending fails, assume the client disconnected
            dead.append(ws)
    
    # Remove disconnected clients
    for ws in dead:
        ws_clients.discard(ws)

async def handle_telemetry_line(raw: str):
    """
    This is the core function that handles each line of data received.
    It uses 'TELEMETRY_CONFIG' to know which column is which.
    """
    parts = [p.strip() for p in raw.split(",")]
    
    # We check if we have enough columns based on our config
    # Note: Optional fields at the end might be missing, so we allow slightly fewer.
    min_required = len([x for x in TELEMETRY_CONFIG if not x.get("optional", False)])
    
    if len(parts) < min_required:
        ring.append(json.dumps({"bad_line": raw}))
        log_json(level="warn", event="telemetry_short", len=len(parts), required=min_required)
        return

    # 1) Parse data dynamically using the config
    parsed_data = {}     # Holds the values for the Telemetry object (e.g., altitude_m=50.2)
    clean_parts = []     # Holds the clean strings for the CSV file
    
    # Loop through every column defined in telemetry_config.json
    for i, cfg in enumerate(TELEMETRY_CONFIG):
        key = cfg.get("internal_key") # e.g., "altitude_m"
        dtype = cfg.get("type")       # e.g., "float"
        
        # Get the raw string value from the CSV line
        val_str = parts[i] if i < len(parts) else ""
        val_str = val_str.strip()
        
        # SKIP columns (like empty spaces in the spec)
        if dtype == "skip":
            clean_parts.append("") # Keep the empty space in the saved CSV
            continue
            
        # Convert the string to the correct type (int/float/str)
        value = None
        clean_str = val_str # Default for string types
        
        try:
            if dtype == "int":
                value = int(val_str) if val_str else 0
                clean_str = str(value)
            elif dtype == "float":
                value = float(val_str) if val_str else 0.0
                # Format floats nicely for the CSV file (2 decimal places usually)
                if key and ("lat" in key or "lon" in key): 
                    clean_str = f"{value:.5f}" # GPS needs more precision
                elif key and "pressure" in key:
                    clean_str = f"{value:.3f}"
                else:
                    clean_str = f"{value:.2f}"
            else: # string
                value = val_str
                clean_str = val_str
        except ValueError:
            # If conversion fails (e.g. text in a number field), use defaults
            if dtype == "int": value = 0
            elif dtype == "float": value = 0.0
            else: value = ""
            clean_str = str(value)

        # Save to our parsed data dictionary (if it maps to a Telemetry field)
        if key:
            parsed_data[key] = value
            
        # Add to the clean CSV list
        clean_parts.append(clean_str)

    # 2) Create the Telemetry object
    # We add the Ground Station calculated fields here
    parsed_data["gs_ts_utc"] = now_utc_iso()
    parsed_data["gs_rx_count"] = state.rx_count + 1
    parsed_data["gs_loss_total"] = state.loss_count
    parsed_data["gs_raw_line"] = raw
    
    # This '**parsed_data' magic passes the dictionary as arguments
    tel = Telemetry(**parsed_data)

    # 3) Reconstruct the CLEAN CSV line
    clean_csv = ",".join(clean_parts)

    # 4) Append to the CSV file
    if state.csv_ready:
        with CSV_CURRENT.open("a", encoding="utf-8", newline="") as f:
            f.write(clean_csv + "\r\n")

    # 5) Update counters
    state.rx_count += 1
    # Try to find packet count to check for loss
    # We look for 'packet_count' in our parsed data
    pkt = parsed_data.get("packet_count", 0)
    
    if state.last_pkt is not None and pkt > state.last_pkt + 1:
        state.loss_count += (pkt - state.last_pkt - 1)
    state.last_pkt = pkt

    # 6) Send to UI
    payload = tel.dict()
    payload['gs_raw_line'] = raw
    await broadcast_ws(payload)
    ring.append(json.dumps({"telemetry": payload}))

# ===================== SIMULATION MODE (Testing) =====================
async def sim_sender(file_path: Path):
    """
    Reads a file with pressure data and sends it to the CanSat to simulate flight.
    """
    # Send commands to enable simulation mode
    await uplink_q.put(f"CMD,{TEAM_ID:04},SIM,ENABLE")
    await asyncio.sleep(0.2)
    await uplink_q.put(f"CMD,{TEAM_ID:04},SIM,ACTIVATE")
    await asyncio.sleep(0.2)

    if not file_path.exists():
        log_json(level="error", event="sim_file_missing", file=str(file_path)); return

    # Read the file line by line
    with file_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            # Send pressure command (SIMP)
            await uplink_q.put(f"CMD,{TEAM_ID:04},SIMP,{s}")
            # Wait 1 second between sends (to match 1 Hz rate)
            await asyncio.sleep(1.0)
    log_json(event="sim_complete", file=str(file_path))

# ===================== DUMMY DATA GENERATOR (No Hardware Needed) =====================
dummy_task: Optional[asyncio.Task] = None
dummy_state = {
    "packet": 0,
    "lat": 18.788,
    "lon": 98.985,
    "last_alt": 0.0,
}

def hms_from_seconds(s: float) -> str:
    """Converts seconds into HH:MM:SS format."""
    s = int(s)
    hours = s // 3600
    minutes = (s % 3600) // 60
    seconds = s % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def generate_dummy_telemetry_line() -> str:
    """Creates a fake CSV telemetry line for testing the UI."""
    dummy_state["packet"] += 1
    pkt = dummy_state["packet"]
    
    # Move GPS slightly
    dummy_state["lat"] += (random.random() - 0.5) * 0.0002
    dummy_state["lon"] += (random.random() - 0.5) * 0.0002
    
    # Simulate altitude change (up and down)
    altitude = 150 + math.sin(pkt / 30) * 120 + (random.random() - 0.5) * 5
    temp = 25 - (altitude / 100)
    voltage = 12.6 - (pkt / 500)
    current = 0.5 + (random.random() - 0.5) * 0.2
    
    mission_time = hms_from_seconds(pkt)
    
    # Determine flight state based on altitude
    state = 'LAUNCH_PAD'
    if altitude > 20:
        if altitude > dummy_state["last_alt"]:
            state = 'ASCENT'
        else:
            state = 'DESCENT'
    dummy_state["last_alt"] = altitude

    # Dictionary of all current dummy values
    val_map = {
        "team_id": str(TEAM_ID),
        "mission_time": mission_time,
        "packet_count": str(pkt),
        "mode": 'F',
        "state": state,
        "altitude_m": f"{altitude:.2f}",
        "temperature_c": f"{temp:.2f}",
        "pressure_kpa": f"{101.325 * math.pow(1 - 2.25577e-5 * altitude, 5.25588):.3f}",
        "voltage_v": f"{voltage:.2f}",
        "current_a": f"{current:.3f}",
        "gyro_r_dps": f"{(random.random() - 0.5) * 20:.3f}",
        "gyro_p_dps": f"{(random.random() - 0.5) * 20:.3f}",
        "gyro_y_dps": f"{180 + (random.random() - 0.5) * 40:.3f}",
        "accel_r_dps2": f"{(random.random() - 0.5) * 2:.3f}",
        "accel_p_dps2": f"{(random.random() - 0.5) * 2:.3f}",
        "accel_y_dps2": f"{9.8 + (random.random() - 0.5):.3f}",
        "gps_time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "gps_altitude_m": f"{altitude + 10:.2f}",
        "gps_lat": f"{dummy_state['lat']:.4f}",
        "gps_lon": f"{dummy_state['lon']:.4f}",
        "gps_sats": str(random.randint(8, 12)),
        "cmd_echo": "CMD_OK" if pkt % 10 != 0 else "CX,ON",
        "heading": f"{(pkt * 5) % 360:.2f}",
    }

    # Build the line based on the config order
    line_parts = []
    for cfg in TELEMETRY_CONFIG:
        key = cfg.get("internal_key")
        dtype = cfg.get("type")
        
        if dtype == "skip":
            line_parts.append("")
        elif key in val_map:
            line_parts.append(val_map[key])
        else:
            # Default fallback for missing keys
            line_parts.append("0")

    return ",".join(line_parts)

async def dummy_data_sender():
    """Generates and processes dummy data once per second."""
    log_json(event="dummy_data_started")
    while True:
        line = generate_dummy_telemetry_line()
        await handle_telemetry_line(line)
        await asyncio.sleep(1)


# ===================== FASTAPI APPLICATION SETUP =====================
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    This function runs when the server starts and stops.
    STARTUP: It starts the background thread for serial reading and the task for writing.
    SHUTDOWN: It cleans up and closes the connections.
    """
    # Startup logic
    log_json(event="startup", team=TEAM_ID, server_serial=USE_SERVER_SERIAL)
    ensure_csv_header()
    
    tasks = []
    serial_thread = None

    if USE_SERVER_SERIAL:
        # Start Serial Reader Thread (this needs to be a thread because reading is blocking)
        loop = asyncio.get_running_loop()
        serial_thread = threading.Thread(target=serial_read_thread_target, args=(loop,), daemon=True)
        serial_thread.start()
        
        # Start Serial Writer Task (this can be an async task)
        tasks.append(asyncio.create_task(serial_writer_worker()))
    
    # Keep the WebSocket connection alive with a ping every 10 seconds
    async def ws_ping():
        while True:
            await asyncio.sleep(10)
            await broadcast_ws({"type": "ping"})
            
    tasks.append(asyncio.create_task(ws_ping()))
    
    yield # The application runs here
    
    # Shutdown logic
    log_json(event="shutdown")
    
    # Signal thread to stop
    _stop_event.set()
    if serial_thread:
        serial_thread.join(timeout=2)
        
    for t in tasks:
        t.cancel()

app = FastAPI(title="CanSat Ground Station (Python)", lifespan=lifespan)


@app.post("/api/dummy/start")
async def api_dummy_start():
    """Starts generating fake data."""
    global dummy_task
    if dummy_task and not dummy_task.done():
        return {"ok": False, "message": "Dummy task already running"}
    dummy_state["packet"] = 0
    dummy_task = asyncio.create_task(dummy_data_sender())
    return {"ok": True}

@app.post("/api/dummy/stop")
async def api_dummy_stop():
    """Stops generating fake data."""
    global dummy_task
    if dummy_task and not dummy_task.done():
        dummy_task.cancel()
        log_json(event="dummy_data_stopped")
        return {"ok": True}
    return {"ok": False, "message": "Dummy task not running"}

# ===================== API ENDPOINTS (Web Interface Connects Here) =====================

# ---- Health / Logs ----
@app.get("/api/health")
async def api_health():
    """Returns the current status of the system."""
    return {
        "serial": {"port": state.cfg.port, "baud": state.cfg.baud, "server_serial": USE_SERVER_SERIAL},
        "csv": str(CSV_CURRENT),
        "rx": {"received": state.rx_count, "lost": state.loss_count},
        "last_cmd": state.last_cmd,
    }

@app.get("/api/logs")
async def api_logs(n: int = 500):
    """Returns the last N log messages."""
    n = max(1, min(n, 5000))
    return list(ring)[-n:]

# ---- Serial config / ports ----
@app.get("/api/serial/ports")
async def api_serial_ports():
    """Lists all available USB serial ports."""
    ports = [{"port": p.device, "info": f"{p.description} {p.hwid}"} for p in serial.tools.list_ports.comports()]
    return {"ports": ports}

@app.get("/api/serial/bauds")
async def api_serial_bauds():
    """Lists allowed connection speeds."""
    return {"presets": BAUD_PRESETS}

@app.get("/api/serial/config")
async def api_serial_get():
    """Gets current serial settings."""
    return state.cfg.dict()

@app.post("/api/serial/config")
async def api_serial_set(cfg: SerialCfg):
    """Updates serial settings and reconnects."""
    if cfg.baud not in BAUD_PRESETS:
        raise HTTPException(400, detail="baud not allowed")
    state.cfg = cfg
    log_json(event="cfg_changed", port=cfg.port, baud=cfg.baud)
    
    # Force reconnect by closing current port
    global _serial_port
    with _serial_lock:
        if _serial_port and _serial_port.is_open:
            try:
                _serial_port.close()
            except:
                pass
            _serial_port = None
            
    return {"ok": True}

# ---- Command uplink ----
@app.post("/api/command")
async def api_command(body: CommandBody):
    """
    Receives a command from the website (e.g., "CX,ON"),
    adds the Team ID prefix, and queues it to be sent.
    """
    # body.cmd is something like "CX,ON"
    uplink = f"CMD,{TEAM_ID:04},{body.cmd.strip()}"
    state.last_cmd = uplink
    await uplink_q.put(uplink)
    return {"ok": True, "sent": uplink}

# ---- Simulation start ----
@app.post("/api/sim/start")
async def api_sim_start(file: Optional[str] = None):
    """Starts reading a simulation file."""
    path = Path(file or "sim_pressure.csv")
    asyncio.create_task(sim_sender(path))
    return {"ok": True, "running": True, "file": str(path)}

# ---- Browser → Server telemetry ingest ----
@app.post("/api/ingest")
async def api_ingest(body: IngestBody):
    """Allows the browser to send data to the backend (used for WebSerial)."""
    line = body.line.strip()
    if not line:
        raise HTTPException(400, detail="empty")
    await handle_telemetry_line(line)
    return {"ok": True}

# ---- CSV folder open / save-now ----
def _open_folder(path: Path):
    """Opens a folder in the operating system's file explorer."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # Windows
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)]) # Mac
        else:
            subprocess.Popen(["xdg-open", str(path)]) # Linux
        return True, None
    except Exception as e:
        return False, str(e)

@app.get("/api/csv/open-folder")
async def api_csv_open_folder():
    """API to open the data folder."""
    if not DATA_DIR.exists():
        return JSONResponse(status_code=404, content={"ok": False, "error": "Folder not found", "path": str(DATA_DIR)})
    ok, err = _open_folder(DATA_DIR)
    if not ok:
        return JSONResponse(status_code=500, content={"ok": False, "error": err, "path": str(DATA_DIR)})
    return {"ok": True, "path": str(DATA_DIR)}

@app.post("/api/csv/save-now")
async def api_csv_save_now(payload: dict = Body(...)):
    """
    Force saves a list of rows to a new CSV file.
    Useful if the browser has data that the backend missed.
    """
    rows: List[str] = payload.get("rows") or []
    if not rows:
        return JSONResponse(status_code=400, content={"ok": False, "error": "no rows"})

    # Try to find the Team ID in the data
    team_id = f"{TEAM_ID:04}"
    for line in rows:
        p0 = (line.split(",", 1)[0] or "").strip()
        if p0.isdigit():
            team_id = p0.zfill(4)
            break

    # Create a unique filename so we don't overwrite existing files
    out_path = DATA_DIR / f"Flight_{team_id}.csv"
    i = 1
    while out_path.exists():
        out_path = DATA_DIR / f"Flight_{team_id}({i}).csv"
        i += 1

    content = CSV_HEADER + "\r\n" + "\r\n".join(rows) + "\r\n"
    out_path.write_text(content, encoding="utf-8", newline="\r\n")
    return {"ok": True, "path": str(out_path)}

# ---- WebSocket Endpoint ----
@app.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket):
    """
    Manages the live connection to the browser.
    When a browser connects, it adds it to the list to receive updates.
    """
    await ws.accept()
    ws_clients.add(ws)
    
    c = ws.client
    c_info = f"{c.host}:{c.port}" if c else "unknown"
    log_json(event="ws_connected", client=c_info)
    try:
        while True:
            await ws.receive_text()   # Keep waiting for messages (detects disconnects)
    except WebSocketDisconnect:
        pass
    finally:
        # Cleanup when disconnected
        ws_clients.discard(ws)
        c = ws.client
        c_info = f"{c.host}:{c.port}" if c else "unknown"
        log_json(event="ws_disconnected", client=c_info)

# ---- Static UI ----
# Serve the 'ui' folder as a website
app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")

if __name__ == "__main__":
    # This part runs when you execute 'python main.py'
    host = "0.0.0.0"
    port = 8000

    try:
        # Try to find the actual IP address of this computer
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            local_ip = s.getsockname()[0]
        except Exception:
            local_ip = "127.0.0.1"
        finally:
            s.close()
    except Exception:
        local_ip = "127.0.0.1"

    print("="*50)
    print("Daedalus Ground Station")
    print(f"Local UI: http://localhost:{port}")
    print("Remote Access: Run 'ngrok http 8000' in a new terminal")
    print("="*50)

    print("Available serial ports:")
    ports = serial.tools.list_ports.comports()
    for port_info, desc, hwid in sorted(ports):
        print(f"- {port_info}: {desc} [{hwid}]")
    print("="*50)

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    uvicorn.run(app, host=host, port=port, log_level="info")
