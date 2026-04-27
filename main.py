import uvicorn
import socket
import random
import math



import os
import re
import sys
import json
import csv
import asyncio
import logging
import subprocess
from logging.handlers import RotatingFileHandler
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Optional, Set, List

import aiofiles
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
# Team ID 
TEAM_ID = 1043

# This is the default USB port the computer uses to talk to the radio.
# On Windows it is usually "COM3", "COM4", etc.
# On Linux/Mac it looks like "/dev/ttyUSB0".
DEFAULT_PORT = "/dev/cu.usbserial-A50285BI"

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
# [REQ-64] Generate csv files of all sensor data
# [REQ-70] Display mission time, temperature, GPS, packet count, state
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

# Build the CSV Header string directly from the config (only what the CanSat sends)
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

class LogBody(BaseModel):
    """Structure for switching the active log file."""
    label: str

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
    yaw: float = 0.0
    tof: float = 0.0

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
    sim_enabled: bool = False   # Is the simulation mode enabled?
    # Active log label — empty string means default file (Flight_1043.csv)
    log_label: str = ""
    # KML auto-save: collect GPS points for Google Earth export
    kml_points: Deque = field(default_factory=lambda: deque(maxlen=3000))  # [{lat, lon, alt, state}]
    kml_max_alt: float = 0.0    # Track max altitude for KML metadata

state = GSState()

# ===================== KML AUTO-SAVE =====================
KML_CURRENT = DATA_DIR / f"Flight_{TEAM_ID:04}.kml"

def get_active_csv() -> Path:
    """Returns the CSV path for the current log session."""
    if state.log_label:
        return DATA_DIR / f"Flight_{TEAM_ID:04}_{state.log_label}.csv"
    return CSV_CURRENT

def get_active_kml() -> Path:
    """Returns the KML path for the current log session."""
    if state.log_label:
        return DATA_DIR / f"Flight_{TEAM_ID:04}_{state.log_label}.kml"
    return KML_CURRENT


def _build_kml(points: list, max_alt: float) -> str:
    """Builds a KML string from collected GPS points, segmented by flight state."""
    if len(points) < 2:
        return ""

    # Define styles for different states (KML color is aabbggrr)
    # ff00ff00 = Green (Ascent)
    # ff00aaff = Orange (Descent)
    # ffffffff = White (Default)
    styles = {
        "ASCENT":  {"color": "ff00ff00", "width": "4"},
        "DESCENT": {"color": "ff00aaff", "width": "4"},
        "DEFAULT": {"color": "ffffffff", "width": "3"},
    }

    # Group points into segments by state
    segments = []
    if points:
        current_state = points[0].get("state", "UNKNOWN")
        current_segment = [points[0]]
        
        for p in points[1:]:
            s = p.get("state", "UNKNOWN")
            if s != current_state:
                segments.append({"state": current_state, "points": current_segment})
                current_state = s
                current_segment = [p]
            else:
                current_segment.append(p)
        segments.append({"state": current_state, "points": current_segment})

    placemarks = ""
    for i, seg in enumerate(segments):
        state_name = seg["state"]
        pts = seg["points"]
        if len(pts) < 1: continue
        
        # If it's a single point segment, we can't draw a line, but we usually want to connect to the next
        # So we add the first point of the next segment if it exists
        if i < len(segments) - 1:
            pts_to_draw = pts + [segments[i+1]["points"][0]]
        else:
            pts_to_draw = pts

        if len(pts_to_draw) < 2: continue

        style = styles.get(state_name, styles["DEFAULT"])
        color = style["color"]
        width = style["width"]
        
        coords = "\n          ".join(f"{p['lon']:.6f},{p['lat']:.6f},{p['alt']:.1f}" for p in pts_to_draw)
        
        placemarks += f"""
    <Placemark>
      <name>{state_name} Phase</name>
      <Style><LineStyle><color>{color}</color><width>{width}</width></LineStyle></Style>
      <LineString>
        <extrude>1</extrude><tessellate>1</tessellate>
        <altitudeMode>absolute</altitudeMode>
        <coordinates>
          {coords}
        </coordinates>
      </LineString>
    </Placemark>"""

    # Add Deployment marker if we find a state change that looks like deployment
    deployment_placemark = ""
    for i in range(1, len(points)):
        prev_s = points[i-1].get("state", "")
        curr_s = points[i].get("state", "")
        # Look for the transition out of ASCENT
        if prev_s == "ASCENT" and curr_s != "ASCENT":
            p = points[i]
            deployment_placemark = f"""
    <Placemark><name>Deployment Point</name>
      <Style><IconStyle><scale>1.2</scale><Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle></Style>
      <Point><altitudeMode>absolute</altitudeMode>
        <coordinates>{p['lon']:.6f},{p['lat']:.6f},{p['alt']:.1f}</coordinates>
      </Point></Placemark>"""
            break

    first = points[0]
    last = points[-1]
    apex = max(points, key=lambda p: p['alt'])

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>DAEDALUS #{TEAM_ID} Flight Path</name>
    <description>Max altitude: {int(max_alt)} m | Packets: {len(points)}</description>
    <Style id="launch"><IconStyle><color>ff00cc00</color><scale>1.2</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/go.png</href></Icon>
    </IconStyle></Style>
    <Style id="land"><IconStyle><color>ff0000ff</color><scale>1.2</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/stop.png</href></Icon>
    </IconStyle></Style>
    <Style id="apex"><IconStyle><color>ff00ffff</color><scale>1.1</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/shapes/star.png</href></Icon>
    </IconStyle></Style>
    {placemarks}
    {deployment_placemark}
    <Placemark><name>Launch</name><styleUrl>#launch</styleUrl>
      <Point><altitudeMode>clampToGround</altitudeMode>
        <coordinates>{first['lon']:.6f},{first['lat']:.6f},0</coordinates>
      </Point></Placemark>
    <Placemark><name>Landing</name><styleUrl>#land</styleUrl>
      <Point><altitudeMode>clampToGround</altitudeMode>
        <coordinates>{last['lon']:.6f},{last['lat']:.6f},0</coordinates>
      </Point></Placemark>
    <Placemark><name>Apogee ({int(apex['alt'])} m)</name><styleUrl>#apex</styleUrl>
      <Point><altitudeMode>absolute</altitudeMode>
        <coordinates>{apex['lon']:.6f},{apex['lat']:.6f},{apex['alt']:.1f}</coordinates>
      </Point></Placemark>
  </Document>
</kml>"""

async def _save_kml():
    """Writes the current KML data to disk."""
    kml_str = _build_kml(state.kml_points, state.kml_max_alt)
    if kml_str:
        try:
            async with aiofiles.open(get_active_kml(), "w", encoding="utf-8") as f:
                await f.write(kml_str)
        except Exception as e:
            log_json(level="error", event="kml_save_failed", error=str(e))

ring: Deque[str] = deque(maxlen=10_000)   # Keeps the last 10,000 log messages in memory
ws_clients: Set[WebSocket] = set()        # A list of all web browsers currently connected
uplink_q: asyncio.Queue[str] = asyncio.Queue() # A queue (line) of commands waiting to be sent
_kml_gps_count: int = 0                   # Count valid GPS packets; write KML every 10

_serial_transport = None
_serial_writer_lock = asyncio.Lock()

def ensure_csv_header(path: Optional[Path] = None):
    """Checks if the CSV file exists. If not, creates it and adds the header row."""
    target = path or get_active_csv()
    if not target.exists():
        target.write_bytes((CSV_HEADER + "\r\n").encode("utf-8"))
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
    # client_list = []
    # for ws in ws_clients:
    #     c = ws.client
    #     if c:
    #         client_list.append(f"{c.host}:{c.port}")
    #     else:
    #         client_list.append("unknown")
            
    # log_json(event="ws_broadcast", clients=client_list)
    
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

    # Use csv.reader to handle quoted fields correctly (e.g., "CX,ON")
    reader = csv.reader([raw], skipinitialspace=True)
    try:
        parts = next(reader)
    except StopIteration:
        return # Empty line
    
    parts = [p.strip() for p in parts]
    
    # We check if we have enough columns based on our config
    # Note: Optional fields at the end might be missing, so we allow slightly fewer.
    min_required = len([x for x in TELEMETRY_CONFIG if not x.get("optional", False)])
    
    if len(parts) < min_required:
        ring.append(json.dumps({"bad_line": raw}))
        # Save unexpected lines so we don't lose them
        if state.csv_ready:
            async with aiofiles.open(get_active_csv(), "a", encoding="utf-8", newline="") as f:
                await f.write(raw + "\r\n")
        return

    # 1) Parse data dynamically using the config (for UI display only; CSV is saved as raw)
    parsed_data = {}

    for i, cfg in enumerate(TELEMETRY_CONFIG):
        key = cfg.get("internal_key")
        dtype = cfg.get("type")
        val_str = (parts[i] if i < len(parts) else "").strip()

        try:
            if dtype == "int":
                value = int(val_str) if val_str else 0
            elif dtype == "float":
                value = float(val_str) if val_str else 0.0
            else:
                value = val_str
        except ValueError:
            if dtype == "int": value = 0
            elif dtype == "float": value = 0.0
            else: value = ""

        if key:
            parsed_data[key] = value

    # 2) Create the Telemetry object
    # We add the Ground Station calculated fields here
    parsed_data["gs_ts_utc"] = now_utc_iso()
    parsed_data["gs_rx_count"] = state.rx_count + 1
    parsed_data["gs_loss_total"] = state.loss_count
    parsed_data["gs_raw_line"] = raw
    
    # This '**parsed_data' magic passes the dictionary as arguments
    tel = Telemetry(**parsed_data)

    # 4) Append to the CSV file (ALWAYS SAVE RAW EXACTLY AS RECEIVED)
    if state.csv_ready:
        async with aiofiles.open(get_active_csv(), "a", encoding="utf-8", newline="") as f:
            await f.write(raw + "\r\n")


    # 4b) Auto-save KML (Google Earth) — collect GPS points and write to disk
    gps_lat = parsed_data.get("gps_lat", 0.0)
    gps_lon = parsed_data.get("gps_lon", 0.0)
    gps_sats = parsed_data.get("gps_sats", 0)
    alt_m = parsed_data.get("altitude_m", 0.0)
    if isinstance(gps_lat, (int, float)) and isinstance(gps_lon, (int, float)):
        if gps_lat != 0.0 and gps_lon != 0.0 and gps_sats > 5:  # Only save with good GPS fix (>5 sats)
            global _kml_gps_count
            state.kml_points.append({
                "lat": gps_lat, 
                "lon": gps_lon, 
                "alt": max(0, alt_m),
                "state": parsed_data.get("state", "UNKNOWN")
            })
            if alt_m > state.kml_max_alt:
                state.kml_max_alt = alt_m
            _kml_gps_count += 1
            if _kml_gps_count % 10 == 0:  # write KML to disk every 10 valid GPS packets
                await _save_kml()

    # 5) Update counters
    state.rx_count += 1
    # [REQ-78] Count the number of received packets
    
    # Packet Loss Calculation (Sequence-based)
    # [REQ-65] Uses packet_count field from telemetry to detect gaps accurately
    pkt = parsed_data.get("packet_count", 0)
    if state.last_pkt is not None and pkt > 0:
        if pkt > state.last_pkt + 1:
            state.loss_count += pkt - state.last_pkt - 1
    state.last_pkt = pkt

    # 6) Send to UI
    payload = tel.model_dump()
    await broadcast_ws(payload)
    ring.append(json.dumps({"telemetry": payload}))

# ===================== SIMULATION MODE (Testing) =====================
sim_task: Optional[asyncio.Task] = None

async def sim_file_streamer(file_path: Path):
    """
    Streams the pressure data from the file (Step 3 of simulation).
    # [REQ-74] Transmit pressure data from a csv file provided by the competition at a 1 Hz interval
    # [REQ-83] Ground station sends air pressure values at a one second interval
    # [REQ-84] Use radio uplink pressure values for altitude
    """
    if not file_path.exists():
        log_json(level="error", event="sim_file_missing", file=str(file_path))
        # Try to find it in the current directory if full path failed
        fallback = ROOT_DIR / "cansat_2023_simp.csv"
        if fallback.exists():
            file_path = fallback
        else:
            return

    log_json(event="sim_streaming_start", file=str(file_path))

    # 3. Stream Pressure Data (1 Hz)
    try:
        with file_path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                # Skip empty lines or headers
                if not s or s.startswith("#"):
                    continue
                
                # Logic: If the file has "CMD,..." use it as is. 
                # If it is just a number, wrap it in the proper command structure.
                # Also handle the '$' placeholder as per spec.
                if "$" in s:
                    s = s.replace("$", f"{TEAM_ID:04}")

                if s.startswith("CMD,"):
                    await uplink_q.put(s)
                elif s.isdigit():
                    await uplink_q.put(f"CMD,{TEAM_ID:04},SIMP,{s}")
                else:
                    # Fallback for unknown formats, or maybe log a warning
                    pass
                
                # Wait 1 second between sends (Requirement: 1 Hz)
                await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        log_json(event="sim_cancelled", file=str(file_path))
        raise
            
    log_json(event="sim_complete", file=str(file_path))

async def sim_sender(file_path: Path):
    """
    Reads a file with pressure data and sends it to the CanSat to simulate flight.
    Follows sequence: SIM,ENABLE -> SIM,ACTIVATE -> Stream SIMP packets.
    # [REQ-73] Command payload to operate in simulation mode by sending SIMULATION ENABLE and SIMULATION ACTIVATE
    # [REQ-85] Enter simulation mode only after receiving ENABLE and ACTIVATE commands
    """
    # 1. Enable Simulation Mode
    state.sim_enabled = True
    await uplink_q.put(f"CMD,{TEAM_ID:04},SIM,ENABLE")
    log_json(event="sim_command", cmd="SIM,ENABLE")
    await asyncio.sleep(1.0) # Wait for radio/processing
    
    # 2. Activate Simulation Mode
    await uplink_q.put(f"CMD,{TEAM_ID:04},SIM,ACTIVATE")
    log_json(event="sim_command", cmd="SIM,ACTIVATE")
    await asyncio.sleep(1.0)

    # 3. Stream
    await sim_file_streamer(file_path)

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
    
    # Simulate altitude change (go up a bit, then drop instantly to 0)
    if pkt < 5:
        altitude = 100 + (pkt * 10) + (random.random() - 0.5) * 5
    else:
        altitude = 150 - ((pkt - 5) * 5) + (random.random() - 0.5) * 5

    if altitude <= 0:
        altitude = 0.0 + (random.random() - 0.5) * 0.5

    temp = 25 - (altitude / 100)
    voltage = 12.6 - (pkt / 500)
    current = 0.5 + (random.random() - 0.5) * 0.2
    
    mission_time = hms_from_seconds(pkt)
    
    # Determine flight state based on altitude
    flight_state = 'LAUNCH_PAD'
    if dummy_state.get("has_landed", False) or altitude <= 0.5:
        flight_state = 'LANDED'
        dummy_state["has_landed"] = True
    elif altitude > 20:
        if altitude > dummy_state["last_alt"]:
            flight_state = 'ASCENT'
        else:
            flight_state = 'DESCENT'
    elif dummy_state["last_alt"] > 20 and altitude <= 20:
        flight_state = 'LANDED'
        dummy_state["has_landed"] = True

    dummy_state["last_alt"] = altitude

    # Dictionary of all current dummy values
    val_map = {
        "team_id": str(TEAM_ID),
        "mission_time": mission_time,
        "packet_count": str(pkt),
        "mode": 'F',
        "state": flight_state,
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
        "yaw": f"{(pkt * 5) % 360:.2f}",
        "tof": f"{random.uniform(0, 5):.3f}",
    }

    # Build the line based on the config order
    line_parts = []
    for cfg in TELEMETRY_CONFIG:
        key = cfg.get("internal_key")
        dtype = cfg.get("type")
        
        if key in val_map:
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
    return state.cfg.model_dump()

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
    # [REQ-63] Command CanSat to calibrate altitude to zero (CAL)
    # [REQ-82] Set time by ground command (ST,GPS or ST,UTC)
    # [REQ-86] Commands to activate all mechanisms (MEC,PL,ON etc.)
    """
    global sim_task
    cmd_upper = body.cmd.strip().upper()

    # body.cmd is something like "CX,ON"
    uplink = f"CMD,{TEAM_ID:04},{body.cmd.strip()}"
    state.last_cmd = uplink
    await uplink_q.put(uplink)

    # Trigger simulation file streaming if SIM,ACTIVATE is sent manually
    if cmd_upper == "SIM,ENABLE":
        state.sim_enabled = True
    elif cmd_upper == "SIM,DISABLE":
        state.sim_enabled = False
        if sim_task and not sim_task.done():
            sim_task.cancel()

    if cmd_upper == "SIM,ACTIVATE":
        if state.sim_enabled:
            if sim_task and not sim_task.done():
                pass
            else:
                path = ROOT_DIR / "cansat_2023_simp.csv"
                sim_task = asyncio.create_task(sim_file_streamer(path))
        else:
            log_json(level="warn", event="sim_activate_ignored", reason="sim_not_enabled")
            
    return {"ok": True, "sent": uplink}

# ---- Simulation start ----
@app.post("/api/sim/start")
async def api_sim_start(file: Optional[str] = None):
    """Starts reading a simulation file."""
    # Default to the requirement file name
    filename = file or "cansat_2023_simp.csv"
    path = ROOT_DIR / filename
    
    # If not found at root, check if user provided a full path or just a name
    if not path.exists() and not Path(filename).is_absolute():
        # Check in 'data' folder just in case
        path_data = DATA_DIR / filename
        if path_data.exists():
            path = path_data

    global sim_task
    if sim_task and not sim_task.done():
        sim_task.cancel()
        
    sim_task = asyncio.create_task(sim_sender(path))
    return {"ok": True, "running": True, "file": str(path)}

# ---- Browser \u2192 Server telemetry ingest ----
@app.post("/api/ingest")
async def api_ingest(body: IngestBody):
    """Allows the browser to send data to the backend (used for WebSerial)."""
    line = body.line.strip()
    if not line:
        raise HTTPException(400, detail="empty")
    await handle_telemetry_line(line)
    return {"ok": True}

# ---- Log switching ----
@app.get("/api/log/current")
async def api_log_current():
    """Returns the active log label and file path."""
    return {
        "label": state.log_label or "default",
        "file": str(get_active_csv()),
        "kml":  str(get_active_kml()),
    }

@app.post("/api/log/set")
async def api_log_set(body: LogBody):
    """
    Switch the active log file.
    Send {"label": "log1"} to start writing to Flight_1043_log1.csv.
    Send {"label": ""} to return to the default Flight_1043.csv.
    """
    # Sanitize: alphanumeric, underscore, hyphen only; max 32 chars
    raw = body.label.strip().replace(" ", "_")
    label = re.sub(r"[^a-zA-Z0-9_\-]", "", raw)[:32]

    state.log_label = label

    # Create the new CSV with a header if it doesn't exist yet
    new_csv = get_active_csv()
    ensure_csv_header(new_csv)

    # Reset KML state so this log gets its own flight path
    state.kml_points.clear()
    state.kml_max_alt = 0.0

    # Reset packet-loss tracking so a satellite restart doesn't skew counters
    state.last_pkt = None

    display = label or "default"
    log_json(event="log_switched", label=display, file=str(new_csv))

    await broadcast_ws({
        "type": "log_switched",
        "label": display,
        "file": new_csv.name,
    })
    return {"ok": True, "label": display, "file": str(new_csv)}

# ---- KML download endpoint ----
@app.get("/api/kml")
async def api_kml_download():
    """Download the auto-saved KML file for the active log session."""
    kml_path = get_active_kml()
    if kml_path.exists():
        from fastapi.responses import FileResponse
        return FileResponse(
            path=str(kml_path),
            media_type="application/vnd.google-earth.kml+xml",
            filename=kml_path.name,
        )
    raise HTTPException(status_code=404, detail="No KML file yet \u2014 waiting for GPS data.")

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

    content = CSV_HEADER + "\r\n" + "\r\n".join(r.rstrip("\r\n") for r in rows) + "\r\n"
    async with aiofiles.open(out_path, "w", encoding="utf-8", newline="") as f:
        await f.write(content)
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
    for p in sorted(ports, key=lambda x: x.device):
        print(f"- {p.device}: {p.description} [{p.hwid}]")
    print("="*50)

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    uvicorn.run(app, host=host, port=port, log_level="info")
