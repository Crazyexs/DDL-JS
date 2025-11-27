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

# ===================== CONFIG =====================
TEAM_ID = 1043
DEFAULT_PORT = "COM3"          # Linux: "/dev/ttyUSB0"; macOS: "/dev/tty.usbserial-XXXX"
DEFAULT_BAUD = 115200
USE_SERVER_SERIAL = True       # True = backend อ่าน/เขียน serial; False = เฉพาะ WebSerial ฝั่ง browser

# โฟลเดอร์หลัก
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
UI_DIR = ROOT_DIR / "ui"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
UI_DIR.mkdir(parents=True, exist_ok=True)

# CSV ปัจจุบัน (Flight_<TEAM>.csv)
CSV_CURRENT = DATA_DIR / f"Flight_{TEAM_ID:04}.csv"

BAUD_PRESETS = [9600, 19200, 38400, 57600, 115200, 230400, 250000, 460800, 921600]

CSV_HEADER = (
    "TEAM_ID,MISSION_TIME,PACKET_COUNT,MODE,STATE,ALTITUDE,TEMPERATURE,PRESSURE,VOLTAGE,CURRENT,"
    "GYRO_R,GYRO_P,GYRO_Y,ACCEL_R,ACCEL_P,ACCEL_Y,GPS_TIME,GPS_ALTITUDE,GPS_LATITUDE,GPS_LONGITUDE,GPS_SATS,CMD_ECHO,,"
    "HEADING"
)

# ===================== LOGGING =====================
logger = logging.getLogger("gs")
logger.setLevel(logging.INFO)
file_h = RotatingFileHandler(LOG_DIR / "ground.jsonl", maxBytes=5_000_000, backupCount=5)
file_h.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(file_h)
console = logging.StreamHandler()
console.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s %(message)s'))
logger.addHandler(console)

def log_json(**kw):
    logger.info(json.dumps(kw, ensure_ascii=False))

# ===================== MODELS =====================
class SerialCfg(BaseModel):
    port: str = Field(default=DEFAULT_PORT)
    baud: int = Field(default=DEFAULT_BAUD)

class CommandBody(BaseModel):
    # payload จาก UI เช่น "CX,ON" หรือ "ST,GPS" (ฝั่ง backend จะเติม "CMD,<TEAM_ID>," ให้อัตโนมัติ)
    cmd: str

class IngestBody(BaseModel):
    line: str

class Telemetry(BaseModel):
    team_id: int
    mission_time: str
    packet_count: int
    mode: str
    state: str
    altitude_m: float
    temperature_c: float
    pressure_kpa: float
    voltage_v: float
    current_a: float
    gyro_r_dps: float
    gyro_p_dps: float
    gyro_y_dps: float
    accel_r_dps2: float
    accel_p_dps2: float
    accel_y_dps2: float
    gps_time: str
    gps_altitude_m: float
    gps_lat: float
    gps_lon: float
    gps_sats: int
    cmd_echo: str
    
    # Optional data
    heading: Optional[float] = None
    
    # Ground station calculated fields
    gs_ts_utc: str
    gs_rx_count: int
    gs_loss_total: int
    gs_raw_line: Optional[str] = None

# ===================== GLOBAL STATE =====================
@dataclass
class GSState:
    cfg: SerialCfg = field(default_factory=SerialCfg)
    rx_count: int = 0
    loss_count: int = 0
    last_pkt: Optional[int] = None
    csv_ready: bool = False
    last_cmd: str = "—"

state = GSState()
ring: Deque[str] = deque(maxlen=10_000)   # /api/logs
ws_clients: Set[WebSocket] = set()
uplink_q: asyncio.Queue[str] = asyncio.Queue()

_serial_transport = None
_serial_writer_lock = asyncio.Lock()

def ensure_csv_header():
    if not CSV_CURRENT.exists():
        CSV_CURRENT.write_text(CSV_HEADER + "\r\n", encoding="utf-8", newline="\r\n")
    state.csv_ready = True

ensure_csv_header()

# ===================== SERIAL (Threaded/Blocking for Windows Stability) =====================
import threading
import time

# Shared serial object (protected by logic, single writer)
_serial_port: Optional[serial.Serial] = None
_serial_lock = threading.Lock()
_stop_event = threading.Event()

def serial_read_thread_target(loop):
    """
    Runs in a separate thread.
    1. Tries to open serial port.
    2. Reads lines in a blocking loop.
    3. Dispatches lines to the main asyncio loop.
    """
    global _serial_port
    
    log_json(event="serial_thread_start")

    while not _stop_event.is_set():
        # 1. Connect
        if _serial_port is None:
            try:
                # Only check availability occasionally to avoid spam
                available_ports = [p.device for p in serial.tools.list_ports.comports()]
                if state.cfg.port not in available_ports:
                    log_json(level="error", event="port_not_found", port=state.cfg.port, available=available_ports)
                    time.sleep(5)
                    continue

                log_json(event="serial_connecting", port=state.cfg.port, baud=state.cfg.baud)
                ser = serial.Serial(state.cfg.port, state.cfg.baud, timeout=1)
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

        # 2. Read Loop
        try:
            if _serial_port and _serial_port.is_open:
                # Blocking read (timeout=1 allows checking _stop_event)
                line_bytes = _serial_port.readline()
                if line_bytes:
                    try:
                        line = line_bytes.decode(errors="ignore").rstrip("\r\n")
                        if line:
                            # Dispatch to main loop
                            asyncio.run_coroutine_threadsafe(handle_telemetry_line(line), loop)
                    except Exception:
                        pass
            else:
                # Should not happen if logic is correct, but safety net
                with _serial_lock:
                    _serial_port = None
                time.sleep(1)

        except Exception as e:
            log_json(level="error", event="serial_read_error", error=str(e))
            with _serial_lock:
                if _serial_port:
                    try:
                        _serial_port.close()
                    except: 
                        pass
                    _serial_port = None
            time.sleep(1)

    # Cleanup on exit
    with _serial_lock:
        if _serial_port:
            _serial_port.close()
    log_json(event="serial_thread_stop")

async def serial_writer_worker():
    """
    Async task that pulls from uplink_q and writes to the serial port
    using the shared _serial_port object (thread-safe write).
    """
    while True:
        cmd = await uplink_q.get()
        try:
            data = (cmd + "\r\n").encode()
            
            # Write is fast, but we use the lock to ensure the port doesn't vanish mid-write
            # or conflict if we had multiple writers (we don't, but safety first)
            wrote = False
            with _serial_lock:
                if _serial_port and _serial_port.is_open:
                    _serial_port.write(data)
                    _serial_port.flush()
                    wrote = True
            
            if wrote:
                log_json(subsystem="uplink", sent=cmd)
                ring.append(json.dumps({"uplink": cmd}))
            else:
                log_json(level="warn", event="uplink_dropped_no_serial", cmd=cmd)
                await broadcast_ws({"type": "error", "message": f"UPLINK FAILED: Serial not connected."})

        except Exception as e:
            log_json(level="error", event="uplink_error", error=str(e), cmd=cmd)
            await broadcast_ws({"type": "error", "message": f"UPLINK ERROR: {e}"})

# ===================== TELEMETRY PIPELINE =====================
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

async def broadcast_ws(payload: dict):
    text = json.dumps(payload)
    dead = []
    
    # Safe client list generation
    client_list = []
    for ws in ws_clients:
        c = ws.client
        if c:
            client_list.append(f"{c.host}:{c.port}")
        else:
            client_list.append("unknown")
            
    log_json(event="ws_broadcast", clients=client_list)
    for ws in list(ws_clients):
        try:
            await ws.send_text(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)

async def handle_telemetry_line(raw: str):
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) < 22: # Minimum fields as per spec
        ring.append(json.dumps({"bad_line": raw}))
        log_json(level="warn", event="telemetry_short", len=len(parts))
        return

    # 1) Parse first to ensure validity before logging
    s_f = lambda i, d=0.0: float(parts[i]) if len(parts) > i and parts[i] else d
    s_i = lambda i, d=0: int(parts[i]) if len(parts) > i and parts[i] else d
    s_s = lambda i, d='': str(parts[i]) if len(parts) > i and parts[i] else d
    
    tel = Telemetry(
        team_id=s_i(0, TEAM_ID),
        mission_time=s_s(1),
        packet_count=s_i(2),
        mode=s_s(3),
        state=s_s(4),
        altitude_m=s_f(5),
        temperature_c=s_f(6),
        pressure_kpa=s_f(7),
        voltage_v=s_f(8),
        current_a=s_f(9),
        gyro_r_dps=s_f(10),
        gyro_p_dps=s_f(11),
        gyro_y_dps=s_f(12),
        accel_r_dps2=s_f(13),
        accel_p_dps2=s_f(14),
        accel_y_dps2=s_f(15),
        gps_time=s_s(16),
        gps_altitude_m=s_f(17),
        gps_lat=s_f(18),
        gps_lon=s_f(19),
        gps_sats=s_i(20),
        cmd_echo=s_s(21),
        # Optional data
        heading=s_f(22),
        # Ground station calculated fields
        gs_ts_utc=now_utc_iso(),
        gs_rx_count=state.rx_count + 1, # Increment before creation
        gs_loss_total=state.loss_count
    )

    # 2) Reconstruct CLEAN CSV line for logging (Rule G2 compliance)
    # We use the parsed values to ensure format uniformity (no random spaces, correct decimal places)
    # Note the double comma before HEADING to satisfy "Optional Data" spec
    clean_csv = (
        f"{tel.team_id},{tel.mission_time},{tel.packet_count},{tel.mode},{tel.state},"
        f"{tel.altitude_m:.2f},{tel.temperature_c:.1f},{tel.pressure_kpa:.2f},"
        f"{tel.voltage_v:.2f},{tel.current_a:.2f},"
        f"{tel.gyro_r_dps:.2f},{tel.gyro_p_dps:.2f},{tel.gyro_y_dps:.2f},"
        f"{tel.accel_r_dps2:.2f},{tel.accel_p_dps2:.2f},{tel.accel_y_dps2:.2f},"
        f"{tel.gps_time},{tel.gps_altitude_m:.2f},{tel.gps_lat:.5f},{tel.gps_lon:.5f},{tel.gps_sats},"
        f"{tel.cmd_echo},,{tel.heading if tel.heading is not None else ''}"
    )

    # 3) append CLEAN row to CSV
    if state.csv_ready:
        with CSV_CURRENT.open("a", encoding="utf-8", newline="") as f:
            f.write(clean_csv + "\r\n")

    # 4) counters
    state.rx_count += 1
    try:
        pkt = int(parts[2])
    except Exception:
        pkt = 0
    if state.last_pkt is not None and pkt > state.last_pkt + 1:
        state.loss_count += (pkt - state.last_pkt - 1)
    state.last_pkt = pkt

    # 5) build JSON for clients
    payload = tel.dict()
    payload['gs_raw_line'] = raw # Still send raw to UI for debugging if needed
    await broadcast_ws(payload)
    ring.append(json.dumps({"telemetry": payload}))

# ===================== SIM MODE SENDER =====================
async def sim_sender(file_path: Path):
    await uplink_q.put(f"CMD,{TEAM_ID:04},SIM,ENABLE")
    await asyncio.sleep(0.2)
    await uplink_q.put(f"CMD,{TEAM_ID:04},SIM,ACTIVATE")
    await asyncio.sleep(0.2)

    if not file_path.exists():
        log_json(level="error", event="sim_file_missing", file=str(file_path)); return

    with file_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            await uplink_q.put(f"CMD,{TEAM_ID:04},SIMP,{s}")
            await asyncio.sleep(1.0)
    log_json(event="sim_complete", file=str(file_path))

# ===================== DUMMY DATA (for testing) =====================
dummy_task: Optional[asyncio.Task] = None
dummy_state = {
    "packet": 0,
    "lat": 18.788,
    "lon": 98.985,
    "last_alt": 0.0,
}

def hms_from_seconds(s: float) -> str:
    s = int(s)
    hours = s // 3600
    minutes = (s % 3600) // 60
    seconds = s % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def generate_dummy_telemetry_line() -> str:
    dummy_state["packet"] += 1
    pkt = dummy_state["packet"]
    
    dummy_state["lat"] += (random.random() - 0.5) * 0.0002
    dummy_state["lon"] += (random.random() - 0.5) * 0.0002
    
    altitude = 150 + math.sin(pkt / 30) * 120 + (random.random() - 0.5) * 5
    temp = 25 - (altitude / 100)
    voltage = 12.6 - (pkt / 500)
    current = 0.5 + (random.random() - 0.5) * 0.2
    
    mission_time = hms_from_seconds(pkt) # Simple mission time based on packet count
    
    state = 'LAUNCH_PAD'
    if altitude > 20:
        if altitude > dummy_state["last_alt"]:
            state = 'ASCENT'
        else:
            state = 'DESCENT'
    dummy_state["last_alt"] = altitude

    line = [
        str(TEAM_ID),
        mission_time,
        str(pkt),
        'F', # Mode
        state,
        f"{altitude:.2f}",
        f"{temp:.2f}",
        f"{101.325 * math.pow(1 - 2.25577e-5 * altitude, 5.25588):.3f}", # Pressure
        f"{voltage:.2f}",
        f"{current:.3f}",
        f"{(random.random() - 0.5) * 20:.3f}", # Gyro R
        f"{(random.random() - 0.5) * 20:.3f}", # Gyro P
        f"{180 + (random.random() - 0.5) * 40:.3f}", # Gyro Y
        f"{(random.random() - 0.5) * 2:.3f}", # Accel R
        f"{(random.random() - 0.5) * 2:.3f}", # Accel P
        f"{9.8 + (random.random() - 0.5):.3f}", # Accel Y
        datetime.now(timezone.utc).strftime("%H:%M:%S"), # GPS Time
        f"{altitude + 10:.2f}", # GPS Alt
        f"{dummy_state['lat']:.4f}",
        f"{dummy_state['lon']:.4f}",
        str(random.randint(8, 12)), # GPS Sats
        "CMD_OK" if pkt % 10 != 0 else "CX,ON",
        f"{(pkt * 5) % 360:.2f}", # Heading
    ]
    return ",".join(line)

async def dummy_data_sender():
    log_json(event="dummy_data_started")
    while True:
        line = generate_dummy_telemetry_line()
        await handle_telemetry_line(line)
        await asyncio.sleep(1)


# ===================== FASTAPI APP & LIFESPAN =====================
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    log_json(event="startup", team=TEAM_ID, server_serial=USE_SERVER_SERIAL)
    ensure_csv_header()
    
    tasks = []
    serial_thread = None

    if USE_SERVER_SERIAL:
        # Start Serial Reader Thread
        loop = asyncio.get_running_loop()
        serial_thread = threading.Thread(target=serial_read_thread_target, args=(loop,), daemon=True)
        serial_thread.start()
        
        # Start Serial Writer Task
        tasks.append(asyncio.create_task(serial_writer_worker()))
    
    async def ws_ping():
        while True:
            await asyncio.sleep(10)
            await broadcast_ws({"type": "ping"})
            
    tasks.append(asyncio.create_task(ws_ping()))
    
    yield
    
    # Shutdown
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
    global dummy_task
    if dummy_task and not dummy_task.done():
        return {"ok": False, "message": "Dummy task already running"}
    dummy_state["packet"] = 0
    dummy_task = asyncio.create_task(dummy_data_sender())
    return {"ok": True}

@app.post("/api/dummy/stop")
async def api_dummy_stop():
    global dummy_task
    if dummy_task and not dummy_task.done():
        dummy_task.cancel()
        log_json(event="dummy_data_stopped")
        return {"ok": True}
    return {"ok": False, "message": "Dummy task not running"}

# ===================== FASTAPI APP =====================

# ---- Health / Logs ----
@app.get("/api/health")
async def api_health():
    return {
        "serial": {"port": state.cfg.port, "baud": state.cfg.baud, "server_serial": USE_SERVER_SERIAL},
        "csv": str(CSV_CURRENT),
        "rx": {"received": state.rx_count, "lost": state.loss_count},
        "last_cmd": state.last_cmd,
    }

@app.get("/api/logs")
async def api_logs(n: int = 500):
    n = max(1, min(n, 5000))
    return list(ring)[-n:]

# ---- Serial config / ports ----
@app.get("/api/serial/ports")
async def api_serial_ports():
    ports = [{"port": p.device, "info": f"{p.description} {p.hwid}"} for p in serial.tools.list_ports.comports()]
    return {"ports": ports}

@app.get("/api/serial/bauds")
async def api_serial_bauds():
    return {"presets": BAUD_PRESETS}

@app.get("/api/serial/config")
async def api_serial_get():
    return state.cfg.dict()

@app.post("/api/serial/config")
async def api_serial_set(cfg: SerialCfg):
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

# ---- Command uplink (backend เติม prefix CMD,<TEAM_ID>,...) ----
@app.post("/api/command")
async def api_command(body: CommandBody):
    # body.cmd เช่น "CX,ON" หรือ "ST,GPS"
    uplink = f"CMD,{TEAM_ID:04},{body.cmd.strip()}"
    state.last_cmd = uplink
    await uplink_q.put(uplink)
    return {"ok": True, "sent": uplink}

# ---- Simulation start ----
@app.post("/api/sim/start")
async def api_sim_start(file: Optional[str] = None):
    path = Path(file or "sim_pressure.csv")
    asyncio.create_task(sim_sender(path))
    return {"ok": True, "running": True, "file": str(path)}

# ---- Browser → Server telemetry ingest (WebSerial ฝั่ง browser) ----
@app.post("/api/ingest")
async def api_ingest(body: IngestBody):
    line = body.line.strip()
    if not line:
        raise HTTPException(400, detail="empty")
    await handle_telemetry_line(line)
    return {"ok": True}

# ---- CSV folder open / save-now ----
def _open_folder(path: Path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True, None
    except Exception as e:
        return False, str(e)

@app.get("/api/csv/open-folder")
async def api_csv_open_folder():
    if not DATA_DIR.exists():
        return JSONResponse(status_code=404, content={"ok": False, "error": "Folder not found", "path": str(DATA_DIR)})
    ok, err = _open_folder(DATA_DIR)
    if not ok:
        return JSONResponse(status_code=500, content={"ok": False, "error": err, "path": str(DATA_DIR)})
    return {"ok": True, "path": str(DATA_DIR)}

@app.post("/api/csv/save-now")
async def api_csv_save_now(payload: dict = Body(...)):
    """
    payload: { "rows": [ "TEAM_ID,...", ... ] }
    - ถ้าไม่ส่ง rows มา จะ error 400 (UI ควรส่ง rows หรือ ingest มาก่อน)
    - บันทึกไฟล์เป็น Flight_<TEAM_ID>.csv; ถ้าซ้ำ จะเพิ่ม (1), (2), ...
    """
    rows: List[str] = payload.get("rows") or []
    if not rows:
        return JSONResponse(status_code=400, content={"ok": False, "error": "no rows"})

    # หา TEAM_ID จากคอลัมน์แรกของบรรทัดใดบรรทัดหนึ่ง
    team_id = f"{TEAM_ID:04}"
    for line in rows:
        p0 = (line.split(",", 1)[0] or "").strip()
        if p0.isdigit():
            team_id = p0.zfill(4)
            break

    out_path = DATA_DIR / f"Flight_{team_id}.csv"
    i = 1
    while out_path.exists():
        out_path = DATA_DIR / f"Flight_{team_id}({i}).csv"
        i += 1

    content = CSV_HEADER + "\r\n" + "\r\n".join(rows) + "\r\n"
    out_path.write_text(content, encoding="utf-8", newline="\r\n")
    return {"ok": True, "path": str(out_path)}

# ---- WebSocket ----
@app.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    
    c = ws.client
    c_info = f"{c.host}:{c.port}" if c else "unknown"
    log_json(event="ws_connected", client=c_info)
    try:
        while True:
            await ws.receive_text()   # no-op; แค่ detect disconnect
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)
        c = ws.client
        c_info = f"{c.host}:{c.port}" if c else "unknown"
        log_json(event="ws_disconnected", client=c_info)

# ---- Static UI (same origin) ----
app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")

# ---- Startup/Shutdown (Handled by lifespan) ----
# @app.on_event("startup") / @app.on_event("shutdown") removed.

if __name__ == "__main__":
    host = "0.0.0.0"
    port = 8000

    try:
        # Try to find the actual local IP for display purposes
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # doesn't even have to be reachable
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