(() => {
/* ======================== tiny helpers ======================== */
const TEAM_ID = (window.DGS_TEAM_ID || 1043);
const $ = (s) => document.querySelector(s);
const fmt1 = (n) => (Number.isFinite(+n) ? (+n).toFixed(1) : "—");
const fmt5 = (n) => (Number.isFinite(+n) ? (+n).toFixed(5) : "—");
const escapeHtml = (s) => s.replace(/[&<>"']/g, (m)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));
const nowUTC = () => { const d=new Date(); return d.toUTCString().split(" ")[4]; };
const toast = (msg)=>{
  const d=document.createElement("div");
  d.textContent=msg;
  d.style.cssText="position:fixed;right:16px;bottom:16px;background:#0b1220;color:#fff;padding:10px 12px;border-radius:10px;border:1px solid #2b3a55;opacity:.98;font-weight:700;z-index:9999";
  document.body.appendChild(d); setTimeout(()=>d.remove(),1400);
};

/* ======================== DOM refs ======================== */
const utcClock = $("#utcClock");
const missionEl = $("#missionTime");
const gpsMini = $("#gpsMini");
const gpsMiniTitle = $("#gpsMiniTitle");
const connPill = $("#connPill");

const containerState = $("#containerState");
const payloadState   = $("#payloadState");
const contHealthyEl  = $("#contHealthy");
const contBadEl      = $("#contBad");
const plHealthyEl    = $("#plHealthy");
const plBadEl        = $("#plBad");
const contBattPct    = $("#contBattPct");
const plBattPct      = $("#plBattPct");

const modeBrowser = $("#modeBrowser");
const modeServer  = $("#modeServer");
const btnConnectBrowser = $("#btnConnectBrowser");
const btnDisconnectBrowser = $("#btnDisconnectBrowser");
const serverSerialPanel = $("#serverSerialPanel");
const portSel = $("#portSel");
const baudSel = $("#baudSel");
const applyPort = $("#applyPort");
const refreshPorts = $("#refreshPorts");
const healthKV = $("#healthKV");

const mapLink = $("#gmapA");
const btnStartMission = $("#btnStartMission");
const btnSaveCSV = $("#btnSaveCSV");      // ตอนนี้ = เปิดโฟลเดอร์ CSV
const btnResetAll = $("#btnResetAll");

const quickCmd = $("#quickCmd");
const manualCmd = $("#manualCmd");
const sendCmd  = $("#sendCmd");

const rawBox = $("#rawBox");
const autoScroll = $("#autoScroll");
const freezeChk  = $("#freeze");
const wrapLines  = $("#wrapLines");
const logN       = $("#logN");
const refreshLogsBtn = $("#refreshLogs");
const copyLogsBtn    = $("#copyLogs");

/* ======================== REST/WS endpoints ======================== */
const API = {
  ports : "/api/serial/ports",
  bauds : "/api/serial/bauds",
  setCfg: "/api/serial/config",
  getCfg: "/api/serial/config",
  health: "/api/health",
  command: "/api/command",
  logs: (n)=> `/api/logs?n=${n||500}`,
  ingest: "/api/ingest",
  csvOpenFolder: "/api/csv/open-folder",
  csvSaveNow: "/api/csv/save-now",
  ws: () => {
    const loc = window.location;
    const proto = loc.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${loc.host}/ws/telemetry`;
  }
};
const jget  = async (u)=> (await fetch(u)).json();
const jpost = async (u,b)=> (await fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)})).json();

/* ======================== clock & mission timer ======================== */
let missionStart = null;
function tickClock(){
  const t = nowUTC();
  if (utcClock) utcClock.textContent = `${t} UTC`;
  if (missionStart){
    const sec = Math.max(0, Math.floor((Date.now()-missionStart)/1000));
    const h = String(Math.floor(sec/3600)).padStart(2,"0");
    const m = String(Math.floor((sec%3600)/60)).padStart(2,"0");
    const s = String(sec%60).padStart(2,"0");
    if (missionEl) missionEl.textContent = `${h}:${m}:${s}`;
  }
}
setInterval(tickClock, 250); tickClock();

/* ======================== mode UI ======================== */
function updateModeUI(){ if (serverSerialPanel) serverSerialPanel.style.display = modeServer?.checked? "" : "none"; }
modeBrowser?.addEventListener("change", updateModeUI);
modeServer?.addEventListener("change", updateModeUI);
updateModeUI();

/* ======================== health & serial config ======================== */
async function updateHealth(){
  try{
    const h = await jget(API.health);
    const lastCmd = h?.last_cmd || "—";
    if (healthKV){
      healthKV.innerHTML = `
        <div><label>Port</label><div class="big">${h?.serial?.port ?? "—"}</div></div>
        <div><label>Baud</label><div class="big">${h?.serial?.baud ?? "—"}</div></div>
        <div><label>RX</label><div class="big ok">${h?.rx?.received ?? 0}</div></div>
        <div><label>Lost</label><div class="big ${(h?.rx?.lost||0) > 0 ? "warn":"ok"}">${h?.rx?.lost ?? 0}</div></div>
        <div style="grid-column:span 2"><label>CSV</label><div>${h?.csv ?? "—"}</div></div>
        <div style="grid-column:span 2">
          <label>Last Command</label>
          <div class="big" style="font-weight:800;letter-spacing:.3px">${escapeHtml(lastCmd)}</div>
        </div>`;
    }
    // hook สำหรับอัปเดตจากฝั่งส่งคำสั่ง
    window.__setLastCommand = (cmd)=> {
      if (!healthKV) return;
      const lb = healthKV.querySelector("div.big:last-child");
      if (lb) lb.textContent = cmd;
    };
  }catch(e){ /* ignore */ }
}
setInterval(updateHealth, 1500);

/* ----- โหลดพอร์ต/บอดเรต ----- */
async function loadPorts(){
  if (!portSel) return;
  portSel.innerHTML = "";
  try{
    const { ports=[] } = await jget(API.ports);
    ports.forEach(p => {
      const o = document.createElement("option");
      o.value = p.port; o.textContent = p.port;
      portSel.appendChild(o);
    });
    const cfg = await jget(API.getCfg);
    if (cfg?.port){
      if (![...portSel.options].some(o=>o.value===cfg.port)){
        const o = document.createElement("option");
        o.value = cfg.port; o.textContent = `${cfg.port} (current)`;
        portSel.appendChild(o);
      }
      portSel.value = cfg.port;
    }
  }catch(e){}
}
async function loadBauds(){
  if (!baudSel) return;
  baudSel.innerHTML = "";
  try{
    const { presets=[] } = await jget(API.bauds);
    presets.forEach(b=>{
      const o=document.createElement("option");
      o.value=b; o.textContent=`${b} baud`; baudSel.appendChild(o);
    });
    const cfg = await jget(API.getCfg);
    if (cfg?.baud) baudSel.value = cfg.baud;
  }catch(e){}
}
applyPort?.addEventListener("click", async ()=>{
  await jpost(API.setCfg,{port: portSel.value, baud: parseInt(baudSel.value,10)});
  toast(`Server serial → ${portSel.value} @ ${baudSel.value}`);
  setTimeout(updateHealth, 600);
});
refreshPorts?.addEventListener("click", ()=>{ loadPorts(); loadBauds(); });

/* ======================== connection indicator ======================== */
let ws;
function setConn(on){
  if (!connPill) return;
  connPill.textContent = on ? "Live Telemetry" : "Disconnected";
  connPill.className = "pill" + (on ? " ok" : "");
}
function connectWS(){
  try{ ws?.close(); }catch{}
  ws = new WebSocket(API.ws());
  ws.onopen  = ()=> setConn(true);
  ws.onclose = ()=> { setConn(false); setTimeout(connectWS, 1500); };
  ws.onmessage = (ev)=> {
    try{ onTelemetry(JSON.parse(ev.data)); }catch(_){}
  };
}

/* ======================== charts ======================== */
const chartAlt  = echarts.init($("#chart-cont-alt"), "dark");
const chartGpsA = echarts.init($("#chart-cont-gpsalt"), "dark");
const chartVolt = echarts.init($("#chart-cont-volt"), "dark");
const chartTemp = echarts.init($("#chart-cont-temp"), "dark");

function baseLine(name){ return {type:"line", name, showSymbol:false, smooth:true, data:[], lineStyle:{width:2.2}, sampling:"lttb", animation:false, markPoint:{data:[{type:"max",name:"max"},{type:"min",name:"min"}],label:{color:"#fff"}}}; }
function baseOpt(unit){ return { grid:{left:44,right:12,top:22,bottom:32}, tooltip:{trigger:"axis",axisPointer:{type:"cross"}}, xAxis:{type:"time",axisLabel:{color:"#9aa3b2"},splitLine:{show:true,lineStyle:{color:"rgba(255,255,255,0.05)"}}}, yAxis:{type:"value",name:unit,axisLabel:{color:"#9aa3b2"},splitLine:{show:true,lineStyle:{color:"rgba(255,255,255,0.08)"}}}, dataZoom:[{type:"inside"},{type:"slider",height:14}], series:[baseLine("")] }; }
chartAlt.setOption(baseOpt("m"));
chartGpsA.setOption(baseOpt("m"));
chartVolt.setOption(baseOpt("V"));
chartTemp.setOption(baseOpt("°C"));

const chartPlGyro = echarts.init($("#chart-pl-gyro"), "dark");
const chartPlAcc  = echarts.init($("#chart-pl-acc"), "dark");
function tripleOpt(unit){ return { grid:{left:44,right:12,top:22,bottom:32}, tooltip:{trigger:"axis",axisPointer:{type:"cross"}}, legend:{top:2,textStyle:{color:"#cfe3ff"}}, xAxis:{type:"time",axisLabel:{color:"#9aa3b2"},splitLine:{show:true,lineStyle:{color:"rgba(255,255,255,0.05)"}}}, yAxis:{type:"value",name:unit,axisLabel:{color:"#9aa3b2"},splitLine:{show:true,lineStyle:{color:"rgba(255,255,255,0.08)"}}}, dataZoom:[{type:"inside"},{type:"slider",height:14}], series:[ baseLine("R"), baseLine("P"), baseLine("Y") ] }; }
chartPlGyro.setOption({...tripleOpt("deg/s"), series:[baseLine("GYRO_R"), baseLine("GYRO_P"), baseLine("GYRO_Y")]});
chartPlAcc .setOption({...tripleOpt("deg/s²"), series:[baseLine("ACC_R"),  baseLine("ACC_P"),  baseLine("ACC_Y")]});

window.addEventListener("resize", ()=>{ [chartAlt,chartGpsA,chartVolt,chartTemp,chartPlGyro,chartPlAcc].forEach(c=>c.resize()); });

const maxPts = 2000;
function pushCharts(t){
  const ts = t.gs_ts_utc ? new Date(t.gs_ts_utc).getTime() : Date.now();

  const push1 = (chart, val)=>{
    if (!Number.isFinite(val)) return;
    const opt = chart.getOption(); const arr = opt.series[0].data;
    arr.push([ts, val]); if (arr.length>maxPts) arr.shift(); chart.setOption(opt, false, false);
  };
  const push3 = (chart, a,b,c)=>{
    const opt = chart.getOption(); const s = opt.series; const vals=[a,b,c];
    for (let i=0;i<3;i++){ if (Number.isFinite(vals[i])){ s[i].data.push([ts, vals[i]]); if (s[i].data.length>maxPts) s[i].data.shift(); } }
    chart.setOption(opt, false, false);
  };

  push1(chartTemp, +t.temperature_c);
  push1(chartAlt,  +t.altitude_m);
  push1(chartGpsA, +t.gps_altitude_m);
  push1(chartVolt, +t.voltage_v);
  push3(chartPlGyro, +t.gyro_r_dps, +t.gyro_p_dps, +t.gyro_y_dps);
  push3(chartPlAcc,  +t.accel_r_dps2, +t.accel_p_dps2, +t.accel_y_dps2);
}

/* ======================== map ======================== */
const map = L.map("map",{zoomControl:true}).setView([18.788,98.985],13);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19, attribution:"© OpenStreetMap contributors"}).addTo(map);
const marker = L.marker([18.788,98.985]).addTo(map);

/* ======================== logs ======================== */
const telemetryRows = [];  // for possible manual CSV
function highlightLog(s){
  let x = escapeHtml(s);
  x = x.replace(/\bCMD\b/g, '<span class="k cmd">CMD</span>');
  x = x.replace(/\bERROR\b|\bERR\b/g, '<span class="k err">$&</span>');
  x = x.replace(/\bWARN(ING)?\b/g, '<span class="k warn">$&</span>');
  x = x.replace(/\bSIM(ULATION|ULATE)?\b/g, '<span class="k cmd">$&</span>');
  x = x.replace(/\bCAL\b/g, '<span class="k cmd">CAL</span>');
  return x;
}
function addLogLine(line){
  if (freezeChk?.checked) return;
  const div = document.createElement("div");
  div.className = "logline";
  div.innerHTML = `<span class="ts">${nowUTC()}</span><span class="text">${highlightLog(line)}</span>`;
  rawBox?.appendChild(div);
  if (autoScroll?.checked) rawBox.scrollTop = rawBox.scrollHeight;
}
async function refreshLogs(){
  if (freezeChk?.checked) return;
  try{
    const n = parseInt(logN?.value||"500",10) || 500;
    const rows = await jget(API.logs(n));
    if (rawBox) rawBox.innerHTML = "";
    (rows||[]).forEach(r=> addLogLine(typeof r==="string"? r : JSON.stringify(r)));
  }catch(e){}
}
refreshLogsBtn?.addEventListener("click", refreshLogs);
copyLogsBtn?.addEventListener("click", async ()=>{
  try{ await navigator.clipboard.writeText(rawBox.innerText); toast("Logs copied"); }catch{}
});
wrapLines?.addEventListener("change", ()=> rawBox?.classList.toggle("wrap", wrapLines.checked));
setInterval(refreshLogs, 2500);

/* ======================== telemetry router ======================== */
let contHealthy=0, contBad=0, plHealthy=0, plBad=0;
function isNum(x){ return Number.isFinite(+x); }
function estBatteryPct(v){ if(!isNum(v)) return null; return Math.max(0, Math.min(100, Math.round((v-3.3)/(4.2-3.3)*100))); }

function onTelemetry(t){
  // raw
  const raw = t.raw_line || t.raw || "";
  if (raw){
    addLogLine(raw);
    telemetryRows.push(raw);
  }

  // states
  const st = t.state || "—";
  if (containerState) containerState.textContent = `STATE: ${st}`;
  if (payloadState)   payloadState.textContent   = `STATE: ${st}`;

  // counters (simple heuristic)
  if (isNum(t.packet_count) && isNum(t.altitude_m)) { contHealthy++; plHealthy++; }
  else { contBad++; plBad++; }
  if (contHealthyEl) contHealthyEl.textContent = contHealthy;
  if (contBadEl)     contBadEl.textContent     = contBad;
  if (plHealthyEl)   plHealthyEl.textContent   = plHealthy;
  if (plBadEl)       plBadEl.textContent       = plBad;

  // battery
  const cB = isNum(t.battery_pct) ? Math.round(+t.battery_pct) : estBatteryPct(+t.voltage_v);
  if (contBattPct) contBattPct.textContent = isNum(cB) ? cB : "—";
  const pB = isNum(t.payload_battery_pct) ? Math.round(+t.payload_battery_pct) : estBatteryPct(+t.voltage_v);
  if (plBattPct) plBattPct.textContent = isNum(pB) ? pB : "—";

  // charts
  pushCharts(t);

  // gps mini + map + link
  const lat = +t.gps_lat, lon = +t.gps_lon, sats = t.gps_sats;
  if (isNum(lat) && isNum(lon)){
    const mini = `GPS: ${fmt5(lat)}, ${fmt5(lon)} • sats: ${sats ?? "—"}`;
    if (gpsMini) gpsMini.textContent = mini;
    if (gpsMiniTitle) gpsMiniTitle.textContent = `${fmt5(lat)}, ${fmt5(lon)} • sats: ${sats ?? "—"}`;
    if (mapLink) mapLink.href = `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`;
    marker.setLatLng([lat, lon]);
    if (!map._hasCentered){ map.setView([lat, lon], 15); map._hasCentered = true; }
  }
}

/* ======================== commands ======================== */
quickCmd?.addEventListener("change", ()=>{ if (quickCmd.value) handleCommand(quickCmd.value); });
sendCmd?.addEventListener("click", ()=>{
  const s = (manualCmd.value||"").trim();
  if (!s) return;
  handleCommand(s);
});

let dummyTimer = null;
let dummyIntervalMs = 1000;

function handleCommand(text){
  // ground-station only helpers
  if (text === "/clear"){ if (rawBox) rawBox.innerHTML=""; manualCmd.value=""; quickCmd.value=""; return; }
  if (text === "/dummy.on"){ startDummy(); manualCmd.value=""; quickCmd.value=""; return; }
  if (text === "/dummy.off"){ stopDummy(); manualCmd.value=""; quickCmd.value=""; return; }
  if (text.startsWith("/dummy.time")){ const sec = parseFloat(text.split(/\s+/)[1]); if (isFinite(sec) && sec>0){ dummyIntervalMs = Math.round(sec*1000); toast(`Dummy interval = ${sec}s`);} manualCmd.value=""; quickCmd.value=""; return; }

  // payload commands (auto-wrap)
  if (text === "/cal") return sendPayloadCmd("CAL");
  if (text === "/cx.on") return sendPayloadCmd("CX,ON");
  if (text === "/cx.off") return sendPayloadCmd("CX,OFF");
  if (text === "/st.gps") return sendPayloadCmd("ST,GPS");
  if (text.startsWith("/st ")) { const hhmmss=text.split(" ")[1]; return sendPayloadCmd(`ST,${hhmmss}`); }
  if (text === "/sim.enable") return sendPayloadCmd("SIM,ENABLE");
  if (text === "/sim.activate") return sendPayloadCmd("SIM,ACTIVATE");
  if (text === "/sim.disable")  return sendPayloadCmd("SIM,DISABLE");
  if (text.startsWith("/simp ")) { const pa=text.split(" ")[1]; return sendPayloadCmd(`SIMP,${pa}`); }
  if (text.startsWith("/mec.") && (text.endsWith(".on") || text.endsWith(".off"))){
    const mid = text.slice(5); const [dev, onoff] = mid.split(".");
    return sendPayloadCmd(`MEC,${(dev||"").toUpperCase()},${(onoff||"").toUpperCase()}`);
  }

  // raw หรือ short-form
  if (/^CMD\s*,/i.test(text)) {        // ผู้ใช้พิมพ์ CMD,... มาเอง
    return sendRawToBackend(text);
  } else if (/^[A-Z]+,/.test(text)) {  // ผู้ใช้พิมพ์สั้นๆ เช่น CX,ON
    return sendPayloadCmd(text);
  }

  manualCmd.value=""; quickCmd.value="";
}

// ✅ แก้ให้เข้ากับ main.py ใหม่
async function sendPayloadCmd(body){
  // Browser Serial → เขียน CMD,<TEAM>,...
  if (serialWriter) {
    const full = `CMD,${String(TEAM_ID).padStart(4,"0")},${body}`;
    await serialWrite(full + "\r\n");
    if (window.__setLastCommand) window.__setLastCommand(full);
    toast(`TX (browser): ${full}`);
    return;
  }
  // Server Serial → ส่งสั้นๆ ไปให้ backend ต่อหัวให้
  await jpost(API.command,{cmd: body});
  const shown = `CMD,${String(TEAM_ID).padStart(4,"0")},${body}`;
  if (window.__setLastCommand) window.__setLastCommand(shown);
  toast(`TX (backend): ${shown}`);
}
async function sendRawToBackend(cmd){
  // raw CMD ที่ user ใส่มาเอง
  if (serialWriter){
    await serialWrite(cmd + "\r\n");
    if (window.__setLastCommand) window.__setLastCommand(cmd);
    toast(`TX (browser): ${cmd}`);
  } else {
    // ถ้าเป็น CMD,.... เต็ม ให้ตัด "CMD,<TEAM>," ออกก่อน โพสต์สั้นๆ ให้ backend
    const m = cmd.match(/^CMD\s*,\s*\d{1,4}\s*,\s*(.+)$/i);
    const body = m ? m[1] : cmd; // ถ้าไม่ match จะปล่อยไปทั้งสตริง (ให้ backend เติมหัวอีกครั้งไม่ได้)
    await jpost(API.command,{cmd: body});
    if (window.__setLastCommand) window.__setLastCommand(cmd);
    toast(`TX (backend): ${cmd}`);
  }
}

/* ======================== Start Mission / Open CSV Folder / Reset ======================== */
btnStartMission?.addEventListener("click", async ()=>{
  await sendPayloadCmd("ST,GPS");
  if (!missionStart) missionStart = Date.now();
  toast("Mission time started (ST GPS)");
});

// ปุ่มนี้ตอนนี้ = เปิดโฟลเดอร์ CSV บนเครื่อง Windows
btnSaveCSV?.addEventListener("click", async ()=>{
  try{
    const r = await jget(API.csvOpenFolder);
    if (r?.ok) toast("Opened CSV folder");
    else toast("Cannot open CSV folder");
  }catch(e){ toast("Open folder failed"); }
});

btnResetAll?.addEventListener("click", ()=>{
  contHealthy=contBad=plHealthy=plBad=0;
  if (contHealthyEl) contHealthyEl.textContent="0";
  if (plHealthyEl)   plHealthyEl.textContent="0";
  if (contBadEl)     contBadEl.textContent="0";
  if (plBadEl)       plBadEl.textContent="0";
  missionStart=null; if (missionEl) missionEl.textContent="00:00:00";
  if (rawBox) rawBox.innerHTML="";
  telemetryRows.length=0;
  [chartAlt,chartGpsA,chartVolt,chartTemp,chartPlGyro,chartPlAcc].forEach(ch=>{
    const opt=ch.getOption(); opt.series.forEach(s=>s.data=[]); ch.setOption(opt,true,false);
  });
  toast("All cleared");
});

/* ======================== Browser Serial ======================== */
let serialPort=null, serialReader=null, serialWriter=null;
class LineBreakTransformer{
  constructor(){ this.container=""; }
  transform(chunk, controller){ this.container += chunk; const lines = this.container.split(/\r?\n/); this.container = lines.pop(); for(const l of lines) controller.enqueue(l); }
  flush(controller){ if (this.container) controller.enqueue(this.container); }
}
async function serialWrite(s){ await serialWriter.write(s); }

btnConnectBrowser?.addEventListener("click", async ()=>{
  if (!("serial" in navigator)) return alert("Use Chrome/Edge desktop for Web Serial.");
  try{
    serialPort = await navigator.serial.requestPort({ filters: [] });
    const baud = parseInt(baudSel?.value || "115200", 10);
    await serialPort.open({ baudRate: baud });

    const dec = new TextDecoderStream(); serialPort.readable.pipeTo(dec.writable);
    const lineStream = dec.readable.pipeThrough(new TransformStream(new LineBreakTransformer()));
    serialReader = lineStream.getReader();

    const enc = new TextEncoderStream(); enc.readable.pipeTo(serialPort.writable);
    serialWriter = enc.writable.getWriter();

    setConn(true); toast(`Browser serial @ ${baud}`);
    (async function readLoop(){
      try{
        while(true){
          const {value, done} = await serialReader.read(); if (done) break;
          const line = (value||"").trim(); if (!line) continue;
          try{ await fetch(API.ingest,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({line})}); }catch{}
        }
      }catch(e){ console.warn("serial read error", e); }
    })();
  }catch(e){ alert("Serial open failed: "+e); }
});

btnDisconnectBrowser?.addEventListener("click", async ()=>{
  try{ await serialReader?.cancel(); }catch{}
  try{ serialReader?.releaseLock(); }catch{}
  try{ serialWriter?.releaseLock(); }catch{}
  try{ await serialPort?.close(); }catch{}
  serialReader=serialWriter=serialPort=null; setConn(false); toast("Browser serial disconnected");
});


function startDummy(){
  stopDummy();
  dummyTimer = setInterval(()=>{
    const d = new Date(); const hh=String(d.getUTCHours()).padStart(2,"0"); const mm=String(d.getUTCMinutes()).padStart(2,"0"); const ss=String(d.getUTCSeconds()).padStart(2,"0");
    const line = `${TEAM_ID},${hh}:${mm}:${ss},${Math.floor(Date.now()/1000)%10000},F,ASCENT,${(5+Math.random()*2).toFixed(1)},${(15+Math.random()*0.5).toFixed(1)},${(101.3+Math.random()*0.1).toFixed(1)},${(12.0+Math.random()*0.1).toFixed(1)},${(Math.random()*1).toFixed(1)},${(Math.random()*1).toFixed(1)},${(Math.random()*1).toFixed(1)},${(Math.random()*1).toFixed(1)},${(Math.random()*1).toFixed(1)},${(Math.random()*1).toFixed(1)},0,0,0,${Math.floor(Math.random()*5)},${hh}:${mm}:${ss},${(6+Math.random()*0.5).toFixed(1)},18.788,98.985,${7+Math.floor(Math.random()*2)},CXON`;
    fetch(API.ingest,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({line})});
  }, dummyIntervalMs);
  toast("Dummy telemetry ON");
}
function stopDummy(){ if (dummyTimer){ clearInterval(dummyTimer); dummyTimer=null; toast("Dummy telemetry OFF"); }}

/* ======================== boot ======================== */
(async function boot(){
  connectWS();
  await updateHealth();
  await loadPorts(); await loadBauds();
})();
})(); // end IIFE
