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
    rx: 0,
    loss: 0,
    csv: 'TEAM_ID,MISSION_TIME,PACKET,MODE,STATE,ALT_M,TEMP_C,PRESS_KPA,VOLT_V,GYRO_R_DPS,GYRO_P_DPS,GYRO_Y_DPS,ACC_R_DPS2,ACC_P_DPS2,ACC_Y_DPS2,MAG_R,MAG_P,MAG_Y,AUTO_GYRO_DPS,GPS_TIME,GPS_ALT_M,GPS_LAT,GPS_LON,GPS_SATS,CMD_ECHO,GS_TS_UTC,GS_RX_COUNT,GS_LOSS_TOTAL\n',
    lastGPSHMS: null,
    altZero: 0,
    lastAlt: 0,
    // link
    linkType: '—', // 'Browser' | 'Server' | '—'
    // Browser serial
    br: { port: null, reader: null, writer: null, baud: 115200, textDecoder: null, textEncoder: null, readLoopAbort: null },
    // Server bridge (optional)
    sv: { ws: null, url: 'ws://localhost:8787', open: false, port: '', baud: 115200 },
    // dummy
    dummy: { on: false, id: null, period: 1000, simEnabled: false, simActive: false, pressure_pa: 101325 },
  };

  // ---------- DOM ----------
  const el = {
    // clocks
    utcClock: $('#utcClock'),
    missionSmall: $('#missionTime'),
    missionBig: $('#missionTimeBig'),
    // mode
    modeBrowser: $('#modeBrowser'),
    modeServer: $('#modeServer'),
    linkType: $('#linkType'),       // optional (not in your HTML; safe)
    portName: $('#portName'),       // optional
    baudVal:  $('#baudVal'),        // optional
    connPill: $('#connPill'),
    // browser serial panel
    browserPanel: $('#browserSerialPanel') || $('#connectionPanel') || $('.group'), // best-effort
    browserBaudSel: $('#browserBaudSel'), // optional
    btnBrowserPick: $('#btnBrowserPick'), // optional
    btnConnectBrowser: $('#btnConnectBrowser'),
    btnDisconnectBrowser: $('#btnDisconnectBrowser'),
    // server panel (works with either #serverPanel or your #serverSerialPanel)
    serverPanel: $('#serverPanel') || $('#serverSerialPanel'),
    wsUrl: $('#wsUrl'),                     // optional
    btnConnectServer: $('#btnConnectServer'), // optional
    btnDisconnectServer: $('#btnDisconnectServer'), // optional
    portSel: $('#portSel'),
    baudSel: $('#baudSel'),
    applyPort: $('#applyPort'),
    closePort: $('#closePort'),       // optional
    refreshPorts: $('#refreshPorts'),
    // map + mission
    btnStartMission: $('#btnStartMission'),
    mapEl: $('#map'),
    mapToggle: $('#toggleMapSize'),
    gpsMini: $('#gpsMiniTitle'),
    gmapA: $('#gmapA'),
    // health
    rxCount: $('#rxCount'),
    lossCount: $('#lossCount'),
    contState: $('#containerState'),
    plState: $('#payloadState'),
    contBattPct: $('#contBattPct'),
    plBattPct: $('#plBattPct'),
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
    btnSaveCSV: $('#btnSaveCSV'),
    resetAll: $('#btnResetAllTop'),
    lastCmd: $('#lastCmd'),
    healthLastCmd: $('#healthLastCmd'),
    // commands
    quick: $('#quickCmd'),
    manual: $('#manualCmd'),
    send: $('#sendCmd'),
    btnDemoPaste: $('#btnDemoPaste'),
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

  // ---------- pills / health ----------
  function setPill(connected) {
    if (!el.connPill) return;
    el.connPill.textContent = connected ? 'Connected' : 'Disconnected';
    el.connPill.className = 'pill' + (connected ? ' ok' : '');
  }
  function setLink(type, port = '—', baud = '—') {
    st.linkType = type;
    el.linkType && (el.linkType.textContent = type);
    el.portName && (el.portName.textContent = port || '—');
    el.baudVal && (el.baudVal.textContent = baud || '—');
    setPill(type !== '—');
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
  el.btnStartMission?.addEventListener('click', () => { if (!st.t0) st.t0 = Date.now(); });

  // ---------- map ----------
  function initMap() {
    if (!el.mapEl) return;
    st.map = L.map('map', { zoomControl: true, attributionControl: false }).setView([18.788, 98.985], 16);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(st.map);
    st.marker = L.marker([18.788, 98.985]).addTo(st.map);
  }
  el.mapToggle?.addEventListener('click', () => {
    if (!el.mapEl) return;
    el.mapEl.classList.toggle('large');
    setTimeout(() => st.map?.invalidateSize(), 80);
    el.mapToggle.textContent = el.mapEl.classList.contains('large') ? 'Small' : 'Full';
  });

  // ---------- charts ----------
  function makeLine(elId, name) {
    const elc = document.getElementById(elId);
    if (!elc) return null;
    const inst = echarts.init(elc);
    inst.setOption({
      grid: { left: 40, right: 12, top: 18, bottom: 28 },
      animation: false,
      xAxis: { type: 'category', data: [], axisLabel: { show: false } },
      yAxis: { type: 'value', name, scale: true, nameTextStyle: { fontSize: 10 } },
      series: [{ type: 'line', name, showSymbol: false, data: [] }],
      tooltip: { trigger: 'axis' }
    });
    return inst;
  }
  function makeMulti(elId, names) {
    const elc = document.getElementById(elId);
    if (!elc) return null;
    const inst = echarts.init(elc);
    inst.setOption({
      grid: { left: 44, right: 12, top: 18, bottom: 28 },
      animation: false,
      xAxis: { type: 'category', data: [], axisLabel: { show: false } },
      yAxis: { type: 'value', scale: true },
      legend: { data: names },
      series: names.map(n => ({ type: 'line', name: n, showSymbol: false, data: [] })),
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
    st.charts.temp = makeLine('chart-cont-temp', '°C');
    st.charts.alt = makeLine('chart-cont-alt', 'm');
    st.charts.gpsalt = makeLine('chart-cont-gpsalt', 'm');
    st.charts.volt = makeLine('chart-cont-volt', 'V');
    st.charts.gyro = makeMulti('chart-pl-gyro', ['R', 'P', 'Y']);
    st.charts.acc = makeMulti('chart-pl-acc', ['R', 'P', 'Y']);
  }
  window.addEventListener('resize', () => {
    Object.values(st.charts).forEach(c => c?.resize());
    st.map?.invalidateSize();
  });

  // ---------- CSV -> telemetry (28 columns) ----------
  function csvToTelemetry(line) {
    const parts = line.trim().split(',');
    if (parts.length < 28) return null;
    const N = i => (parts[i] === '' ? null : Number(parts[i]));
    const S = i => (parts[i] ?? '');
    return {
      team_id: N(0),
      mission_time: S(1),
      packet_count: N(2),
      mode: S(3),
      state: S(4),
      altitude_m: N(5),
      temperature_c: N(6),
      pressure_kpa: N(7),
      voltage_v: N(8),
      gyro_r_dps: N(9),
      gyro_p_dps: N(10),
      gyro_y_dps: N(11),
      accel_r_dps2: N(12),
      accel_p_dps2: N(13),
      accel_y_dps2: N(14),
      mag_r_gauss: N(15),
      mag_p_gauss: N(16),
      mag_y_gauss: N(17),
      auto_gyro_rot_rate_dps: N(18),
      gps_time: S(19),
      gps_altitude_m: N(20),
      gps_lat: N(21),
      gps_lon: N(22),
      gps_sats: N(23),
      cmd_echo: S(24),
      gs_ts_utc: S(25),
      gs_rx_count: N(26),
      gs_loss_total: N(27),
    };
  }

  // ---------- telemetry handling ----------
  function battPct(v) {
    // Approx 3S Li-ion: tweak if needed
    const pct = (v - 10.8) / (12.6 - 10.8) * 100;
    return Math.max(0, Math.min(100, Math.round(pct)));
  }
  function onTelemetry(t) {
    // counters
    st.rx += 1; el.rxCount && (el.rxCount.textContent = st.rx);
    st.loss = t.gs_loss_total | 0; el.lossCount && (el.lossCount.textContent = st.loss);

    // states
    el.contState && (el.contState.textContent = 'STATE: ' + (t.state || '—'));
    el.plState && (el.plState.textContent = 'STATE: ' + (t.state || '—'));
    const bp = battPct(+t.voltage_v || 0);
    el.contBattPct && (el.contBattPct.textContent = bp);
    el.plBattPct && (el.plBattPct.textContent = bp);

    if (t.gps_time && /^\d\d:\d\d:\d\d$/.test(t.gps_time)) st.lastGPSHMS = t.gps_time;
    if (typeof t.altitude_m === 'number') st.lastAlt = t.altitude_m;

    // charts
    const label = t.mission_time || t.gps_time || hms();
    pushChart(st.charts.temp, label, +t.temperature_c || 0);
    pushChart(st.charts.alt, label, (+t.altitude_m || 0) - st.altZero);
    pushChart(st.charts.gpsalt, label, +t.gps_altitude_m || 0);
    pushChart(st.charts.volt, label, +t.voltage_v || 0);
    pushChart(st.charts.gyro, label, [+t.gyro_r_dps || 0, +t.gyro_p_dps || 0, +t.gyro_y_dps || 0]);
    pushChart(st.charts.acc, label, [+t.accel_r_dps2 || 0, +t.accel_p_dps2 || 0, +t.accel_y_dps2 || 0]);

    // map
    if (typeof t.gps_lat === 'number' && typeof t.gps_lon === 'number') {
      st.marker?.setLatLng([t.gps_lat, t.gps_lon]);
      st.map?.panTo([t.gps_lat, t.gps_lon], { animate: false });
      el.gpsMini && (el.gpsMini.textContent = `${t.gps_lat.toFixed(5)}, ${t.gps_lon.toFixed(5)} • sats: ${t.gps_sats ?? '—'}`);
      el.gmapA && (el.gmapA.href = `https://maps.google.com/?q=${t.gps_lat},${t.gps_lon}`);
    }
  }
  function renderTelemetryLine(t) {
    const gy = `${num(t.gyro_r_dps)}/${num(t.gyro_p_dps)}/${num(t.gyro_y_dps)}`;
    const ac = `${num(t.accel_r_dps2)}/${num(t.accel_p_dps2)}/${num(t.accel_y_dps2)}`;
    const txt = `#${t.packet_count || '—'} ${t.state || '—'} alt ${num((t.altitude_m || 0) - st.altZero)}m gpsAlt ${num(t.gps_altitude_m)}m T ${num(t.temperature_c)}°C V ${num(t.voltage_v)}V sats ${t.gps_sats ?? '—'} | gyro ${gy} | accel ${ac} | loss ${t.gs_loss_total ?? 0}${t.cmd_echo ? ` | echo ${t.cmd_echo}` : ''}`;
    log('cmd', txt);
  }
  function csvAppend(t) {
    const f = (x) => (x === undefined || x === null) ? '' : String(x);
    st.csv += [
      f(t.team_id), f(t.mission_time), f(t.packet_count), f(t.mode), f(t.state),
      f(t.altitude_m), f(t.temperature_c), f(t.pressure_kpa), f(t.voltage_v),
      f(t.gyro_r_dps), f(t.gyro_p_dps), f(t.gyro_y_dps),
      f(t.accel_r_dps2), f(t.accel_p_dps2), f(t.accel_y_dps2),
      f(t.mag_r_gauss), f(t.mag_p_gauss), f(t.mag_y_gauss),
      f(t.auto_gyro_rot_rate_dps), f(t.gps_time), f(t.gps_altitude_m),
      f(t.gps_lat), f(t.gps_lon), f(t.gps_sats),
      f(t.cmd_echo), f(t.gs_ts_utc), f(t.gs_rx_count), f(t.gs_loss_total)
    ].join(',') + '\n';
  }

  // ---------- Unified ingestor (CSV or JSON) ----------
  window.DGS_appendLine = function (input) {
    // input can be: raw CSV string, raw JSON string, or {telemetry:{...}} object
    let handled = false;

    // (A) Direct object with telemetry
    if (typeof input === 'object' && input && input.telemetry) {
      const t = input.telemetry;
      csvAppend(t);
      renderTelemetryLine(t);
      onTelemetry(t);
      if (t.cmd_echo) { el.lastCmd && (el.lastCmd.textContent = t.cmd_echo); el.healthLastCmd && (el.healthLastCmd.textContent = t.cmd_echo); }
      handled = true;
    }

    // (B) Raw string
    if (!handled && typeof input === 'string') {
      const s = input.trim();

      // Try JSON
      if (s.startsWith('{')) {
        try {
          const obj = JSON.parse(s);
          if (obj && obj.telemetry) {
            const t = obj.telemetry;
            csvAppend(t);
            renderTelemetryLine(t);
            onTelemetry(t);
            if (t.cmd_echo) { el.lastCmd && (el.lastCmd.textContent = t.cmd_echo); el.healthLastCmd && (el.healthLastCmd.textContent = t.cmd_echo); }
            handled = true;
          }
        } catch (_) { /* not JSON */ }
      }

      // Try CSV (28 fields)
      if (!handled && s.includes(',')) {
        const t = csvToTelemetry(s);
        if (t) {
          csvAppend(t);
          renderTelemetryLine(t);
          onTelemetry(t);
          if (t.cmd_echo) { el.lastCmd && (el.lastCmd.textContent = t.cmd_echo); el.healthLastCmd && (el.healthLastCmd.textContent = t.cmd_echo); }
          handled = true;
        }
      }

      // Fallback: plain text to log
      if (!handled) { info(s); handled = true; }
    }

    // (C) Anything else → stringify to log
    if (!handled) {
      info(typeof input === 'string' ? input : JSON.stringify(input));
    }
  };

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
  el.refreshLogs?.addEventListener('click', () => { if (!el.rawBox) return; el.rawBox.innerHTML = ''; info('Log cleared.'); });
  el.copyLogs?.addEventListener('click', async () => { if (!el.rawBox) return; await navigator.clipboard.writeText([...(el.rawBox.querySelectorAll('.logline'))].map(n => n.innerText).join('\n')); cmdEcho('Logs copied.'); });
  el.btnSaveCSV?.addEventListener('click', () => { const a = document.createElement('a'); a.href = 'data:text/plain;charset=utf-8,' + encodeURIComponent(st.csv); a.download = `Flight_${st.teamId}.csv`; a.click(); });
  el.resetAll?.addEventListener('click', () => { if (el.rawBox) el.rawBox.innerHTML = ''; Object.values(st.charts).forEach(c => c?.clear()); initCharts(); cmdEcho('Reset all.'); });

  // ---------- commands ----------
  const COMMANDS = [
    '/clear',
    '/dummy.on', '/dummy.off', '/dummy.time 0.5',
    '/cal',
    '/cx.on', '/cx.off',
    '/st.gps', '/st 13:35:59',
    '/sim.enable', '/sim.activate', '/sim.disable', '/simp 101325',
    '/mec.RELEASE.on', '/mec.RELEASE.off'
  ];
  function fillCmds() {
    if (!el.quick) return;
    el.quick.innerHTML = '';
    const opt0 = document.createElement('option'); opt0.value = ''; opt0.textContent = '— Quick Command —';
    el.quick.append(opt0);
    COMMANDS.forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = c; el.quick.append(o); });
  }
  fillCmds();
  el.quick?.addEventListener('change', () => { if (el.quick.value && el.manual) { el.manual.value = el.quick.value; el.quick.value = ''; } });

  function dispatch(cmdLine) {
    const parts = cmdLine.trim().split(/\s+/);
    const cmd = (parts.shift() || '').toLowerCase();
    el.lastCmd && (el.lastCmd.textContent = cmdLine);
    el.healthLastCmd && (el.healthLastCmd.textContent = cmdLine);
    switch (cmd) {
      case '/clear': el.rawBox && (el.rawBox.innerHTML = ''); info('Cleared.'); return;
      case '/dummy.on': startDummy(); return;
      case '/dummy.off': stopDummy(); return;
      case '/dummy.time': {
        const sec = parseFloat(parts[0]); if (isFinite(sec) && sec > 0) { setDummyPeriod(sec); } else err('dummy.time <sec>'); return;
      }
      case '/cal': st.altZero = st.lastAlt || 0; cmdEcho(`Altitude zero set to ${num(st.altZero)} m`); return;
      case '/cx.on': cmdEcho('CX ON (echo)'); return;
      case '/cx.off': cmdEcho('CX OFF (echo)'); return;
      case '/st.gps': {
        const hh = st.lastGPSHMS;
        if (hh && /^\d\d:\d\d:\d\d$/.test(hh)) {
          const [h, m, s] = hh.split(':').map(Number);
          st.t0 = Date.now() - ((h * 3600 + m * 60 + s) * 1000);
          cmdEcho(`Mission time set from GPS ${hh}`);
        } else {
          warn('No GPS time; using now'); st.t0 = Date.now();
        }
        return;
      }
      case '/st': {
        const hh = (parts[0] || '');
        if (/^\d\d:\d\d:\d\d$/.test(hh)) {
          const [h, m, s] = hh.split(':').map(Number);
          st.t0 = Date.now() - (h * 3600 + m * 60 + s) * 1000;
          cmdEcho(`Mission time set to ${hh} UTC`);
        } else err('Use /st hh:mm:ss');
        return;
      }
      case '/sim.enable': st.dummy.simEnabled = true; cmdEcho('SIM ENABLE'); return;
      case '/sim.activate': st.dummy.simActive = true; cmdEcho('SIM ACTIVATE'); return;
      case '/sim.disable': st.dummy.simActive = false; st.dummy.simEnabled = false; cmdEcho('SIM DISABLE'); return;
      case '/simp': {
        const pa = parseFloat(parts[0]); if (isFinite(pa) && pa > 0) { st.dummy.pressure_pa = pa; cmdEcho(`SIMP ${pa} Pa`); } else err('Use /simp <pressure_pa>'); return;
      }
      default:
        if (/^\/mec\.[a-z0-9_\-]+\.on$/.test(cmd) || /^\/mec\.[a-z0-9_\-]+\.off$/.test(cmd)) { cmdEcho(`MEC ${cmd}`); return; }
        // transport write to device/bridge
        writeTransport(cmdLine + '\n');
        cmdEcho(cmdLine);
        return;
    }
  }
  el.send?.addEventListener('click', () => { const v = (el.manual?.value || '').trim(); if (!v) return; dispatch(v); if (el.manual) el.manual.value = ''; });

  // ---------- dummy ----------
  function makeDummyTelemetry() {
    const altitude = 6 + Math.random() * 1.5;
    const t = {
      team_id: st.teamId,
      mission_time: st.t0 ? hms(new Date(Date.now())) : '00:00:00',
      packet_count: st.rx + 1,
      mode: 'F', state: 'ASCENT',
      altitude_m: altitude, temperature_c: 15 + Math.random(),
      pressure_kpa: st.dummy.simEnabled && st.dummy.simActive ? st.dummy.pressure_pa / 1000 : 101.3 + (Math.random() * 0.2 - 0.1),
      voltage_v: 12.1 + (Math.random() * 0.2 - 0.1),
      gyro_r_dps: +(Math.random() * 1).toFixed(1),
      gyro_p_dps: +(Math.random() * 1).toFixed(1),
      gyro_y_dps: +(Math.random() * 1).toFixed(1),
      accel_r_dps2: +(Math.random() * 1).toFixed(1),
      accel_p_dps2: +(Math.random() * 1).toFixed(1),
      accel_y_dps2: +(Math.random() * 1).toFixed(1),
      mag_r_gauss: 0, mag_p_gauss: 0, mag_y_gauss: 0,
      auto_gyro_rot_rate_dps: +(Math.random() * 3).toFixed(0),
      gps_time: hms(), gps_altitude_m: altitude - 0.2, gps_lat: 18.788, gps_lon: 98.985, gps_sats: 7,
      cmd_echo: 'CXON',
      gs_ts_utc: new Date().toISOString(), gs_rx_count: st.rx + 1, gs_loss_total: st.loss | 0
    };
    DGS_appendLine({ telemetry: t });
  }
  function startDummy() { if (st.dummy.on) return; st.dummy.on = true; st.dummy.id = setInterval(makeDummyTelemetry, st.dummy.period); info(`Dummy started @ ${st.dummy.period}ms`); }
  function stopDummy() { if (!st.dummy.on) return; clearInterval(st.dummy.id); st.dummy.on = false; info('Dummy stopped'); }
  function setDummyPeriod(sec) { const ms = Math.max(50, Math.round(sec * 1000)); st.dummy.period = ms; if (st.dummy.on) { stopDummy(); startDummy(); } info(`Dummy period ${sec}s`); }

  // ---------- Browser (Web Serial) ----------
  async function browserPickPort() {
    try {
      const port = await navigator.serial.requestPort();
      st.br.port = port;
      info('Port picked (browser).');
      el.portName && (el.portName.textContent = 'WebSerial');
    } catch (e) {
      warn('User cancelled port picker.');
    }
  }
  async function browserConnect() {
    if (!('serial' in navigator)) { err('Web Serial not supported. Use Chrome/Edge over HTTPS or localhost.'); return; }
    try {
      if (!st.br.port) await browserPickPort();
      if (!st.br.port) return;
      st.br.baud = parseInt(el.browserBaudSel?.value || '115200', 10);
      await st.br.port.open({ baudRate: st.br.baud });

      // Streams
      st.br.textDecoder = new TextDecoderStream();
      st.br.textEncoder = new TextEncoderStream();
      st.br.readLoopAbort = new AbortController();

      // Pipe: device.readable -> decoder.writable
      st.br.port.readable.pipeTo(st.br.textDecoder.writable).catch(() => { });
      // Pipe: encoder.readable -> device.writable
      st.br.textEncoder.readable.pipeTo(st.br.port.writable).catch(() => { });

      st.br.reader = st.br.textDecoder.readable.getReader();
      st.br.writer = st.br.textEncoder.writable.getWriter();

      setLink('Browser', 'WebSerial', st.br.baud);
      info('Browser serial connected.');

      // Read loop (CSV/JSON auto-detect)
      let buf = '';
      (async () => {
        try {
          while (true) {
            const { value, done } = await st.br.reader.read();
            if (done) break;
            if (value) {
              buf += value;
              let idx;
              while ((idx = buf.indexOf('\n')) >= 0) {
                const line = buf.slice(0, idx).replace(/\r$/, '');
                buf = buf.slice(idx + 1);
                DGS_appendLine(line); // <-- unified ingestor
              }
            }
          }
        } catch (e) {
          err('Browser read loop error: ' + e.message);
        }
      })();
    } catch (e) {
      err('Browser connect error: ' + e.message);
    }
  }
  async function browserDisconnect() {
    try { await st.br.reader?.cancel(); } catch { }
    try { await st.br.writer?.close(); } catch { }
    try { await st.br.port?.close(); } catch { }
    const keepBaud = st.br.baud || 115200;
    st.br = { port: null, reader: null, writer: null, baud: keepBaud, textDecoder: null, textEncoder: null, readLoopAbort: null };
    setLink('—'); info('Browser serial disconnected.');
  }
  async function browserWrite(text) {
    try {
      if (st.br.writer) { await st.br.writer.write(text); }
      else warn('Browser serial not connected.');
    } catch (e) {
      err('Browser write error: ' + e.message);
    }
  }

  // ---------- Server bridge (WebSocket JSON) [optional] ----------
  // Protocol:
  //  -> {"type":"list"}
  //  <- {"type":"ports","ports":[{"path":"COM3","friendly":"USB-UART"}, ...]}
  //  -> {"type":"open","path":"COM3","baud":115200}
  //  <- {"type":"open","ok":true}
  //  -> {"type":"write","data":"CMD,<id>,CX,ON\n"}
  //  <- {"type":"read","data":"<line\\n>"} (CSV or JSON)
  //  <- {"type":"log","level":"info|warn|err","msg":"..."}

  function serverConnect() {
    try {
      st.sv.url = (el.wsUrl?.value || '').trim() || 'ws://localhost:8787';
      const ws = new WebSocket(st.sv.url);
      st.sv.ws = ws;
      ws.onopen = () => { setLink('Server', '(ws)', '—'); info('Server WS connected.'); serverSend({ type: 'list' }); };
      ws.onclose = () => { setLink('—'); info('Server WS closed.'); };
      ws.onerror = () => { err('WS error'); };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'ports') {
            if (el.portSel) {
              el.portSel.innerHTML = '';
              (msg.ports || []).forEach(p => {
                const o = document.createElement('option');
                o.value = p.path || p.comName || p.device || p.name || '';
                o.textContent = p.friendly ? `${p.friendly} (${o.value})` : o.value;
                el.portSel.append(o);
              });
            }
            info(`Server: ${msg.ports?.length || 0} port(s)`);
          } else if (msg.type === 'open') {
            if (msg.ok) {
              info('Server serial open ok');
              st.sv.open = true;
              el.portName && (el.portName.textContent = el.portSel?.value || '(server)');
              el.baudVal && (el.baudVal.textContent = el.baudSel?.value || '115200');
            } else { err('Server open failed'); }
          } else if (msg.type === 'close') {
            info('Server serial closed'); st.sv.open = false;
            el.portName && (el.portName.textContent = '—'); el.baudVal && (el.baudVal.textContent = '—');
          } else if (msg.type === 'read') {
            DGS_appendLine(msg.data); // <-- unified ingestor
          } else if (msg.type === 'log') {
            const lv = (msg.level || 'info').toLowerCase();
            (lv === 'err' ? err : lv === 'warn' ? warn : info)(msg.msg || '');
          } else if (msg.type === 'error') {
            err('Server: ' + (msg.msg || 'unknown error'));
          } else {
            info('Server msg: ' + ev.data);
          }
        } catch {
          info('WS text: ' + ev.data);
        }
      };
    } catch (e) {
      err('Server connect error: ' + e.message);
    }
  }
  function serverSend(obj) {
    if (st.sv.ws && st.sv.ws.readyState === 1) st.sv.ws.send(JSON.stringify(obj));
    else warn('WS not connected.');
  }
  function serverDisconnect() { try { st.sv.ws?.close(); } catch { } st.sv.ws = null; }
  function serverOpenSerial() {
    const path = el.portSel?.value;
    const baud = parseInt(el.baudSel?.value || '115200', 10);
    if (!path) { warn('Select a server port first.'); return; }
    serverSend({ type: 'open', path, baud });
  }
  function serverCloseSerial() { serverSend({ type: 'close' }); }
  function serverRefreshPorts() { serverSend({ type: 'list' }); }
  function serverWrite(text) { serverSend({ type: 'write', data: text }); }

  // ---------- transport mux ----------
  function writeTransport(text) {
    if (st.linkType === 'Browser') return browserWrite(text);
    if (st.linkType === 'Server') return serverWrite(text);
    warn('No transport connected; echo only.');
  }

  // ---------- mode switch (show/hide groups if you have both) ----------
  function showBrowser() {
    if (el.browserPanel) el.browserPanel.style.display = 'flex';
    if (el.serverPanel) el.serverPanel.style.display = 'none';
    setLink('—');
  }
  function showServer() {
    if (el.browserPanel) el.browserPanel.style.display = 'none';
    if (el.serverPanel) el.serverPanel.style.display = 'flex';
    setLink('—');
  }
  el.modeBrowser?.addEventListener('change', () => { if (el.modeBrowser.checked) showBrowser(); });
  el.modeServer?.addEventListener('change', () => { if (el.modeServer.checked) showServer(); });

  // ---------- wire buttons ----------
  // browser
  el.btnBrowserPick?.addEventListener('click', browserPickPort);
  el.btnConnectBrowser?.addEventListener('click', async () => {
    await browserConnect();
    if (st.br.port) setLink('Browser', 'WebSerial', el.browserBaudSel?.value || '115200');
  });
  el.btnDisconnectBrowser?.addEventListener('click', browserDisconnect);
  // server
  el.btnConnectServer?.addEventListener('click', serverConnect);
  el.btnDisconnectServer?.addEventListener('click', serverDisconnect);
  el.applyPort?.addEventListener('click', serverOpenSerial);
  el.closePort?.addEventListener('click', serverCloseSerial);
  el.refreshPorts?.addEventListener('click', serverRefreshPorts);

  // demo paste
  el.btnDemoPaste?.addEventListener('click', () => {
    const altitude = 6.2;
    const t = {
      team_id: st.teamId, mission_time: hms(), packet_count: st.rx + 1, mode: 'F', state: 'ASCENT',
      altitude_m: altitude, temperature_c: 15.1, pressure_kpa: 101.3, voltage_v: 12.1,
      gyro_r_dps: 0.5, gyro_p_dps: 0.4, gyro_y_dps: 0.3,
      accel_r_dps2: 0.2, accel_p_dps2: 0.1, accel_y_dps2: 0.3,
      mag_r_gauss: 0, mag_p_gauss: 0, mag_y_gauss: 0,
      auto_gyro_rot_rate_dps: 0,
      gps_time: hms(), gps_altitude_m: altitude - 0.2, gps_lat: 18.788, gps_lon: 98.985, gps_sats: 7,
      cmd_echo: 'CXON',
      gs_ts_utc: new Date().toISOString(), gs_rx_count: st.rx + 1, gs_loss_total: st.loss | 0
    };
    DGS_appendLine({ telemetry: t });
  });

  // ---------- init ----------
  function init() {
    // default visible section = Browser (works with your current HTML)
    showBrowser();
    // default bauds
    if (el.baudSel) el.baudSel.value = '115200';
    if (el.browserBaudSel) el.browserBaudSel.value = '115200';
    // map/charts
    initMap(); initCharts();
    // banner
    info('Ready. Pick a mode (Browser or Server).');
    info('If Browser mode fails: use Chrome/Edge and load this page via HTTPS or from localhost.');
  }
  window.addEventListener('DOMContentLoaded', init);
})();
}