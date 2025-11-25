import uvicorn
import socket

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
import serial.tools.list_ports
import serial_asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from datetime import datetime, timezone

# ===================== CONFIG =====================
TEAM_ID = 1043
DEFAULT_PORT = "COM5"          # Linux: "/dev/ttyUSB0"; macOS: "/dev/tty.usbserial-XXXX"
DEFAULT_BAUD = 115200
USE_SERVER_SERIAL = True       # True = backend อ่าน/เขียน serial; False = เฉพาะ WebSerial ฝั่ง browser

# โฟลเดอร์หลัก
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(r"C:\Users\Admin\Downloads\DDL-JS\data")  # ตามที่ผู้ใช้ระบุ
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
    "GYRO_R,GYRO_P,GYRO_Y,ACCEL_R,ACCEL_P,ACCEL_Y,GPS_TIME,GPS_ALTITUDE,GPS_LATITUDE,GPS_LONGITUDE,GPS_SATS,CMD_ECHO,"
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

# ===================== SERIAL (server-side) =====================
class LineReader(asyncio.Protocol):
    def __init__(self):
        self.buf = bytearray()

    def connection_made(self, transport):
        global _serial_transport
        _serial_transport = transport
        log_json(event="serial_connected", port=state.cfg.port, baud=state.cfg.baud)

    def data_received(self, data: bytes):
        self.buf.extend(data)
        while b'\n' in self.buf:
            line, _, rest = self.buf.partition(b'\n')
            self.buf = bytearray(rest)
            s = line.decode(errors="ignore").rstrip("\r")
            asyncio.create_task(handle_telemetry_line(s))

    def connection_lost(self, exc):
        global _serial_transport
        log_json(event="serial_disconnected", reason=str(exc) if exc else "EOF")
        _serial_transport = None

async def open_serial():
    while True:
        try:
            # โปรดทราบ: ต้องมี pyserial-asyncio ติดตั้งอยู่
            await serial_asyncio.create_serial_connection(
                asyncio.get_running_loop(), LineReader, state.cfg.port, baudrate=state.cfg.baud
            )
            return
        except Exception as e:
            log_json(level="warn", event="serial_open_failed", port=state.cfg.port, baud=state.cfg.baud, error=str(e))
            await asyncio.sleep(2)

async def serial_reader_manager():
    while True:
        await open_serial()
        while _serial_transport is not None:
            await asyncio.sleep(0.5)

async def serial_writer_worker():
    while True:
        cmd = await uplink_q.get()
        data = (cmd + "\r\n").encode()
        async with _serial_writer_lock:
            if _serial_transport is None:
                log_json(level="warn", event="uplink_dropped_cmd_no_serial", cmd=cmd)
                await broadcast_ws({"type": "error", "message": f"UPLINK FAILED for '{cmd}': No serial port."})
            else:
                try:
                    _serial_transport.write(data)
                    log_json(subsystem="uplink", sent=cmd)
                    ring.append(json.dumps({"uplink": cmd}))
                except Exception as e:
                    log_json(level="error", event="serial_write_error", error=str(e), cmd=cmd)
                    await broadcast_ws({"type": "error", "message": f"UPLINK FAILED for '{cmd}': {e}"})

# ===================== TELEMETRY PIPELINE =====================
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

async def broadcast_ws(payload: dict):
    text = json.dumps(payload)
    dead = []
    log_json(event="ws_broadcast", clients=[f"{ws.client.host}:{ws.client.port}" for ws in ws_clients])
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

    # 1) append exact row to CSV
    if state.csv_ready:
        with CSV_CURRENT.open("a", encoding="utf-8", newline="") as f:
            f.write(raw + "\r\n")

    # 2) counters
    state.rx_count += 1
    try:
        pkt = int(parts[2])
    except Exception:
        pkt = 0
    if state.last_pkt is not None and pkt > state.last_pkt + 1:
        state.loss_count += (pkt - state.last_pkt - 1)
    state.last_pkt = pkt

    # 3) build JSON for clients
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
        gs_rx_count=state.rx_count,
        gs_loss_total=state.loss_count
    )
    payload = tel.dict()
    payload['gs_raw_line'] = raw
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

# ===================== FASTAPI APP =====================
app = FastAPI(title="CanSat Ground Station (Python)")

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
    global _serial_transport
    if _serial_transport is not None:
        try:
            _serial_transport.close()
        except Exception:
            pass
        _serial_transport = None
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
    log_json(event="ws_connected", client=f"{ws.client.host}:{ws.client.port}")
    try:
        while True:
            await ws.receive_text()   # no-op; แค่ detect disconnect
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)
        log_json(event="ws_disconnected", client=f"{ws.client.host}:{ws.client.port}")

# ---- Static UI (same origin) ----
app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")

# ---- Startup/Shutdown ----
@app.on_event("startup")
async def _startup():
    log_json(event="startup", team=TEAM_ID, server_serial=USE_SERVER_SERIAL)
    ensure_csv_header()
    if USE_SERVER_SERIAL:
        asyncio.create_task(serial_reader_manager())
        asyncio.create_task(serial_writer_worker())
    
    async def ws_ping():
        while True:
            await asyncio.sleep(10)
            await broadcast_ws({"type": "ping"})
            
    asyncio.create_task(ws_ping())

@app.on_event("shutdown")
async def _shutdown():
    log_json(event="shutdown")

if __name__ == "__main__":
    host = "0.0.0.0"
    port = 8000

    # Get local IP address
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = "127.0.0.1"
    finally:
        s.close()

    print("="*50)
    print("Daedalus Ground Station")
    print(f"Access the UI from this computer at: http://localhost:{port}")
    print(f"Access the UI from other devices on the same network at: http://{local_ip}:{port}")
    print("="*50)

    uvicorn.run(app, host=host, port=port)
