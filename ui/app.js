if (!window.__DGS_BOOTED__) {
  window.__DGS_BOOTED__ = true;

/* DAEDALUS #1043 — app.js (CSV + JSON)
 * - Browser (Web Serial): pick port, open/close, read loop, write on commands
 * - Server bridge (WebSocket, optional): list/open/close/read/write via JSON protocol
 * - Unified DGS_appendLine(): accepts CSV (28 cols) or {"telemetry":{...}}
 * - Everything logs to the UI (info/warn/err)
 */

(function () {
  // ---------- helpers ----------
  const $ = (s) => document.querySelector(s);
  const pad = (n) => String(n).padStart(2, '0');
  const hms = (d = new Date()) => `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  const esc = (s) => String(s).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
  const num = (x, d = 1) => (x === undefined || x === null || isNaN(+x)) ? '—' : (+x).toFixed(d);
  const getCssVar = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  // ---------- state ----------
  const st = {
    teamId: window.DGS_TEAM_ID || 1043,
    t0: null,
    charts: {},
    map: null,
    marker: null,
    ws: null, // WebSocket instance
    lastGPSHMS: null,
    altZero: 0,
    lastAlt: 0,
    // dummy
    dummy: { id: null, packet: 0, lat: 18.788, lon: 98.985 },
  };

  // ---------- DOM ----------
  const el = {
    // theme
    toggleTheme: $('#toggleTheme'),
    // clocks
    utcClock: $('#utcClock'),
    missionSmall: $('#missionTime'),
    missionBig: $('#missionTimeBig'),
    // conn
    connPill: $('#connPill'),
    // map + mission
    btnStartMission: $('#btnStartMission'),
    mapEl: $('#map'),
    mapToggle: $('#toggleMapSize'),
    gpsMini: $('#gpsMiniTitle'),
    gmapA: $('#gmapA'),
    // health
    rxCount: $('#rxCount'),
    lossCount: $('#lossCount'),
    // logs
    rawBox: $('#rawBox'),
    logN: $('#logN'),
    auto: $('#autoScroll'),
    freeze: $('#freeze'),
    wrap: $('#wrapLines'),
    refreshLogs: $('#refreshLogs'),
    jumpLive: $('#jumpLive'),
    jumpLiveBtn: $('#jumpLiveBtn'),
    copyLogs: $('#copyLogs'),
    resetAll: $('#btnResetAllTop'),
    lastCmd: $('#lastCmd'),
    // commands
    quick: $('#quickCmd'),
    manual: $('#manualCmd'),
    send: $('#sendCmd'),
    // new buttons from index.html
    btnOpenCsvFolder: $('#btnOpenCsvFolder'),
    btnSim: $('#btnSim'),
    
    // New Large Displays
    missionState: $('#missionState'),
    liveAltitude: $('#liveAltitude'),
    missionMode: $('#missionMode'),
    gpsSats: $('#gpsSats'),
    compassArrow: $('#compassArrow'),
    heading: $('#heading'),

    // New Key Values
    val_temp: $('#val_temp'),
    val_pressure: $('#val_pressure'),
    val_voltage: $('#val_voltage'),
    val_current: $('#val_current'),
    val_gyro_x: $('#val_gyro_x'),
    val_gyro_y: $('#val_gyro_y'),
    val_gyro_z: $('#val_gyro_z'),
    val_accel_x: $('#val_accel_x'),
    val_accel_y: $('#val_accel_y'),
    val_accel_z: $('#val_accel_z'),
    
    // Chart Toggles
    altitudeToggles: $('#altitudeToggles'),
  };

  // ---------- log UI ----------
  function log(kind, msg) {
    const ts = hms();
    const klass = kind === 'err' ? 'k err' : kind === 'warn' ? 'k warn' : (kind === 'cmd' ? 'k cmd' : 'text');
    const line = document.createElement('div');
    line.className = 'logline';
    line.innerHTML = `<span class="ts">[${ts}]</span><span class="${klass}">${esc(msg)}</span>`;
    if (!el.rawBox) return;
    const max = Number(el.logN?.value || 500);
    while (el.rawBox.children.length >= max) el.rawBox.removeChild(el.rawBox.firstChild);
    el.rawBox.appendChild(line);
    if (el.auto?.checked && !el.freeze?.checked) el.rawBox.scrollTop = el.rawBox.scrollHeight;
  }
  function info(m) { log('info', m); }
  function warn(m) { log('warn', m); }
  function err(m) { log('err', m); }
  function cmdEcho(m) { log('cmd', m); }


  // ---------- health & connection ----------
  function setPill(connected, text = 'Connected') {
    if (!el.connPill) return;
    el.connPill.textContent = connected ? text : 'Disconnected';
    el.connPill.className = 'pill' + (connected ? ' ok' : '');
  }

  // ---------- clocks ----------
  function tickUTC() {
    if (!el.utcClock) return;
    const d = new Date();
    el.utcClock.textContent = `UTC: ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
  }
  setInterval(tickUTC, 1000); tickUTC();

  function tickMission() {
    if (!st.t0 || el.freeze?.checked) return;
    const s = Math.floor((Date.now() - st.t0) / 1000);
    const t = `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
    el.missionSmall && (el.missionSmall.textContent = 'Mission: ' + t);
    el.missionBig && (el.missionBig.textContent = t);
  }
  setInterval(tickMission, 250);
  el.btnStartMission?.addEventListener('click', () => { if (!st.t0) st.t0 = Date.now(); info("Mission Timer Started.");});


  // ---------- map ----------
  function initMap() {
    if (!el.mapEl) return;
    st.map = L.map('map', { zoomControl: true, attributionControl: false }).setView([18.788, 98.985], 16);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(st.map);
    st.marker = L.marker([18.788, 98.985]).addTo(st.map);
  }
  
  // ---------- charts ----------
  function getChartColors() {
    return [getCssVar('--chart-color-1'), getCssVar('--chart-color-2')];
  }

  function makeMulti(elId, names) {
    const elc = document.getElementById(elId);
    if (!elc) return null;
    const inst = echarts.init(elc);
    const colors = getChartColors();
    inst.setOption({
      grid: { left: 44, right: 18, top: 38, bottom: 28 },
      animation: false,
      xAxis: { type: 'category', data: [], axisLabel: { show: false } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: getCssVar('--muted')} },
      legend: { show: false, data: names, top: 0, textStyle: { color: getCssVar('--fg') } }, // Keep legend data, but hide it
      series: names.map((n, i) => ({ type: 'line', name: n, showSymbol: false, data: [], lineStyle: { color: colors[i] } })),
      tooltip: { trigger: 'axis' }
    });
    return inst;
  }

  function pushChart(inst, label, values) {
    if (!inst) return;
    const opt = inst.getOption();
    opt.xAxis[0].data.push(label);
    (Array.isArray(values) ? values : [values]).forEach((v, i) => opt.series[i].data.push(v));
    const max = 120;
    if (opt.xAxis[0].data.length > max) { opt.xAxis[0].data.shift(); opt.series.forEach(s => s.data.shift()); }
    inst.setOption(opt, false, true);
  }
  
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
  


  window.addEventListener('resize', () => {
    Object.values(st.charts).forEach(c => c?.resize());
    st.map?.invalidateSize();
  });

  // ---------- telemetry handling ----------
  function updateCompass(heading) {
    if (!el.compassArrow) return;
    el.compassArrow.style.transform = `rotate(${heading || 0}deg)`;
    el.heading.textContent = `${num(heading, 0)}°`;
  }

  function onTelemetry(t) {
    // This function is the main entry point for new telemetry data from the backend
    if (el.freeze?.checked) return;

    // ----- Big Displays -----
    el.missionState && (el.missionState.textContent = t.state || '—');
    el.liveAltitude && (el.liveAltitude.textContent = num(t.altitude_m, 1));
    
    // ----- Strip Displays -----
    el.missionMode && (el.missionMode.textContent = t.mode || '—');
    el.gpsSats && (el.gpsSats.textContent = t.gps_sats ?? '—');
    updateCompass(t.heading);

    // ----- Key Value Panel -----
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


    // ----- Counters -----
    el.rxCount && (el.rxCount.textContent = t.gs_rx_count);
    el.lossCount && (el.lossCount.textContent = t.gs_loss_total);

    // ----- Time & State Tracking -----
    // Use mission time from telemetry if valid, otherwise fallback to local tick
    if (t.mission_time && /^\d\d:\d\d:\d\d$/.test(t.mission_time)) {
        el.missionBig && (el.missionBig.textContent = t.mission_time);
    }

    if (t.gps_time && /^\d\d:\d\d:\d\d$/.test(t.gps_time)) st.lastGPSHMS = t.gps_time;
    if (typeof t.altitude_m === 'number') st.lastAlt = t.altitude_m;

    // ----- Command Echo -----
    if (t.cmd_echo) {
      el.lastCmd && (el.lastCmd.textContent = t.cmd_echo);
    }

    // ----- Charts -----
    const label = t.mission_time || hms();
    pushChart(st.charts.altitude, label, [t.altitude_m]);

    // ----- Map -----
    if (t.gps_lat && t.gps_lon && typeof t.gps_lat === 'number' && typeof t.gps_lon === 'number') {
      const pos = [t.gps_lat, t.gps_lon];
      st.marker?.setLatLng(pos);
      st.map?.panTo(pos, { animate: false });
      el.gpsMini && (el.gpsMini.textContent = `${t.gps_lat.toFixed(5)}, ${t.gps_lon.toFixed(5)} • sats: ${t.gps_sats ?? '—'}`);
      el.gmapA && (el.gmapA.href = `https://maps.google.com/?q=${t.gps_lat},${t.gps_lon}`);
    }

    // ----- Log Summary Line -----
    try {
      const showRaw = el.showRaw?.checked;
      let logText;

      if (showRaw && t.gs_raw_line) {
          logText = t.gs_raw_line;
      } else {
          // "Easy Read" Format: #PKT STATE | Alt | Volt | Temp | Press | ...
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

  // ---------- logs UX ----------
  (function () {
    // DOM elements
    el.showRaw = $('#showRaw');
    
    if (!el.rawBox) return;
    const update = () => {
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

  // ---------- commands ----------
  const QUICK_COMMANDS = [
    'CX,ON', 'CX,OFF',
    'CAL',
    'ST,GPS',
    'SIM,ENABLE', 'SIM,ACTIVATE', 'SIM,DISABLE',
    'MEC,PL,ON', 'MEC,PL,OFF',
    '/dummy.on', '/dummy.off'
  ];
  function fillCmds() {
    if (!el.quick) return;
    el.quick.innerHTML = '';
    const opt0 = document.createElement('option'); opt0.value = ''; opt0.textContent = '— Quick Command —';
    el.quick.append(opt0);
    QUICK_COMMANDS.forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = c; el.quick.append(o); });
  }

  async function sendCommand(cmdStr) {
    const cmd = cmdStr.trim();
    if (!cmd) return;

    // Handle local slash-commands
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

    // Immediate UI Update for remote commands
    el.lastCmd.textContent = cmd;
    cmdEcho('> ' + cmd); // Optimistic echo to log

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
      // The successful command will be echoed back in the telemetry packet later
    } catch (e) {
      err(`Command failed: ${e.message}`);
    }
  }

  el.quick?.addEventListener('change', () => { if (el.quick.value && el.manual) { el.manual.value = el.quick.value; el.quick.value = ''; } });
  el.send?.addEventListener('click', () => { const v = (el.manual?.value || '').trim(); if (!v) return; sendCommand(v); if (el.manual) el.manual.value = ''; });
  el.manual?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); el.send.click(); } });


  // ---------- WebSocket Connection ----------
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
          onTelemetry(data);
        }
      } catch (e) {
        warn(`Invalid JSON from backend: ${e.message}`);
      }
    };

    st.ws.onclose = () => {
      st.ws = null;
      err('Backend disconnected.');
      setPill(false, 'Retrying...');
      setTimeout(connect, 2000); // Reconnect after 2s
    };

    st.ws.onerror = (e) => {
      err('WebSocket error. Check browser console for details.');
      console.error('WebSocket error:', e);
      st.ws?.close();
    };
  }

  // ---------- Action Buttons ----------
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
  
  // ---------- Theme ----------
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

  // ---------- init ----------
  function init() {
    initMap();
    initCharts();
    fillCmds();
    initTheme();
    info('DAEDALUS Ground Station Initialized.');
    connect();
    
    // Force map resize for mobile layout
    setTimeout(() => {
        window.dispatchEvent(new Event('resize'));
    }, 500);
  }
  window.addEventListener('DOMContentLoaded', init);

})();
}