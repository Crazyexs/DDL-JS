if (!window.__DGS_BOOTED__) {
  window.__DGS_BOOTED__ = true;

/* DAEDALUS #1043 — app.js
 *
 * This file controls the website (Frontend).
 * It does three main things:
 * 1. Connects to the Backend (Python) to get live data.
 * 2. Updates the screen (text, charts, maps) when data arrives.
 * 3. Sends commands from the buttons back to the Backend.
 */

(function () {
  // ---------- HELPERS (Little shortcuts) ----------
  const $ = (s) => document.querySelector(s); // Selects an element on the page
  const pad = (n) => String(n).padStart(2, '0'); // Adds a zero in front (5 -> 05)
  const hms = (d = new Date()) => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; // Gets time as HH:MM:SS
  // This cleans text to prevent code injection attacks
  const esc = (s) => String(s).replace(/[&<""']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
  // Formats a number (e.g., 12.3456 -> 12.3)
  const num = (x, d = 1) => (x === undefined || x === null || isNaN(+x)) ? '—' : (+x).toFixed(d);
  // Gets a color from the CSS file
  const getCssVar = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  // ---------- STATE (Variables that change) ----------
  const st = {
    teamId: window.DGS_TEAM_ID || 1043,
    t0: null,      // Start time of the mission
    charts: {},    // Stores the chart objects
    map: null,     // Stores the map object
    marker: null,  // Stores the map marker object
    ws: null,      // The WebSocket connection to the server
    lastGPSHMS: null,
    altZero: 0,
    lastAlt: 0,
    // Dummy data state
    dummy: { id: null, packet: 0, lat: 18.788, lon: 98.985 },
  };

  // ---------- DOM ELEMENTS (Links to HTML items) ----------
  const el = {
    // Theme button
    toggleTheme: $("#toggleTheme"),
    // Clocks
    utcClock: $("#utcClock"),
    missionSmall: $("#missionTime"),
    missionBig: $("#missionTimeBig"),
    // Connection status pill
    connPill: $("#connPill"),
    // Map & Mission controls
    btnStartMission: $("#btnStartMission"),
    mapEl: $("#map"),
    mapToggle: $("#toggleMapSize"),
    gpsMini: $("#gpsMiniTitle"),
    gmapA: $("#gmapA"),
    // Health Counters
    rxCount: $("#rxCount"),
    lossCount: $("#lossCount"),
    // Log Box elements
    rawBox: $("#rawBox"),
    logN: $("#logN"),
    auto: $("#autoScroll"),
    freeze: $("#freeze"),
    wrap: $("#wrapLines"),
    refreshLogs: $("#refreshLogs"),
    jumpLive: $("#jumpLive"),
    jumpLiveBtn: $("#jumpLiveBtn"),
    copyLogs: $("#copyLogs"),
    resetAll: $("#btnResetAllTop"),
    lastCmd: $("#lastCmd"),
    // Command Inputs
    quick: $("#quickCmd"),
    manual: $("#manualCmd"),
    send: $("#sendCmd"),
    // New buttons
    btnOpenCsvFolder: $("#btnOpenCsvFolder"),
    btnSim: $("#btnSim"),
    
    // Large Text Displays
    missionState: $("#missionState"),
    liveAltitude: $("#liveAltitude"),
    missionMode: $("#missionMode"),
    gpsSats: $("#gpsSats"),
    compassArrow: $("#compassArrow"),
    heading: $("#heading"),

    // Key Value Grid items
    val_temp: $("#val_temp"),
    val_pressure: $("#val_pressure"),
    val_voltage: $("#val_voltage"),
    val_current: $("#val_current"),
    val_gyro_x: $("#val_gyro_x"),
    val_gyro_y: $("#val_gyro_y"),
    val_gyro_z: $("#val_gyro_z"),
    val_accel_x: $("#val_accel_x"),
    val_accel_y: $("#val_accel_y"),
    val_accel_z: $("#val_accel_z"),
    
    // Chart Toggles
    altitudeToggles: $("#altitudeToggles"),
  };

  // ---------- LOGGING FUNCTIONS (Writing to the screen box) ----------
  function log(kind, msg) {
    const ts = hms();
    // Choose color based on message type (error, warning, command, or normal)
    const klass = kind === 'err' ? 'k err' : kind === 'warn' ? 'k warn' : (kind === 'cmd' ? 'k cmd' : 'text');
    
    const line = document.createElement('div');
    line.className = 'logline';
    line.innerHTML = `<span class="ts">[${ts}]</span><span class="${klass}">${esc(msg)}</span>`;
    
    if (!el.rawBox) return;
    
    // Keep only the last N lines to prevent the browser from getting slow
    const max = Number(el.logN?.value || 500);
    while (el.rawBox.children.length >= max) el.rawBox.removeChild(el.rawBox.firstChild);
    
    el.rawBox.appendChild(line);
    
    // Auto-scroll to the bottom unless the user paused it
    if (el.auto?.checked && !el.freeze?.checked) el.rawBox.scrollTop = el.rawBox.scrollHeight;
  }
  
  // Shortcuts for logging
  function info(m) { log('info', m); }
  function warn(m) { log('warn', m); }
  function err(m) { log('err', m); }
  function cmdEcho(m) { log('cmd', m); }


  // ---------- HEALTH & CONNECTION UI ----------
  function setPill(connected, text = 'Connected') {
    if (!el.connPill) return;
    el.connPill.textContent = connected ? text : 'Disconnected';
    el.connPill.className = 'pill' + (connected ? ' ok' : '');
  }

  // ---------- CLOCKS ----------
  // Updates the UTC clock every second
  function tickUTC() {
    if (!el.utcClock) return;
    const d = new Date();
    el.utcClock.textContent = `UTC: ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
  }
  setInterval(tickUTC, 1000); tickUTC();

  // Updates the Mission Clock (T+ XX:XX:XX)
  function tickMission() {
    if (!st.t0 || el.freeze?.checked) return;
    const s = Math.floor((Date.now() - st.t0) / 1000);
    const t = `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
    el.missionSmall && (el.missionSmall.textContent = 'Mission: ' + t);
    el.missionBig && (el.missionBig.textContent = t);
  }
  setInterval(tickMission, 250);
  
  // Start button for the mission clock
  el.btnStartMission?.addEventListener('click', () => { if (!st.t0) st.t0 = Date.now(); info("Mission Timer Started.");});


  // ---------- MAP LOGIC ----------
  function initMap() {
    if (!el.mapEl) return;
    // Create the map centered on a default location
    st.map = L.map('map', { zoomControl: true, attributionControl: false }).setView([18.788, 98.985], 16);
    // Load map tiles from OpenStreetMap
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(st.map);
    // Add a marker pin
    st.marker = L.marker([18.788, 98.985]).addTo(st.map);
  }
  
  // ---------- CHART LOGIC (Graphs) ----------
  function getChartColors() {
    return [getCssVar('--chart-color-1'), getCssVar('--chart-color-2')];
  }

  // Creates a new chart using ECharts library
  function makeMulti(elId, names) {
    const elc = document.getElementById(elId);
    if (!elc) return null;
    const inst = echarts.init(elc);
    const colors = getChartColors();
    inst.setOption({
      grid: { left: 44, right: 18, top: 38, bottom: 28 },
      animation: false,
      xAxis: { type: 'category', data: [], axisLabel: { show: false } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: getCssVar('--muted') } },
      legend: { show: false, data: names, top: 0, textStyle: { color: getCssVar('--fg') } }, // Keep legend data, but hide it
      series: names.map((n, i) => ({ type: 'line', name: n, showSymbol: false, data: [], lineStyle: { color: colors[i] } })),
      tooltip: { trigger: 'axis' }
    });
    return inst;
  }

  // Adds new data points to an existing chart
  function pushChart(inst, label, values) {
    if (!inst) return;
    const opt = inst.getOption();
    
    // Add new X-axis label (Time)
    opt.xAxis[0].data.push(label);
    
    // Add new Y-axis values (Data)
    (Array.isArray(values) ? values : [values]).forEach((v, i) => opt.series[i].data.push(v));
    
    // Keep chart size fixed (remove old points if too many)
    const max = 120;
    if (opt.xAxis[0].data.length > max) { opt.xAxis[0].data.shift(); opt.series.forEach(s => s.data.shift()); }
    
    inst.setOption(opt, false, true);
  }
  
  // Updates chart colors when theme changes
  function updateChartColors() {
    const colors = getChartColors();
    const muted = getCssVar('--muted');
    const fg = getCssVar('--fg');
    
    for (const chart of Object.values(st.charts)) {
      if (!chart) continue;
      chart.setOption({
        yAxis: { axisLabel: { color: muted } },
        legend: { textStyle: { color: fg } },
        series: chart.getOption().series.map((s, i) => ({
          name: s.name,
          lineStyle: { color: colors[i] }
        }))
      });
    }
  }

  function initCharts() {
    st.charts.altitude = makeMulti('chart-altitude', ['Altitude']);
  }
  

  // Resize charts when the window size changes
  window.addEventListener('resize', () => {
    Object.values(st.charts).forEach(c => c?.resize());
    st.map?.invalidateSize();
  });

  // ---------- TELEMETRY HANDLING (The Core Logic) ----------
  
  // Rotates the compass arrow
  function updateCompass(heading) {
    if (!el.compassArrow) return;
    el.compassArrow.style.transform = `rotate(${heading || 0}deg)`;
    el.heading.textContent = `${num(heading, 0)}°`;
  }

  // This function runs EVERY TIME a new data packet arrives!
  function onTelemetry(t) {
    if (el.freeze?.checked) return; // Stop updating if "Freeze" is checked

    // 1. Update Big Text Displays
    el.missionState && (el.missionState.textContent = t.state || '—');
    el.liveAltitude && (el.liveAltitude.textContent = num(t.altitude_m, 1));
    
    // 2. Update Strip Displays
    el.missionMode && (el.missionMode.textContent = t.mode || '—');
    el.gpsSats && (el.gpsSats.textContent = t.gps_sats ?? '—');
    updateCompass(t.heading);

    // 3. Update Key Value Grid
    el.val_temp && (el.val_temp.textContent = `${num(t.temperature_c, 1)} °C`);
    el.val_pressure && (el.val_pressure.textContent = `${num(t.pressure_kpa, 2)} kPa`);
    el.val_voltage && (el.val_voltage.textContent = `${num(t.voltage_v, 2)} V`);
    el.val_current && (el.val_current.textContent = `${num(t.current_a, 3)} A`);
    
    el.val_gyro_x && (el.val_gyro_x.textContent = num(t.gyro_r_dps, 2));
    el.val_gyro_y && (el.val_gyro_y.textContent = num(t.gyro_p_dps, 2));
    el.val_gyro_z && (el.val_gyro_z.textContent = num(t.gyro_y_dps, 2));
    
    el.val_accel_x && (el.val_accel_x.textContent = num(t.accel_r_dps2, 2));
    el.val_accel_y && (el.val_accel_y.textContent = num(t.accel_p_dps2, 2));
    el.val_accel_z && (el.val_accel_z.textContent = num(t.accel_y_dps2, 2));


    // 4. Update Packet Counters
    el.rxCount && (el.rxCount.textContent = t.gs_rx_count);
    el.lossCount && (el.lossCount.textContent = t.gs_loss_total);

    // 5. Update Time
    // Use mission time from telemetry if valid
    if (t.mission_time && /^\d\d:\d\d:\d\d$/.test(t.mission_time)) {
        el.missionBig && (el.missionBig.textContent = t.mission_time);
    }

    if (t.gps_time && /^\d\d:\d\d:\d\d$/.test(t.gps_time)) st.lastGPSHMS = t.gps_time;
    if (typeof t.altitude_m === 'number') st.lastAlt = t.altitude_m;

    // 6. Update Command Echo (what the satellite said it received)
    if (t.cmd_echo) {
      el.lastCmd && (el.lastCmd.textContent = t.cmd_echo);
    }

    // 7. Update Charts
    const label = t.mission_time || hms();
    pushChart(st.charts.altitude, label, [t.altitude_m]);

    // 8. Update Map
    if (t.gps_lat && t.gps_lon && typeof t.gps_lat === 'number' && typeof t.gps_lon === 'number') {
      const pos = [t.gps_lat, t.gps_lon];
      st.marker?.setLatLng(pos); // Move marker
      st.map?.panTo(pos, { animate: false }); // Move camera
      el.gpsMini && (el.gpsMini.textContent = `${t.gps_lat.toFixed(5)}, ${t.gps_lon.toFixed(5)} • sats: ${t.gps_sats ?? '—'}`);
      el.gmapA && (el.gmapA.href = `https://maps.google.com/?q=${t.gps_lat},${t.gps_lon}`);
    }

    // 9. Update Text Log (bottom right box)
    try {
      const showRaw = el.showRaw?.checked;
      let logText;

      if (showRaw && t.gs_raw_line) {
          logText = t.gs_raw_line;
      } else {
          // Create an "Easy Read" format for the log
          logText = `#${t.packet_count} ${t.state} | ` +
                    `Alt:${num(t.altitude_m)}m | ` +
                    `Bat:${num(t.voltage_v, 2)}V | ` +
                    `T:${num(t.temperature_c, 1)}C | ` +
                    `P:${num(t.pressure_kpa, 1)}k | ` +
                    (t.cmd_echo ? `Echo:${t.cmd_echo}` : '');
      }
      log('info', logText);
    } catch (e) {
      console.error("Log error:", e);
    }
  }

  // ---------- LOGS UI CONTROL ----------
  (function () {
    // DOM elements
    el.showRaw = $("#showRaw");
    
    if (!el.rawBox) return;
    const update = () => {
      // Detect if user scrolled up
      const atBottom = (el.rawBox.scrollHeight - el.rawBox.clientHeight - el.rawBox.scrollTop) < 24;
      if (el.jumpLive) el.jumpLive.hidden = atBottom || el.auto?.checked;
    };
    el.rawBox.addEventListener('scroll', update);
    el.auto?.addEventListener('change', update);
    el.jumpLiveBtn?.addEventListener('click', () => { el.rawBox.scrollTop = el.rawBox.scrollHeight; el.auto && (el.auto.checked = true); update(); });
    const mo = new MutationObserver(() => { if (el.auto?.checked) el.rawBox.scrollTop = el.rawBox.scrollHeight; update(); });
    mo.observe(el.rawBox, { childList: true, subtree: false });
  })();
  el.refreshLogs?.addEventListener('click', () => { if (!el.rawBox) return; el.rawBox.innerHTML = ''; info('Log view cleared.'); });
  el.copyLogs?.addEventListener('click', async () => { if (!el.rawBox) return; await navigator.clipboard.writeText([...(el.rawBox.querySelectorAll('.logline'))].map(n => n.innerText).join('\n')); cmdEcho('Logs copied to clipboard.'); });
  el.resetAll?.addEventListener('click', () => { if (el.rawBox) el.rawBox.innerHTML = ''; Object.values(st.charts).forEach(c => c?.clear()); initCharts(); cmdEcho('UI Reset.'); });

  // ---------- COMMANDS (Sending data to satellite) ----------
  const QUICK_COMMANDS = [
    'CX,ON', 'CX,OFF',
    'CAL',
    'ST,GPS',
    'SIM,ENABLE', 'SIM,ACTIVATE', 'SIM,DISABLE',
    'MEC,PL,ON', 'MEC,PL,OFF',
    '/dummy.on', '/dummy.off'
  ];
  
  // Populates the dropdown menu
  function fillCmds() {
    if (!el.quick) return;
    el.quick.innerHTML = '';
    const opt0 = document.createElement('option'); opt0.value = ''; opt0.textContent = '— Quick Command —';
    el.quick.append(opt0);
    QUICK_COMMANDS.forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = c; el.quick.append(o); });
  }

  // Sends the command to the backend
  async function sendCommand(cmdStr) {
    const cmd = cmdStr.trim();
    if (!cmd) return;

    // Handle local slash-commands (shortcuts that don't go to the satellite)
    if (cmd.startsWith('/')) {
        const command = cmd.toLowerCase();
        if (command === '/dummy.on') {
            fetch('/api/dummy/start', {method: 'POST'});
            info('Requesting dummy data from server...');
            return;
        }
        if (command === '/dummy.off') {
            fetch('/api/dummy/stop', {method: 'POST'});
            info('Stopping dummy data on server...');
            return;
        }
        if (command === '/clear') {
            el.rawBox && (el.rawBox.innerHTML = '');
            info('Log view cleared.');
            return;
        }
        err(`Unknown local command: ${cmd}`);
        return;
    }

    // Update UI immediately to show we tried to send
    el.lastCmd.textContent = cmd;
    cmdEcho('> ' + cmd);

    try {
      const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cmd: cmd }),
      });
      if (!res.ok) {
        const errBody = await res.text();
        throw new Error(`HTTP ${res.status}: ${errBody}`);
      }
      // If successful, we just wait. The satellite will echo the command back later if it got it.
    } catch (e) {
      err(`Command failed: ${e.message}`);
    }
  }

  el.quick?.addEventListener('change', () => { if (el.quick.value && el.manual) { el.manual.value = el.quick.value; el.quick.value = ''; } });
  el.send?.addEventListener('click', () => { const v = (el.manual?.value || '').trim(); if (!v) return; sendCommand(v); if (el.manual) el.manual.value = ''; });
  el.manual?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); el.send.click(); } });


  // ---------- WEBSOCKET CONNECTION (Real-time link) ----------
  function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/telemetry`;
    info(`Connecting to ${url}...`);
    st.ws = new WebSocket(url);

    st.ws.onopen = () => {
      info('Backend connected.');
      setPill(true, 'Connected');
    };

    st.ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === 'error') {
          err(data.message || 'Received an unknown error from backend.');
        } else if (data.type !== 'ping') {
          onTelemetry(data); // Process the data!
        }
      } catch (e) {
        warn(`Invalid JSON from backend: ${e.message}`);
      }
    };

    st.ws.onclose = () => {
      st.ws = null;
      err('Backend disconnected.');
      setPill(false, 'Retrying...');
      setTimeout(connect, 2000); // Try to reconnect after 2 seconds
    };

    st.ws.onerror = (e) => {
      err('WebSocket error. Check browser console for details.');
      console.error('WebSocket error:', e);
      st.ws?.close();
    };
  }

  // ---------- ACTION BUTTONS ----------
  el.btnOpenCsvFolder?.addEventListener('click', async () => {
      try {
          const res = await fetch('/api/csv/open-folder');
          if (!res.ok) throw new Error(await res.text());
          info("Request to open CSV log folder sent.");
      } catch (e) {
          err(`Could not open folder: ${e.message}`);
      }
  });

  el.btnSim?.addEventListener('click', async () => {
      try {
          const res = await fetch('/api/sim/start', { method: 'POST' });
          if (!res.ok) throw new Error(await res.text());
          info("Request to start simulation sent.");
      } catch (e) {
          err(`Could not start sim: ${e.message}`);
      }
  });
  
  // ---------- THEME (Light/Dark Mode) ----------
  function initTheme() {
    const root = document.documentElement;
    const saved = localStorage.getItem('dgs-theme');
    if (saved === 'light' || saved === 'dark') {
      root.setAttribute('data-theme', saved);
    }
    
    el.toggleTheme?.addEventListener('click', ()=>{
      const cur = root.getAttribute('data-theme') || 'light';
      const next = cur === 'light' ? 'dark' : 'light';
      root.setAttribute('data-theme', next);
      localStorage.setItem('dgs-theme', next);
      updateChartColors();
    });
  }

  // ---------- INITIALIZATION (Startup) ----------
  function init() {
    initMap();
    initCharts();
    fillCmds();
    initTheme();
    info('DAEDALUS Ground Station Initialized.');
    connect();
    
    // Force map to resize correctly after loading
    setTimeout(() => {
        window.dispatchEvent(new Event('resize'));
    }, 500);
  }
  window.addEventListener('DOMContentLoaded', init);

})();
}