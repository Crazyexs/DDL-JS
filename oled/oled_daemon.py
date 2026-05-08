#!/usr/bin/env python3
"""
Daedalus GCS — OLED Display Daemon
128×64 SSD1306 / SH1106 via I²C (default) or SPI

R3/R5 pads → I²C mode  (SDA=GPIO2/pin3, SCL=GPIO3/pin5)
R4 pad     → SPI mode   (standard SPI0 pins)

Modes:
  startup      Boot animation + 4 status checks  [auto on launch]
  pi_stats     CPU / RAM / Temp / Voltage         [default after boot]
  telemetry    Live CanSat values picked in /display
  custom_text  User-typed message from /display
  pixel_art    128×64 image pushed from /display

State file : /tmp/daedalus_oled.json   (written by GCS backend)
GCS API    : http://127.0.0.1:8080     (polled for live telemetry)
"""

import sys
import os
import time
import json
import logging
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

import psutil
from PIL import Image, ImageDraw, ImageFont

# ── luma.oled ────────────────────────────────────────────────────────────────
try:
    from luma.core.interface.serial import i2c, spi
    from luma.oled.device import ssd1306, sh1106
    LUMA_OK = True
except ImportError:
    LUMA_OK = False

# ── Constants ─────────────────────────────────────────────────────────────────
GCS_URL    = "http://127.0.0.1:8080"
STATE_FILE = Path("/tmp/daedalus_oled.json")
WIDTH, HEIGHT = 128, 64

# I²C defaults (R3/R5 pads → I²C)
I2C_PORT = 1
I2C_ADDR = 0x3C   # some modules use 0x3D

# SPI defaults (R4 pad → SPI)
SPI_DEVICE  = 0
SPI_PORT    = 0
SPI_DC_PIN  = 24
SPI_RST_PIN = 25

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
MONO_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
GPS_FIX_TIMEOUT = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [oled] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("oled")


# ── Font loader ───────────────────────────────────────────────────────────────
def _font(size: int, mono: bool = False) -> ImageFont.ImageFont:
    path = MONO_PATH if mono else FONT_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


# Pre-load sizes we actually use
F8  = _font(8)
F9  = _font(9)
F10 = _font(10)
F12 = _font(12)
F16 = _font(16)
F20 = _font(20)
FM8 = _font(8,  mono=True)
FM9 = _font(9,  mono=True)
FM10= _font(10, mono=True)


# ── Display init ──────────────────────────────────────────────────────────────
def init_display(interface: str = "i2c"):
    if not LUMA_OK:
        log.error("luma.oled not installed — run: pip install luma.oled")
        return None
    try:
        if interface == "spi":
            ser = spi(device=SPI_DEVICE, port=SPI_PORT,
                      gpio_DC=SPI_DC_PIN, gpio_RST=SPI_RST_PIN)
        else:
            ser = i2c(port=I2C_PORT, address=I2C_ADDR)
        dev = ssd1306(ser, width=WIDTH, height=HEIGHT)
        log.info(f"OLED ready ({interface.upper()}, {WIDTH}×{HEIGHT}, addr=0x{I2C_ADDR:02X})")
        return dev
    except Exception as e:
        log.error(f"OLED init failed: {e}")
        return None


# ── State file ────────────────────────────────────────────────────────────────
_state_mtime = 0.0
_state_cache: dict = {"mode": "startup"}


def read_state() -> dict:
    global _state_mtime, _state_cache
    try:
        mtime = STATE_FILE.stat().st_mtime
        if mtime != _state_mtime:
            _state_mtime = mtime
            _state_cache = json.loads(STATE_FILE.read_text())
    except Exception:
        pass
    return _state_cache


def write_state(patch: dict) -> None:
    cur = read_state().copy()
    cur.update(patch)
    STATE_FILE.write_text(json.dumps(cur))


# ── System stats ──────────────────────────────────────────────────────────────
def pi_stats() -> dict:
    cpu  = psutil.cpu_percent(interval=None)
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    temp = 0.0
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text()
        temp = int(raw.strip()) / 1000.0
    except Exception:
        try:
            for vals in (psutil.sensors_temperatures() or {}).values():
                if vals:
                    temp = vals[0].current
                    break
        except Exception:
            pass

    volt = 0.0
    try:
        out = subprocess.check_output(
            ["vcgencmd", "measure_volts", "core"], timeout=1, text=True
        )
        volt = float(out.strip().replace("volt=", "").replace("V", ""))
    except Exception:
        pass

    ip = "n/a"
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    return {
        "cpu": cpu,
        "ram_pct": mem.percent,
        "disk_pct": disk.percent,
        "temp": temp,
        "volt": volt,
        "ip": ip,
    }


# ── GCS API helpers ───────────────────────────────────────────────────────────
def _get(path: str, timeout: float = 2.0) -> dict:
    try:
        with urllib.request.urlopen(f"{GCS_URL}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def check_health() -> dict:
    h = _get("/api/health", timeout=3)
    return {
        "api":    bool(h),
        "serial": bool(h.get("serial", {}).get("server_serial")),
        "csv":    bool(h.get("csv")),
    }


def fetch_telemetry() -> dict:
    return _get("/api/display/data")


# ── Drawing helpers ───────────────────────────────────────────────────────────
def new_img() -> tuple:
    img = Image.new("1", (WIDTH, HEIGHT), 0)
    return img, ImageDraw.Draw(img)


def hbar(draw, x: int, y: int, w: int, h: int, pct: float) -> None:
    draw.rectangle([x, y, x + w - 1, y + h - 1], outline=1, fill=0)
    filled = max(0, min(w - 2, int((w - 2) * pct / 100)))
    if filled:
        draw.rectangle([x + 1, y + 1, x + filled, y + h - 2], fill=1)


def text_w(draw, text: str, font) -> int:
    try:
        return draw.textbbox((0, 0), text, font=font)[2]
    except AttributeError:
        return len(text) * 6


# ── Render: startup title ─────────────────────────────────────────────────────
def render_title(device) -> None:
    img, d = new_img()
    d.text((8, 4),  "DAEDALUS GCS",   font=F12, fill=1)
    d.line([(0, 20), (127, 20)],       fill=1)
    d.text((18, 24), "Ground Station", font=F9,  fill=1)
    d.line([(0, 43), (127, 43)],       fill=1)
    d.text((30, 47), "Booting...",     font=F9,  fill=1)
    device.display(img)


# ── Render: status checks ─────────────────────────────────────────────────────
def render_checks(device, results: list) -> None:
    """results = [(label, True|False|None), ...]  None = pending"""
    img, d = new_img()
    d.text((0, 0), "SYSTEM CHECK", font=FM8, fill=1)
    d.line([(0, 11), (127, 11)], fill=1)
    for i, (label, ok) in enumerate(results):
        y = 14 + i * 12
        d.text((2, y), label, font=FM8, fill=1)
        if ok is None:
            badge = "[......]"
        elif ok:
            badge = "[  OK  ]"
        else:
            badge = "[ FAIL ]"
        d.text((78, y), badge, font=FM8, fill=1)
    device.display(img)


# ── Render: Pi stats ──────────────────────────────────────────────────────────
def render_pi_stats(device, s: dict) -> None:
    img, d = new_img()
    # Header
    d.text((0, 0), "Pi STATS", font=FM8, fill=1)
    d.text((65, 0), f"T:{s['temp']:.0f}°C", font=FM8, fill=1)
    d.line([(0, 10), (127, 10)], fill=1)
    # CPU
    d.text((0, 13), f"CPU {s['cpu']:4.0f}%", font=FM8, fill=1)
    hbar(d, 62, 14, 64, 8, s["cpu"])
    # RAM
    d.text((0, 25), f"RAM {s['ram_pct']:4.0f}%", font=FM8, fill=1)
    hbar(d, 62, 26, 64, 8, s["ram_pct"])
    # Disk
    d.text((0, 37), f"DSK {s['disk_pct']:4.0f}%", font=FM8, fill=1)
    hbar(d, 62, 38, 64, 8, s["disk_pct"])
    # Footer
    d.line([(0, 49), (127, 49)], fill=1)
    d.text((0, 52), f"{s['volt']:.2f}V", font=FM8, fill=1)
    d.text((44, 52), s["ip"][:18], font=FM8, fill=1)
    device.display(img)


# ── Render: telemetry fields ──────────────────────────────────────────────────
def render_telemetry(device, data: dict, fields: list) -> None:
    img, d = new_img()
    fields = (fields or [])[:4]
    if not fields:
        d.text((4, 20), "No fields selected.", font=F9,  fill=1)
        d.text((4, 34), "Use /display page.",  font=FM8, fill=1)
        device.display(img)
        return

    row_h = HEIGHT // len(fields)
    font_val = [F20, F16, F12, F10][len(fields) - 1]

    for i, key in enumerate(fields):
        y0 = i * row_h
        label = key.replace("_", " ").upper()
        raw = data.get(key, "—")
        if isinstance(raw, float):
            val_str = f"{raw:.2f}"
        else:
            val_str = str(raw)

        d.text((0, y0), label, font=FM8, fill=1)
        d.text((0, y0 + 9), val_str, font=font_val, fill=1)
        if i < len(fields) - 1:
            d.line([(0, y0 + row_h - 1), (127, y0 + row_h - 1)], fill=1)

    device.display(img)


# ── Render: custom text ───────────────────────────────────────────────────────
def render_custom_text(device, text: str) -> None:
    img, d = new_img()
    if not text.strip():
        d.text((20, 28), "No text set.", font=F9, fill=1)
        device.display(img)
        return

    lines = text.strip().split("\n")[:6]
    total = len(lines)
    font = (F20 if total == 1 and len(lines[0]) <= 10
            else F16 if total <= 2
            else F10 if total <= 4
            else F9)
    lh = font.size if hasattr(font, "size") else 12
    y0 = max(0, (HEIGHT - lh * total) // 2)

    for i, line in enumerate(lines):
        tw = text_w(d, line, font)
        x = max(0, (WIDTH - tw) // 2)
        d.text((x, y0 + i * lh), line[:22], font=font, fill=1)

    device.display(img)


# ── Render: pixel art ─────────────────────────────────────────────────────────
def render_pixel_art(device, b64_png: str) -> None:
    import base64, io
    try:
        raw = base64.b64decode(b64_png)
        src = Image.open(io.BytesIO(raw)).convert("1").resize((WIDTH, HEIGHT))
        device.display(src)
    except Exception as e:
        img, d = new_img()
        d.text((4, 26), "Image error:", font=FM8, fill=1)
        d.text((4, 36), str(e)[:20],   font=FM8, fill=1)
        device.display(img)


# ── Startup sequence ──────────────────────────────────────────────────────────
def run_startup(device) -> None:
    render_title(device)
    time.sleep(1.5)

    results = [
        ("API Health", None),
        ("XBee Radio", None),
        ("CSV Store",  None),
        ("Fan Status", None),
    ]
    render_checks(device, results)
    time.sleep(0.3)

    h = check_health()
    results[0] = ("API Health", h["api"])
    render_checks(device, results)
    time.sleep(0.3)

    results[1] = ("XBee Radio", h["serial"])
    render_checks(device, results)
    time.sleep(0.3)

    results[2] = ("CSV Store",  h["csv"])
    render_checks(device, results)
    time.sleep(0.3)

    # Fan: pass if CPU temp < 85 °C
    try:
        t = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
        fan_ok = t < 85.0
    except Exception:
        fan_ok = True
    results[3] = ("Fan Status", fan_ok)
    render_checks(device, results)
    time.sleep(2.0)


# ── Main loop ─────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("Starting OLED daemon")

    st = read_state()
    interface = st.get("interface", "i2c")
    device = None

    # Keep retrying until display is found
    while device is None:
        device = init_display(interface)
        if device is None:
            log.warning("Display not found — retrying in 10 s")
            time.sleep(10)
            st = read_state()
            interface = st.get("interface", "i2c")

    run_startup(device)
    write_state({"mode": "pi_stats"})

    _pi_cache:  dict  = {}
    _pi_ts:     float = 0.0
    _gcs_cache: dict  = {}
    _gcs_ts:    float = 0.0

    while True:
        try:
            st   = read_state()
            mode = st.get("mode", "pi_stats")
            now  = time.time()

            if mode == "pi_stats":
                if now - _pi_ts > 1.0:
                    _pi_cache = pi_stats()
                    _pi_ts = now
                render_pi_stats(device, _pi_cache)
                time.sleep(0.5)

            elif mode == "telemetry":
                if now - _gcs_ts > 0.5:
                    _gcs_cache = fetch_telemetry()
                    _gcs_ts = now
                render_telemetry(device, _gcs_cache, st.get("telemetry_fields", []))
                time.sleep(0.2)

            elif mode == "custom_text":
                render_custom_text(device, st.get("custom_text", ""))
                time.sleep(0.5)

            elif mode == "pixel_art":
                render_pixel_art(device, st.get("pixel_art", ""))
                time.sleep(1.0)

            else:
                time.sleep(0.5)

        except KeyboardInterrupt:
            log.info("Shutting down")
            break
        except Exception as e:
            log.error(f"Render error: {e}")
            time.sleep(1)

    try:
        device.cleanup()
    except Exception:
        pass


if __name__ == "__main__":
    main()
