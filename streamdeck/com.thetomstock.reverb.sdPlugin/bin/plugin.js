"use strict";
// Stream Deck-plugin for TheTomStock_Reverb. Snakker med appen over den lokale kontrollporten (control_server.py)
// og med Stream Deck-programmet over WebSocket. Bruker bare det som følger med Node, så det trengs ingen bygging.
const net = require("net");
const http = require("http");
const crypto = require("crypto");

const APP_NAME = "TheTomStock_Reverb";
const PORTS = [8765, 8766, 8767, 8768, 8769, 8770, 8771, 8772, 8773, 8774];
const POLL_MS = 600;
const ACTION_KNOB = "com.thetomstock.reverb.knob";
const ACTION_TOGGLE = "com.thetomstock.reverb.toggle";
const ACTION_PRESET = "com.thetomstock.reverb.preset";

// kortnavn som får plass på en tast
const KNOB_NAMES = {
  in_gain: "Mikrofon", room: "Rom", damping: "Myk lyd", wet: "Ekko", dry: "Stemme", width: "Bredde",
  out_gain: "Volum ut", lc_freq: "Lavkutt", gate_db: "Støygrense", comp_amt: "Jevn lyd", tone: "Lys/mørk",
  predelay: "Ekko-start", mon_vol: "Øre-volum",
};
const TOGGLE_NAMES = { echo: "Ekko", monitor: "Hør meg selv", lowcut: "Lavkutt", gate: "Støyfilter", comp: "Kompressor" };

const RED = "#ff1f1f";
const GOLD = "#d4af37";
const DIM = "#4a3d15";
const GREY = "#6b6b6b";

// ---------------------------------------------------------------- WebSocket mot Stream Deck

function connectSocket(port, onOpen, onText, onClose) {
  const sock = net.connect({ host: "127.0.0.1", port });
  sock.setNoDelay(true);
  let buf = Buffer.alloc(0);
  let upgraded = false;
  let fragments = [];

  const frame = (opcode, payload) => {
    const n = payload.length;
    let head;
    if (n < 126) {
      head = Buffer.from([0x80 | opcode, 0x80 | n]);
    } else if (n < 65536) {
      head = Buffer.alloc(4);
      head[0] = 0x80 | opcode;
      head[1] = 0x80 | 126;
      head.writeUInt16BE(n, 2);
    } else {
      head = Buffer.alloc(10);
      head[0] = 0x80 | opcode;
      head[1] = 0x80 | 127;
      head.writeBigUInt64BE(BigInt(n), 2);
    }
    const mask = crypto.randomBytes(4);
    const body = Buffer.alloc(n);
    for (let i = 0; i < n; i++) body[i] = payload[i] ^ mask[i & 3];
    return Buffer.concat([head, mask, body]);
  };

  const readFrames = () => {
    while (buf.length >= 2) {
      const fin = (buf[0] & 0x80) !== 0;
      const opcode = buf[0] & 0x0f;
      const masked = (buf[1] & 0x80) !== 0;
      let len = buf[1] & 0x7f;
      let off = 2;
      if (len === 126) {
        if (buf.length < 4) return;
        len = buf.readUInt16BE(2);
        off = 4;
      } else if (len === 127) {
        if (buf.length < 10) return;
        len = Number(buf.readBigUInt64BE(2));
        off = 10;
      }
      const maskKey = masked ? buf.subarray(off, off + 4) : null;
      if (masked) off += 4;
      if (buf.length < off + len) return;
      const payload = Buffer.from(buf.subarray(off, off + len));
      buf = buf.subarray(off + len);
      if (maskKey) for (let i = 0; i < len; i++) payload[i] ^= maskKey[i & 3];

      if (opcode === 8) {
        sock.end();
        return;
      } else if (opcode === 9) {
        sock.write(frame(10, payload));
      } else if (opcode === 0 || opcode === 1 || opcode === 2) {
        fragments.push(payload);
        if (fin) {
          const whole = Buffer.concat(fragments);
          fragments = [];
          onText(whole.toString("utf8"));
        }
      }
    }
  };

  sock.on("connect", () => {
    const key = crypto.randomBytes(16).toString("base64");
    sock.write(
      "GET / HTTP/1.1\r\n" +
        `Host: 127.0.0.1:${port}\r\n` +
        "Upgrade: websocket\r\nConnection: Upgrade\r\n" +
        `Sec-WebSocket-Key: ${key}\r\nSec-WebSocket-Version: 13\r\n\r\n`
    );
  });
  sock.on("data", (chunk) => {
    buf = Buffer.concat([buf, chunk]);
    if (!upgraded) {
      const end = buf.indexOf("\r\n\r\n");
      if (end < 0) return;
      if (!/^HTTP\/1\.1 101/.test(buf.toString("latin1", 0, end))) {
        sock.destroy();
        return;
      }
      buf = buf.subarray(end + 4);
      upgraded = true;
      onOpen();
    }
    readFrames();
  });
  sock.on("error", () => {});
  sock.on("close", onClose);

  return { send: (obj) => sock.writable && sock.write(frame(1, Buffer.from(JSON.stringify(obj), "utf8"))) };
}

// ---------------------------------------------------------------- kontrollporten i appen

let appPort = null;
let state = null; // siste /state fra appen, null når appen ikke svarer

function getJson(port, path) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: "127.0.0.1", port, path, timeout: 1500 }, (res) => {
      let text = "";
      res.setEncoding("utf8");
      res.on("data", (d) => (text += d));
      res.on("end", () => {
        try {
          const body = JSON.parse(text);
          if (res.statusCode === 200) resolve(body);
          else reject(new Error(body.error || "feil " + res.statusCode));
        } catch (e) {
          reject(e);
        }
      });
    });
    req.on("timeout", () => req.destroy(new Error("tidsavbrudd")));
    req.on("error", reject);
  });
}

async function findApp() {
  for (const port of PORTS) {
    try {
      const info = await getJson(port, "/ping");
      if (info.app === APP_NAME) return port;
    } catch (e) {
      // ingen app på denne porten
    }
  }
  return null;
}

async function api(path) {
  for (let attempt = 0; attempt < 2; attempt++) {
    if (appPort === null) appPort = await findApp();
    if (appPort === null) throw new Error("appen kjører ikke");
    try {
      return await getJson(appPort, path);
    } catch (e) {
      if (e.message && !/ECONN|tidsavbrudd|socket|ECONNRESET/i.test(e.message)) throw e;
      appPort = null;
    }
  }
  throw new Error("appen kjører ikke");
}

const q = encodeURIComponent;

// ---------------------------------------------------------------- tegning av tastene

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const svgUri = (svg) => "data:image/svg+xml;charset=utf8," + encodeURIComponent(svg);

function arc(cx, cy, r, fromDeg, toDeg) {
  const pt = (d) => [cx + r * Math.cos((d * Math.PI) / 180), cy - r * Math.sin((d * Math.PI) / 180)];
  const [x0, y0] = pt(fromDeg);
  const [x1, y1] = pt(toDeg);
  const large = fromDeg - toDeg > 180 ? 1 : 0;
  return `M${x0.toFixed(1)} ${y0.toFixed(1)} A${r} ${r} 0 ${large} 1 ${x1.toFixed(1)} ${y1.toFixed(1)}`;
}

function knobKey(label, text, pct, symbol) {
  const dead = pct === null;
  const track = `<path d="${arc(72, 62, 46, 225, -45)}" fill="none" stroke="${DIM}" stroke-width="9" stroke-linecap="round"/>`;
  const value =
    dead || pct <= 0
      ? ""
      : `<path d="${arc(72, 62, 46, 225, 225 - 2.7 * Math.min(100, pct))}" fill="none" stroke="${RED}" stroke-width="9" stroke-linecap="round"/>`;
  return svgUri(
    `<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144" viewBox="0 0 144 144">` +
      `<rect width="144" height="144" fill="#0a0a0a"/>${track}${value}` +
      `<text x="72" y="72" text-anchor="middle" font-family="Segoe UI, Arial" font-weight="700" font-size="${text.length > 6 ? 22 : 28}" fill="${dead ? GREY : "#f2ead3"}">${esc(text)}</text>` +
      (symbol ? `<text x="72" y="100" text-anchor="middle" font-family="Segoe UI, Arial" font-size="26" fill="${GOLD}">${symbol}</text>` : "") +
      `<text x="72" y="134" text-anchor="middle" font-family="Segoe UI, Arial" font-size="${label.length > 9 ? 17 : 20}" fill="${GOLD}">${esc(label)}</text>` +
      `</svg>`
  );
}

function toggleKey(label, on) {
  const dead = on === null;
  const colour = dead ? GREY : on ? RED : DIM;
  const status = dead ? "–" : on ? "PÅ" : "AV";
  return svgUri(
    `<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144" viewBox="0 0 144 144">` +
      `<rect width="144" height="144" fill="#0a0a0a"/>` +
      `<circle cx="72" cy="58" r="36" fill="${on ? "#3a0c0a" : "#111"}" stroke="${colour}" stroke-width="7"/>` +
      `<text x="72" y="68" text-anchor="middle" font-family="Segoe UI, Arial" font-weight="700" font-size="30" fill="${dead ? GREY : on ? "#f2ead3" : "#9a8f6e"}">${status}</text>` +
      `<text x="72" y="130" text-anchor="middle" font-family="Segoe UI, Arial" font-size="${label.length > 9 ? 18 : 22}" fill="${GOLD}">${esc(label)}</text>` +
      `</svg>`
  );
}

function wrap(name) {
  const words = String(name || "Lydoppsett").trim().split(/\s+/);
  const lines = [];
  for (const w of words) {
    const last = lines[lines.length - 1];
    if (last !== undefined && (last + " " + w).length <= 9) lines[lines.length - 1] = last + " " + w;
    else lines.push(w);
  }
  return lines.slice(0, 3).map((l) => (l.length > 10 ? l.slice(0, 9) + "…" : l));
}

function presetKey(name, active, dead) {
  const lines = wrap(name);
  const colour = dead ? GREY : active ? RED : GOLD;
  const y0 = 72 - ((lines.length - 1) * 28) / 2 + 9;
  const text = lines
    .map((l, i) => `<text x="72" y="${y0 + i * 28}" text-anchor="middle" font-family="Segoe UI, Arial" font-weight="700" font-size="${lines.length > 2 ? 22 : 26}" fill="${dead ? GREY : "#f2ead3"}">${esc(l)}</text>`)
    .join("");
  return svgUri(
    `<svg xmlns="http://www.w3.org/2000/svg" width="144" height="144" viewBox="0 0 144 144">` +
      `<rect width="144" height="144" fill="#0a0a0a"/>` +
      `<rect x="8" y="8" width="128" height="128" rx="18" fill="${active ? "#3a0c0a" : "#111"}" stroke="${colour}" stroke-width="6"/>` +
      text +
      `</svg>`
  );
}

// ---------------------------------------------------------------- Stream Deck-hendelser

const args = process.argv.slice(2);
const argValue = (name) => args[args.indexOf(name) + 1];
const sdPort = Number(argValue("-port"));
const pluginUUID = argValue("-pluginUUID");
const registerEvent = argValue("-registerEvent");

const actions = new Map(); // context -> { action, settings, controller }
let sd = null;
let pollTimer = null;
const repeaters = new Map(); // context -> intervall for tasten som holdes inne

const send = (obj) => sd && sd.send(obj);
const knobSettings = (s) => ({ knob: "wet", keyAction: "up", amount: 5, setPct: 50, dialSteps: 1, ...s });
const toggleSettings = (s) => ({ name: "echo", mode: "toggle", ...s });
const presetSettings = (s) => ({ name: "Lydoppsett", values: {}, toggles: {}, ...s });

function presetQuery(s) {
  const parts = [];
  for (const [key, pct] of Object.entries(s.values || {})) {
    if (typeof pct === "number" && isFinite(pct)) parts.push(`pct_${q(key)}=${pct}`);
  }
  for (const [name, on] of Object.entries(s.toggles || {})) {
    if (on === "on" || on === "off") parts.push(`${q(name)}=${on}`);
  }
  return "/set?" + parts.join("&");
}

function presetActive(s) {
  if (!state) return false;
  const entries = Object.entries(s.values || {}).filter(([, v]) => typeof v === "number");
  const switches = Object.entries(s.toggles || {}).filter(([, v]) => v === "on" || v === "off");
  if (!entries.length && !switches.length) return false;
  return (
    entries.every(([k, v]) => state.knobs[k] && Math.abs(state.knobs[k].pct - v) < 1.5) &&
    switches.every(([k, v]) => state.toggles[k] === (v === "on"))
  );
}

function render(context) {
  const a = actions.get(context);
  if (!a) return;
  if (a.action === ACTION_KNOB) {
    const s = knobSettings(a.settings);
    const k = state && state.knobs[s.knob];
    const label = KNOB_NAMES[s.knob] || s.knob;
    if (a.controller === "Encoder") {
      send({
        event: "setFeedback",
        context,
        payload: { title: label, value: k ? k.text : "Start appen", indicator: { value: k ? Math.round(k.pct) : 0 } },
      });
    } else {
      const symbol = s.keyAction === "up" ? "▲" : s.keyAction === "down" ? "▼" : s.keyAction === "reset" ? "↺" : "";
      send({
        event: "setImage",
        context,
        payload: { image: knobKey(label, k ? k.text : "Start appen", k ? k.pct : null, symbol), target: 0 },
      });
    }
  } else if (a.action === ACTION_TOGGLE) {
    const s = toggleSettings(a.settings);
    const on = state ? state.toggles[s.name] : null;
    send({ event: "setImage", context, payload: { image: toggleKey(TOGGLE_NAMES[s.name] || s.name, on), target: 0 } });
  } else if (a.action === ACTION_PRESET) {
    const s = presetSettings(a.settings);
    send({ event: "setImage", context, payload: { image: presetKey(s.name, presetActive(s), !state), target: 0 } });
  }
}

const renderAll = () => actions.forEach((_, context) => render(context));

async function refresh() {
  try {
    state = await api("/state");
  } catch (e) {
    state = null;
  }
  renderAll();
}

function startPolling() {
  if (pollTimer === null) {
    pollTimer = setInterval(refresh, POLL_MS);
    refresh();
  }
}

function stopPollingIfIdle() {
  if (actions.size === 0 && pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function call(context, path) {
  try {
    state = await api(path);
    renderAll();
  } catch (e) {
    send({ event: "showAlert", context });
  }
}

// mange små dreiesteg samles til ett kall, så appen ikke drukner i forespørsler
const pendingSteps = new Map();
function step(context, knob, steps) {
  const p = pendingSteps.get(knob) || { steps: 0, timer: null };
  p.steps += steps;
  if (p.timer === null) {
    p.timer = setTimeout(() => {
      pendingSteps.delete(knob);
      if (p.steps !== 0) call(context, `/step?knob=${q(knob)}&steps=${p.steps}`);
    }, 40);
  }
  pendingSteps.set(knob, p);
}

function keyDown(context) {
  const a = actions.get(context);
  if (!a) return;
  keyUp(context);
  if (a.action === ACTION_KNOB) {
    const s = knobSettings(a.settings);
    const amount = Math.max(1, Number(s.amount) || 1);
    if (s.keyAction === "up" || s.keyAction === "down") {
      const dir = s.keyAction === "up" ? 1 : -1;
      call(context, `/step?knob=${q(s.knob)}&steps=${dir * amount}`);
      // holdes tasten inne, fortsetter den å skru
      const wait = setTimeout(() => {
        repeaters.set(context, setInterval(() => call(context, `/step?knob=${q(s.knob)}&steps=${dir * amount}`), 150));
      }, 450);
      repeaters.set(context, wait);
    } else if (s.keyAction === "set") {
      call(context, `/set?knob=${q(s.knob)}&pct=${Number(s.setPct) || 0}`);
    } else {
      call(context, `/reset?knob=${q(s.knob)}`);
    }
  } else if (a.action === ACTION_TOGGLE) {
    const s = toggleSettings(a.settings);
    const state_ = s.mode === "on" ? "&state=on" : s.mode === "off" ? "&state=off" : "";
    call(context, `/toggle?name=${q(s.name)}${state_}`);
  } else if (a.action === ACTION_PRESET) {
    call(context, presetQuery(presetSettings(a.settings)));
  }
}

function keyUp(context) {
  const r = repeaters.get(context);
  if (r !== undefined) {
    clearTimeout(r);
    clearInterval(r);
    repeaters.delete(context);
  }
}

async function capture(msg) {
  // «Bruk nåværende lyd» i lydoppsett: send knappenes verdier tilbake til innstillingsvinduet
  try {
    const now = await api("/state");
    const values = {};
    for (const [key, k] of Object.entries(now.knobs)) values[key] = Math.round(k.pct);
    send({ event: "sendToPropertyInspector", action: msg.action, context: msg.context, payload: { values, toggles: now.toggles } });
  } catch (e) {
    send({ event: "showAlert", context: msg.context });
  }
}

function onMessage(text) {
  let msg;
  try {
    msg = JSON.parse(text);
  } catch (e) {
    return;
  }
  const p = msg.payload || {};
  switch (msg.event) {
    case "willAppear":
      actions.set(msg.context, { action: msg.action, settings: p.settings || {}, controller: p.controller || "Keypad" });
      render(msg.context);
      startPolling();
      break;
    case "willDisappear":
      keyUp(msg.context);
      actions.delete(msg.context);
      stopPollingIfIdle();
      break;
    case "didReceiveSettings": {
      const a = actions.get(msg.context);
      if (a) {
        a.settings = p.settings || {};
        render(msg.context);
      }
      break;
    }
    case "keyDown":
      keyDown(msg.context);
      break;
    case "keyUp":
      keyUp(msg.context);
      break;
    case "dialRotate": {
      const a = actions.get(msg.context);
      if (a && a.action === ACTION_KNOB) {
        const s = knobSettings(a.settings);
        step(msg.context, s.knob, (p.ticks || 0) * Math.max(1, Number(s.dialSteps) || 1));
      }
      break;
    }
    case "dialDown":
    case "touchTap": {
      const a = actions.get(msg.context);
      if (a && a.action === ACTION_KNOB) call(msg.context, `/reset?knob=${q(knobSettings(a.settings).knob)}`);
      break;
    }
    case "sendToPlugin":
      if (p.cmd === "capture") capture(msg);
      break;
  }
}

sd = connectSocket(
  sdPort,
  () => send({ event: registerEvent, uuid: pluginUUID }),
  onMessage,
  () => process.exit(0)
);
