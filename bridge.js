// Simple WS ↔ Serial bridge: ws://localhost:8787
const WebSocket = require('ws');
const { SerialPort } = require('serialport');
const { ReadlineParser } = require('@serialport/parser-readline');

const wss = new WebSocket.Server({ port: 8787 }, () =>
  console.log('WS bridge on ws://localhost:8787')
);

let ser = null;
let parser = null;

async function listPorts() {
  const ports = await SerialPort.list();
  return ports.map(p => ({
    path: p.path || p.comName,
    friendly: [p.manufacturer, p.friendlyName, p.pnpId].filter(Boolean).join(' ')
  }));
}

function wsSend(ws, obj) { try { ws.send(JSON.stringify(obj)); } catch {} }

wss.on('connection', (ws) => {
  wsSend(ws, { type: 'log', level: 'info', msg: 'Client connected' });

  ws.on('message', async (data) => {
    let msg = {};
    try { msg = JSON.parse(data.toString()); } catch { return; }

    if (msg.type === 'list') {
      wsSend(ws, { type: 'ports', ports: await listPorts() });
    }

    if (msg.type === 'open') {
      // close previous
      if (ser) { try { ser.close(); } catch {} ser = null; }
      try {
        ser = new SerialPort({ path: msg.path, baudRate: Number(msg.baud) || 115200 });
        parser = ser.pipe(new ReadlineParser({ delimiter: '\n' }));
        parser.on('data', (line) => wsSend(ws, { type: 'read', data: line.replace(/\r$/, '') }));
        ser.on('error', (e) => wsSend(ws, { type: 'log', level: 'err', msg: 'serial error: ' + e.message }));
        wsSend(ws, { type: 'open', ok: true });
      } catch (e) {
        wsSend(ws, { type: 'open', ok: false });
        wsSend(ws, { type: 'log', level: 'err', msg: 'open failed: ' + e.message });
      }
    }

    if (msg.type === 'close') {
      if (ser) { try { ser.close(); } catch {} ser = null; }
      wsSend(ws, { type: 'close' });
    }

    if (msg.type === 'write') {
      if (ser && ser.writable) ser.write(msg.data);
      else wsSend(ws, { type: 'log', level: 'warn', msg: 'serial not open' });
    }
  });

  ws.on('close', () => {
    if (ser) { try { ser.close(); } catch {} ser = null; }
  });
});
