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
      charts: {},            // Stores the chart objects
      cesiumViewer: null,    // 3D Cesium globe viewer
      cesiumMarker: null,    // Cesium entity for CanSat marker
      flightPath: [],        // Array of Cesium.Cartesian3 for 3D trail
      cesiumFlightPath: null,// Cesium polyline entity
      cesiumAltStem: null,   // Vertical altitude line (ground → CanSat)
      lastCesiumAlt: 0,      // Last known altitude for live callbacks
      map: null,             // [recovery overlay only] Leaflet
      marker: null,          // unused, kept for compat
      ws: null,      // The WebSocket connection to the server
      lastGPSHMS: null,
      altZero: 0,
      lastAlt: 0,
      maxAlt: 0,
      gps_lat: null,
      gps_lon: null,
      // Audio and Recovery State
      audioEnabled: true,
      voiceNavEnabled: true,
      lastSpokenState: null,
      recoveryMap: null,
      recoveryMarker: null,
      userMarker: null,
      recoveryRoute: null,
      userLoc: null,
      geoWatchId: undefined,
      lastNavSpeech: 0,
      arrivedSpoken: false,
      // Dummy data state
      dummy: { id: null, packet: 0, lat: 18.788, lon: 98.985 },
    };

    // ---------- DOM ELEMENTS (Links to HTML items) ----------
    const el = {
      // Audio & Theme buttons
      toggleTheme: $("#toggleTheme"),
      toggleAudio: $("#toggleAudio"),
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

      // Recovery Mode
      recoveryGroup: $("#recoveryGroup"),
      btnFindPayload: $("#btnFindPayload"),
      recoveryOverlay: $("#recoveryOverlay"),
      btnCloseRecovery: $("#btnCloseRecovery"),
      btnVoiceNav: $("#btnVoiceNav"),
      recovDist: $("#recovDist"),
      recovHeading: $("#recovHeading"),

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

    // ---------- AUDIO (TTS) & MATH HELPERS ----------
    let audioUnlocked = false;

    function unlockAudio() {
      if (audioUnlocked) return;
      // Play a tiny silent utterance to unlock the speech engine on first click
      const u = new SpeechSynthesisUtterance('');
      window.speechSynthesis.speak(u);
      audioUnlocked = true;
      document.body.removeEventListener('click', unlockAudio);
      document.body.removeEventListener('touchstart', unlockAudio);
    }

    // Browsers require a user gesture before SpeechSynthesis can run.
    document.body.addEventListener('click', unlockAudio);
    document.body.addEventListener('touchstart', unlockAudio);

    function speak(text) {
      if (!st.audioEnabled) return;
      if (!window.speechSynthesis) return;

      // Force unlock if not already (some browsers allow it if triggered by a button directly)
      if (!audioUnlocked) unlockAudio();

      window.speechSynthesis.cancel(); // Cancel ongoing
      const u = new SpeechSynthesisUtterance(text);
      // Use an English voice if available
      const voices = window.speechSynthesis.getVoices();
      const voice = voices.find(v => v.lang.includes('en-GB') || v.lang.includes('en-US')) || voices[0];
      if (voice) u.voice = voice;
      window.speechSynthesis.speak(u);
    }

    function calcDistance(lat1, lon1, lat2, lon2) {
      const R = 6371e3;
      const rad = Math.PI / 180;
      const phi1 = lat1 * rad;
      const phi2 = lat2 * rad;
      const dl = (lon2 - lon1) * rad;
      const a = Math.sin((lat2 - lat1) * rad / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dl / 2) ** 2;
      return R * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
    }

    function calcHeading(lat1, lon1, lat2, lon2) {
      const rad = Math.PI / 180;
      const dl = (lon2 - lon1) * rad;
      const y = Math.sin(dl) * Math.cos(lat2 * rad);
      const x = Math.cos(lat1 * rad) * Math.sin(lat2 * rad) - Math.sin(lat1 * rad) * Math.cos(lat2 * rad) * Math.cos(dl);
      return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
    }

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
    el.btnStartMission?.addEventListener('click', () => { if (!st.t0) st.t0 = Date.now(); info("Mission Timer Started."); });

    // ---------- MAP LOGIC (3D Globe — CesiumJS, fully offline) ----------
    function initMap() {
      if (!el.mapEl) return;

      // Offline: no Cesium Ion token needed
      Cesium.Ion.defaultAccessToken = '';

      const viewer = new Cesium.Viewer('map', {
        baseLayerPicker:       false, // We supply our own offline imagery
        geocoder:              false, // No online geocoding
        homeButton:            false,
        sceneModePicker:       true,  // Allow 3D / Columbus / 2D switching
        navigationHelpButton:  false,
        animation:             false,
        timeline:              false,
        fullscreenButton:      false,
        infoBox:               false,
        selectionIndicator:    false,
      });
      st.cesiumViewer = viewer;

      // ── Offline imagery: NaturalEarthII is bundled inside CesiumJS ──
      viewer.scene.imageryLayers.removeAll();
      viewer.scene.imageryLayers.addImageryProvider(
        new Cesium.TileMapServiceImageryProvider({
          url: Cesium.buildModuleUrl('Assets/Textures/NaturalEarthII'),
          fileExtension: 'jpg',
        })
      );

      // ── Flat WGS84 ellipsoid — zero terrain tile requests ───────────
      viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();

      // ── Camera: near-horizon angle so altitude is clearly visible ──────
      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(98.978, 18.781, 1200),
        orientation: {
          heading: Cesium.Math.toRadians(0),
          pitch:   Cesium.Math.toRadians(-22), // near-horizontal = shows altitude in air
          roll:    0.0,
        },
      });

      // ── CanSat marker (floats at GPS altitude, no ground-clamp) ────────
      st.cesiumMarker = viewer.entities.add({
        name: 'CanSat #1043',
        position: Cesium.Cartesian3.fromDegrees(98.985, 18.788, 0),
        point: {
          pixelSize: 16,
          color: Cesium.Color.fromCssColorString('#4da3ff'),
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 2,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          // No heightReference → NONE by default → floats at absolute altitude
        },
        label: {
          // Live altitude text updated every telemetry packet via CallbackProperty
          text: new Cesium.CallbackProperty(
            () => `#1043\n${Math.round(st.lastCesiumAlt)} m`,
            false
          ),
          font: 'bold 12px monospace',
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.fromCssColorString('#0a0c14'),
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cesium.Cartesian2(0, -28),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          showBackground: true,
          backgroundColor: Cesium.Color.fromCssColorString('#0a0c14').withAlpha(0.65),
          backgroundPadding: new Cesium.Cartesian2(6, 4),
        },
      });

      // ── Altitude stem: vertical line from ground directly to CanSat ───────
      // This is the KEY visual that shows the CanSat is "in the air"
      st.cesiumAltStem = viewer.entities.add({
        name: 'Altitude Stem',
        polyline: {
          positions: new Cesium.CallbackProperty(() => {
            if (st.gps_lat === null || st.gps_lon === null) return [];
            return [
              Cesium.Cartesian3.fromDegrees(st.gps_lon, st.gps_lat, 0),
              Cesium.Cartesian3.fromDegrees(st.gps_lon, st.gps_lat, Math.max(1, st.lastCesiumAlt)),
            ];
          }, false),
          width: 2,
          material: new Cesium.ColorMaterialProperty(
            Cesium.Color.fromCssColorString('#ffb454').withAlpha(0.9)
          ),
          arcType: Cesium.ArcType.NONE,
        },
      });

      // ── 3D flight-path polyline (live via CallbackProperty) ──────────
      st.flightPath = [];
      st.cesiumFlightPath = viewer.entities.add({
        name: 'Flight Path',
        polyline: {
          positions: new Cesium.CallbackProperty(() => st.flightPath, false),
          width: 3,
          material: new Cesium.ColorMaterialProperty(
            Cesium.Color.fromCssColorString('#4da3ff').withAlpha(0.85)
          ),
          arcType: Cesium.ArcType.NONE,
        },
      });
    }

    // ---------- CHART LOGIC (Graphs) ----------
    function getChartColors() {
      return [getCssVar('--chart-color-1'), getCssVar('--chart-color-2'), getCssVar('--warn')];
    }

    // Creates a new chart using ECharts library
    function makeMulti(elId, names, opts = {}) {
      const elc = document.getElementById(elId);
      if (!elc) {
        console.error("makeMulti: Element not found:", elId);
        return null;
      }
      console.log("makeMulti: Initializing chart:", elId);
      const inst = echarts.init(elc);
      const colors = getChartColors();
      const { smooth = false, stack = undefined, area = false } = opts;
      const gridColor = getCssVar('--muted');

      inst.setOption({
        grid: { left: 35, right: 20, top: 30, bottom: 30, containLabel: true },
        animation: false,
        xAxis: {
          type: 'category',
          data: [],
          axisLabel: { show: true, color: gridColor, fontSize: 11 },
          splitLine: { show: true, lineStyle: { color: gridColor, opacity: 0.25 } } // Vertical grid lines
        },
        yAxis: {
          type: 'value',
          scale: true,
          axisLabel: { color: gridColor, fontSize: 11 },
          splitLine: { lineStyle: { color: gridColor, opacity: 0.25 } }
        },
        legend: { show: true, data: names, top: 0, textStyle: { color: getCssVar('--fg'), fontSize: 11 }, icon: 'roundRect' },
        series: names.map((n, i) => ({
          type: 'line',
          name: n,
          smooth: smooth,
          stack: stack,
          areaStyle: (area && i === 0) ? { opacity: 0.15 } : undefined,
          showSymbol: true, // Show dots
          symbolSize: 8,    // Size of the dots
          data: [],
          lineStyle: { width: 4.0, color: colors[i % colors.length] },
          itemStyle: { color: colors[i % colors.length] }
        })),
        tooltip: { trigger: 'axis', backgroundColor: 'rgba(20, 20, 20, 0.9)', textStyle: { color: '#fff' }, borderWidth: 0 }
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
      (Array.isArray(values) ? values : [values]).forEach((v, i) => {
        if (opt.series[i]) opt.series[i].data.push(v);
      });

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
        const opt = chart.getOption();
        chart.setOption({
          xAxis: { splitLine: { lineStyle: { color: muted, opacity: 0.25 } } },
          yAxis: { axisLabel: { color: muted }, splitLine: { lineStyle: { color: muted, opacity: 0.25 } } },
          legend: { textStyle: { color: fg } },
          series: opt.series.map((s, i) => ({
            name: s.name,
            lineStyle: { color: colors[i % colors.length] },
            itemStyle: { color: colors[i % colors.length] }
          }))
        });
      }
    }

    function initCharts() {
      // Altitude: Smooth + Area fill
      st.charts.altitude = makeMulti('chart-altitude', ['Altitude'], { smooth: true, area: true });
      // Power: Smooth, Dual Axis (Voltage left, Current right)
      st.charts.power = makeMulti('chart-power', ['Voltage', 'Current'], { smooth: true });
      // Accel: Stacked
      st.charts.accel = makeMulti('chart-accel', ['Acc X', 'Acc Y', 'Acc Z'], { stack: 'Total' });
      // Gyro: Stacked
      st.charts.gyro = makeMulti('chart-gyro', ['Gyr X', 'Gyr Y', 'Gyr Z'], { stack: 'Total' });
    }


    // Resize charts and Cesium globe when the window size changes
    window.addEventListener('resize', () => {
      Object.values(st.charts).forEach(c => c?.resize());
      st.cesiumViewer?.resize();
    });

    // ---------- TELEMETRY HANDLING (The Core Logic) ----------

    // Rotates the compass arrow
    function updateCompass(heading) {
      if (!el.compassArrow) return;
      el.compassArrow.style.transform = `rotate(${heading || 0}deg)`;
      el.heading.textContent = `${num(heading, 0)}°`;
    }

    // This function runs EVERY TIME a new data packet arrives!
    // [REQ-67] All telemetry shall be displayed in real time in text format
    // [REQ-68] Displayed in SI units and units indicated on displays
    // [REQ-70] Display mission time, temperature, GPS, packet count, state
    function onTelemetry(t) {
      if (el.freeze?.checked) return; // Stop updating if "Freeze" is checked

      // --- AUDIO & ALTITUDE TRACKING ---
      if (typeof t.altitude_m === 'number') {
        if (t.altitude_m > st.maxAlt) st.maxAlt = t.altitude_m;
      }

      if (t.state && t.state.trim() !== '' && t.state !== st.lastSpokenState) {
        if (st.lastSpokenState !== null) { // Only speak on changes, not on initial boot spam
          if (t.state === 'LANDED') {
            const timeStr = (t.mission_time || '').replace(/:/g, ' ');
            speak(`Mission Successful. Highest altitude reached: ${Math.round(st.maxAlt)} meters.`);
            if (el.recoveryGroup) el.recoveryGroup.style.display = 'block'; // Show Recovery Button
          } else {
            speak(`State changed to ${t.state}.`);
          }
        }
        st.lastSpokenState = t.state;
      }

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
      // [REQ-69] Plot altitude, battery voltage, current, accelerometer, rotation rates in real time
      const label = t.mission_time || hms();
      pushChart(st.charts.altitude, label, [t.altitude_m]);
      pushChart(st.charts.power, label, [t.voltage_v, t.current_a]);
      pushChart(st.charts.accel, label, [t.accel_r_dps2, t.accel_p_dps2, t.accel_y_dps2]);
      pushChart(st.charts.gyro, label, [t.gyro_r_dps, t.gyro_p_dps, t.gyro_y_dps]);

      // 8. Update 3D Cesium Map
      if (t.gps_lat && t.gps_lon && typeof t.gps_lat === 'number' && typeof t.gps_lon === 'number') {
        const lat = t.gps_lat, lon = t.gps_lon;
        const alt = typeof t.altitude_m === 'number' ? Math.max(0, t.altitude_m) : 0;
        st.gps_lat = lat;
        st.gps_lon = lon;
        st.lastCesiumAlt = alt;  // drives CallbackProperty on stem + label

        if (st.cesiumViewer) {
          // Marker floats at real GPS altitude (no ground clamping)
          const pos3d = Cesium.Cartesian3.fromDegrees(lon, lat, alt);
          if (st.cesiumMarker) {
            st.cesiumMarker.position = new Cesium.ConstantPositionProperty(pos3d);
          }
          // Append point to 3D flight trail
          st.flightPath.push(pos3d);
          if (st.flightPath.length > 600) st.flightPath.shift();
        }

        el.gpsMini && (el.gpsMini.textContent = `${lat.toFixed(5)}, ${lon.toFixed(5)} • sats: ${t.gps_sats ?? '—'}`);
        el.gmapA && (el.gmapA.href = `https://maps.google.com/?q=${lat},${lon}`);

        // Keep recovery overlay marker in sync (Leaflet)
        if (st.recoveryMarker) st.recoveryMarker.setLatLng([lat, lon]);
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
      'CAL', 'RESET',
      'ST,GPS',
      'SIM,ENABLE', 'SIM,ACTIVATE', 'SIM,DISABLE',
      'MEC,PL,ON', 'MEC,PL,OFF',
      'MEC,INS,ON', 'MEC,INS,OFF',
      'MEC,PAR,ON', 'MEC,PAR,OFF',
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
          fetch('/api/dummy/start', { method: 'POST' });
          info('Requesting dummy data from server...');
          return;
        }
        if (command === '/dummy.off') {
          fetch('/api/dummy/stop', { method: 'POST' });
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
      // el.lastCmd.textContent = cmd;  <-- REMOVED per user request (wait for echo)
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

    // ---------- RECOVERY MAP & AUDIO LOGIC ----------
    el.toggleAudio?.addEventListener('click', () => {
      st.audioEnabled = !st.audioEnabled;
      el.toggleAudio.textContent = `🔊 Audio: ${st.audioEnabled ? 'ON' : 'OFF'}`;
      if (st.audioEnabled) speak("Audio Assistant Enabled");
    });

    el.btnVoiceNav?.addEventListener('click', () => {
      st.voiceNavEnabled = !st.voiceNavEnabled;
      el.btnVoiceNav.textContent = `🔊 Voice Nav: ${st.voiceNavEnabled ? 'ON' : 'OFF'}`;
    });

    function initRecoveryMap() {
      if (st.recoveryMap) return;
      st.recoveryMap = L.map('recoveryMap', { zoomControl: true, attributionControl: false }).setView([18.788, 98.985], 16);

      // Offline Map Support for Mark Walker Award: 
      // We cannot fetch openstreetmap tiles without WiFi, so we load an empty color background
      // and rely entirely on the Distance/Heading readouts and drawn paths to navigate in the field.
      // L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(st.recoveryMap);
      st.recoveryMap.getContainer().style.background = '#e0e0e0'; // Light grey offline background

      st.recoveryMarker = L.marker([18.788, 98.985]).addTo(st.recoveryMap); // Payload 
      st.gcsMarker = L.circleMarker([18.788, 98.985], { radius: 8, color: 'blue' }).addTo(st.recoveryMap); // User

      st.recoveryLine = L.polyline([[18.788, 98.985], [18.788, 98.985]], { color: 'red', weight: 4, dashArray: '10, 10' }).addTo(st.recoveryMap);
    }

    el.btnFindPayload?.addEventListener('click', () => {
      if (!st.gps_lat || !st.gps_lon) {
        alert("No valid GPS data for payload yet.");
        return;
      }
      el.recoveryOverlay.style.display = 'flex';
      initRecoveryMap();
      st.recoveryMap.invalidateSize();

      const payloadPos = [st.gps_lat, st.gps_lon];
      st.recoveryMarker.setLatLng(payloadPos);
      st.recoveryMap.setView(payloadPos, 18);

      // Start tracking user location
      if (navigator.geolocation) {
        st.geoWatchId = navigator.geolocation.watchPosition(pos => {
          const uLat = pos.coords.latitude;
          const uLon = pos.coords.longitude;
          st.userLoc = [uLat, uLon];
          st.gcsMarker.setLatLng(st.userLoc);
          st.recoveryLine.setLatLngs([st.userLoc, payloadPos]);

          const dist = calcDistance(uLat, uLon, payloadPos[0], payloadPos[1]);
          const hdg = calcHeading(uLat, uLon, payloadPos[0], payloadPos[1]);

          el.recovDist.textContent = `${Math.round(dist)} m`;
          el.recovHeading.textContent = `${Math.round(hdg)}°`;

          if (st.voiceNavEnabled && dist > 5) {
            const now = Date.now();
            if (!st.lastNavSpeech || (now - st.lastNavSpeech > 15000)) { // Speak every 15s
              speak(`Payload is ${Math.round(dist)} meters away. Heading ${Math.round(hdg)} degrees.`);
              st.lastNavSpeech = now;
            }
          } else if (st.voiceNavEnabled && dist <= 5 && !st.arrivedSpoken) {
            speak("You have arrived at the payload.");
            st.arrivedSpoken = true;
          }
        }, err => console.warn("Geo error", err), { enableHighAccuracy: true });
      } else {
        alert("Geolocation (External GPS) not supported or allowed.");
      }
    });

    el.btnCloseRecovery?.addEventListener('click', () => {
      el.recoveryOverlay.style.display = 'none';
      if (st.geoWatchId !== undefined && navigator.geolocation) {
        navigator.geolocation.clearWatch(st.geoWatchId);
        st.geoWatchId = undefined;
      }
    });

    // ---------- THEME (Light/Dark Mode) ----------
    function initTheme() {
      const root = document.documentElement;
      const saved = localStorage.getItem('dgs-theme');
      if (saved === 'light' || saved === 'dark') {
        root.setAttribute('data-theme', saved);
      }

      el.toggleTheme?.addEventListener('click', () => {
        const cur = root.getAttribute('data-theme') || 'light';
        const next = cur === 'light' ? 'dark' : 'light';
        root.setAttribute('data-theme', next);
        localStorage.setItem('dgs-theme', next);
        updateChartColors();
      });
    }

    // ---------- INITIALIZATION (Startup) ----------
    async function fetchDiagnosticText() {
      try {
        const res = await fetch('/api/health');
        if (res.ok) {
          const data = await res.json();
          if (!data.serial || !data.serial.port) {
            return "Warning: XBee port configuration not found.";
          } else {
            return `System initialized. Connected to Ground Station hardware on port ${data.serial.port}.`;
          }
        } else {
          return "System initialized with backend warnings.";
        }
      } catch (e) {
        return "Warning: Ground Station backend is offline.";
      }
    }

    function init() {
      initMap();
      fillCmds();
      initTheme();

      // Announce startup health
      const setupSpeech = async () => {
        const msg = await fetchDiagnosticText();
        if (audioUnlocked) {
          speak(msg);
        } else {
          const onFirstClick = () => {
            speak(msg);
            document.body.removeEventListener('click', onFirstClick);
            document.body.removeEventListener('touchstart', onFirstClick);
          };
          document.body.addEventListener('click', onFirstClick);
          document.body.addEventListener('touchstart', onFirstClick);
        }
      };
      // Run immediately instead of waiting 1000ms
      setupSpeech();

      // [REQ-77] All data shall be shown simultaneously in the ground station GUI (Tabs not allowed)
      info('DAEDALUS Ground Station Initialized.');
      connect();

      // Force map to resize correctly after loading
      setTimeout(() => {
        window.dispatchEvent(new Event('resize'));
        initCharts(); // Delay chart init to ensure CSS layout is ready
      }, 200);
    }
    window.addEventListener('DOMContentLoaded', init);

  })();
}