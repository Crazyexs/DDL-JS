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
    const esc = (s) => String(s).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
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
      cesiumHasFix: false,   // True after first GPS → triggers auto-zoom
      map: null,             // 2D Leaflet map (offline / toggled)
      marker: null,          // Leaflet 2D marker
      kmlPoints: [],         // [{lat,lon,alt}] collected for KML export
      kmlExported: false,    // KML only exported once (at landing)
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
      gcsMarker: null,
      recoveryLine: null,
      userLoc: null,
      geoWatchId: undefined,
      lastNavSpeech: 0,
      arrivedSpoken: false,
      // Dummy data state
      dummy: { id: null, packet: 0, lat: 18.788, lon: 98.985 },
      // Pinned GPS target (user-defined landing zone)
      pinnedLat: null,
      pinnedLon: null,
      // Calculated physics
      speed: 0,
      lastSpeedMs: 0,       // wall-clock ms of the previous altitude sample
      // Descent / Fall speed tracking
      releaseAlt: null,
      releaseTime: null,    // satellite mission_time seconds when descent started
      // Resilience
      isReplaying: false,       // suppress audio/logs during ring-buffer replay
      reconnectDelay: 2000,     // current backoff delay (ms); grows on repeated failures
      reconnectTimer: null,     // handle for the pending reconnect setTimeout
      lastChartTs: 0,           // timestamp of last chart push (for 5 Hz throttle)
      lastSpeedAlt: undefined,  // altitude at the previous speed sample
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
      activeLogLabel: $("#activeLogLabel"),
      btnSim: $("#btnSim"),
      btnExportKML: $("#btnExportKML"),

      // Pin GPS target
      btnPinGps: $("#btnPinGps"),
      pinnedDistDisplay: $("#pinnedDistDisplay"),

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
      val_speed: $("#val_speed"),
      val_gforce: $("#val_gforce"),
      fallSpeedBox: $("#fallSpeedBox"),
      val_fall_speed: $("#val_fall_speed"),
      val_battery_pct: $("#val_battery_pct"),
      battery_bar: $("#battery_bar"),

      // Chart Toggles
      altitudeToggles: $("#altitudeToggles"),
      showRaw: $("#showRaw"),

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

    // Parse "HH:MM:SS" mission time string → total seconds (null if invalid)
    function parseMissionSec(hms) {
      if (!hms || !/^\d\d:\d\d:\d\d$/.test(hms)) return null;
      const [h, m, s] = hms.split(':').map(Number);
      return h * 3600 + m * 60 + s;
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

      // Throttled auto-scroll (Pi: avoids layout thrashing on low-CPU hardware)
      if (el.auto?.checked && !el.freeze?.checked) {
        if (!el.rawBox._scrollPending) {
          el.rawBox._scrollPending = true;
          requestAnimationFrame(() => {
            el.rawBox.scrollTop = el.rawBox.scrollHeight;
            el.rawBox._scrollPending = false;
          });
        }
      }
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

    // Updates the Mission Clock (T+ XX:XX:XX) — header strip only.
    // missionBig (map panel) is driven exclusively by satellite mission_time in onTelemetry.
    function tickMission() {
      if (!st.t0 || el.freeze?.checked) return;
      const s = Math.floor((Date.now() - st.t0) / 1000);
      const t = `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
      el.missionSmall && (el.missionSmall.textContent = 'Mission: ' + t);
    }
    setInterval(tickMission, 250);

    // Start button for the mission clock
    el.btnStartMission?.addEventListener('click', () => { if (!st.t0) st.t0 = Date.now(); info("Mission Timer Started."); });

    // ---------- MAP LOGIC ---------------------------------------------------
    // Online  → CesiumJS 3D globe with Esri World Imagery (Google Earth quality)
    // Offline → 2D Leaflet with OpenStreetMap (uses browser-cached tiles)
    // -------------------------------------------------------------------------

    function _cesiumSetupEntities(viewer) {
      // CanSat marker — floats at real GPS altitude (no ground clamping)
      st.cesiumMarker = viewer.entities.add({
        name: `CanSat #${st.teamId}`,
        position: Cesium.Cartesian3.fromDegrees(98.985, 18.788, 0),
        point: {
          pixelSize: 16,
          color: Cesium.Color.fromCssColorString('#4da3ff'),
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: 2,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: {
          text: new Cesium.CallbackProperty(
            () => `#${st.teamId}\n${Math.round(st.lastCesiumAlt)} m`, false),
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

      // Yellow vertical stem — most visible indicator that CanSat is IN THE AIR
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

      // Blue 3D flight-path trail
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

    // ── 3D mode ── tiles served from SW cache when offline ──────────────
    function initCesium3D() {
      if (!el.mapEl) return;
      Cesium.Ion.defaultAccessToken = '';

      const viewer = new Cesium.Viewer('map', {
        baseLayerPicker:      false,
        geocoder:             false,
        homeButton:           false,
        sceneModePicker:      true,
        navigationHelpButton: false,
        animation:            false,
        timeline:             false,
        fullscreenButton:     false,
        infoBox:              false,
        selectionIndicator:   false,
      });
      st.cesiumViewer = viewer;

      viewer.scene.imageryLayers.removeAll();
      viewer.scene.imageryLayers.addImageryProvider(
        new Cesium.UrlTemplateImageryProvider({
          url: 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          credit: 'Esri, Maxar, GeoEye, Earthstar Geographics, CNES/Airbus DS',
          maximumLevel: 19,
        })
      );

      viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();

      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(98.978, 18.781, 1200),
        orientation: {
          heading: Cesium.Math.toRadians(0),
          pitch:   Cesium.Math.toRadians(-22),
          roll:    0.0,
        },
      });

      _cesiumSetupEntities(viewer);
      if (el.mapToggle) el.mapToggle.textContent = '→ 2D';
    }

    // ── 2D mode (manual toggle) ── tiles served from SW cache when offline ──
    function initLeaflet2D() {
      if (!el.mapEl) return;
      st.map = L.map('map', { zoomControl: true, attributionControl: false })
        .setView([18.788, 98.985], 15);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
      }).addTo(st.map);

      st.marker = L.marker([18.788, 98.985]).addTo(st.map);
      if (el.mapToggle) el.mapToggle.textContent = '→ 3D';
    }

    function initMap() {
      if (!el.mapEl) return;
      initCesium3D();
      el.mapToggle?.addEventListener('click', toggleMap);
    }

    // ── Toggle between 3D Cesium and 2D Leaflet ──────────────────────
    function toggleMap() {
      if (st.cesiumViewer) {
        // 3D → 2D
        try { st.cesiumViewer.destroy(); } catch(e) {}
        st.cesiumViewer = null; st.cesiumMarker = null;
        st.cesiumAltStem = null; st.cesiumFlightPath = null;
        if (el.mapEl) el.mapEl.innerHTML = '';
        initLeaflet2D();
        // Restore last known position on 2D map
        if (st.gps_lat !== null && st.gps_lon !== null && st.marker) {
          st.marker.setLatLng([st.gps_lat, st.gps_lon]);
          st.map?.panTo([st.gps_lat, st.gps_lon]);
        }
      } else {
        // 2D → 3D
        if (st.map) { try { st.map.remove(); } catch(e) {} st.map = null; st.marker = null; }
        if (el.mapEl) el.mapEl.innerHTML = '';
        initCesium3D();
        // If GPS already exists, zoom straight in after init
        if (st.gps_lat !== null && st.gps_lon !== null) {
          setTimeout(() => {
            st.cesiumViewer?.camera.flyTo({
              destination: Cesium.Cartesian3.fromDegrees(
                st.gps_lon, st.gps_lat, Math.max(st.lastCesiumAlt + 500, 600)),
              orientation: { heading: 0, pitch: Cesium.Math.toRadians(-30), roll: 0 },
              duration: 1.5,
            });
          }, 600);
        }
      }
    }

    // ── KML export (Google Earth 3D flight path) ──────────────────────
    // Triggered automatically when the CanSat LANDS, or manually via button.
    
    el.btnExportKML?.addEventListener('click', () => {
      st.kmlExported = false; // Allow manual re-export
      generateKML();
    });

    function generateKML() {
      if (st.kmlPoints.length < 2) {
        // If triggered manually by button, tell them why it failed
        if (!st.kmlExported && el.btnExportKML) info('Not enough GPS data to generate a map yet.');
        return;
      }
      if (st.kmlExported) return;
      st.kmlExported = true;

      const coords = st.kmlPoints
        .map(p => `${p.lon.toFixed(6)},${p.lat.toFixed(6)},${p.alt.toFixed(1)}`)
        .join('\n          ');
      const first  = st.kmlPoints[0];
      const last   = st.kmlPoints[st.kmlPoints.length - 1];
      const apex   = st.kmlPoints.reduce((a, b) => a.alt > b.alt ? a : b);
      const teamId = st.teamId || 1043;

      const kml = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>DAEDALUS #${teamId} Flight Path</name>
    <description>Max altitude: ${Math.round(st.maxAlt)} m | Packets: ${st.kmlPoints.length}</description>
    <Style id="path"><LineStyle><color>ff00aaff</color><width>3</width></LineStyle></Style>
    <Style id="launch"><IconStyle><color>ff00cc00</color><scale>1.2</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/go.png</href></Icon>
    </IconStyle></Style>
    <Style id="land"><IconStyle><color>ff0000ff</color><scale>1.2</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/stop.png</href></Icon>
    </IconStyle></Style>
    <Style id="apex"><IconStyle><color>ff00ffff</color><scale>1.1</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/shapes/star.png</href></Icon>
    </IconStyle></Style>
    <Placemark>
      <name>Flight Path</name><styleUrl>#path</styleUrl>
      <LineString>
        <extrude>1</extrude><tessellate>1</tessellate>
        <altitudeMode>absolute</altitudeMode>
        <coordinates>
          ${coords}
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark><name>Launch</name><styleUrl>#launch</styleUrl>
      <Point><altitudeMode>clampToGround</altitudeMode>
        <coordinates>${first.lon.toFixed(6)},${first.lat.toFixed(6)},0</coordinates>
      </Point></Placemark>
    <Placemark><name>Landing</name><styleUrl>#land</styleUrl>
      <Point><altitudeMode>clampToGround</altitudeMode>
        <coordinates>${last.lon.toFixed(6)},${last.lat.toFixed(6)},0</coordinates>
      </Point></Placemark>
    <Placemark><name>Apogee (${Math.round(apex.alt)} m)</name><styleUrl>#apex</styleUrl>
      <Point><altitudeMode>absolute</altitudeMode>
        <coordinates>${apex.lon.toFixed(6)},${apex.lat.toFixed(6)},${apex.alt.toFixed(1)}</coordinates>
      </Point></Placemark>
  </Document>
</kml>`;

      const blob = new Blob([kml], { type: 'application/vnd.google-earth.kml+xml' });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url;  a.download = `DAEDALUS_${teamId}_flight.kml`;  a.click();
      URL.revokeObjectURL(url);
      info('Google Earth KML downloaded! Open in Google Earth to view 3D flight path.');
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
      const inst = echarts.init(elc);
      inst._data = { labels: [], series: names.map(() => []) }; // cache for fast pushChart
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
        yAxis: names.includes('Batt %') ? [
          {
            type: 'value',
            scale: true,
            axisLabel: { color: gridColor, fontSize: 11 },
            splitLine: { lineStyle: { color: gridColor, opacity: 0.25 } }
          },
          {
            type: 'value',
            max: 100,
            min: 0,
            axisLabel: { show: false },
            splitLine: { show: false }
          }
        ] : {
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
          yAxisIndex: n === 'Batt %' ? 1 : 0,
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

    // Adds new data points to an existing chart.
    // Uses a cached _data object to avoid the expensive getOption() deep-clone on every packet.
    function pushChart(inst, label, values) {
      if (!inst || !inst._data) return;
      const d = inst._data;
      d.labels.push(label);
      (Array.isArray(values) ? values : [values]).forEach((v, i) => {
        if (d.series[i]) d.series[i].push(v);
      });
      const max = 120;
      if (d.labels.length > max) {
        d.labels.shift();
        d.series.forEach(s => s.shift());
      }
      inst.setOption({
        xAxis: { data: d.labels },
        series: d.series.map(s => ({ data: s })),
      }, false, true);
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
      // Power: Smooth
      st.charts.power = makeMulti('chart-power', ['Voltage', 'Current'], { smooth: true });
      // Accel: Stacked
      st.charts.accel = makeMulti('chart-accel', ['Acc X', 'Acc Y', 'Acc Z'], { stack: 'Total' });
      // Gyro: Stacked
      st.charts.gyro = makeMulti('chart-gyro', ['Gyr X', 'Gyr Y', 'Gyr Z'], { stack: 'Total' });
    }


    // Resize charts, Cesium globe, and Leaflet map when window resizes
    window.addEventListener('resize', () => {
      Object.values(st.charts).forEach(c => c?.resize());
      st.cesiumViewer?.resize();
      st.map?.invalidateSize();
    });

    // ---------- TELEMETRY HANDLING (The Core Logic) ----------

    // Rotates the compass arrow
    function updateCompass(yaw) {
      if (el.compassArrow) el.compassArrow.style.transform = `rotate(${yaw || 0}deg)`;
      if (el.heading) el.heading.textContent = `${num(yaw, 0)}°`;
    }

    // This function runs EVERY TIME a new data packet arrives!
    // [REQ-67] All telemetry shall be displayed in real time in text format
    // [REQ-68] Displayed in SI units and units indicated on displays
    // [REQ-70] Display mission time, temperature, GPS, packet count, state
    function onTelemetry(t) {
      if (el.freeze?.checked) return; // Stop updating if "Freeze" is checked

      // If the payload sent something that doesn't match the telemetry format, just print it!
      if (t.bad_line !== undefined) {
        log('info', t.bad_line);
        return;
      }

      // --- AUDIO & ALTITUDE TRACKING ---
      if (typeof t.altitude_m === 'number') {
        if (t.altitude_m > st.maxAlt) st.maxAlt = t.altitude_m;
      }

      if (t.state && t.state.trim() !== '' && t.state !== st.lastSpokenState) {
        if (st.lastSpokenState !== null && !st.isReplaying) {
          if (t.state === 'LANDED') {
            speak(`Mission Successful. Highest altitude reached: ${Math.round(st.maxAlt)} meters.`);
            if (el.recoveryGroup) el.recoveryGroup.style.display = 'block';
            generateKML(); // Auto-export 3D flight path for Google Earth
          } else {
            speak(`State changed to ${t.state}.`);
          }
        }
        st.lastSpokenState = t.state;
        
        // Setup Avg Fall Speed Box when descent / release begins
        if (t.state === 'DESCENT' || t.state === 'PAYLOAD_REALEASE' || t.state === 'PAYLOAD_RELEASE') {
          if (st.releaseAlt == null) {
            st.releaseAlt  = typeof t.altitude_m === 'number' ? t.altitude_m : 0;
            st.releaseTime = parseMissionSec(t.mission_time); // satellite clock, TX-rate-agnostic
          }
          if (el.fallSpeedBox) el.fallSpeedBox.style.display = 'flex';
        } else if (t.state === 'LAUNCH_PAD' || t.state === 'IDLE_SAFE') {
          st.releaseAlt  = null;
          st.releaseTime = null;
          if (el.fallSpeedBox) el.fallSpeedBox.style.display = 'none';
        }
      }

      // Avg Fall Speed — uses satellite mission_time clock so it is correct at any TX rate.
      // dt_sec changes only when mission_time ticks (1 s resolution), which is fine for an average.
      if (st.releaseAlt != null && st.releaseTime != null && typeof t.altitude_m === 'number') {
        const currentSec = parseMissionSec(t.mission_time);
        if (currentSec !== null) {
          const dt_sec = currentSec - st.releaseTime;
          if (dt_sec > 0) {
            const drop = st.releaseAlt - t.altitude_m; // positive = falling
            const avgFallSpeed = drop / dt_sec;         // true m/s
            if (el.val_fall_speed) el.val_fall_speed.textContent = `${num(avgFallSpeed, 2)} m/s`;
          }
        }
      }

      // 1. Update Big Text Displays
      el.missionState && (el.missionState.textContent = t.state || '—');
      el.liveAltitude && (el.liveAltitude.textContent = num(t.altitude_m, 1));

      // 2. Update Strip Displays
      el.missionMode && (el.missionMode.textContent = t.mode || '—');
      el.gpsSats && (el.gpsSats.textContent = t.gps_sats ?? '—');
      updateCompass(t.yaw);

      // 3. Update Key Value Grid
      el.val_temp && (el.val_temp.textContent = `${num(t.temperature_c, 1)} °C`);
      el.val_pressure && (el.val_pressure.textContent = `${num(t.pressure_kpa, 2)} kPa`);
      
      const voltage = t.voltage_v || 0;
      el.val_voltage && (el.val_voltage.textContent = `${num(voltage, 2)} V`);
      
      // 2S Li-ion discharge curve lookup (per-cell × 2): non-linear interpolation
      // Points derived from standard 18650 discharge curve at ~0.5C
      const LI_ION_2S = [
        [8.40, 100], [8.20, 95], [8.00, 88], [7.80, 78],
        [7.60, 63],  [7.40, 48], [7.20, 32], [7.00, 18],
        [6.80, 9],   [6.60, 4],  [6.40, 1],  [6.00, 0],
      ];
      let pct = 0;
      if (voltage >= LI_ION_2S[0][0]) {
        pct = 100;
      } else if (voltage <= LI_ION_2S[LI_ION_2S.length - 1][0]) {
        pct = 0;
      } else {
        for (let i = 0; i < LI_ION_2S.length - 1; i++) {
          const [v1, p1] = LI_ION_2S[i], [v2, p2] = LI_ION_2S[i + 1];
          if (voltage <= v1 && voltage >= v2) {
            pct = p2 + (p1 - p2) * ((voltage - v2) / (v1 - v2));
            break;
          }
        }
      }
      
      if (el.val_battery_pct) {
          el.val_battery_pct.textContent = `${num(pct, 0)}%`;
          const bColor = pct > 50 ? getCssVar('--ok') : pct > 20 ? getCssVar('--warn') : getCssVar('--err');
          el.val_battery_pct.style.color = bColor;
          if (el.battery_bar) el.battery_bar.style.background = bColor;
      }
      if (el.battery_bar) el.battery_bar.style.width = `${pct}%`;

      el.val_current && (el.val_current.textContent = `${num(t.current_a, 3)} A`);

      el.val_gyro_x && (el.val_gyro_x.textContent = num(t.gyro_r_dps, 2));
      el.val_gyro_y && (el.val_gyro_y.textContent = num(t.gyro_p_dps, 2));
      el.val_gyro_z && (el.val_gyro_z.textContent = num(t.gyro_y_dps, 2));

      el.val_accel_x && (el.val_accel_x.textContent = num(t.accel_r_dps2, 2));
      el.val_accel_y && (el.val_accel_y.textContent = num(t.accel_p_dps2, 2));
      el.val_accel_z && (el.val_accel_z.textContent = num(t.accel_y_dps2, 2));

      // Calculate G Force and Speed
      const accel_mag = Math.sqrt(
        (t.accel_r_dps2 || 0)**2 + 
        (t.accel_p_dps2 || 0)**2 + 
        (t.accel_y_dps2 || 0)**2
      );
      const g_force = accel_mag / 9.80665;
      el.val_gforce && (el.val_gforce.textContent = `${num(g_force, 2)} G`);

      // Instantaneous vertical speed — uses browser wall clock so it is correct at any TX rate.
      // Minimum 50 ms window prevents division by near-zero on back-to-back packets.
      const _wallNow = Date.now();
      if (st.lastSpeedMs > 0 && st.lastSpeedAlt !== undefined && typeof t.altitude_m === 'number') {
        const dt_sec = (_wallNow - st.lastSpeedMs) / 1000;
        if (dt_sec >= 0.05) {
          const raw_speed = Math.abs(t.altitude_m - st.lastSpeedAlt) / dt_sec;
          st.speed = st.speed * 0.7 + raw_speed * 0.3; // EMA smoothing
        }
      } else {
        st.speed = 0;
      }
      if (typeof t.altitude_m === 'number') {
        st.lastSpeedAlt = t.altitude_m;
        st.lastSpeedMs  = _wallNow;
      }

      if (t.state === 'LANDED' || t.state === 'LAUNCH_PAD' || t.state === 'IDLE_SAFE') {
          st.speed = 0;
      }
      el.val_speed && (el.val_speed.textContent = `${num(st.speed, 2)} m/s`);

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
      // During replay: push every packet to restore chart history.
      // During live:   throttle to 5 Hz so ECharts stays fast at high TX rates (e.g. 10 Hz).
      const _now = Date.now();
      if (st.isReplaying || _now - st.lastChartTs >= 200) {
        const label = t.mission_time || hms();
        pushChart(st.charts.altitude, label, [t.altitude_m]);
        pushChart(st.charts.power, label, [t.voltage_v, t.current_a]);
        pushChart(st.charts.accel, label, [t.accel_r_dps2, t.accel_p_dps2, t.accel_y_dps2]);
        pushChart(st.charts.gyro, label, [t.gyro_r_dps, t.gyro_p_dps, t.gyro_y_dps]);
        if (!st.isReplaying) st.lastChartTs = _now;
      }

      // 8. Update 3D Cesium Map & KML Export
      if (typeof t.gps_lat === 'number' && typeof t.gps_lon === 'number' && (t.gps_lat !== 0 || t.gps_lon !== 0)) {
        const lat = t.gps_lat, lon = t.gps_lon;
        const alt = typeof t.altitude_m === 'number' ? Math.max(0, t.altitude_m) : 0;
        
        // Update UI text regardless of satellite count
        el.gpsMini && (el.gpsMini.textContent = `${lat.toFixed(5)}, ${lon.toFixed(5)} \u2022 sats: ${t.gps_sats ?? '\u2014'}`);
        el.gmapA && (el.gmapA.href = `https://maps.google.com/?q=${lat},${lon}`);

        // Only plot coordinates when we have a solid GPS 3D fix (> 3 sats)
        if (Number(t.gps_sats) > 3) {
          // Always update the position state \u2014 map will snap here when live data arrives
          st.gps_lat = lat;
          st.gps_lon = lon;
          st.lastCesiumAlt = alt;

          // Skip expensive map rendering during replay; let live data handle it
          if (!st.isReplaying) {
            if (st.cesiumViewer) {
              // 3D mode: marker floats at real GPS altitude
              const pos3d = Cesium.Cartesian3.fromDegrees(lon, lat, alt);
              if (st.cesiumMarker) {
                st.cesiumMarker.position = new Cesium.ConstantPositionProperty(pos3d);
              }
              st.flightPath.push(pos3d);
              if (st.flightPath.length > 600) st.flightPath.shift();
              // Auto-zoom to first GPS fix
              if (!st.cesiumHasFix) {
                st.cesiumHasFix = true;
                st.cesiumViewer.camera.flyTo({
                  destination: Cesium.Cartesian3.fromDegrees(lon, lat, 1500),
                  orientation: {
                    heading: Cesium.Math.toRadians(0),
                    pitch:   Cesium.Math.toRadians(-30),
                    roll:    0.0,
                  },
                  duration: 2.0,
                });
              }
            } else if (st.map) {
              // 2D mode: standard Leaflet pan + marker
              if (st.marker) st.marker.setLatLng([lat, lon]);
              st.map.panTo([lat, lon], { animate: false });
            }

            // Collect GPS point for KML export (backend already has these; skip during replay)
            st.kmlPoints.push({ lat, lon, alt });
            if (st.kmlPoints.length > 2000) st.kmlPoints.shift();

            // Keep recovery overlay marker in sync (Leaflet)
            if (st.recoveryMarker) st.recoveryMarker.setLatLng([lat, lon]);
          }

          // Update pinned GPS distance (cheap text update \u2014 always run)
          updatePinnedDist();
        }
      }

      // 9. Update Text Log (bottom right box) \u2014 suppressed during replay to avoid flooding
      if (!st.isReplaying) {
        try {
          const showRaw = el.showRaw?.checked;
          let logText;

          if (showRaw && t.gs_raw_line) {
            logText = t.gs_raw_line;
          } else {
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
    }

    // ---------- LOGS UI CONTROL ----------
    (function () {
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
    el.wrap?.addEventListener('change', () => {
      el.rawBox?.classList.toggle('wrap', el.wrap.checked);
    });
    el.refreshLogs?.addEventListener('click', () => { if (!el.rawBox) return; el.rawBox.innerHTML = ''; info('Log view cleared.'); });
    el.copyLogs?.addEventListener('click', async () => {
      if (!el.rawBox) return;
      try {
        const text = [...el.rawBox.querySelectorAll('.logline')].map(n => n.innerText).join('\n');
        await navigator.clipboard.writeText(text);
        cmdEcho('Logs copied to clipboard.');
      } catch (e) {
        err(`Copy failed: ${e.message}. Try Ctrl+A, Ctrl+C in the log box.`);
      }
    });
    el.resetAll?.addEventListener('click', () => { if (el.rawBox) el.rawBox.innerHTML = ''; Object.values(st.charts).forEach(c => c?.clear()); initCharts(); cmdEcho('UI Reset.'); });

    // ---------- COMMANDS (Sending data to satellite) ----------
    const QUICK_COMMANDS = [
      // Telemetry
      'CX,ON', 'CX,OFF',
      // State Overrides
      'STATE,IDLE_SAFE', 'STATE,LAUNCH_PAD', 'STATE,ASCENT', 'STATE,APOGEE',
      'STATE,DESCENT', 'STATE,PROBE_REALEASE', 'STATE,PAYLOAD_REALEASE', 'STATE,LANDED',
      // Calibration & Reset
      'CAL', 'RESET', 'CAL,MAG,START', 'CAL,NORTH', 'CAL,MAG,STATUS', 'CAL,MAG,RESET',
      // Simulation
      'SIM,ENABLE', 'SIM,ACTIVATE', 'SIM,DISABLE',
      // Mechanical \u2014 Payload release servo
      'MEC,PL,ON', 'MEC,PL,OFF',
      // Mechanical \u2014 Instrument bay servo
      'MEC,INS,ON', 'MEC,INS,OFF',
      // Mechanical \u2014 Parachute spin motor
      'MEC,PAR,CW', 'MEC,PAR,ACW', 'MEC,PAR,OFF',
      // Log switching (local GCS only \u2014 not sent to satellite)
      '/log.clear',
      // Dummy data
      '/dummy.on', '/dummy.off',
    ];

    // Commands that require a numeric value typed after the prefix
    const PARAM_COMMANDS = [
      { prefix: '/log ',            label: '/log <name>',              hint: 'Enter log name (e.g. log1, preflight, run2):' },
      { prefix: 'SIMP,',           label: 'SIMP,<pressure>',          hint: 'Enter simulated pressure (Pa):' },
      { prefix: 'SET,MAIN_ALT,',   label: 'SET,MAIN_ALT,<alt_m>',     hint: 'Enter main chute deployment altitude (m):' },
      { prefix: 'SET,APOGEE_ALT,', label: 'SET,APOGEE_ALT,<alt_m>',   hint: 'Enter apogee altitude threshold (m):' },
      { prefix: 'SET,TX_RATE,',    label: 'SET,TX_RATE,<1-10>',       hint: 'Enter telemetry TX rate (1\u201310 Hz):' },
      { prefix: 'SET,INS_TOF,',    label: 'SET,INS_TOF,<val>',       hint: 'Enter instrument ToF threshold (m):' },
      { prefix: 'SET,INS_NEAR,',   label: 'SET,INS_NEAR,<val>',      hint: 'Enter instrument near threshold (m):' },
      { prefix: 'SET,INS_CRIT,',   label: 'SET,INS_CRIT,<val>',      hint: 'Enter instrument critical threshold (m):' },
      { prefix: 'CAL,TOF,',        label: 'CAL,TOF,<dist_mm>',       hint: 'Enter VL53L1X calibration distance (mm):' },
      { prefix: 'SERVO,A,',        label: 'SERVO,A,<0-180>',          hint: 'Enter servo A angle (0\u2013180):' },
      { prefix: 'SERVO,B,',        label: 'SERVO,B,<0-180>',          hint: 'Enter servo B angle (0\u2013180):' },
    ];

    // Populates the dropdown menu
    function fillCmds() {
      if (!el.quick) return;
      el.quick.innerHTML = '';
      const opt0 = document.createElement('option'); opt0.value = ''; opt0.textContent = '\u2014 Quick Command \u2014';
      el.quick.append(opt0);
      QUICK_COMMANDS.forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = c; el.quick.append(o); });
      PARAM_COMMANDS.forEach(p => { const o = document.createElement('option'); o.value = '__param__' + p.prefix; o.textContent = p.label; el.quick.append(o); });
    }

    // Sends the command to the backend
    async function sendCommand(cmdStr) {
      const cmd = cmdStr.trim();
      if (!cmd) return;

      // Handle local slash-commands (shortcuts that don't go to the satellite)
      if (cmd.startsWith('/')) {
        const command = cmd.toLowerCase();

        // /log <name>  \u2192  switch active log file on the backend
        if (command.startsWith('/log ') || command === '/log.clear') {
          const label = command === '/log.clear' ? '' : cmd.slice(5).trim();
          fetch('/api/log/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label }),
          })
            .then(r => r.text())
            .then(text => {
              try {
                const d = JSON.parse(text);
                if (d.ok) {
                  const display = d.label || 'default';
                  if (el.activeLogLabel) el.activeLogLabel.textContent = display;
                  info(`Log switched \u2192 ${d.file}`);
                } else err(`Log switch failed: ${d.error || JSON.stringify(d)}`);
              } catch { err(`Log switch server error: ${text.slice(0, 80)}`); }
            })
            .catch(e => err(`Log switch error: ${e.message}`));
          return;
        }

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

    el.quick?.addEventListener('change', () => {
      const val = el.quick.value;
      if (!val) return;
      el.quick.value = '';
      if (val.startsWith('__param__')) {
        const prefix = val.slice(9);
        const paramDef = PARAM_COMMANDS.find(p => p.prefix === prefix);
        const input = prompt(paramDef?.hint || `Enter value for ${prefix}`);
        if (input === null || input.trim() === '') return;
        sendCommand(prefix + input.trim());
      } else {
        if (el.manual) el.manual.value = val;
      }
    });
    el.send?.addEventListener('click', () => { const v = (el.manual?.value || '').trim(); if (!v) return; sendCommand(v); if (el.manual) el.manual.value = ''; });
    el.manual?.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); el.send?.click(); } });


    // ---------- RING-BUFFER REPLAY ----------
    // Fetches the server's in-memory ring buffer and replays telemetry packets
    // into onTelemetry() so charts, key values, and GPS state are restored
    // without flooding the log box or triggering voice announcements.
    async function replayMissedPackets() {
      try {
        // 300 log entries is enough to find 120 telemetry packets for full chart history
        const res = await fetch('/api/logs?n=300');
        if (!res.ok) return;
        const lines = await res.json();

        st.isReplaying = true;
        let replayed = 0;
        for (const raw of lines) {
          try {
            const obj = JSON.parse(raw);
            if (obj.telemetry) { onTelemetry(obj.telemetry); replayed++; }
          } catch (_) {}
        }
        st.isReplaying = false;

        if (replayed > 0) info(`\u21a9 Restored ${replayed} packets from server history.`);
      } catch (e) {
        st.isReplaying = false;
        warn(`History restore failed: ${e.message}`);
      }
    }

    // ---------- WEBSOCKET CONNECTION (Real-time link) ----------
    function connect() {
      // Don't open a second socket if one is already live
      if (st.ws && st.ws.readyState === WebSocket.OPEN) return;

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const url = `${protocol}//${window.location.host}/ws/telemetry`;
      info(`Connecting to ${url}\u2026`);
      st.ws = new WebSocket(url);

      st.ws.onopen = () => {
        st.reconnectDelay = 2000; // reset backoff on success
        info('Backend connected.');
        setPill(true, 'Connected');
        // On first page load initCharts() runs 200ms after connect (CSS layout pass).
        // Wait 300ms before replaying so charts exist; on reconnect they already do.
        const replayDelay = Object.keys(st.charts).length === 0 ? 300 : 0;
        setTimeout(replayMissedPackets, replayDelay);
      };

      st.ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.type === 'error') {
            err(data.message || 'Received an unknown error from backend.');
          } else if (data.type === 'log_switched') {
            const label = data.label || 'default';
            if (el.activeLogLabel) el.activeLogLabel.textContent = label;
            cmdEcho(`Log \u2192 ${data.file}`);
            speak(`Log switched to ${label}.`);
          } else if (data.type === 'serial_status') {
            const lbl = document.getElementById('serialStatusLabel');
            if (data.connected) {
              info(`Serial reconnected on ${data.port}.`);
              if (lbl) { lbl.textContent = `\u25cf ${data.port}`; lbl.style.color = 'var(--ok)'; }
            } else {
              warn(`Serial disconnected from ${data.port}. Auto-reconnecting\u2026`);
              if (lbl) { lbl.textContent = '\u25cf disconnected'; lbl.style.color = 'var(--err)'; }
            }
          } else if (data.type !== 'ping') {
            onTelemetry(data); // Process the data!
          }
        } catch (e) {
          warn(`Invalid JSON from backend: ${e.message}`);
        }
      };

      st.ws.onclose = () => {
        st.ws = null;
        // Exponential backoff: 2 \u2192 3 \u2192 4.5 \u2192 \u2026 capped at 30 s
        const delay = st.reconnectDelay;
        st.reconnectDelay = Math.min(Math.round(st.reconnectDelay * 1.5), 30000);
        err(`Backend disconnected. Retrying in ${(delay / 1000).toFixed(0)} s\u2026`);
        setPill(false, `Retry in ${(delay / 1000).toFixed(0)} s`);
        clearTimeout(st.reconnectTimer);
        st.reconnectTimer = setTimeout(connect, delay);
      };

      st.ws.onerror = (e) => {
        err('WebSocket error. Check browser console for details.');
        console.error('WebSocket error:', e);
        st.ws?.close();
      };
    }

    // Reconnect immediately when the tab becomes visible (e.g. MacBook wake from sleep)
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && (!st.ws || st.ws.readyState !== WebSocket.OPEN)) {
        clearTimeout(st.reconnectTimer);
        st.reconnectDelay = 2000; // reset backoff \u2014 user is actively back
        connect();
      }
    });

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
      el.toggleAudio.textContent = `Audio: ${st.audioEnabled ? 'ON' : 'OFF'}`;
      if (st.audioEnabled) speak("Audio Assistant Enabled");
    });

    el.btnVoiceNav?.addEventListener('click', () => {
      st.voiceNavEnabled = !st.voiceNavEnabled;
      el.btnVoiceNav.textContent = `Voice Nav: ${st.voiceNavEnabled ? 'ON' : 'OFF'}`;
    });

    function initRecoveryMap() {
      if (st.recoveryMap) return;
      st.recoveryMap = L.map('recoveryMap', { zoomControl: true, attributionControl: false }).setView([18.788, 98.985], 16);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
      }).addTo(st.recoveryMap);

      st.recoveryMarker = L.marker([18.788, 98.985]).addTo(st.recoveryMap);
      st.gcsMarker = L.circleMarker([18.788, 98.985], { radius: 8, color: '#4da3ff', fillColor: '#4da3ff', fillOpacity: 0.9, weight: 2 }).addTo(st.recoveryMap);
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
          // Use live marker position so recovery line updates if GPS keeps arriving
          const pll = st.recoveryMarker.getLatLng();
          const livePayload = [pll.lat, pll.lng];
          st.recoveryLine.setLatLngs([st.userLoc, livePayload]);

          const dist = calcDistance(uLat, uLon, livePayload[0], livePayload[1]);
          const hdg = calcHeading(uLat, uLon, livePayload[0], livePayload[1]);

          el.recovDist.textContent = `${Math.round(dist)} m`;
          el.recovHeading.textContent = `${Math.round(hdg)}\u00b0`;

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
        }, geoErr => console.warn("Geo error", geoErr), { enableHighAccuracy: true });
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

    // ---------- PIN GPS TARGET ----------
    function updatePinnedDist() {
      if (!el.pinnedDistDisplay) return;
      if (st.pinnedLat === null || st.pinnedLon === null || !st.gps_lat || !st.gps_lon) {
        el.pinnedDistDisplay.textContent = '\u2014';
        return;
      }
      const d = calcDistance(st.gps_lat, st.gps_lon, st.pinnedLat, st.pinnedLon);
      el.pinnedDistDisplay.textContent = d < 1000
        ? `${Math.round(d)} m`
        : `${(d / 1000).toFixed(2)} km`;
    }

    el.btnPinGps?.addEventListener('click', () => {
      const raw = prompt('Paste GPS coordinates (lat, lon):\nExample: 18.7880, 98.9850');
      if (!raw) return;
      const parts = raw.trim().split(/[\s,;]+/);
      const lat = parseFloat(parts[0]);
      const lon = parseFloat(parts[1]);
      if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        alert('Invalid coordinates. Use format: 18.7880, 98.9850');
        return;
      }
      st.pinnedLat = lat;
      st.pinnedLon = lon;
      updatePinnedDist();
      info(`GPS pinned at ${lat.toFixed(5)}, ${lon.toFixed(5)}`);
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

    async function syncLogLabel() {
      try {
        const res = await fetch('/api/log/current');
        if (res.ok) {
          const data = await res.json();
          const display = data.label || 'default';
          if (el.activeLogLabel) el.activeLogLabel.textContent = display;
        }
      } catch (_) {}
    }

    // ---------- SERIAL PORT SELECTOR ----------
    async function loadSerialPorts() {
      const portSel    = document.getElementById('serialPortSel');
      const baudSel    = document.getElementById('serialBaudSel');
      const statusLbl  = document.getElementById('serialStatusLabel');
      if (!portSel || !baudSel) return;
      try {
        const [pr, br, cr] = await Promise.all([
          fetch('/api/serial/ports'),
          fetch('/api/serial/bauds'),
          fetch('/api/serial/config'),
        ]);
        const { ports }   = await pr.json();
        const { presets } = await br.json();
        const cfg          = await cr.json();

        portSel.innerHTML = ports.length
          ? ports.map(p => `<option value="${p.port}" ${p.port === cfg.port ? 'selected' : ''}>${p.port} — ${p.info.slice(0, 30)}</option>`).join('')
          : '<option value="">No ports found</option>';

        baudSel.innerHTML = presets.map(b =>
          `<option value="${b}" ${b === cfg.baud ? 'selected' : ''}>${b}</option>`
        ).join('');

        if (statusLbl) { statusLbl.textContent = `● ${cfg.port}`; statusLbl.style.color = 'var(--muted)'; }
      } catch (e) {
        if (portSel) portSel.innerHTML = '<option value="">Error — server offline?</option>';
      }
    }

    function initSerialSelector() {
      const portSel   = document.getElementById('serialPortSel');
      const baudSel   = document.getElementById('serialBaudSel');
      if (!portSel || !baudSel) return;

      loadSerialPorts();

      document.getElementById('btnSerialRefresh')?.addEventListener('click', loadSerialPorts);

      document.getElementById('btnSerialConnect')?.addEventListener('click', async () => {
        const port = document.getElementById('serialPortSel')?.value;
        const baud = Number(document.getElementById('serialBaudSel')?.value);
        if (!port || !baud) return;
        try {
          const res = await fetch('/api/serial/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ port, baud }),
          });
          if (!res.ok) throw new Error('HTTP ' + res.status);
          info(`Serial reconnecting → ${port} @ ${baud}`);
          const statusLbl = document.getElementById('serialStatusLabel');
          if (statusLbl) { statusLbl.textContent = `● ${port}`; statusLbl.style.color = 'var(--warn)'; }
        } catch (e) {
          err(`Serial config failed: ${e.message}`);
        }
      });
    }

    function init() {
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
      }
      initMap();
      fillCmds();
      initTheme();
      syncLogLabel();
      initSerialSelector();

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