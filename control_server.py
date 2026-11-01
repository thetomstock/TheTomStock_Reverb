"""Lokal kontrollport for TheTomStock_Reverb (brukes av Stream Deck-pluginet).

Lytter bare på 127.0.0.1, altså den samme PC-en som appen kjører på. Alle kommandoer er vanlige
GET-forespørsler og svarer med JSON. Selve endringene gjøres på hovedtråden til appen (tkinter tåler
ikke andre tråder), så HTTP-tråden legger jobbene i en kø som appen tømmer med pump().

  /ping                         er appen her?
  /state                        alle knapper og brytere med gjeldende verdi
  /set?wet=40&room=80&echo=on   sett flere knapper (rå verdi) og brytere på en gang
  /set?knob=wet&pct=40          sett en knapp i prosent av skalaen (0-100)
  /set?pct_wet=40&pct_room=80   som over, flere knapper på en gang
  /step?knob=wet&steps=2        skru opp (+) eller ned (-), ett steg er det samme som ett klikk med musehjulet
  /reset?knob=wet               tilbake til standard (uten knob: alle knapper)
  /toggle?name=echo[&state=on]  bryter: echo, monitor, lowcut, gate, comp
  /mode?name=avansert           visning: enkel eller avansert
"""
import json
import math
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

PORTS = range(8765, 8775)
HOSTS = ("127.0.0.1", "localhost")
TOGGLES = ("echo", "monitor", "lowcut", "gate", "comp")
ON = ("on", "1", "true", "pa", "på")
OFF = ("off", "0", "false", "av")
WAIT_S = 1.5


def _number(text, name):
    try:
        v = float(text)
    except ValueError:
        raise ValueError(f"{name} må være et tall") from None
    if not math.isfinite(v):
        raise ValueError(f"{name} må være et tall")
    return v


def _state_arg(text):
    t = text.lower()
    if t in ON:
        return True
    if t in OFF:
        return False
    raise ValueError("state må være on eller off")


def _knob(app, q):
    key = q.get("knob")
    if key not in app.knobs:
        raise ValueError("ukjent knob: " + str(key))
    return app.knobs[key]


def _knob_text(key, knob):
    if knob.fmt:
        return knob.fmt(knob.value)
    if key in ("in_gain", "out_gain"):
        return f"{knob.value:+.0f} dB"
    return f"{(knob.value - knob.lo) / (knob.hi - knob.lo) * 100:.0f} %"


def _toggle_values(app):
    p = app.engine.params
    return {"echo": not p["bypass"], "monitor": p["monitor"], "lowcut": p["lowcut"], "gate": p["gate"],
            "comp": p["comp"]}


def state(app):
    knobs = {}
    for key, knob in app.knobs.items():
        knobs[key] = {"label": knob.label, "value": knob.value, "min": knob.lo, "max": knob.hi,
                      "default": knob.default, "pct": (knob.value - knob.lo) / (knob.hi - knob.lo) * 100,
                      "text": _knob_text(key, knob)}
    return {"app": app.app_name, "version": app.app_version, "mode": app.mode, "knobs": knobs,
            "toggles": _toggle_values(app)}


def _set(app, q):
    changes, switches = [], []
    for name, value in q.items():
        if name in app.knobs:
            knob = app.knobs[name]
            changes.append((knob, _number(value, name)))
        elif name in TOGGLES:
            switches.append((name, _state_arg(value)))
        elif name.startswith("pct_") and name[4:] in app.knobs:
            knob = app.knobs[name[4:]]
            changes.append((knob, knob.lo + (knob.hi - knob.lo) * _number(value, name) / 100))
        elif name not in ("knob", "value", "pct"):
            raise ValueError("ukjent navn: " + name)
    if "knob" in q:
        knob = _knob(app, q)
        if "pct" in q:
            changes.append((knob, knob.lo + (knob.hi - knob.lo) * _number(q["pct"], "pct") / 100))
        elif "value" in q:
            changes.append((knob, _number(q["value"], "value")))
        else:
            raise ValueError("mangler value eller pct")
    for knob, v in changes:
        knob.set(v)
    for name, on in switches:
        app.control_toggle(name, on)


def handle(app, path, q):
    """Kjøres på hovedtråden. Kaster ValueError for dårlig input og LookupError for ukjent adresse."""
    if path == "/ping":
        return {"app": app.app_name, "version": app.app_version}
    if path == "/state":
        return state(app)
    if path == "/set":
        _set(app, q)
    elif path == "/step":
        knob = _knob(app, q)
        knob.set(knob.value + _number(q.get("steps", "1"), "steps") * (knob.hi - knob.lo) / 50.0)
    elif path == "/reset":
        for knob in ([_knob(app, q)] if "knob" in q else app.knobs.values()):
            knob.set(knob.default)
    elif path == "/toggle":
        name = q.get("name")
        if name not in TOGGLES:
            raise ValueError("name må være en av: " + ", ".join(TOGGLES))
        app.control_toggle(name, _state_arg(q["state"]) if "state" in q else None)
    elif path == "/mode":
        if q.get("name") not in ("enkel", "avansert"):
            raise ValueError("name må være enkel eller avansert")
        app.control_mode(q["name"])
    else:
        raise LookupError(path)
    return state(app)


class _Job:
    def __init__(self, path, q):
        self.path, self.q = path, q
        self.status, self.body = 500, {"error": "ukjent feil"}
        self.done = threading.Event()

    def run(self, app):
        try:
            self.status, self.body = 200, handle(app, self.path, self.q)
        except ValueError as e:
            self.status, self.body = 400, {"error": str(e)}
        except LookupError:
            self.status, self.body = 404, {"error": "ukjent adresse"}
        except Exception as e:  # noqa: BLE001
            self.status, self.body = 500, {"error": str(e)}
        self.done.set()


class ControlServer:
    def __init__(self, app):
        self.app = app
        self.jobs = queue.Queue()
        self.httpd = None
        self.port = None

    def start(self):
        jobs = self.jobs

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # appen har ingen konsoll, og stderr finnes ikke i .exe-en
                pass

            def _send(self, status, body):
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                # Stopper nettsider fra å styre appen: de kan ikke sette Host til noe annet enn adressen sin
                # (DNS rebinding), og nettlesere merker alle forespørsler fra andre sider med Sec-Fetch-Site.
                if self.headers.get("Host", "").rsplit(":", 1)[0] not in HOSTS:
                    return self._send(403, {"error": "ugyldig Host"})
                if self.headers.get("Sec-Fetch-Site", "none") not in ("none", "same-origin"):
                    return self._send(403, {"error": "ikke tillatt fra nettsider"})
                url = urlsplit(self.path)
                q = {k: v[-1] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
                job = _Job(url.path, q)
                jobs.put(job)
                if not job.done.wait(WAIT_S):
                    return self._send(503, {"error": "appen svarer ikke"})
                self._send(job.status, job.body)

        for port in PORTS:
            try:
                self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            except OSError:
                continue
            self.port = port
            threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
            return port
        return None

    def pump(self):
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                return
            job.run(self.app)

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
