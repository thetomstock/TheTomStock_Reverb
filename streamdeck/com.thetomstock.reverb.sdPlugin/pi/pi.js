"use strict";
// Felles kode for innstillingsvinduene (property inspector). Hver side setter window.page = { init, message }.
const KNOBS = [
  ["in_gain", "Mikrofon"], ["room", "Romstørrelse"], ["damping", "Myk lyd"], ["wet", "Mengde ekko"],
  ["dry", "Din stemme"], ["width", "Rombredde"], ["out_gain", "Volum ut"], ["lc_freq", "Kutt dype lyder"],
  ["gate_db", "Støygrense"], ["comp_amt", "Jevn lyd"], ["tone", "Lys / mørk"], ["predelay", "Ekko-start"],
  ["mon_vol", "Volum i ørene"],
];
const TOGGLES = [
  ["echo", "Ekko"], ["monitor", "Hør meg selv"], ["lowcut", "Kutt dype lyder"], ["gate", "Støyfilter"],
  ["comp", "Kompressor"],
];

let socket = null;
let myUUID = null;
let myAction = null;
let settings = {};

function connectElgatoStreamDeckSocket(port, uuid, registerEvent, info, actionInfo) {
  myUUID = uuid;
  const parsed = JSON.parse(actionInfo);
  myAction = parsed.action;
  settings = parsed.payload.settings || {};
  socket = new WebSocket("ws://127.0.0.1:" + port);
  socket.onopen = () => {
    socket.send(JSON.stringify({ event: registerEvent, uuid }));
    window.page.init(settings);
  };
  socket.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.event === "sendToPropertyInspector" && window.page.message) window.page.message(msg.payload);
  };
}

function save() {
  if (socket && socket.readyState === 1) {
    socket.send(JSON.stringify({ event: "setSettings", context: myUUID, payload: settings }));
  }
}

function sendToPlugin(payload) {
  if (socket && socket.readyState === 1) {
    socket.send(JSON.stringify({ event: "sendToPlugin", action: myAction, context: myUUID, payload }));
  }
}

function fillSelect(select, pairs) {
  for (const [value, text] of pairs) {
    const o = document.createElement("option");
    o.value = value;
    o.textContent = text;
    select.appendChild(o);
  }
}

// kobler alle felt med data-key til innstillingene: leser startverdi, og lagrer ved endring
function bindFields(defaults) {
  document.querySelectorAll("[data-key]").forEach((el) => {
    const key = el.dataset.key;
    const stored = settings[key] !== undefined ? settings[key] : defaults[key];
    el.value = stored;
    const out = document.getElementById(key + "Val");
    if (out) out.textContent = stored + " %";
    el.addEventListener("input", () => {
      settings[key] = el.type === "number" || el.type === "range" ? Number(el.value) : el.value;
      if (out) out.textContent = el.value + " %";
      save();
      if (window.page.changed) window.page.changed();
    });
  });
}
