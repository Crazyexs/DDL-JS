import uvicorn
import socket
import sys
import os
import re
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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from datetime import datetime, timezone

# ===================== CONFIGURATION =====================
# Team ID 
TEAM_ID = 1043

# This is the default USB port the computer uses to talk to the radio.
# On Windows it is usually "COM3", "COM4", etc.
# On Linux/Mac it looks like "/dev/ttyUSB0".
DEFAULT_PORT = "/dev/cu.usbserial-00000000"

# This is the speed of the connection. Both the radio and computer must match this number.
DEFAULT_BAUD = 115200

# Default 64-bit XBee destination address (DH + DL).
# DH is always 0013A200 for same-model modules; DL is the unique part.
# Changed at runtime via POST /api/xbee/config — no restart needed.
DEFAULT_XBEE_DH = "0013A200"
DEFAULT_XBEE_DL = "41F77466"

# The XBee 64-bit broadcast address. We refuse to ever transmit to it so a
# command always goes to exactly the one unit selected in /config — never to
# every radio in range at once.
XBEE_BROADCAST_ADDR = "000000000000FFFF"

# ---- Preset XBee units (Quick Select buttons 1-3 in /config) ----
# Edit these to match your physical XBee modules. The /config page shows one
# button per preset; pressing it applies that address instantly (no typing).
# DH is 0013A200 for all same-model XBee PRO 900HP — only DL differs per unit.
# Read DL off each module's label or via ATSL in XCTU, then paste it here.
XBEE_PRESETS = [
    {"slot": 1, "name": "Unit 1",  "dh": "0013A200", "dl": "41F77466"},
    {"slot": 2, "name": "Unit 2",  "dh": "0013A200", "dl": "41071708"},  # TODO: set real DL
    {"slot": 3, "name": "Unit 3",  "dh": "0013A200", "dl": "41E15A39"},  # TODO: set real DL
]

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

# Only 115200 is supported — XBee 900HP default for this mission.
BAUD_PRESETS = [115200]

# ===================== TELEMETRY CONFIG (Dynamic Loading) =====================
# We load the structure of the CSV from 'telemetry_config.json'
# This allows you to change the order of columns without changing the code.
# [REQ-64] Generate csv files of all sensor data
# [REQ-70] Display mission time, temperature, GPS, packet count, state
def load_telemetry_config():
    config_path = ROOT_DIR / "telemetry_config.json"
    if not config_path.exists():
        print("Warning: telemetry_config.json not found, using built-in default.")
        return [
            { "csv_header": "TEAM_ID",       "internal_key": "team_id",        "type": "int"   },
            { "csv_header": "MISSION_TIME",  "internal_key": "mission_time",   "type": "str"   },
            { "csv_header": "PACKET_COUNT",  "internal_key": "packet_count",   "type": "int"   },
            { "csv_header": "MODE",          "internal_key": "mode",           "type": "str"   },
            { "csv_header": "STATE",         "internal_key": "state",          "type": "str"   },
            { "csv_header": "ALTITUDE",      "internal_key": "altitude_m",     "type": "float" },
            { "csv_header": "TEMPERATURE",   "internal_key": "temperature_c",  "type": "float" },
            { "csv_header": "PRESSURE",      "internal_key": "pressure_kpa",   "type": "float" },
            { "csv_header": "VOLTAGE",       "internal_key": "voltage_v",      "type": "float" },
            { "csv_header": "CURRENT",       "internal_key": "current_a",      "type": "float" },
            { "csv_header": "GYRO_R",        "internal_key": "gyro_r_dps",     "type": "float" },
            { "csv_header": "GYRO_P",        "internal_key": "gyro_p_dps",     "type": "float" },
            { "csv_header": "GYRO_Y",        "internal_key": "gyro_y_dps",     "type": "float" },
            { "csv_header": "ACCEL_R",       "internal_key": "accel_r_dps2",   "type": "float" },
            { "csv_header": "ACCEL_P",       "internal_key": "accel_p_dps2",   "type": "float" },
            { "csv_header": "ACCEL_Y",       "internal_key": "accel_y_dps2",   "type": "float" },
            { "csv_header": "GPS_TIME",      "internal_key": "gps_time",       "type": "str"   },
            { "csv_header": "GPS_ALTITUDE",  "internal_key": "gps_altitude_m", "type": "float" },
            { "csv_header": "GPS_LATITUDE",  "internal_key": "gps_lat",        "type": "float" },
            { "csv_header": "GPS_LONGITUDE", "internal_key": "gps_lon",        "type": "float" },
            { "csv_header": "GPS_SATS",      "internal_key": "gps_sats",       "type": "int"   },
            { "csv_header": "CMD_ECHO",      "internal_key": "cmd_echo",       "type": "str"   },
            { "csv_header": "ARM_STATE",     "internal_key": "arm_state",      "type": "str"   },
            { "csv_header": "DEPLOY",        "internal_key": "deploy",         "type": "str"   },
            { "csv_header": "YAW",           "internal_key": "yaw",            "type": "float" },
            { "csv_header": "HEADING_GPS",   "internal_key": "heading_gps",    "type": "float" },
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

class XBeeCfg(BaseModel):
    """XBee destination address split into DH and DL (each 8 hex chars = 4 bytes)."""
    dh: str = Field(default=DEFAULT_XBEE_DH, description="Destination High — 8 hex chars")
    dl: str = Field(default=DEFAULT_XBEE_DL, description="Destination Low  — 8 hex chars")

class Telemetry(BaseModel):
    """
    The structure of a single packet of data from the CanSat.
    Field order matches telemetry_config.json (CSV column order).
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
    arm_state: str = "DISARMED"
    deploy: str = "0"
    yaw: float = 0.0
    heading_gps: float = 0.0

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
    last_current_a: Optional[float] = None  # Most recent current reading (A)
    rssi_dbm: Optional[int] = None          # Last-hop RSSI from ATDB (negative dBm)
    xbee_dh: str = DEFAULT_XBEE_DH         # Current XBee destination high (8 hex chars)
    xbee_dl: str = DEFAULT_XBEE_DL         # Current XBee destination low  (8 hex chars)
    last_tx_status: Optional[int] = None    # Last uplink delivery status (0x00 = delivered)
    kml_landed_saved: bool = False          # True after final KML save on LANDED state

state = GSState()

# ===================== STARTUP SERIAL PORT SELECTION =====================
def _select_serial_port_at_startup():
    """Interactive port picker shown once at import time when stdin is a real terminal.
    When running headless (systemd/no TTY), auto-detects the first USB serial port.
    """
    ports = sorted(serial.tools.list_ports.comports(), key=lambda p: p.device)

    if not sys.stdin.isatty():
        # Running headless (e.g. systemd on Raspberry Pi) — auto-detect XBee port.
        usb_ports = [p for p in ports if "USB" in p.hwid.upper() or "ttyUSB" in p.device or "ttyACM" in p.device]
        if usb_ports:
            state.cfg.port = usb_ports[0].device
            log_json(event="auto_port_selected", port=state.cfg.port, reason="headless_mode")
        return

    print("\n" + "=" * 54)
    print("  DAEDALUS — SELECT SERIAL PORT")
    print("=" * 54)
    if not ports:
        print("  (No serial ports detected — will retry after server starts)")
        print("=" * 54 + "\n")
        return
    for i, p in enumerate(ports, 1):
        marker = "  <- current" if p.device == state.cfg.port else ""
        print(f"  [{i}]  {p.device:<22} {p.description}{marker}")
    print(f"\n  [Enter]  Keep default ({state.cfg.port})")
    print("=" * 54)
    try:
        raw = input("  Choice: ").strip()
        if raw:
            idx = int(raw) - 1
            if 0 <= idx < len(ports):
                state.cfg.port = ports[idx].device
                print(f"  -> Port set to {state.cfg.port}")
            else:
                print("  Invalid choice — keeping default.")
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    print("=" * 54 + "\n")

# NOTE: _select_serial_port_at_startup() is intentionally NOT called at import
# time — it now runs inside the FastAPI lifespan startup so importing this
# module (tests, reloaders) does not block on stdin.

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
    """
    Builds a standard KML 2.2 file from GPS points — compatible with all viewers.
    Includes: state-colored 3D path with extruded walls, ground-shadow track,
    and event markers (Launch, Apogee, Deployment, Landing).
    KML color format: AABBGGRR (alpha-blue-green-red).
    """
    if len(points) < 2:
        return ""

    # ── Altitude helper ────────────────────────────────────────────────
    # Use barometric altitude (AGL, calibrated to 0 at launch pad) throughout.
    # All path elements use altitudeMode=relativeToGround so Google Earth adds
    # this value on top of the actual terrain — works correctly at any launch site
    # elevation, and the slope of the rocket ascent/descent is always visible.
    def kml_alt(p: dict) -> float:
        return float(p.get("alt") or 0)

    # ── State → colour/width map ───────────────────────────────────────
    STATE_COLORS: dict = {
        "LAUNCH_PAD":      ("ff14d414", "3"),   # dim green   — on pad
        "ASCENT":          ("ff00ee00", "5"),   # bright green — rocket going up
        "APOGEE":          ("ff00ffff", "4"),   # yellow       — at apogee
        "DESCENT":         ("ff0055ff", "5"),   # orange       — parachute descent
        "PROBE_RELEASE":   ("ff00aaff", "4"),   # amber
        "PAYLOAD_RELEASE": ("ff00ccff", "4"),   # light orange
        "LANDED":          ("ff0000ff", "3"),   # red          — on the ground
        "DEFAULT":         ("ffaaaaaa", "3"),   # grey         — unknown
    }
    STATE_LABELS: dict = {
        "LAUNCH_PAD":      "On Launch Pad",
        "ASCENT":          "Rocket Ascent",
        "APOGEE":          "Apogee",
        "DESCENT":         "CanSat Descent (Parachute)",
        "PROBE_RELEASE":   "Probe Released",
        "PAYLOAD_RELEASE": "Payload Released",
        "LANDED":          "Landed",
        "DEFAULT":         "Unknown Phase",
    }

    # ── Style definitions ──────────────────────────────────────────────
    style_defs = ""
    for sid, (color, width) in STATE_COLORS.items():
        wall_fill = "44" + color[2:]   # 27 % opacity fill on extruded walls
        style_defs += (
            f'\n  <Style id="s_{sid}">'
            f'<LineStyle><color>{color}</color><width>{width}</width></LineStyle>'
            f'<PolyStyle><color>{wall_fill}</color><outline>0</outline></PolyStyle>'
            f'</Style>'
        )
    style_defs += """
  <Style id="s_launch">
    <IconStyle><scale>1.4</scale><color>ff00cc00</color>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/go.png</href></Icon>
    </IconStyle>
    <LabelStyle><color>ff00cc00</color><scale>1.1</scale></LabelStyle>
  </Style>
  <Style id="s_apogee">
    <IconStyle><scale>1.3</scale><color>ff00ffff</color>
      <Icon><href>http://maps.google.com/mapfiles/kml/shapes/star.png</href></Icon>
    </IconStyle>
    <LabelStyle><color>ff00ffff</color><scale>1.0</scale></LabelStyle>
  </Style>
  <Style id="s_deploy">
    <IconStyle><scale>1.1</scale><color>ff0055ff</color>
      <Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon>
    </IconStyle>
    <LabelStyle><color>ff0055ff</color><scale>0.9</scale></LabelStyle>
  </Style>
  <Style id="s_landing">
    <IconStyle><scale>1.4</scale><color>ff0000ff</color>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/stop.png</href></Icon>
    </IconStyle>
    <LabelStyle><color>ff0000ff</color><scale>1.1</scale></LabelStyle>
  </Style>
  <Style id="s_shadow">
    <LineStyle><color>55ffffff</color><width>1</width></LineStyle>
  </Style>"""

    # ── Segment path by flight state ──────────────────────────────────
    segments: list = []
    curr_state = points[0].get("state", "UNKNOWN")
    curr_seg   = [points[0]]
    for p in points[1:]:
        s = p.get("state", "UNKNOWN")
        if s != curr_state:
            segments.append({"state": curr_state, "pts": curr_seg})
            curr_state, curr_seg = s, [p]
        else:
            curr_seg.append(p)
    segments.append({"state": curr_state, "pts": curr_seg})

    path_xml = ""
    for i, seg in enumerate(segments):
        sname = seg["state"]
        pts   = seg["pts"]
        # Bridge gap to next segment so path has no holes at state transitions
        draw  = pts + ([segments[i+1]["pts"][0]] if i < len(segments) - 1 else [])
        if len(draw) < 2:
            continue
        sid    = sname if sname in STATE_COLORS else "DEFAULT"
        label  = STATE_LABELS.get(sname, sname)
        coords = "\n          ".join(
            f"{p['lon']:.6f},{p['lat']:.6f},{kml_alt(p):.1f}" for p in draw
        )
        path_xml += (
            f'\n    <Placemark>'
            f'<name>{label} ({len(pts)} pts)</name>'
            f'<StyleUrl>#s_{sid}</StyleUrl>'
            f'<LineString>'
            f'<extrude>1</extrude><tessellate>1</tessellate>'
            f'<altitudeMode>relativeToGround</altitudeMode>'
            f'<coordinates>\n          {coords}\n        </coordinates>'
            f'</LineString></Placemark>'
        )

    # Ground-shadow track — projects flight path onto terrain so horizontal drift is visible
    shadow_coords = "\n          ".join(
        f"{p['lon']:.6f},{p['lat']:.6f},0" for p in points
    )
    shadow_xml = (
        "\n    <Placemark>"
        "<name>Ground Track (Shadow)</name>"
        "<StyleUrl>#s_shadow</StyleUrl>"
        "<LineString>"
        "<tessellate>1</tessellate>"
        "<altitudeMode>clampToGround</altitudeMode>"
        f"<coordinates>\n          {shadow_coords}\n        </coordinates>"
        "</LineString></Placemark>"
    )

    # ── Key event markers ─────────────────────────────────────────────
    first = points[0]
    last  = points[-1]
    apex  = max(points, key=kml_alt)
    apex_alt_m = kml_alt(apex)

    events_xml = (
        f'\n    <Placemark><name>Launch Site</name>'
        f'<description><![CDATA[<b>Rocket Launch</b><br/>'
        f'Lat: {first["lat"]:.5f}&deg; Lon: {first["lon"]:.5f}&deg;<br/>'
        f'Mission Time: {first.get("mission_time", "—")}]]></description>'
        f'<StyleUrl>#s_launch</StyleUrl>'
        f'<Point><altitudeMode>clampToGround</altitudeMode>'
        f'<coordinates>{first["lon"]:.6f},{first["lat"]:.6f},0</coordinates>'
        f'</Point></Placemark>'

        f'\n    <Placemark><name>Apogee — {int(apex_alt_m)} m</name>'
        f'<description><![CDATA[<b>Maximum Altitude</b><br/>'
        f'Altitude: {apex_alt_m:.1f} m<br/>'
        f'Lat: {apex["lat"]:.5f}&deg; Lon: {apex["lon"]:.5f}&deg;<br/>'
        f'Mission Time: {apex.get("mission_time", "—")}]]></description>'
        f'<StyleUrl>#s_apogee</StyleUrl>'
        f'<Point><altitudeMode>relativeToGround</altitudeMode>'
        f'<coordinates>{apex["lon"]:.6f},{apex["lat"]:.6f},{apex_alt_m:.1f}</coordinates>'
        f'</Point></Placemark>'
    )

    # One marker per state-transition event (deployment, descent begin, etc.)
    seen_transitions: set = set()
    deploy_states = {"DESCENT", "PROBE_RELEASE", "PAYLOAD_RELEASE", "APOGEE"}
    deploy_labels = {
        "DESCENT":         "Parachute Descent Begin",
        "PROBE_RELEASE":   "Probe Released",
        "PAYLOAD_RELEASE": "Payload Released",
        "APOGEE":          "Apogee State",
    }
    for i in range(1, len(points)):
        prev_s = points[i-1].get("state", "")
        curr_s = points[i].get("state", "")
        key    = f"{prev_s}->{curr_s}"
        if curr_s in deploy_states and key not in seen_transitions:
            seen_transitions.add(key)
            ep    = points[i]
            ep_alt = kml_alt(ep)
            dlabel = deploy_labels.get(curr_s, curr_s)
            events_xml += (
                f'\n    <Placemark><name>{dlabel}</name>'
                f'<description><![CDATA[<b>{dlabel}</b><br/>'
                f'Altitude: {ep_alt:.1f} m<br/>'
                f'Lat: {ep["lat"]:.5f}&deg; Lon: {ep["lon"]:.5f}&deg;<br/>'
                f'Mission Time: {ep.get("mission_time", "—")}]]></description>'
                f'<StyleUrl>#s_deploy</StyleUrl>'
                f'<Point><altitudeMode>relativeToGround</altitudeMode>'
                f'<coordinates>{ep["lon"]:.6f},{ep["lat"]:.6f},{ep_alt:.1f}</coordinates>'
                f'</Point></Placemark>'
            )

    events_xml += (
        f'\n    <Placemark><name>Landing Site</name>'
        f'<description><![CDATA[<b>CanSat Landing</b><br/>'
        f'Lat: {last["lat"]:.5f}&deg; Lon: {last["lon"]:.5f}&deg;<br/>'
        f'Mission Time: {last.get("mission_time", "—")}]]></description>'
        f'<StyleUrl>#s_landing</StyleUrl>'
        f'<Point><altitudeMode>clampToGround</altitudeMode>'
        f'<coordinates>{last["lon"]:.6f},{last["lat"]:.6f},0</coordinates>'
        f'</Point></Placemark>'
    )

    # ── LookAt — initial camera centred between launch and landing ────
    ctr_lat   = (first["lat"] + last["lat"]) / 2
    ctr_lon   = (first["lon"] + last["lon"]) / 2
    cam_range = max(3000, int(apex_alt_m) * 4)

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        '  <Document>\n'
        f'    <name>DAEDALUS #{TEAM_ID} — Full Flight Path</name>\n'
        f'    <description>Max altitude: {int(max_alt)} m | GPS points: {len(points)}</description>\n'
        f'    <LookAt>\n'
        f'      <longitude>{ctr_lon:.6f}</longitude>\n'
        f'      <latitude>{ctr_lat:.6f}</latitude>\n'
        f'      <altitude>0</altitude><heading>0</heading><tilt>50</tilt>\n'
        f'      <range>{cam_range}</range>\n'
        f'      <altitudeMode>relativeToGround</altitudeMode>\n'
        f'    </LookAt>\n'
        f'{style_defs}\n'
        '    <Folder><name>Flight Path</name><open>1</open>\n'
        f'{path_xml}\n'
        f'{shadow_xml}\n'
        '    </Folder>\n'
        '    <Folder><name>Key Events</name><open>1</open>\n'
        f'{events_xml}\n'
        '    </Folder>\n'
        '  </Document>\n'
        '</kml>'
    )

async def _save_kml():
    """Writes the current KML data to disk."""
    try:
        kml_str = _build_kml(list(state.kml_points), state.kml_max_alt)
        if kml_str:
            async with aiofiles.open(get_active_kml(), "w", encoding="utf-8") as f:
                await f.write(kml_str)
    except Exception as e:
        log_json(level="error", event="kml_save_failed", error=str(e))

ring: Deque[str] = deque(maxlen=10_000)   # Keeps the last 10,000 log messages in memory
ws_clients: Set[WebSocket] = set()        # A list of all web browsers currently connected
uplink_q: asyncio.Queue[str] = asyncio.Queue(maxsize=100) # A queue (line) of commands waiting to be sent
_kml_gps_count: int = 0                   # Count valid GPS packets; write KML every 10
_csv_write_lock: asyncio.Lock = asyncio.Lock()  # Serialises CSV append so concurrent writers don't interleave bytes

def ensure_csv_header(path: Optional[Path] = None):
    """Checks if the CSV file exists. If not, creates it and adds the header row."""
    target = path or get_active_csv()
    if not target.exists():
        target.write_bytes((CSV_HEADER + "\r\n").encode("utf-8"))
    state.csv_ready = True

# ===================== XBEE API MODE 2 FRAME CODEC =====================
_API2_ESCAPE_SET = frozenset([0x7E, 0x7D, 0x11, 0x13])

def _api2_escape(data: bytes) -> bytes:
    """Apply API Mode 2 byte-escaping to a raw byte sequence."""
    out = bytearray()
    for byte in data:
        if byte in _API2_ESCAPE_SET:
            out += bytes([0x7D, byte ^ 0x20])
        else:
            out.append(byte)
    return bytes(out)

def _read_api2_frame(ser: serial.Serial) -> Optional[dict]:
    """
    Read one API Mode 2 frame from the GCS XBee UART.

    Returns one of:
      {"type": "telemetry", "payload": bytes}   — 0x90 RX Indicator (telemetry CSV)
      {"type": "rssi",      "dbm":    int  }    — 0x88 AT Response for ATDB query
      None                                       — timeout / bad checksum / other frame
    """
    # Sync to start delimiter — 0x7E is never escaped so we scan for it raw.
    while True:
        b = ser.read(1)
        if not b:
            return None
        if b[0] == 0x7E:
            break

    def _read_unescaped(n: int) -> Optional[bytearray]:
        buf = bytearray()
        while len(buf) < n:
            b = ser.read(1)
            if not b:
                return None
            if b[0] == 0x7D:
                b2 = ser.read(1)
                if not b2:
                    return None
                buf.append(b2[0] ^ 0x20)
            else:
                buf.append(b[0])
        return buf

    length_raw = _read_unescaped(2)
    if length_raw is None:
        return None
    length = (length_raw[0] << 8) | length_raw[1]
    if length > 300:
        return None

    body = _read_unescaped(length + 1)
    if body is None:
        return None

    if (sum(body) & 0xFF) != 0xFF:
        return None

    frame_type = body[0]

    # 0x90 = Receive Packet (RX Indicator)
    # Header: frame_type(1) + src_64(8) + src_16(2) + options(1) = 12 bytes
    if frame_type == 0x90 and length >= 12:
        return {"type": "telemetry", "payload": bytes(body[12:length])}

    # 0x88 = AT Command Response — we use this to read back ATDB (last-hop RSSI).
    # Body layout: frame_type(1) + frame_id(1) + cmd[2] + status(1) + value(N)
    # For ATDB: value is 1 byte = RSSI magnitude (negate to get dBm).
    if frame_type == 0x88 and length >= 6:
        at_cmd   = bytes(body[2:4])
        status   = body[4]
        if at_cmd == b'DB' and status == 0x00:
            rssi_dbm = -body[5]         # XBee reports magnitude; negate for dBm
            return {"type": "rssi", "dbm": rssi_dbm}

    # 0x8B = Transmit Status — tells us whether an uplink actually reached the CanSat.
    # DigiMesh layout: frame_type(1) + frame_id(1) + 16-bit dest(2) + tx_retries(1)
    #                  + delivery_status(1) + discovery_status(1) = 7 bytes.
    # delivery_status 0x00 == delivered; anything else == not delivered (no ACK, no route…).
    if frame_type == 0x8B and length >= 7:
        return {"type": "tx_status", "delivery": body[5], "retries": body[4]}

    return None


def _build_db_query() -> bytes:
    """
    Build an API Mode 2 Local AT Command Request (0x08) that queries ATDB.
    ATDB returns the RSSI of the last received RF packet (last-hop, in dBm magnitude).
    This command is LOCAL — it queries the GCS XBee directly, does not go over RF.
    """
    content  = bytearray([0x08, 0x01, 0x44, 0x42])  # frame_type, frame_id, 'D', 'B'
    length   = len(content)
    checksum = (0xFF - (sum(content) & 0xFF)) & 0xFF
    len_bytes = bytes([length >> 8, length & 0xFF])
    body      = bytes(content) + bytes([checksum])
    return b'\x7E' + _api2_escape(len_bytes) + _api2_escape(body)


def _build_api2_tx_frame(payload: bytes) -> bytes:
    """
    Build an API Mode 2 Transmit Request (0x10) frame addressed to PAYLOAD_XBEE_ADDR.
    Escapes 0x7E, 0x7D, 0x11, 0x13 everywhere except the leading start delimiter.
    """
    dest_hex = (state.xbee_dh + state.xbee_dl).upper()
    # Safety: never broadcast. Always send to the single unit set in /config.
    if dest_hex == XBEE_BROADCAST_ADDR:
        raise ValueError("refusing to transmit to the XBee broadcast address — pick a specific unit in /config")

    content = bytearray([0x10, 0x01])   # frame type: TX Request, frame ID: 1
    content += bytes.fromhex(dest_hex)  # 64-bit destination (8 bytes) — the /config unit only
    content += b'\xFF\xFE'             # 16-bit dest = unknown/let stack decide
    content += b'\x00'                 # broadcast radius = 0
    content += b'\xC0'                 # options = 0xC0 (DigiMesh)
    content += payload

    length   = len(content)
    checksum = (0xFF - (sum(content) & 0xFF)) & 0xFF

    len_bytes = bytes([length >> 8, length & 0xFF])
    body      = bytes(content) + bytes([checksum])
    return b'\x7E' + _api2_escape(len_bytes) + _api2_escape(body)


# ===================== SERIAL COMMUNICATION (Talking to Hardware) =====================
import threading
import time
import queue

# These variables help share the serial connection safely between different parts of the program.
_serial_port: Optional[serial.Serial] = None
_serial_lock = threading.Lock()
_stop_event = threading.Event()

# --- Single-threaded serial I/O ----------------------------------------------
# CRITICAL: ALL reads AND writes to _serial_port must happen ONLY inside
# serial_read_thread_target(). Reading and writing the same tty fd from two
# different threads makes pyserial's read() raise
#   SerialException: device reports readiness to read but returned no data
#                    (device disconnected or multiple access on port?)
# on Linux (e.g. Raspberry Pi). The read loop treats that as a lost link and
# reconnects — the spurious "auto reconnect on every uplink" bug. macOS tolerates
# the race, which is why it only surfaces on Linux. So other threads hand outgoing
# frames to _tx_queue and the reader drains it.
_tx_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=200)  # outgoing API frames
_serial_connected = threading.Event()   # set while the port is open & usable
_reconnect_request = threading.Event()  # set by HTTP handlers to ask for a clean reconnect


def _close_serial():
    """Close and clear the shared port. Called ONLY from the reader thread."""
    global _serial_port
    _serial_connected.clear()
    with _serial_lock:
        if _serial_port:
            try:
                _serial_port.close()
            except Exception:
                pass
            _serial_port = None
    # Drop any unsent uplinks so they aren't fired late after a reconnect.
    try:
        while True:
            _tx_queue.get_nowait()
    except queue.Empty:
        pass


def _drain_tx_queue(ser: serial.Serial):
    """
    Write every queued uplink frame to the radio. Runs in the reader thread so it
    never races _read_api2_frame(). A write failure propagates to the caller, which
    treats it as a genuine disconnect and reconnects.
    """
    while True:
        try:
            data = _tx_queue.get_nowait()
        except queue.Empty:
            return
        ser.write(data)
        ser.flush()

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
                # Short read timeout bounds uplink latency: the loop returns from
                # read() promptly to drain the TX queue. Safe at 115200 — a single
                # API frame arrives contiguously and won't truncate within 0.2s.
                ser = serial.Serial(state.cfg.port, state.cfg.baud, timeout=0.2)

                # Safely save the connection object
                with _serial_lock:
                    _serial_port = ser
                _serial_connected.set()
                # We just opened with the current cfg, so any pending request is satisfied.
                _reconnect_request.clear()
                log_json(event="serial_connected", port=state.cfg.port)
                _thread_broadcast({"type": "serial_status", "connected": True, "port": state.cfg.port}, loop)
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

        # 2. Read + Write Loop — ALL serial I/O happens in THIS thread only, so a
        #    uplink write can never race the blocking read below (which on Linux
        #    would raise "multiple access on port" and force a spurious reconnect).
        try:
            # Honor a clean-reconnect request from an HTTP handler (e.g. config change).
            if _reconnect_request.is_set():
                _reconnect_request.clear()
                log_json(event="serial_reconnect_request", port=state.cfg.port)
                _close_serial()
                _thread_broadcast({"type": "serial_status", "connected": False, "port": state.cfg.port}, loop)
                continue

            if _serial_port and _serial_port.is_open:
                # Flush any queued uplink frames first (single-threaded write).
                _drain_tx_queue(_serial_port)

                frame = _read_api2_frame(_serial_port)
                if frame is None:
                    pass  # timeout or bad checksum — port is still fine

                elif frame["type"] == "telemetry":
                    try:
                        line = frame["payload"].decode(errors="ignore").rstrip("\r\n")
                        if line:
                            try:
                                asyncio.run_coroutine_threadsafe(handle_telemetry_line(line), loop)
                            except RuntimeError:
                                pass
                    except Exception:
                        pass
                    # Query RSSI of this packet from the local GCS XBee immediately.
                    # ATDB is a LOCAL command — write it here in the same (and only)
                    # I/O thread so it can never race the read above.
                    try:
                        _serial_port.write(_build_db_query())
                        _serial_port.flush()
                    except Exception:
                        pass

                elif frame["type"] == "rssi":
                    state.rssi_dbm = frame["dbm"]
                    _thread_broadcast({"type": "rssi", "dbm": frame["dbm"]}, loop)

                elif frame["type"] == "tx_status":
                    # Delivery receipt for the last uplink command (0x00 = delivered).
                    state.last_tx_status = frame["delivery"]
                    _thread_broadcast({
                        "type": "tx_status",
                        "delivery": frame["delivery"],
                        "ok": frame["delivery"] == 0,
                        "retries": frame["retries"],
                    }, loop)
            else:
                # Port object missing or closed — clean up and reconnect.
                _close_serial()
                _thread_broadcast({"type": "serial_status", "connected": False, "port": state.cfg.port}, loop)
                time.sleep(1)

        except Exception as e:
            # A genuine read/write failure (real disconnect). Close and reconnect.
            log_json(level="error", event="serial_read_error", error=str(e))
            _close_serial()
            _thread_broadcast({"type": "serial_status", "connected": False, "port": state.cfg.port}, loop)
            time.sleep(1)

    # Cleanup when the program stops
    _close_serial()
    log_json(event="serial_thread_stop")

async def serial_writer_worker():
    """
    Waits for commands in the queue and hands them to the reader thread to send.

    It must NOT write to the serial port directly: that would put a write on a
    different thread from the blocking read, which trips pyserial's "multiple
    access on port" error on Linux and causes a reconnect on every uplink. Instead
    it builds the API frame and pushes the bytes onto _tx_queue, which the single
    serial I/O thread drains between reads.
    """
    while True:
        # Wait for a command to appear in the queue
        cmd = await uplink_q.get()
        try:
            # Fast-fail with clear feedback if the radio isn't connected.
            if not _serial_connected.is_set():
                log_json(level="warn", event="uplink_dropped_no_serial", cmd=cmd)
                await broadcast_ws({"type": "error", "message": "UPLINK FAILED: Serial not connected."})
                continue

            # Wrap the command in an API Mode 2 Transmit Request frame (0x10) and
            # hand it to the reader thread for the actual write.
            data = _build_api2_tx_frame((cmd + "\r\n").encode())
            try:
                _tx_queue.put_nowait(data)
            except queue.Full:
                log_json(level="warn", event="uplink_dropped_tx_full", cmd=cmd)
                await broadcast_ws({"type": "error", "message": "UPLINK FAILED: TX buffer full."})
                continue

            log_json(subsystem="uplink", sent=cmd)
            ring.append(json.dumps({"uplink": cmd}))

        except Exception as e:
            log_json(level="error", event="uplink_error", error=str(e), cmd=cmd)
            await broadcast_ws({"type": "error", "message": f"UPLINK ERROR: {e}"})

# ===================== TELEMETRY PIPELINE (Processing Data) =====================
def now_utc_iso() -> str:
    """Returns the current time in UTC as a string."""
    return datetime.now(timezone.utc).isoformat()

_BROADCAST_BUDGET = 64  # Maximum simultaneously-scheduled broadcasts.
_pending_broadcasts: Set[asyncio.Future] = set()

def _thread_broadcast(payload: dict, loop) -> None:
    """Call broadcast_ws from a non-async thread. Drops the broadcast if too
    many are already pending so a slow event loop cannot grow an unbounded
    scheduling queue under high TX rates."""
    if len(_pending_broadcasts) >= _BROADCAST_BUDGET:
        return
    try:
        fut = asyncio.run_coroutine_threadsafe(broadcast_ws(payload), loop)
    except RuntimeError:
        return
    _pending_broadcasts.add(fut)
    fut.add_done_callback(_pending_broadcasts.discard)

async def broadcast_ws(payload: dict):
    """Sends a JSON message to all connected web browsers in parallel so a
    single slow client cannot back-pressure the telemetry pipeline."""
    text = json.dumps(payload)
    clients = list(ws_clients)
    if not clients:
        return
    results = await asyncio.gather(
        *[ws.send_text(text) for ws in clients],
        return_exceptions=True,
    )
    for ws, res in zip(clients, results):
        if isinstance(res, Exception):
            ws_clients.discard(ws)
            log_json(level="info", event="ws_client_disconnected", remaining=len(ws_clients))

async def handle_telemetry_line(raw: str):
    """
    Core function that handles each line of data received from the CanSat.
    Saves the raw line unconditionally FIRST, then parses it for the UI.
    """

    # ── STEP 0: Save RAW line unconditionally ────────────────────────────────
    # Every byte the CanSat sends is written to disk immediately, before any
    # parsing or validation. Nothing is ever discarded or lost.
    # Lock ensures concurrent writers (live serial + sim) never interleave bytes.
    if state.csv_ready:
        async with _csv_write_lock:
            async with aiofiles.open(get_active_csv(), "a", encoding="utf-8", newline="") as f:
                await f.write(raw + "\r\n")

    # ── STEP 1: Parse fields for UI display ──────────────────────────────
    reader = csv.reader([raw], skipinitialspace=True)
    try:
        parts = next(reader)
    except StopIteration:
        return

    parts = [p.strip() for p in parts]

    # If the packet has too few fields, show it in the UI log and stop here.
    # The raw data is already saved to CSV above so nothing is lost.
    min_required = len([x for x in TELEMETRY_CONFIG if not x.get("optional", False)])
    if len(parts) < min_required:
        ring.append(json.dumps({"bad_line": raw}))
        return

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
            if dtype == "int":   value = 0
            elif dtype == "float": value = 0.0
            else:                value = ""
        if key:
            parsed_data[key] = value

    # ── STEP 2: Build Telemetry object for WebSocket broadcast ───────────────
    # Increment rx_count FIRST so gs_rx_count is correct (was off-by-one).
    state.rx_count += 1
    parsed_data["gs_ts_utc"]    = now_utc_iso()
    parsed_data["gs_rx_count"]  = state.rx_count
    parsed_data["gs_loss_total"] = state.loss_count
    parsed_data["gs_raw_line"]  = raw

    try:
        tel = Telemetry(**parsed_data)
    except Exception as e:
        log_json(level="warn", event="telemetry_parse_error", error=str(e), raw=raw)
        return


    # 4b) Auto-save KML (Google Earth) — collect GPS points and write to disk
    gps_lat = parsed_data.get("gps_lat", 0.0)
    gps_lon = parsed_data.get("gps_lon", 0.0)
    gps_sats = parsed_data.get("gps_sats", 0)
    alt_m = parsed_data.get("altitude_m", 0.0)
    if isinstance(gps_lat, (int, float)) and isinstance(gps_lon, (int, float)):
        if gps_lat != 0.0 and gps_lon != 0.0 and gps_sats > 3:  # Only save with good GPS fix (>3 sats, matches UI)
            global _kml_gps_count
            state.kml_points.append({
                "lat":          gps_lat,
                "lon":          gps_lon,
                "alt":          max(0, alt_m),                              # barometric AGL
                "gps_alt":      float(parsed_data.get("gps_altitude_m") or 0),  # GPS ASL (absolute)
                "state":        parsed_data.get("state", "UNKNOWN"),
                "ts":           now_utc_iso(),                              # UTC for gx:Track animation
                "mission_time": str(parsed_data.get("mission_time", "")),
            })
            if alt_m > state.kml_max_alt:
                state.kml_max_alt = alt_m
            _kml_gps_count += 1
            if _kml_gps_count % 10 == 0:  # write KML to disk every 10 valid GPS packets
                await _save_kml()

    # Final KML save on landing — triggered once per session
    current_flight_state = parsed_data.get("state", "")
    if current_flight_state == "LANDED" and not state.kml_landed_saved:
        state.kml_landed_saved = True
        await _save_kml()
        kml_path = get_active_kml()
        log_json(event="kml_landing_save", file=str(kml_path))
        await broadcast_ws({"type": "kml_saved", "file": kml_path.name})

    # 5) Update counters (rx_count already incremented in step 2)
    state.last_current_a = parsed_data.get("current_a")
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
        fallback = ROOT_DIR / "cansat_2023_simp.txt"
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

                msg: Optional[str] = None
                if s.startswith("CMD,"):
                    msg = s
                else:
                    try:
                        float(s)  # accept both int and float pressure values
                        msg = f"CMD,{TEAM_ID:04},SIMP,{s}"
                    except ValueError:
                        pass  # skip header rows or unrecognised lines

                # Non-blocking put — preserves 1 Hz cadence even if queue is full.
                if msg is not None:
                    try:
                        uplink_q.put_nowait(msg)
                    except asyncio.QueueFull:
                        log_json(level="warn", event="sim_drop_full_queue", line=msg)

                # Wait 1 second between sends (Requirement: 1 Hz)
                await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        log_json(event="sim_cancelled", file=str(file_path))
        raise
    except Exception as e:
        log_json(level="error", event="sim_file_error", error=str(e), file=str(file_path))
            
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
    try:
        uplink_q.put_nowait(f"CMD,{TEAM_ID:04},SIM,ENABLE")
    except asyncio.QueueFull:
        log_json(level="warn", event="sim_drop_full_queue", line="SIM,ENABLE")
    log_json(event="sim_command", cmd="SIM,ENABLE")
    await asyncio.sleep(1.0) # Wait for radio/processing

    # 2. Activate Simulation Mode
    try:
        uplink_q.put_nowait(f"CMD,{TEAM_ID:04},SIM,ACTIVATE")
    except asyncio.QueueFull:
        log_json(level="warn", event="sim_drop_full_queue", line="SIM,ACTIVATE")
    log_json(event="sim_command", cmd="SIM,ACTIVATE")
    await asyncio.sleep(1.0)

    # 3. Stream
    await sim_file_streamer(file_path)

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
    _load_xbee_addr()   # restore the last-selected XBee address (survives restart)
    _select_serial_port_at_startup()
    ensure_csv_header()

    tasks = []
    serial_thread = None

    loop = asyncio.get_running_loop()

    if USE_SERVER_SERIAL:
        # Start Serial Reader Thread (this needs to be a thread because reading is blocking)
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

    yield  # The application runs here

    # Shutdown logic
    log_json(event="shutdown")

    # Cancel background async tasks and wait for them to finish cleanly.
    all_tasks = list(tasks)
    if sim_task and not sim_task.done():
        all_tasks.append(sim_task)
    for t in all_tasks:
        t.cancel()
    if all_tasks:
        await asyncio.gather(*all_tasks, return_exceptions=True)

    # Signal serial thread to stop and wait.
    _stop_event.set()
    if serial_thread:
        serial_thread.join(timeout=2)

app = FastAPI(title="CanSat Ground Station (Python)", lifespan=lifespan)

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
        "current_a": state.last_current_a,
        "rssi_dbm": state.rssi_dbm,
    }

@app.get("/api/logs")
async def api_logs(n: int = 500):
    """Returns the last N log messages."""
    n = max(1, min(n, 5000))
    # Slice the deque from the right without copying the entire buffer.
    from itertools import islice
    start = max(0, len(ring) - n)
    return list(islice(ring, start, len(ring)))

# ---- Serial config / ports ----
@app.get("/api/serial/ports")
async def api_serial_ports():
    """Lists all available USB serial ports."""
    # list_ports.comports() is a blocking OS call — run off the event loop.
    raw = await asyncio.to_thread(serial.tools.list_ports.comports)
    ports = [{"port": p.device, "info": f"{p.description} {p.hwid}"} for p in raw]
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
    
    # Ask the reader thread to reconnect in-thread. Closing the fd from this
    # threadpool thread while the reader is blocked in read() would itself trip
    # the "multiple access on port" error, so we never touch the port here.
    _reconnect_request.set()
    return {"ok": True}

# ---- Command uplink ----
@app.post("/api/command")
async def api_command(body: CommandBody):
    """
    Receives a command from the website (e.g., "CX,ON"),
    adds the Team ID prefix, and queues it to be sent.
    Reports last_cmd only after the queue accepts the request — does not
    falsely advertise a send when the uplink queue is full.
    """
    global sim_task
    cmd_upper = body.cmd.strip().upper()

    # body.cmd is something like "CX,ON"
    uplink = f"CMD,{TEAM_ID:04},{body.cmd.strip()}"

    # Non-blocking enqueue so a saturated uplink does not stall HTTP responses.
    try:
        uplink_q.put_nowait(uplink)
    except asyncio.QueueFull:
        log_json(level="warn", event="uplink_queue_full", cmd=uplink)
        raise HTTPException(status_code=503, detail="Uplink queue full — retry shortly")

    state.last_cmd = uplink

    # Trigger simulation file streaming if SIM,ACTIVATE is sent manually
    if cmd_upper == "SIM,ENABLE":
        state.sim_enabled = True
    elif cmd_upper == "SIM,DISABLE":
        state.sim_enabled = False
        if sim_task and not sim_task.done():
            sim_task.cancel()

    if cmd_upper == "SIM,ACTIVATE":
        if state.sim_enabled:
            # Replace any old finished task — but if a streamer is already
            # active, do not start a second one.
            if not (sim_task and not sim_task.done()):
                path = ROOT_DIR / "cansat_2023_simp.txt"
                sim_task = asyncio.create_task(sim_file_streamer(path))
        else:
            log_json(level="warn", event="sim_activate_ignored", reason="sim_not_enabled")

    return {"ok": True, "sent": uplink}

# ---- Simulation start ----
@app.post("/api/sim/start")
async def api_sim_start(file: Optional[str] = None):
    """Starts reading a simulation file."""
    # Default to the requirement file name
    filename = file or "cansat_2023_simp.txt"
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
    try:
        # Sanitize: alphanumeric, underscore, hyphen only; max 32 chars
        raw = body.label.strip().replace(" ", "_")
        label = re.sub(r"[^a-zA-Z0-9_\-]", "", raw)[:32]

        # Save the current session's KML before switching so no data is lost
        await _save_kml()

        state.log_label = label

        # Create the new CSV with a header if it doesn't exist yet
        new_csv = get_active_csv()
        ensure_csv_header(new_csv)

        # Reset KML state so this log gets its own flight path
        state.kml_points.clear()
        state.kml_max_alt = 0.0
        state.kml_landed_saved = False
        global _kml_gps_count
        _kml_gps_count = 0

        # Reset packet-loss and receive counters — fresh per-log statistics
        state.last_pkt   = None
        state.rx_count   = 0
        state.loss_count = 0

        # Clear ring buffer so reconnect-replay only ever shows this log's data.
        # The new log's CSV is the authoritative history source after this point.
        ring.clear()

        display = label or "default"
        log_json(event="log_switched", label=display, file=str(new_csv))

        await broadcast_ws({
            "type": "log_switched",
            "label": display,
            "file": new_csv.name,
        })
        return {"ok": True, "label": display, "file": str(new_csv)}
    except Exception as e:
        log_json(level="error", event="log_set_failed", error=str(e))
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

# ---- Frontend event logger ----
class GCSEventBody(BaseModel):
    event: str
    detail: Optional[str] = None

@app.post("/api/gcs/log_event")
async def api_gcs_log_event(body: GCSEventBody):
    """Writes a frontend-side event (e.g. mission timer start/stop) to ground.json."""
    kw: dict = {"event": body.event}
    if body.detail:
        kw["detail"] = body.detail
    log_json(**kw)
    return {"ok": True}

# ---- KML download endpoint ----
@app.post("/api/kml/save")
async def api_kml_save():
    """Force an immediate KML save to the data folder."""
    await _save_kml()
    kml_path = get_active_kml()
    if kml_path.exists():
        return {"ok": True, "file": kml_path.name, "path": str(kml_path)}
    return JSONResponse({"ok": False, "message": "Not enough GPS data to build KML yet"}, status_code=400)

@app.get("/api/kml")
async def api_kml_download():
    """Download the auto-saved KML file for the active log session."""
    kml_path = get_active_kml()
    if kml_path.exists():
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
            import shutil
            if shutil.which("pcmanfm"):
                subprocess.Popen(["pcmanfm", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)]) # Linux
        return True, None
    except Exception as e:
        return False, str(e)

_LOCALHOST_HOSTS = {"127.0.0.1", "::1", "localhost"}

@app.get("/api/csv/open-folder")
@app.get("/api/csv/open")  # alias used by app.js
async def api_csv_open_folder(request: Request):
    """Open the data folder — only allowed for local browsers since the folder
    pops on the SERVER desktop, not the client's. Remote clients get 403."""
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCALHOST_HOSTS:
        return JSONResponse(
            status_code=403,
            content={"ok": False, "error": "Open Folder is only available when running the GCS locally.", "path": str(DATA_DIR)},
        )
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



# ---- XBee address config ----
# The active address is persisted here so it survives a restart/reboot. Without
# this, a crash or `gcs restart` silently reverts to the default unit and
# commands would go to the wrong CanSat.
XBEE_STATE_FILE = DATA_DIR / "xbee_addr.json"

def _save_xbee_addr():
    """Persist the current XBee destination address to disk."""
    try:
        XBEE_STATE_FILE.write_text(json.dumps({"dh": state.xbee_dh, "dl": state.xbee_dl}))
    except Exception as e:
        log_json(level="error", event="xbee_save_failed", error=str(e))

def _load_xbee_addr():
    """Restore the saved XBee address on startup. Ignores a missing/corrupt file."""
    try:
        if not XBEE_STATE_FILE.exists():
            return
        d = json.loads(XBEE_STATE_FILE.read_text())
        dh = str(d.get("dh", "")).strip().upper()
        dl = str(d.get("dl", "")).strip().upper()
        # Validate before trusting the file — keep defaults if it's garbage.
        for v in (dh, dl):
            if len(v) != 8:
                raise ValueError("address field not 8 hex chars")
            bytes.fromhex(v)
        state.xbee_dh, state.xbee_dl = dh, dl
        log_json(event="xbee_addr_restored", dh=dh, dl=dl)
    except Exception as e:
        log_json(level="warn", event="xbee_load_failed", error=str(e))

def _validate_hex_field(val: str, label: str) -> str:
    """Validate and normalise an 8-char hex address field."""
    v = val.strip().upper().replace(" ", "")
    if len(v) != 8:
        raise HTTPException(400, detail=f"{label} must be exactly 8 hex characters")
    try:
        bytes.fromhex(v)
    except ValueError:
        raise HTTPException(400, detail=f"{label} contains invalid hex characters")
    return v

@app.get("/api/xbee/config")
async def api_xbee_get():
    """Returns the current XBee destination address."""
    return {
        "dh": state.xbee_dh,
        "dl": state.xbee_dl,
        "full": state.xbee_dh + state.xbee_dl,
        "default_dh": DEFAULT_XBEE_DH,
        "presets": XBEE_PRESETS,
    }

@app.post("/api/xbee/config")
async def api_xbee_set(body: XBeeCfg):
    """
    Update the XBee destination address at runtime.
    DH defaults to 0013A200 (same model modules share this).
    DL is the unique part — change this to target a different unit.
    Emergency: supply dh to override the high bytes too.
    """
    dh = _validate_hex_field(body.dh, "dh")
    dl = _validate_hex_field(body.dl, "dl")
    # Reject the broadcast address — commands must target one specific unit.
    if (dh + dl) == XBEE_BROADCAST_ADDR:
        raise HTTPException(400, detail="broadcast address (…FFFF) not allowed — choose a specific unit")
    old = state.xbee_dh + state.xbee_dl
    state.xbee_dh = dh
    state.xbee_dl = dl
    _save_xbee_addr()   # persist so it survives a restart
    log_json(event="xbee_addr_changed", old=old, new=dh + dl)
    await broadcast_ws({"type": "xbee_addr", "dh": dh, "dl": dl, "full": dh + dl})
    return {"ok": True, "dh": dh, "dl": dl, "full": dh + dl}

# ---- Static UI ----
@app.get("/cmd", include_in_schema=False)
async def cmd_panel():
    return FileResponse(UI_DIR / "cmd.html")

@app.get("/config", include_in_schema=False)
async def config_panel():
    return FileResponse(UI_DIR / "config.html")

# Serve the 'ui' folder as a website
app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")

if __name__ == "__main__":
    # This part runs when you execute 'python main.py'
    host = "0.0.0.0"
    port = 8080  # matches uvicorn command in README and systemd service

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
    print("Remote Access: Run 'ngrok http 8080' in a new terminal")
    print("="*50)

    print("Available serial ports:")
    ports = serial.tools.list_ports.comports()
    for p in sorted(ports, key=lambda x: x.device):
        print(f"- {p.device}: {p.description} [{p.hwid}]")
    print("="*50)

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    uvicorn.run(app, host=host, port=port, log_level="info")
