#!/usr/bin/env python3
"""
Daedalus GCS — LCD Display Daemon
128x128 ST7735 (KMR-1.44 SPI V2) via SPI

Uses the 'st7735' pip package (Pimoroni-compatible) which has the correct
initialization sequence for cheap Chinese KMR-1441 modules and properly
drives the backlight GPIO pin for full brightness.

Wiring (matches your KMR-1441 V2):
  VCC    → Pin 2 or 4  (5V — feeds the onboard regulator for full brightness)
  GND    → Pin 6       (Ground)
  CS     → Pin 24      (GPIO 8 / CE0)
  RESET  → Pin 22      (GPIO 25)
  A0/DC  → Pin 18      (GPIO 24)
  SDA    → Pin 19      (GPIO 10 / MOSI)
  SCK    → Pin 23      (GPIO 11 / SCLK)
  LED    → Pin 18      (GPIO 18 / PWM) — daemon drives this for full brightness
           OR connect directly to 3.3V if you don't want software backlight control

State file : /tmp/daedalus_lcd.json   (written by GCS backend)
GCS API    : http://127.0.0.1:8080     (polled for live telemetry)
"""

import sys
import time
import json
import logging
import urllib.request
from pathlib import Path
from io import BytesIO
import base64

import psutil
from PIL import Image, ImageDraw, ImageFont

# ── Display library (st7735 pip package) ──────────────────────────────────────
# Install: pip install st7735
# This library has the correct init sequence for KMR-1441 V2 (black PCB)
try:
    import st7735
    ST7735_OK = True
except ImportError:
    ST7735_OK = False

# ── Constants ─────────────────────────────────────────────────────────────────
GCS_URL    = "http://127.0.0.1:8080"
STATE_FILE = Path("/tmp/daedalus_lcd.json")
WIDTH, HEIGHT = 128, 128

# GPIO pin numbers (BCM mode)
SPI_PORT    = 0
SPI_CS      = 0          # CE0 = GPIO 8 = Pin 24
DC_PIN      = 24         # GPIO 24 = Pin 18 (A0 on your screen)
RST_PIN     = 25         # GPIO 25 = Pin 22 (RESET on your screen)
BACKLIGHT   = 18         # GPIO 18 = Pin 12 (connect LED pin here for software control)
                         # If LED is wired to 3.3V directly, set BACKLIGHT = None

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
MONO_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [lcd] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("lcd")


# ── Font loader ───────────────────────────────────────────────────────────────
def _font(size: int, mono: bool = False) -> ImageFont.ImageFont:
    path = MONO_PATH if mono else FONT_PATH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


# Pre-load fonts
F8  = _font(8)
F9  = _font(9)
F10 = _font(10)
F12 = _font(12)
F16 = _font(16)
F20 = _font(20)
FM8 = _font(8,  mono=True)
FM9 = _font(9,  mono=True)


# ── Display init ──────────────────────────────────────────────────────────────
def init_display():
    if not ST7735_OK:
        log.error("st7735 library not installed — run: pip install st7735")
        return None
    try:
        dev = st7735.ST7735(
            port=SPI_PORT,
            cs=st7735.BG_SPI_CS_FRONT if SPI_CS == 1 else st7735.BG_SPI_CS_BACK,
            dc=DC_PIN,
            rst=RST_PIN,
            backlight=BACKLIGHT,          # None = backlight always on via hardware
            width=WIDTH,
            height=HEIGHT,
            offset_left=0,               # Try 2 if image is shifted right
            offset_top=0,                # Try 2 if image is shifted down
            rotation=0,
            invert=False,
        )
        dev.begin()
        log.info(f"ST7735 ready ({WIDTH}x{HEIGHT}) on SPI{SPI_PORT}, CS={SPI_CS}, DC=GPIO{DC_PIN}, RST=GPIO{RST_PIN}, BL=GPIO{BACKLIGHT}")
        return dev
    except Exception as e:
        log.error(f"ST7735 init failed: {e}")
        return None


# ── State file ────────────────────────────────────────────────────────────────
_state_mtime = 0.0
_state_cache: dict = {"mode": "startup"}


def read_state() -> dict:
    global _state_mtime, _state_cache
    try:
        mtime = STATE_FILE.stat().st_mtime
        if mtime != _state_mtime:
            _state_cache = json.loads(STATE_FILE.read_text())
            _state_mtime = mtime
    except Exception:
        pass
    return _state_cache


def write_state(patch: dict) -> None:
    global _state_cache
    _state_cache.update(patch)
    try:
        STATE_FILE.write_text(json.dumps(_state_cache))
    except Exception:
        pass


# ── Pi stats ──────────────────────────────────────────────────────────────────
def pi_stats() -> dict:
    cpu  = psutil.cpu_percent(interval=None)
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    temp = 0.0
    try:
        temp = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000.0
    except Exception:
        pass

    volt = 0.0
    try:
        import subprocess
        out = subprocess.check_output(["vcgencmd", "measure_volts", "core"],
                                      timeout=1, text=True)
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
        "cpu":      cpu,
        "ram_pct":  mem.percent,
        "disk_pct": disk.percent,
        "temp":     temp,
        "volt":     volt,
        "ip":       ip,
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
    img = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    return img, ImageDraw.Draw(img)


def send(device, img: Image.Image) -> None:
    """Push a PIL image to the st7735 device."""
    device.display(img)


def hbar(draw, x: int, y: int, w: int, h: int, pct: float) -> None:
    draw.rectangle([x, y, x + w - 1, y + h - 1], outline=(255, 255, 255), fill=(0, 0, 0))
    filled = max(0, min(w - 2, int((w - 2) * pct / 100)))
    if filled:
        draw.rectangle([x + 1, y + 1, x + filled, y + h - 2], fill=(255, 255, 255))


# ── Render: startup title ─────────────────────────────────────────────────────
def render_title(device) -> None:
    img, d = new_img()
    d.text((8, 24),  "DAEDALUS GCS", font=F12,  fill=(255, 255, 255))
    d.line([(0, 44),  (127, 44)],               fill=(255, 255, 255))
    d.text((18, 52), "Ground Station", font=F9, fill=(255, 255, 255))
    d.line([(0, 75),  (127, 75)],               fill=(255, 255, 255))
    d.text((30, 83), "Booting...",    font=F9,  fill=(255, 255, 255))
    send(device, img)


# ── Render: status checks ─────────────────────────────────────────────────────
def render_checks(device, results: list) -> None:
    img, d = new_img()
    d.text((0, 4), "SYSTEM CHECK", font=FM8, fill=(255, 255, 255))
    d.line([(0, 16), (127, 16)], fill=(255, 255, 255))
    for i, (label, ok) in enumerate(results):
        y = 24 + i * 16
        d.text((2, y), label, font=FM8, fill=(255, 255, 255))
        if ok is None:
            badge = "[......]"
        elif ok:
            badge = "[  OK  ]"
        else:
            badge = "[ FAIL ]"
        d.text((78, y), badge, font=FM8, fill=(255, 255, 255))
    send(device, img)


# ── Render: Pi stats ──────────────────────────────────────────────────────────
def render_pi_stats(device, s: dict) -> None:
    img, d = new_img()
    d.text((0, 4),   "Pi STATS",            font=FM8, fill=(255, 255, 255))
    d.text((75, 4),  f"T:{s['temp']:.0f}C", font=FM8, fill=(255, 255, 255))
    d.line([(0, 16), (127, 16)],            fill=(255, 255, 255))
    d.text((0, 26),  f"CPU {s['cpu']:4.0f}%",      font=FM8, fill=(255, 255, 255))
    hbar(d, 58, 19, 68, 8, s["cpu"])
    d.text((0, 46),  f"RAM {s['ram_pct']:4.0f}%",  font=FM8, fill=(255, 255, 255))
    hbar(d, 58, 39, 68, 8, s["ram_pct"])
    d.text((0, 66),  f"DSK {s['disk_pct']:4.0f}%", font=FM8, fill=(255, 255, 255))
    hbar(d, 58, 59, 68, 8, s["disk_pct"])
    d.line([(0, 96), (127, 96)],            fill=(255, 255, 255))
    d.text((0, 102), f"{s['volt']:.2f}V",   font=FM8, fill=(255, 255, 255))
    d.text((44, 102), s["ip"][:18],          font=FM8, fill=(255, 255, 255))
    send(device, img)


# ── Render: telemetry ─────────────────────────────────────────────────────────
def render_telemetry(device, data: dict, fields: list) -> None:
    img, d = new_img()
    tel  = data.get("telemetry", {})
    fields = fields[:4]

    if not fields:
        d.text((4, 40), "No fields selected.", font=F9, fill=(255, 255, 255))
        d.text((4, 60), "Use /display page.",  font=FM8, fill=(255, 255, 255))
        send(device, img)
        return

    row_h = HEIGHT // len(fields)
    font_val = [F20, F16, F12, F10][len(fields) - 1]

    for i, key in enumerate(fields):
        y0    = i * row_h
        label = key.replace("_", " ").upper()
        raw   = tel.get(key, "—")

        if isinstance(raw, float):
            val_str = f"{raw:.2f}"
        else:
            val_str = str(raw)

        d.text((0, y0 + 2),  label,   font=FM8,     fill=(255, 255, 255))
        d.text((0, y0 + 14), val_str, font=font_val, fill=(255, 255, 255))
        if i < len(fields) - 1:
            d.line([(0, y0 + row_h - 1), (127, y0 + row_h - 1)], fill=(100, 100, 100))

    send(device, img)


# ── Render: custom text ───────────────────────────────────────────────────────
def render_custom_text(device, text: str) -> None:
    img, d = new_img()
    if not text:
        d.text((20, 50), "No text set.", font=F9, fill=(255, 255, 255))
        send(device, img)
        return

    lines = text.strip().split("\n")[:6]
    n = len(lines)
    fsize = 14 if (n == 1 and len(lines[0]) <= 10) else (12 if n <= 2 else (8 if n <= 4 else 7))
    font  = _font(fsize, mono=False)
    lh    = int(fsize * 1.3)
    y0    = max(0, (HEIGHT - lh * n) // 2)

    for i, line in enumerate(lines):
        try:
            tw = d.textlength(line, font=font)
        except Exception:
            tw = len(line) * fsize * 0.6
        x = max(0, (WIDTH - tw) // 2)
        d.text((x, y0 + i * lh), line[:22], font=font, fill=(255, 255, 255))

    send(device, img)


# ── Render: pixel art ─────────────────────────────────────────────────────────
def render_pixel_art(device, b64_png: str) -> None:
    if not b64_png:
        img, d = new_img()
        d.text((20, 50), "No image set.", font=F9, fill=(255, 255, 255))
        send(device, img)
        return
    try:
        raw = base64.b64decode(b64_png)
        src = Image.open(BytesIO(raw)).convert("RGB").resize((WIDTH, HEIGHT))
        send(device, src)
    except Exception as e:
        img, d = new_img()
        d.text((4, 40), "Image error:", font=FM8, fill=(255, 255, 255))
        d.text((4, 52), str(e)[:20],   font=FM8, fill=(255, 255, 255))
        send(device, img)


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

    try:
        t      = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
        fan_ok = t < 85.0
    except Exception:
        fan_ok = True
    results[3] = ("Fan Status", fan_ok)
    render_checks(device, results)
    time.sleep(2.0)


# ── Main loop ─────────────────────────────────────────────────────────────────
def main() -> None:
    log.info("Starting LCD daemon (st7735 driver)")

    device = None
    while device is None:
        device = init_display()
        if device is None:
            log.warning("Display not found — retrying in 10 s")
            time.sleep(10)

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
