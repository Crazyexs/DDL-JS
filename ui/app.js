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
    // clocks
    utcClock: $('#utcClock'),
    missionSmall: $('#missionTime'),
    missionBig: $('#missionTimeBig'),
    // conn
    linkType: $('#linkType'),
    portName: $('#portName'),
    baudVal:  $('#baudVal'),
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
    csvName: $('#csvName'),
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
    healthLastCmd: $('#healthLastCmd'),
    // commands
    quick: $('#quickCmd'),
    manual: $('#manualCmd'),
    send: $('#sendCmd'),
    // new buttons from index.html
    btnOpenCsvFolder: $('#btnOpenCsvFolder'),
    btnSim: $('#btnSim'),
    // New Status Panel
    missionState: $('#missionState'),
    missionMode: $('#missionMode'),
    gpsSats: $('#gpsSats'),
    gpsSpeed: $('#gpsSpeed'),
    power: $('#power'),
    compassArrow: $('#compassArrow'),
    heading: $('#heading'),
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

  async function updateHealth() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const health = await res.json();
      el.portName && (el.portName.textContent = health.serial?.port || '—');
      el.baudVal && (el.baudVal.textContent = health.serial?.baud || '—');
      if (el.csvName && health.csv) {
          el.csvName.textContent = health.csv.split(/[\\/]/).pop();
      }
    } catch (e) {
      warn(`Health check failed: ${e.message}`);
    }
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
  function makeMulti(elId, names, colors = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc']) {
    const elc = document.getElementById(elId);
    if (!elc) return null;
    const inst = echarts.init(elc);
    inst.setOption({
      grid: { left: 44, right: 18, top: 38, bottom: 28 },
      animation: false,
      xAxis: { type: 'category', data: [], axisLabel: { show: false } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: 'var(--muted)'} },
      legend: { data: names, top: 0, textStyle: { color: 'var(--fg)' } },
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

  function initCharts() {
    st.charts.altitude = makeMulti('chart-altitude', ['Baro Alt', 'GPS Alt']);
    st.charts.power = makeMulti('chart-power', ['Voltage', 'Current']);
    st.charts.environment = makeMulti('chart-environment', ['Temp', 'Pressure']);
    st.charts.gyro = makeMulti('chart-gyro', ['X', 'Y', 'Z']);
    st.charts.accel = makeMulti('chart-accel', ['X', 'Y', 'Z']);
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

    // Status Panel
    el.missionState && (el.missionState.textContent = t.state || '—');
    el.missionMode && (el.missionMode.textContent = t.mode || '—');
    el.gpsSats && (el.gpsSats.textContent = t.gps_sats ?? '—');
    updateCompass(t.heading);

    // counters from backend
    el.rxCount && (el.rxCount.textContent = t.gs_rx_count);
    el.lossCount && (el.lossCount.textContent = t.gs_loss_total);

    // time
    if (t.gps_time && /^\d\d:\d\d:\d\d$/.test(t.gps_time)) st.lastGPSHMS = t.gps_time;
    if (typeof t.altitude_m === 'number') st.lastAlt = t.altitude_m;

    // command echo
    if (t.cmd_echo) {
      el.lastCmd && (el.lastCmd.textContent = t.cmd_echo);
      el.healthLastCmd && (el.healthLastCmd.textContent = t.cmd_echo);
    }

    // charts
    const label = t.mission_time || hms();
    pushChart(st.charts.altitude, label, [t.altitude_m, t.gps_altitude_m]);
    pushChart(st.charts.power, label, [t.voltage_v, t.current_a]);
    pushChart(st.charts.environment, label, [t.temperature_c, t.pressure_kpa]);
    pushChart(st.charts.gyro, label, [t.gyro_r_dps, t.gyro_p_dps, t.gyro_y_dps]);
    pushChart(st.charts.accel, label, [t.accel_r_dps2, t.accel_p_dps2, t.accel_y_dps2]);

    // map
    if (t.gps_lat && t.gps_lon && typeof t.gps_lat === 'number' && typeof t.gps_lon === 'number') {
      const pos = [t.gps_lat, t.gps_lon];
      st.marker?.setLatLng(pos);
      st.map?.panTo(pos, { animate: false });
      el.gpsMini && (el.gpsMini.textContent = `${t.gps_lat.toFixed(5)}, ${t.gps_lon.toFixed(5)} • sats: ${t.gps_sats ?? '—'}`);
      el.gmapA && (el.gmapA.href = `https://maps.google.com/?q=${t.gps_lat},${t.gps_lon}`);
    }

    // Render a summary line in the log
    const wrapIsOn = el.wrap?.checked;
    let logText;
    if (wrapIsOn && t.gs_raw_line) {
        logText = t.gs_raw_line;
    } else {
        logText = `#${t.packet_count || '—'} ${t.state || '—'} | Alt: ${num(t.altitude_m)}m | ${t.cmd_echo ? `Echo: ${t.cmd_echo}` : ''}`;
    }
    log('info', logText);
  }

  // ---------- logs UX ----------
  (function () {
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
    el.wrap?.addEventListener('change', () => el.rawBox.classList.toggle('wrap', !!el.wrap.checked));
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

  function makeDummyTelemetry() {
    st.dummy.packet += 1;
    st.dummy.lat += (Math.random() - 0.5) * 0.0002;
    st.dummy.lon += (Math.random() - 0.5) * 0.0002;
    const altitude = 150 + Math.sin(st.dummy.packet / 30) * 120 + (Math.random() - 0.5) * 5;
    const temp = 25 - (altitude / 100);
    const voltage = 12.6 - (st.dummy.packet / 500);
    const current = 0.5 + (Math.random() - 0.5) * 0.2;

    const t = {
      team_id: st.teamId,
      mission_time: hms(new Date(Date.now() - (st.t0 ? (Date.now() - st.t0) : 0) + (st.dummy.packet * 1000))),
      packet_count: st.dummy.packet,
      mode: 'F',
      state: altitude < 20 ? 'LAUNCH_PAD' : (st.lastAlt < altitude) ? 'ASCENT' : 'DESCENT',
      altitude_m: altitude,
      temperature_c: temp,
      pressure_kpa: 101.325 * Math.pow(1 - 2.25577e-5 * altitude, 5.25588),
      voltage_v: voltage,
      current_a: current,
      gyro_r_dps: (Math.random() - 0.5) * 20,
      gyro_p_dps: (Math.random() - 0.5) * 20,
      gyro_y_dps: 180 + (Math.random() - 0.5) * 40,
      accel_r_dps2: (Math.random() - 0.5) * 2,
      accel_p_dps2: (Math.random() - 0.5) * 2,
      accel_y_dps2: 9.8 + (Math.random() - 0.5),
      gps_time: hms(),
      gps_altitude_m: altitude + 10,
      gps_lat: st.dummy.lat,
      gps_lon: st.dummy.lon,
      gps_sats: 8 + Math.floor(Math.random() * 4),
      cmd_echo: st.dummy.packet % 10 === 0 ? 'CX,ON' : 'CMD_OK',
      heading: (st.dummy.packet * 5) % 360,
      gs_ts_utc: new Date().toISOString(),
      gs_rx_count: st.dummy.packet,
      gs_loss_total: Math.floor(st.dummy.packet / 100),
    };
    
    // Reconstruct the CSV line for logging
    t.gs_raw_line = [
      t.team_id, t.mission_time, t.packet_count, t.mode, t.state,
      num(t.altitude_m, 2), num(t.temperature_c, 2), num(t.pressure_kpa, 3),
      num(t.voltage_v, 2), num(t.current_a, 3),
      num(t.gyro_r_dps, 3), num(t.gyro_p_dps, 3), num(t.gyro_y_dps, 3),
      num(t.accel_r_dps2, 3), num(t.accel_p_dps2, 3), num(t.accel_y_dps2, 3),
      t.gps_time, num(t.gps_altitude_m, 2), num(t.gps_lat, 4), num(t.gps_lon, 4),
      t.gps_sats, t.cmd_echo, num(t.heading, 2)
    ].join(',');

    onTelemetry(t);
  }

  function startDummy() {
    if (st.dummy.id) return;
    info('Dummy data started. Sends 1 packet/sec.');
    st.dummy.packet = 0;
    st.dummy.id = setInterval(makeDummyTelemetry, 1000);
  }

  function stopDummy() {
    if (!st.dummy.id) return;
    info('Dummy data stopped.');
    clearInterval(st.dummy.id);
    st.dummy.id = null;
  }

  async function sendCommand(cmdStr) {
    const cmd = cmdStr.trim();
    if (!cmd) return;

    // Handle local slash-commands
    if (cmd.startsWith('/')) {
        const command = cmd.toLowerCase();
        if (command === '/dummy.on') {
            startDummy();
            return;
        }
        if (command === '/dummy.off') {
            stopDummy();
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
    el.healthLastCmd.textContent = cmd;
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
    const url = `ws://${window.location.host}/ws/telemetry`;
    info(`Connecting to ${url}...`);
    st.ws = new WebSocket(url);

    st.ws.onopen = () => {
      info('Backend connected.');
      setPill(true, 'Connected');
      updateHealth();
    };

    st.ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === 'error') {
          err(data.message || 'Received an unknown error from backend.');
        } else {
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
      err('WebSocket error.');
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

  // ---------- init ----------
  function init() {
    initMap();
    initCharts();
    fillCmds();
    info('DAEDALUS Ground Station Initialized.');
    connect();
  }
  window.addEventListener('DOMContentLoaded', init);

})();
}