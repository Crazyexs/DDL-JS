# DAEDALUS Ground Station (DDL-JS) — Operations & Troubleshooting Manual

> Team **1043** · CanSat Ground Control Station (GCS)
> Software: **FastAPI (Python)** backend + browser dashboard · XBee PRO 900HP radio (API Mode 2, DigiMesh)
> This manual covers **both branches**: `main` (laptop/desktop) and `raspberry-pi` (Pi 4B field unit).

---

## 0. Quick Facts (memorize these)

| Item | Value |
| --- | --- |
| Team ID | `1043` |
| Dashboard URL | `http://localhost:8080` (or `http://<device-ip>:8080`) |
| Telemetry rate | 1 Hz |
| Radio | XBee PRO 900HP, **API Mode 2**, **DigiMesh**, baud **115200** |
| Serial port (`main`) | macOS `/dev/cu.usbserial-*` · Windows `COMx` (auto-detected/selectable) |
| Serial port (`raspberry-pi`) | `/dev/xbee0` (stable udev name) |
| GPS (Pi only) | VK-172 u-blox on `/dev/ttyACM0`, 9600 baud |
| XBee address page | `http://localhost:8080/config` |
| Command page | `http://localhost:8080/cmd` |
| 64-bit address | **DH** (`0013A200`) + **DL** (unique per unit) |
| Address saved to | `data/xbee_addr.json` (per-machine, **not** in git) |

---

## 1. What the Ground Station Is

The GCS is the **Mission Control software** the Ground Station Crew uses to:

1. **Receive** 1 Hz telemetry from the CanSat over the XBee radio (downlink).
2. **Send** commands to the CanSat (uplink) — e.g. `CX,ON`, `CAL`, `ARM`, `SIM`.
3. **Display** live data: state, altitude, GPS map (3D/2D), charts, RSSI, packet counts.
4. **Log** everything to CSV and auto-generate a KML flight path for Google Earth.

### Architecture
```
CanSat ── RF (900 MHz) ──▶ Ground XBee ── USB serial ──▶ Python backend (main.py)
                                                              │  WebSocket /ws/telemetry
                                                              ▼
                                                    Browser dashboard (ui/)
Operator clicks a command ──▶ POST /api/command ──▶ backend builds API frame ──▶ XBee ── RF ──▶ CanSat
```

There is **one backend** (`main.py`) and a **browser UI** (`ui/`). The backend owns the serial port; the browser only talks to the backend over HTTP/WebSocket. Multiple browsers/phones can connect at once.

---

## 2. The Two Branches

| | `main` | `raspberry-pi` |
| --- | --- | --- |
| Runs on | Laptop/desktop (Mac/Win/Linux) | Raspberry Pi 4B (field unit, kiosk) |
| XBee port | auto-detect / dropdown | fixed `/dev/xbee0` (udev symlink) |
| Serial lock | normal | `exclusive=True` (TIOCEXCL) so nothing else can grab the radio |
| Ground-station GPS | ❌ none | ✅ VK-172 USB GPS (shows GS position, range/bearing to CanSat) |
| Map | 3D Cesium ⇄ 2D Leaflet toggle | same (3D default, fail-safe to 2D) |
| Auto-start | manual | `systemd` service + `gcs` helper command |
| Install | `pip install -r requirements.txt` | `sudo bash scripts/setup-pi.sh` |

**Everything about XBee (presets, `/config`, broadcast guard, delivery receipts, address persistence) is identical on both branches.**

> ⚠️ **Use the right branch.** On the Pi, run the `raspberry-pi` branch. On a laptop, run `main`. Wrong branch = wrong serial port defaults and (on a laptop) no GPS thread.

---

## 3. Hardware Setup

### 3.1 Ground XBee radio
- XBee PRO **900HP** module on a USB adapter (FTDI / SparkFun explorer).
- Must be configured (via **XCTU**) in:
  - **API mode 2** (`AP = 2`)
  - **Baud 115200** (`BD = 7`)
  - Same **network/channel** settings as the CanSat XBee.
- Antenna **must** be attached before powering — transmitting without an antenna can damage the module.

### 3.2 Ground-station GPS (Pi branch only)
- VK-172 u-blox 7 USB dongle → any Pi USB port → appears as `/dev/ttyACM0`.
- Used only to show the **operator's** position and range/bearing to the CanSat. Optional — the GCS works without it.

### 3.3 Cabling rules
- The XBee is **always** a `/dev/ttyUSB*` (FTDI). The GPS is **always** `/dev/ttyACM*` (CDC). They never collide.
- Don't open the XBee port in another program (XCTU, CoolTerm, Arduino Serial Monitor) while the GCS is running — only one process can own the port.

---

## 4. Installing & Launching

### 4.1 `main` branch (laptop)
```bash
cd DDL-JS
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py                    # or: uvicorn main:app --host 0.0.0.0 --port 8080
```
On macOS/Linux, the terminal shows a **serial port picker** at startup — choose the XBee port.

Open **http://localhost:8080**.

### 4.2 `raspberry-pi` branch (Pi 4B)
```bash
cd DDL-JS
git checkout raspberry-pi
sudo bash scripts/setup-pi.sh     # installs deps, udev rule for /dev/xbee0, systemd service, gcs tool
```
Then manage it with the `gcs` helper:
```bash
gcs start      # start backend
gcs stop       # stop backend
gcs restart    # restart (run after every `git pull`)
gcs status     # is it running?
gcs logs       # live backend logs
gcs open       # open dashboard in kiosk browser
```

> 🔁 **After `git pull` on the Pi, always run `gcs restart`** or the old code keeps running.

---

## 5. The Dashboard (what every panel means)

| Panel | Meaning |
| --- | --- |
| **Connected / Disconnected pill** | Serial link to the XBee. Green = backend has the port open. |
| **XBee: 1/2/3/Custom pill** | Which unit commands are being sent to. Click → `/config`. |
| **State** | CanSat flight state (BOOT, LAUNCH_PAD, ASCENT, APOGEE, DESCENT, LANDED…). |
| **Altitude / Mode / GPS Sats / Arm / Deploy** | Live mission values. |
| **Map** | 3D Cesium globe (toggle to 2D). CanSat marker + flight trail. |
| **Link RSSI** | Last-hop signal strength (dBm) from the radio. More negative = weaker. |
| **RX / Lost Packets** | Received count and sequence-gap losses. |
| **Compass / heading** | CanSat heading. |
| **Log: Flight_1043.csv** | Active CSV log file. |

---

## 6. XBee Address Configuration (`/config`)

Open `http://localhost:8080/config`.

- **Quick Select 1 / 2 / 3** — preset units defined in code (`XBEE_PRESETS` in `main.py`). Press a button → it fills the form → press **Apply** to confirm.
- **Custom** — manually enter a new DL (and, with the Emergency toggle, DH) for a unit not in the presets.
- The address is **DH + DL** (each 8 hex chars). DH is `0013A200` for all same-model XBees; **only DL is unique per unit** (read it from `ATSL` in XCTU or the module label).
- The active address is **saved** to `data/xbee_addr.json` and **restored on restart** — so a reboot won't silently send commands to the wrong unit.
- **Broadcast is blocked**: the GCS refuses the broadcast address (`…FFFF`) — every command goes to exactly one unit.

> 👥 **Sharing with a teammate:** the `xbee_addr.json` file is **per-machine** and is **not** in git (it's runtime data). Your friend's GCS creates its own when they pick an address. They get the same **preset buttons** through the code — they just press 1/2/3 on their own `/config`.

> 🚨 **If two CanSats answer one command:** that is **not** the GCS broadcasting. It means **two XBees share the same DL**. Give each unit a unique DL in XCTU.

---

## 7. Command Reference

Send from the **`/cmd`** page or the Quick Command dropdown. The backend auto-prefixes `CMD,1043,` — you only type the rest.

### Quick commands
| Command | Purpose |
| --- | --- |
| `CX,ON` / `CX,OFF` | Telemetry transmission on/off |
| `STATE,<phase>` | Force a flight state (IDLE_SAFE, LAUNCH_PAD, ASCENT, APOGEE, DESCENT, PROBE_RELEASE, PAYLOAD_RELEASE, LANDED) |
| `CAL` | Calibrate (altitude zero) |
| `CAL,MAG,START` / `CAL,NORTH` / `CAL,MAG,STATUS` / `CAL,MAG,RESET` | Magnetometer / heading calibration |
| `RESET` | Reset CanSat |
| `SIM,ENABLE` → `SIM,ACTIVATE` → `SIM,DISABLE` | Simulation mode sequence |
| `MEC,PL,ON/OFF` | Payload-release servo |
| `MEC,INS,ON/OFF` | Instrument-bay servo |
| `MEC,PAR,CW / ACW / OFF` | Parachute spin motor |

### Parameter commands (prompt for a value)
| Command | Value |
| --- | --- |
| `SIMP,<pressure>` | Simulated pressure (Pa) |
| `SET,MAIN_ALT,<m>` | Main chute deploy altitude |
| `SET,APOGEE_ALT,<m>` | Apogee threshold |
| `SET,TX_RATE,<1-10>` | Telemetry rate (Hz) |
| `SET,INS_TOF/NEAR/CRIT,<val>` | Instrument thresholds |
| `CAL,TOF,<mm>` | ToF sensor calibration |
| `SERVO,A/B,<0-180>` | Direct servo angle |

### Local-only (does NOT go to the CanSat)
| Command | Purpose |
| --- | --- |
| `/log <name>` | Switch the active CSV/KML log file (e.g. `/log preflight`) |
| `/log.clear` | Back to default `Flight_1043.csv` |

> ✅ **Uplink delivery receipts:** after a real command, the GCS reads the XBee `0x8B` Transmit Status and shows **“✓ Uplink delivered to CanSat”** or a red **“⚠ Uplink NOT delivered”**. *Sent* now means *reached the CanSat*, not just *written to the radio*.

---

## 8. Data & Logging

| Output | Location | Notes |
| --- | --- | --- |
| Raw + parsed telemetry | `data/Flight_1043.csv` | every line saved immediately, before parsing |
| Flight path (Google Earth) | `data/Flight_1043.kml` | auto-saved every ~10 GPS fixes + on LANDED |
| Backend logs | `logs/ground.jsonl` | structured JSON events |
| Active log switch | `/log <name>` | makes `Flight_1043_<name>.csv` |

The whole `data/` and `logs/` folders are **gitignored** (runtime data, not source).

---

## 9. Remote Access (share the live dashboard)

### Tailscale Funnel (public link — judge does NOT need Tailscale)
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale funnel 8080
```
Gives a public `https://<machine>.<tailnet>.ts.net` link anyone can open. WebSockets work (the UI auto-upgrades to `wss:`).

### Private tailnet (team only, lowest latency)
Install Tailscale on the Pi and the laptop/phone (same account), then open `http://<pi-tailscale-ip>:8080`.

### ngrok (alternative public link)
```bash
ngrok http 8080
```

> The app needs **no code change** for any of these — it binds `0.0.0.0:8080` and builds the WebSocket URL from whatever host you connect through.

---

## 10. Offline Maps (launch-day reality)

- The **app** (Cesium engine, Leaflet, UI) is served by the Pi itself → always works offline.
- The **map imagery tiles** (3D satellite from ArcGIS, 2D streets from OpenStreetMap) come from the internet and are **cached on first view** by the service worker.
- **To have the launch site offline:** while online, pan/zoom around the launch coordinates across the zoom levels you'll use. Those tiles cache to disk and survive reboot.
- Tiles you never viewed show **blank/black** offline. The default map center is the launch site (`38.3756, -79.6074`).

---

# 11. ERROR SCENARIOS — Diagnosis & Fixes (Both Branches)

> How to read this: each scenario lists **what you see**, the **cause**, and **hardware** + **software** fixes. Branch-specific notes are tagged **[main]** / **[Pi]**.

## 11.1 Backend won't start

**A. `python main.py` exits / ModuleNotFoundError**
- Cause: dependencies not installed or wrong venv.
- Fix (SW): `source venv/bin/activate` then `pip install -r requirements.txt`. On the Pi, re-run `sudo bash scripts/setup-pi.sh`.

**B. `Address already in use` / port 8080 busy**
- Cause: another GCS instance is already running.
- Fix (SW): **[Pi]** `gcs stop` then `gcs start`. **[main]** close the other terminal / kill the process. Check: `lsof -i :8080`.

**C. Pi: dashboard never opens in kiosk**
- Fix (SW): `gcs status` → if stopped, `gcs start`; `gcs logs` to see why. `gcs open` to relaunch the browser.

## 11.2 Serial / Radio Connection

**A. Pill stays “Disconnected”; log `port_not_found`**
- What you see: red Disconnected pill; backend log `event=port_not_found`.
- Cause: XBee not detected / wrong port.
- Fix (HW): re-seat the USB XBee adapter; try another USB port/cable (some cables are power-only); confirm the adapter LED is on.
- Fix (SW): **[main]** pick the correct port in the **serial dropdown** (Config panel) and Connect; on the picker at startup choose the right `/dev/cu.usbserial-*` / `COMx`. **[Pi]** confirm `/dev/xbee0` exists: `ls -l /dev/xbee0`. If missing, the udev rule didn't apply — re-run `sudo bash scripts/setup-pi.sh` and replug, or temporarily set the port to `/dev/ttyUSB0`.

**B. Log `serial_open_failed` / “Access is denied” / “Access Denied”**
- Cause: another program owns the port (XCTU, CoolTerm, Arduino, a second GCS).
- Fix (SW): close that program. **[Pi]** the port is opened `exclusive=True`, so this also blocks the GPS thread from ever grabbing it — if you see this, something else has the radio; `sudo lsof /dev/xbee0`.

**C. [Pi] Constant reconnect spam / “multiple access on port”**
- Cause (historical): two threads touching the radio fd. The current code uses a **single serial I/O thread** + `exclusive=True`, so this should not happen.
- Fix (SW): make sure `ModemManager` isn't probing the port (the setup script disables it for the XBee). `sudo systemctl stop ModemManager`. Confirm only `/dev/xbee0` is used for the radio and GPS is on `/dev/ttyACM*`.

**D. Connected pill green but no data** → see **11.4**.

## 11.3 Uplink (commands) not working

**A. Red toast `UPLINK FAILED: Serial not connected`**
- Cause: radio not open.
- Fix: resolve **11.2** first (the Connected pill must be green).

**B. Red toast `UPLINK FAILED: TX buffer full`**
- Cause: commands queued faster than the radio can send (e.g. spamming during a bad link).
- Fix (SW): slow down; wait for the link to recover. Check RSSI (11.4-C).

**C. Buttons do nothing, no toast, page looks loaded** *(regression class)*
- Cause: a JavaScript error during startup aborted the page setup before the command buttons were wired (historically: 3D map failing to initialize first).
- Fix (SW): **hard refresh** (Ctrl/Cmd+Shift+R). The current code wires comms first and the map is fail-safe (falls back to 2D), so this is fixed — but always hard-refresh after a `git pull`. **[Pi]** `gcs restart` then reload the kiosk.

**D. UI says “sent” but CanSat never responds**
- Look at the **delivery receipt**:
  - **“⚠ Uplink NOT delivered — XBee status 0x..”** → the frame reached the radio but didn't get an RF ACK.
    - Fix (HW): improve the link — antenna orientation, line of sight, distance; check the CanSat is powered and its XBee is on.
    - Fix (SW/config): verify the **XBee: pill / `/config` address** matches the unit you're trying to reach.
  - **“✓ Uplink delivered”** but still no behavior → the command *reached the CanSat* but it didn't act — check the command spelling/state preconditions (e.g. `SIM,ACTIVATE` needs `SIM,ENABLE` first; `ARM` preconditions).

**E. Wrong CanSat responds / command goes to the wrong unit**
- Cause: the active address is a different unit, or two units share a DL.
- Fix (SW): on `/config`, press the correct **preset (1/2/3)** or set the custom DL.
- Fix (HW): give each XBee a **unique DL** (`ATSL` in XCTU). Identical DLs make multiple units accept the same command.

**F. After a reboot, commands silently go to Unit 1**
- This is fixed: the address is **persisted** in `data/xbee_addr.json` and restored on startup (log `xbee_addr_restored`).
- If it still reverts: the file is missing/corrupt — log shows `xbee_load_failed`. Just re-select the unit on `/config` (it re-saves). Ensure `data/` is writable.

## 11.4 Downlink (telemetry) problems

**A. Connected but RX Packets stuck at 0**
- Cause: CanSat not transmitting, wrong radio config, or `CX,OFF`.
- Fix (SW): send `CX,ON`.
- Fix (HW): confirm CanSat avionics powered + LED blinking; confirm **both** XBees share **API mode 2, baud 115200, same channel/network**. A baud or channel mismatch = silence.

**B. Garbled / “bad_line” entries, Lost Packets climbing**
- Cause: weak/noisy link, or an XBee not in API mode 2.
- Fix (HW): improve antenna/line-of-sight; reduce distance; check power to the CanSat radio.
- Fix (SW): confirm `AP=2` on **both** modules (the GCS only speaks API mode 2). Frames with bad checksums are dropped silently — rising Lost count with low RX = mostly RF quality.

**C. RSSI very negative (e.g. −95 dBm) or missing**
- Cause: weak link.
- Fix (HW): orient antennas, raise the ground antenna, shorten distance, remove obstructions.

**D. Telemetry shows but values look wrong / columns shifted**
- Cause: the CanSat's CSV field order doesn't match `telemetry_config.json`.
- Fix (SW): align `telemetry_config.json` column order with the CanSat firmware output.

## 11.5 GPS / Position **[Pi only]**

**A. “GS GPS: acquiring fix…” never resolves**
- Cause: no GPS fix / dongle not found.
- Fix (HW): place the VK-172 with **sky view**; cold start can take minutes; check the dongle LED.
- Fix (SW): confirm it enumerated: `ls /dev/ttyACM*`. Log `gps_port_not_found` means it wasn't found — replug; the code skips the XBee port and only uses `ttyACM*`.

**B. CanSat map marker doesn't move**
- Cause: no CanSat GPS fix (needs > 3 sats) — separate from the GS GPS above.
- Fix: wait for the CanSat to get sats (GPS Sats panel), ensure it has sky view on the pad.

## 11.6 Map / Display

**A. Map is blank/black**
- Cause (online): tiles still loading. Cause (offline): those tiles were never cached.
- Fix (SW): while online, pan/zoom the launch area to cache it (see §10). Toggle 2D⇄3D with the **Map Toggle** button.
- **[Pi]** If 3D never renders (weak GPU/WebGL), it **auto-falls back to 2D** — the rest of the dashboard still works. Use 2D for reliability in the kiosk.

**B. Charts/map wrong size after load**
- Fix (SW): resize the window or reload — the app re-triggers layout on resize.

## 11.7 Remote access

**A. Judge can't open the link**
- Cause: you shared a **private** Tailscale IP (needs Tailscale) instead of a public link.
- Fix: use **`tailscale funnel 8080`** (public HTTPS) or **ngrok** — those need nothing on the judge's side.

**B. Page loads remotely but no live data**
- Cause: WebSocket blocked.
- Fix: use the HTTPS funnel/ngrok URL (the app auto-uses `wss:`); avoid mixing `http`/`https`.

## 11.8 Sharing code with a teammate (git)

**A. “My friend pulled but doesn't have `xbee_addr.json`”**
- **Expected.** That file is per-machine runtime data and is **gitignored** — it never comes through `git pull`. Their GCS creates its own when they set an address. Nothing is broken.

**B. Teammate is missing the XBee features (no presets / pill)**
- Cause: wrong branch or stale pull.
- Fix (SW): `git branch` (use `raspberry-pi` on Pi, `main` on laptop); `git pull`; `git log --oneline -1` to confirm the latest commit; **[Pi]** `gcs restart`; then **hard refresh** the browser.

---

# 12. Pre-Flight GCS Checklist (Ground Station Crew)

Tie-in to the Mission Manual §4–§5. Do these at the GCS:

1. ☐ Launch GCS: `python main.py` **[main]** / confirm `gcs status` running **[Pi]**.
2. ☐ Open `http://localhost:8080`; **Connected** pill is green.
3. ☐ Open `/config`; press the correct **preset** for today's CanSat; **Apply**; the **XBee:** pill shows the right unit.
4. ☐ Send `CX,ON`; confirm **“✓ Uplink delivered”**.
5. ☐ Telemetry flowing at **1 Hz**; RX Packets climbing, Lost ~0.
6. ☐ Values sane: time, altitude, **battery ≥ 7.9 V**, GPS sats, state.
7. ☐ RSSI reasonable (not pinned at the noise floor).
8. ☐ Map shows CanSat once it has a GPS fix; launch-area tiles pre-cached if going offline.
9. ☐ Log file correct (`/log <name>` if you want a named run).
10. ☐ Run through `CAL` / `CAL,NORTH` / `ARM` per the integration checklist; confirm each delivery receipt.
11. ☐ Confirm beacon/recovery aids per Mission Manual.

---

# 13. Appendix

### 13.1 Key API endpoints
| Method · Path | Purpose |
| --- | --- |
| `GET /api/health` | port, baud, rx/lost, last cmd, RSSI |
| `GET /api/serial/ports` | list serial ports |
| `POST /api/serial/config` | set port/baud (triggers reconnect) |
| `POST /api/command` | send a command (auto-prefixes `CMD,1043,`) |
| `GET /api/xbee/config` | current address + presets |
| `POST /api/xbee/config` | set address (rejects broadcast, persists) |
| `POST /api/log/set` | switch active log file |
| `POST /api/kml/save` | force a KML save |
| `GET /api/csv/open` | open the data folder |
| `WS /ws/telemetry` | live data stream |

### 13.2 WebSocket message types
`telemetry` (full packet) · `rssi` · `tx_status` (delivery receipt) · `xbee_addr` · `serial_status` · `gs_gps` **[Pi]** · `kml_saved` · `error` · `ping`

### 13.3 Useful backend log events (`logs/ground.jsonl`)
`serial_connected` · `serial_open_failed` · `port_not_found` · `serial_reconnect_request` · `uplink_dropped_no_serial` · `xbee_addr_changed` · `xbee_addr_restored` · `xbee_load_failed` · `bad_xbee_preset` · `gps_connected` · `gps_port_not_found`

### 13.4 XBee delivery status codes (`0x8B`)
`0x00` Success · `0x21` Network ACK failure · `0x25` Route not found · (non-zero = not delivered → check link/address)

### 13.5 File locations
| Path | What |
| --- | --- |
| `main.py` | backend (serial, codec, endpoints) |
| `ui/index.html`, `ui/app.js` | dashboard |
| `ui/config.html` | XBee address page |
| `ui/cmd.html` | command page |
| `telemetry_config.json` | CSV column order |
| `data/Flight_1043.csv` / `.kml` | flight data (gitignored) |
| `data/xbee_addr.json` | persisted address (gitignored, per-machine) |
| `logs/ground.jsonl` | backend logs (gitignored) |
| `scripts/setup-pi.sh` | Pi installer **[Pi]** |

### 13.6 The 60-second emergency triage
1. **Disconnected pill?** → fix the radio/port (§11.2).
2. **Connected but no data?** → `CX,ON`; check baud/channel/API-mode on both XBees (§11.4).
3. **Command not working?** → read the delivery receipt; check the `/config` address (§11.3).
4. **Buttons dead?** → hard refresh (§11.3-C).
5. **Map blank?** → toggle 2D; pre-cache tiles (§11.6).
6. **Still stuck?** → `gcs logs` **[Pi]** / terminal output **[main]** and read the last error event.
