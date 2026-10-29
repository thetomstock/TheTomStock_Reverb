"""TheTomStock_Reverb - sanntids reverb for mikrofon, med skrueknapper.

Mikrofon -> forsterkning -> reverb -> begrenser -> utgang (f.eks. VB-Cable).
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import urllib.request
import webbrowser
from tkinter import ttk

import numpy as np
import sounddevice as sd
from pedalboard import (Compressor, Delay, Gain, HighpassFilter, HighShelfFilter, Limiter, NoiseGate,
                        Pedalboard, Reverb)

APP_NAME = "TheTomStock_Reverb"
APP_VERSION = "1.0.5"
REPO = "thetomstock/TheTomStock_Reverb"
EXE_NAME = "TheTomStock_Reverb.exe"
CABLE_URL = "https://vb-audio.com/Cable/"
SETTINGS_PATH = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME, "settings.json")

BG = "#000000"
PANEL = "#0a0a0a"
FG = "#f2ead3"
MUTED = "#9a8f6e"
ACCENT = "#ff1f1f"
GOLD = "#d4af37"
GOLD_DIM = "#4a3d15"
HOT = "#ff7d8a"


def version_tuple(text):
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])


def download_update(url, dest, expected_sha, progress):
    """Laster ned og kontrollerer filen mot sjekksummen fra GitHub. Kaster feil hvis noe er galt."""
    if not url.startswith(f"https://github.com/{REPO}/releases/download/"):
        raise ValueError("Uventet nedlastingsadresse")
    req = urllib.request.Request(url, headers={"User-Agent": "TheTomStock_Reverb"})
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=20) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if total:
                    progress(done * 100 // total)
        if h.hexdigest() != expected_sha.lower():
            raise ValueError("Filen er skadet (sjekksummen stemmer ikke)")
        with open(dest, "rb") as f:
            if f.read(2) != b"MZ":
                raise ValueError("Filen er ikke et Windows-program")
    except Exception:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise


def write_swap_script(new_path, target, pid, script_path):
    """Lager et lite skript som venter til appen er lukket, bytter filen og starter den på nytt.
    Går noe galt, starter den gamle versjonen igjen."""
    text = f"""@echo off
chcp 65001 >nul
set /a n=0
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
  set /a n+=1
  if %n% GTR 30 goto fail
  timeout /t 1 /nobreak >nul
  goto wait
)
set /a n=0
:retry
move /Y "{new_path}" "{target}" >nul 2>&1
if not errorlevel 1 goto done
set /a n+=1
if %n% GTR 30 goto fail
timeout /t 1 /nobreak >nul
goto retry
:done
set PYINSTALLER_RESET_ENVIRONMENT=1
start "" "{target}"
goto end
:fail
del "{new_path}" >nul 2>&1
set PYINSTALLER_RESET_ENVIRONMENT=1
start "" "{target}"
:end
(goto) 2>nul & del "%~f0"
"""
    with open(script_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)


def launch_swap_script(script_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEIPASS", "_PYI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["cmd.exe", "/c", script_path], env=env, creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def resource_path(name):
    """Finner filer både når appen kjøres som skript og som ferdig .exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def mix(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


# (stil, tekst) - vises i hjelpevinduet
HELP_TEXT = [
    ("h1", "Slik bruker du TheTomStock_Reverb\n"),
    ("", f"Versjon {APP_VERSION}. Appen sjekker selv om det finnes en nyere versjon når den åpnes, og viser en gul melding øverst til høyre hvis det gjør det. "
         "Trykk «Oppdater nå», så laster appen ned den nye versjonen, kontrollerer at filen er riktig, "
         "starter på nytt og beholder innstillingene dine.\n"),
    ("", "Appen gir stemmen din ekko, som når du snakker i et stort rom eller en kirke. "
         "Det skjer mens du sender live, og seerne hører stemmen din med effekten.\n"),

    ("h2", "Kom i gang (gjøres bare første gang)\n"),
    ("b", "1.  Installer VB-Cable. "),
    ("", "Det er et lite gratis program som sender lyden fra denne appen til TikTok. Last det ned her: "),
    ("link", "vb-audio.com/Cable"),
    ("", ". Pakk ut filen, høyreklikk på «VBCABLE_Setup_x64» og velg «Kjør som administrator». "
         "Start så PC-en på nytt.\n"),
    ("b", "2.  Åpne TheTomStock_Reverb igjen. "),
    ("", "Teksten nederst skal bli grønn og si «Klar!». Hvis ikke, trykk «Sjekk på nytt».\n"),
    ("b", "3.  Velg mikrofonen din "),
    ("", "under «Din mikrofon». Ved «Send lyden til» skal det stå «CABLE Input». Det velges vanligvis av seg selv.\n"),
    ("b", "4.  Åpne TikTok LIVE Studio "),
    ("", "og gå til lydinnstillingene. Velg «CABLE Output» som mikrofon. Da er du klar til å sende!\n"),

    ("h2", "Tips mens du sender\n"),
    ("", "•  Bruk hodetelefoner. Da slipper du at høyttalerne lager ekko eller hyl.\n"
         "•  Si noe og se på måleren «LYD INN». Nålen skal gå ca. halvveis opp. "
         "Hvis den ofte går inn i det røde og lampen «PEAK» lyser, skru ned knappen «Mikrofon».\n"
         "•  Knappen «Ekko: PÅ/AV» slår ekkoet av og på uten å stoppe lyden.\n"),

    ("h2", "Hva knappene gjør\n"),
    ("", "De små gule ordene over knappene er de vanlige fagbegrepene. Ordene under knappene forklarer hva de gjør.\n"),
    ("b", "Mikrofon: "), ("", "hvor kraftig stemmen din tas inn. Skru opp hvis du er stille.\n"),
    ("b", "Romstørrelse: "), ("", "liten = lite rom, stor = kirke eller hall.\n"),
    ("b", "Myk lyd: "), ("", "høyt = varmere og mykere ekko, lavt = klarere og skarpere ekko.\n"),
    ("b", "Mengde ekko: "), ("", "hvor mye ekko som legges på. Start lavt og skru opp til det høres bra ut.\n"),
    ("b", "Din stemme: "), ("", "hvor mye av den vanlige stemmen din som slippes gjennom.\n"),
    ("b", "Rombredde: "), ("", "hvor vidt ekkoet virker i hodetelefonene eller høyttalerne.\n"),
    ("b", "Volum ut: "), ("", "hvor høyt lyden sendes til TikTok.\n"),
    ("", "Tips: dobbeltklikk på en knapp for å sette den tilbake til utgangspunktet.\n"),

    ("h2", "Enkel eller Avansert visning\n"),
    ("", "Øverst til høyre bytter du mellom «Enkel» og «Avansert». Enkel viser bare de fire viktigste knappene "
         "(Mikrofon, Romstørrelse, Mengde ekko og Volum ut). Avansert viser alle knappene, pluss en rad med finjustering. "
         "Knappene du ikke ser i Enkel beholder verdiene sine. Bytter du mellom visningene, mister du ingenting. "
         "I Avansert finner du også PÅ/AV-knapper under de tre første finjusteringsknappene, samt valgene for forsinkelse.\n"),
    ("b", "Kutt dype lyder: "), ("", "hvor høyt lavkuttet skjærer. Høyere tall fjerner mer dunk og buldring.\n"),
    ("b", "Støygrense: "), ("", "hvor høy lyden må være før støyfilteret slipper den gjennom. Høyere tall (mot -25) gir sterkere støyfilter.\n"),
    ("b", "Jevn lyd: "), ("", "hvor kraftig kompressoren er. Mot 0 er den svak, mot 100 % er den kraftig.\n"),
    ("b", "Lys / mørk: "), ("", "mot høyre blir stemmen klarere og skarpere, mot venstre mykere og mørkere.\n"),
    ("b", "Ekko-start: "), ("", "en liten pause før ekkoet kommer. Gir stemmen mer plass og blir ofte mer naturlig.\n"),

    ("h2", "Lavkutt og kompressor\n"),
    ("", "Disse tre har hver sin PÅ/AV-knapp i Avansert visning, rett under knappen med samme tema.\n"),
    ("b", "Lavkutt: "),
    ("", "fjerner dype lyder du ikke trenger, som buldring, vind og bordbank. Lar stemmen stå klarere. "
         "Lar du den stå på, er det som regel best.\n"),
    ("b", "Støyfilter: "),
    ("", "demper susing og bakgrunnsstøy når du er stille, så seerne ikke hører det mellom ordene. "
         "Styrken justerer du med knappen «Støygrense» (høyere tall gir sterkere filter). Starter ordene dine å bli "
         "kuttet i begynnelsen eller slutten, velg et lavere tall eller slå det av. Hører du fortsatt støy, velg et høyere.\n"),
    ("b", "Kompressor: "),
    ("", "jevner ut lydstyrken, så rolige ord ikke forsvinner og høye ord ikke blir for kraftige. "
         "Den er stilt middels kraftig og løfter volumet litt. Slå den av hvis du vil ha stemmen helt naturlig.\n"),
    ("", "Alle tre kan slås av og på mens du sender.\n"),

    ("h2", "Forsinkelse\n"),
    ("", "Du finner valget i Avansert visning. Lyden går gjennom appen på noen få tideler av et sekund. «Minst» gir raskest lyd, "
         "men kan få lyden til å knitre på tregere PC-er. Knitrer det, velg «Lav», «Middels» eller «Mest». "
         "«Ekstra rask modus» kan gi enda raskere lyd hvis du har et lydkort eller en USB-mikrofon, "
         "men fungerer ikke alltid.\n"),

    ("h2", "Hvis noe ikke virker\n"),
    ("b", "Seerne hører ingenting: "),
    ("", "sjekk at TikTok LIVE Studio bruker «CABLE Output» som mikrofon, "
         "og at det står «CABLE Input» ved «Send lyden til». Sjekk også at nålene beveger seg når du snakker.\n"),
    ("b", "Nålene beveger seg ikke: "),
    ("", "velg riktig mikrofon under «Din mikrofon», og sjekk at mikrofonen ikke er avslått i Windows.\n"),
    ("b", "Jeg hører meg selv med forsinkelse: "),
    ("", "bruk hodetelefoner, og slå av «Lytt til denne enheten» for mikrofonen i Windows' lydinnstillinger.\n"),
    ("b", "Lyden knitrer: "), ("", "velg en høyere forsinkelse i Avansert visning (Middels eller Mest) og lukk andre tunge programmer.\n"),
    ("b", "Meldingen «Kunne ikke starte lyden»: "),
    ("", "prøv en annen mikrofon i listen, slå av «Ekstra rask modus», eller start appen på nytt.\n"),
]


def rrect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


class RoundBox(tk.Canvas):
    """Panel med runde hjørner. Legg innholdet i .inner."""

    def __init__(self, master, pad=12, radius=18, fill=PANEL, outline=GOLD_DIM):
        super().__init__(master, bg=BG, highlightthickness=0)
        self.pad, self.radius, self.fill, self.outline = pad, radius, fill, outline
        self.inner = tk.Frame(self, bg=fill)
        self.create_window(pad, pad, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._resize)

    def _resize(self, e):
        w, h = e.width + 2 * self.pad, e.height + 2 * self.pad
        self.config(width=w, height=h)
        self.delete("bg")
        rrect(self, 1, 1, w - 1, h - 1, self.radius, fill=self.fill, outline=self.outline, width=1, tags="bg")
        self.tag_lower("bg")


class VUMeter(tk.Canvas):
    """Retro analog VU-måler med elfenbensskive, nål og rød overstyringslampe."""

    DB_MIN, DB_MAX = -36.0, 0.0
    A0, A1 = 150.0, 30.0  # vinkel (grader) ved DB_MIN og DB_MAX
    INK = "#2a2418"

    def __init__(self, master, label, width=370, height=150):
        super().__init__(master, width=width, height=height, bg=BG, highlightthickness=0)
        self.w, self.h, self.label = width, height, label
        self.cx, self.cy, self.R = width / 2, height - 8, 120
        self.level = 0.0
        self.hold = 0
        self._angle = None
        self._build()
        self.feed(0.0)

    def _polar(self, r, ang):
        a = math.radians(ang)
        return self.cx + r * math.cos(a), self.cy - r * math.sin(a)

    def _angle_of(self, db):
        t = (db - self.DB_MIN) / (self.DB_MAX - self.DB_MIN)
        return self.A0 + (self.A1 - self.A0) * t

    def _build(self):
        w, h, cx, cy, R = self.w, self.h, self.cx, self.cy, self.R
        face_bottom = h - 24
        rrect(self, 1, 1, w - 1, h - 1, 16, fill="#090909", outline=GOLD_DIM)
        shades = ("#b3a26a", "#c4b47e", "#d6c792", "#e3d6a2", "#ece0b0")
        for i, col in enumerate(shades):
            rrect(self, 8 + i * 3, 8 + i * 3, w - 8 - i * 3, face_bottom - i * 3, max(4, 10 - i * 2), fill=col)

        a_red = self._angle_of(-6)
        box = lambda r: (cx - r, cy - r, cx + r, cy + r)
        self.create_arc(*box(R + 4), start=self.A0, extent=a_red - self.A0, style="arc", outline=self.INK, width=1)
        self.create_arc(*box(R), start=self.A0, extent=self.A1 - self.A0, style="arc", outline=self.INK, width=1)
        self.create_arc(*box(R + 4), start=a_red, extent=self.A1 - a_red, style="arc", outline="#b3261e", width=4)
        for db in range(int(self.DB_MIN), 1, 3):
            major = db % 6 == 0
            ang = self._angle_of(db)
            x1, y1 = self._polar(R, ang)
            x2, y2 = self._polar(R - (10 if major else 5), ang)
            col = "#b3261e" if db >= -6 else self.INK
            self.create_line(x1, y1, x2, y2, fill=col, width=2 if major else 1)
            if major:
                tx, ty = self._polar(R - 22, ang)
                self.create_text(tx, ty, text=str(db), fill=col, font=("Georgia", 8, "bold"))
        self.create_text(24, 18, text=self.label, anchor="nw", fill=self.INK, font=("Georgia", 16, "bold italic"))
        self.create_text(w - 24, face_bottom - 14, text="dB", anchor="se", fill=self.INK, font=("Georgia", 9, "italic"))
        self.create_text(w - 48, 22, text="PEAK", anchor="e", fill=self.INK, font=("Georgia", 7, "bold"))
        self.lamp = self.create_oval(w - 42, 15, w - 28, 29, fill="#3a0c0a", outline="#6b5a22", width=1)

        self.shadow = self.create_line(cx, cy, cx, cy - 100, fill="#6f6643", width=3, capstyle="round")
        self.needle = self.create_line(cx, cy, cx, cy - 100, fill="#171410", width=2, capstyle="round")

        # sokkel som skjuler nålens dreiepunkt
        self.create_rectangle(3, face_bottom, w - 3, h - 2, fill="#090909", outline="")
        rrect(self, 1, 1, w - 1, h - 1, 16, fill="", outline=GOLD_DIM)
        self.create_arc(cx - 24, face_bottom - 24, cx + 24, face_bottom + 24, start=0, extent=180,
                        style="pieslice", fill="#1a1a1a", outline="#6b5a22")
        self.create_arc(cx - 14, face_bottom - 18, cx + 8, face_bottom - 4, start=60, extent=90,
                        style="arc", outline="#5a5a5a", width=2)

    def feed(self, peak):
        if peak > self.level:
            self.level += (peak - self.level) * 0.7
        else:
            self.level *= 0.90
        db = 20 * math.log10(max(self.level, 1e-5))
        db = min(self.DB_MAX + 1.0, max(self.DB_MIN - 1.0, db))
        ang = round(self._angle_of(db), 1)
        if ang != self._angle:
            self._angle = ang
            tx, ty = self._polar(116, ang)
            self.coords(self.needle, self.cx, self.cy, tx, ty)
            self.coords(self.shadow, self.cx + 2, self.cy + 2, tx + 2, ty + 2)
        if peak >= 0.97:
            self.hold = 18
        elif self.hold:
            self.hold -= 1
        self.itemconfigure(self.lamp, fill="#ff2a1a" if self.hold else "#3a0c0a")


# (key, label, min, max, default, enhet)
KNOBS = [
    ("in_gain", "Mikrofon", -12.0, 24.0, 0.0, ""),
    ("room", "Romstørrelse", 0.0, 1.0, 0.45, ""),
    ("damping", "Myk lyd", 0.0, 1.0, 0.5, ""),
    ("wet", "Mengde ekko", 0.0, 1.0, 0.25, ""),
    ("dry", "Din stemme", 0.0, 1.0, 0.85, ""),
    ("width", "Rombredde", 0.0, 1.0, 1.0, ""),
    ("out_gain", "Volum ut", -24.0, 12.0, 0.0, ""),
]

# knappene som vises i Enkel-visning
SIMPLE_KEYS = ("in_gain", "room", "wet", "out_gain")

# (key, label, min, max, default, formatering) - ekstra finjustering som bare vises i Avansert-visning
ADV_KNOBS = [
    ("lc_freq", "Kutt dype lyder", 40.0, 300.0, 90.0, lambda v: f"{v:.0f} Hz"),
    ("gate_db", "Støygrense", -60.0, -25.0, -44.0, lambda v: f"{v:.0f} dB"),
    ("comp_amt", "Jevn lyd", 0.0, 1.0, 0.6, lambda v: f"{v * 100:.0f} %"),
    ("tone", "Lys / mørk", -1.0, 1.0, 0.0, lambda v: f"{v * 6:+.0f} dB"),
    ("predelay", "Ekko-start", 0.0, 120.0, 0.0, lambda v: f"{v:.0f} ms"),
]

# vanlige fagbegreper som vises over knappene
TERMS = {"in_gain": "INNGANG", "room": "ROMSTØRRELSE", "damping": "DEMPING", "wet": "REVERB",
         "dry": "ORIGINAL", "width": "BREDDE", "out_gain": "UTGANG",
         "lc_freq": "LAVKUTT", "gate_db": "STØYFILTER", "comp_amt": "KOMPRESSOR", "tone": "TONE",
         "predelay": "PRE-DELAY"}


class Knob(tk.Canvas):
    """Dra opp/ned for å endre, dobbeltklikk for standard, musehjul for finjustering."""

    def __init__(self, master, label, lo, hi, default, unit, on_change, value=None, term="", fmt=None):
        super().__init__(master, width=96, height=144, bg=PANEL, highlightthickness=0)
        self.term = term
        self.fmt = fmt
        self.label, self.lo, self.hi, self.default, self.unit = label, lo, hi, default, unit
        self.on_change = on_change
        self.value = default if value is None else min(hi, max(lo, value))
        self._drag_y = None
        self._drag_v = None
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Double-Button-1>", lambda e: self.set(self.default))
        self.bind("<MouseWheel>", self._wheel)
        self.draw()

    def set(self, v):
        self.value = min(self.hi, max(self.lo, v))
        self.draw()
        self.on_change(self.value)

    def _press(self, e):
        self._drag_y, self._drag_v = e.y, self.value

    def _drag(self, e):
        if self._drag_y is None:
            return
        span = self.hi - self.lo
        self.set(self._drag_v + (self._drag_y - e.y) / 150.0 * span)

    def _wheel(self, e):
        self.set(self.value + (1 if e.delta > 0 else -1) * (self.hi - self.lo) / 50.0)

    def draw(self):
        self.delete("all")
        cx, cy = 48, 70
        frac = (self.value - self.lo) / (self.hi - self.lo)
        a0, a1 = 225.0, -45.0  # skalaen går fra 7:30 til 4:30 på urskiva
        glow = 0.4 + 0.6 * frac

        # svakt rødt skjær bak knappen
        for rr, t in ((34, 0.10), (32, 0.20), (30, 0.36)):
            self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=mix(PANEL, ACCENT, t * glow), width=2)

        # skala med streker, de som er passert lyser rødt
        n = 20
        for i in range(n + 1):
            t = i / n
            ang = math.radians(a0 + (a1 - a0) * t)
            major = i % 2 == 0
            r1, r2 = (36, 43) if major else (36, 40)
            lit = t <= frac + 1e-6
            col = ACCENT if lit else ("#8c7a45" if major else "#4d4426")
            if lit:
                self.create_line(cx + r1 * math.cos(ang), cy - r1 * math.sin(ang),
                                 cx + r2 * math.cos(ang), cy - r2 * math.sin(ang),
                                 fill=mix(PANEL, ACCENT, 0.35), width=4, capstyle="round")
            self.create_line(cx + r1 * math.cos(ang), cy - r1 * math.sin(ang),
                             cx + r2 * math.cos(ang), cy - r2 * math.sin(ang),
                             fill=col, width=2 if major else 1)

        # knapp: skygge, riflet kant, børstet metallhette med lysrefleks oppe til venstre
        self.create_oval(cx - 27, cy - 25, cx + 29, cy + 31, fill="#000000", outline="")
        self.create_oval(cx - 28, cy - 28, cx + 28, cy + 28, fill="#0e0e0e", outline="#050505")
        for i in range(48):
            ang = math.radians(i * 7.5)
            self.create_line(cx + 25 * math.cos(ang), cy - 25 * math.sin(ang),
                             cx + 28 * math.cos(ang), cy - 28 * math.sin(ang), fill="#3b3b3b", width=1)
        self.create_oval(cx - 25, cy - 25, cx + 25, cy + 25, fill="#161616", outline="#5a5a5a")
        for k in range(12):
            rad = 23 - k * 1.6
            sh = 0.12 * (23 - rad)
            lum = 34 + int(k * 7)
            self.create_oval(cx - rad - sh, cy - rad - sh, cx + rad - sh, cy + rad - sh,
                             fill="#%02x%02x%02x" % (lum, lum, lum + 2), outline="")
        self.create_oval(cx - 17, cy - 19, cx - 6, cy - 11, fill="#9a9a9a", outline="")
        self.create_oval(cx - 15, cy - 18, cx - 8, cy - 13, fill="#c8c8c8", outline="")

        # retro viser: kremfarget strek med skygge og lite rødt hode
        ang = math.radians(a0 + (a1 - a0) * frac)
        c, sn = math.cos(ang), math.sin(ang)
        self.create_line(cx + 7 * c + 1, cy - 7 * sn + 1, cx + 23 * c + 1, cy - 23 * sn + 1,
                         fill="#000000", width=4, capstyle="round")
        self.create_line(cx + 7 * c, cy - 7 * sn, cx + 23 * c, cy - 23 * sn, fill="#efe4c0", width=3,
                         capstyle="round")
        self.create_oval(cx + 20 * c - 2, cy - 20 * sn - 2, cx + 20 * c + 2, cy - 20 * sn + 2,
                         fill=ACCENT, outline="")

        txt = self.fmt(self.value) if self.fmt else f"{frac * 100:.0f} %"
        self.create_text(cx, 120, text=txt, fill=FG, font=("Segoe UI", 9, "bold"))
        self.create_text(cx, 135, text=self.label, fill=MUTED, font=("Segoe UI", 9))
        self.create_text(cx, 9, text=self.term, fill=GOLD, font=("Segoe UI", 7, "bold"))


class Engine:
    REVERB_STEP = 0.01  # største endring av romparametre per lydblokk, så det ikke klikker

    def __init__(self):
        self.params = {k: d for k, _, _, _, d, _ in KNOBS + ADV_KNOBS}
        self.params.update(bypass=False, lowcut=True, gate=True, comp=True)
        self.stream = None
        self.peak_in = 0.0
        self.peak_out = 0.0
        self.error = None
        self.sr = 48000.0
        self._cur = {}  # glattede verdier, brukes bare av lydtråden
        self._was_on = {"lowcut": True, "gate": True, "comp": True}
        self._build_board()

    def _build_board(self):
        p = self.params
        self.reverb = Reverb(room_size=p["room"], damping=p["damping"], wet_level=1.0,
                             dry_level=0.0, width=p["width"], freeze_mode=0.0)
        self.rev_board = Pedalboard([self.reverb])
        self.hp = HighpassFilter(cutoff_frequency_hz=p["lc_freq"])
        self.lowcut = Pedalboard([self.hp])
        self.gate_plugin = NoiseGate(threshold_db=p["gate_db"], ratio=30.0, attack_ms=2.0, release_ms=150.0)
        self.gate = Pedalboard([self.gate_plugin])
        self.comp_plugin = Compressor(threshold_db=-26.0, ratio=4.0, attack_ms=6.0, release_ms=140.0)
        self.makeup = Gain(gain_db=4.0)
        self.comp = Pedalboard([self.comp_plugin, self.makeup])
        self.tone_plugin = HighShelfFilter(cutoff_frequency_hz=4000.0, gain_db=0.0, q=0.7)
        self.tone_board = Pedalboard([self.tone_plugin])
        self.pre_plugin = Delay(delay_seconds=0.0, feedback=0.0, mix=1.0)
        self.pre_board = Pedalboard([self.pre_plugin])
        self._applied = {}  # sist brukte verdier for plugin-parametre
        self.limiter = Pedalboard([Limiter(threshold_db=-1.0, release_ms=60.0)])
        self._cur.update(room=p["room"], damping=p["damping"], width=p["width"])

    def update(self, key, value):
        self.params[key] = value  # lydtråden henter verdien og glatter den selv

    def _gain(self, key, frames, db):
        """Gain som glir jevnt over blokken i stedet for å hoppe."""
        target = 10 ** (self.params[key] / 20) if db else self.params[key]
        prev = self._cur.get(key, target)
        self._cur[key] = target
        if prev == target:
            return target
        return np.linspace(prev, target, frames, endpoint=False, dtype=np.float32)

    def _apply_comp(self, amt):
        self.comp_plugin.threshold_db = -16.0 - 16.0 * amt
        self.comp_plugin.ratio = 2.0 + 3.3 * amt
        self.makeup.gain_db = 6.0 * amt

    def _sync_plugins(self):
        """Overfører knappenes verdier til filtrene, bare når de er endret."""
        p, applied = self.params, self._applied
        for key, apply in (
                ("lc_freq", lambda v: setattr(self.hp, "cutoff_frequency_hz", v)),
                ("gate_db", lambda v: setattr(self.gate_plugin, "threshold_db", v)),
                ("comp_amt", self._apply_comp),
                ("tone", lambda v: setattr(self.tone_plugin, "gain_db", v * 6.0)),
                ("predelay", lambda v: setattr(self.pre_plugin, "delay_seconds", v / 1000.0))):
            if applied.get(key) != p[key]:
                applied[key] = p[key]
                apply(p[key])

    def _glide_reverb(self):
        for key, attr in (("room", "room_size"), ("damping", "damping"), ("width", "width")):
            target, cur = self.params[key], self._cur[key]
            if cur != target:
                cur = target if abs(target - cur) <= self.REVERB_STEP else cur + math.copysign(self.REVERB_STEP, target - cur)
                self._cur[key] = cur
                setattr(self.reverb, attr, cur)

    def _callback(self, indata, outdata, frames, time_info, status):
        p, sr = self.params, self.sr
        x = indata[:, 0] * self._gain("in_gain", frames, True)
        self.peak_in = max(float(np.abs(x).max()), self.peak_in)
        sig = x.astype(np.float32)[np.newaxis, :]
        self._sync_plugins()
        for key, board in (("lowcut", self.lowcut), ("gate", self.gate), ("comp", self.comp)):
            if p[key]:
                if not self._was_on[key]:
                    board.reset()
                sig = board.process(sig, sr, reset=False)
            self._was_on[key] = p[key]
        stereo = np.repeat(sig, 2, axis=0)
        if p["bypass"]:
            y = stereo
        else:
            self._glide_reverb()
            wet_in = stereo if p["predelay"] < 0.5 else self.pre_board.process(stereo, sr, reset=False)
            wet = self.rev_board.process(wet_in, sr, reset=False)
            y = wet * self._gain("wet", frames, False) + stereo * self._gain("dry", frames, False)
        if abs(p["tone"]) > 0.02:
            y = self.tone_board.process(y.astype(np.float32), sr, reset=False)
        y = y * self._gain("out_gain", frames, True)
        y = self.limiter.process(y.astype(np.float32), sr, reset=False)
        y = np.clip(y, -1.0, 1.0)
        self.peak_out = max(float(np.abs(y).max()), self.peak_out)
        outdata[:, :2] = y.T

    def start(self, in_dev, out_dev, blocksize, exclusive=False):
        self.stop()
        self.error = None
        try:
            din, dout = sd.query_devices(in_dev), sd.query_devices(out_dev)
            self.sr = float(din["default_samplerate"])
            wasapi = sd.WasapiSettings(exclusive=exclusive, auto_convert=not exclusive)
            self.stream = sd.Stream(
                samplerate=self.sr, blocksize=blocksize, device=(in_dev, out_dev),
                channels=(1, 2), dtype="float32", latency="low",
                extra_settings=(wasapi, wasapi), callback=self._callback)
            self.stream.start()
        except Exception as exc:  # noqa: BLE001 - vises i GUI
            self.stream = None
            self.error = str(exc)

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            finally:
                self.stream = None

    def latency_ms(self):
        if self.stream is None:
            return None
        li, lo = self.stream.latency
        return (li + lo) * 1000.0


def list_devices():
    ins, outs = [], []
    wasapi = next((i for i, h in enumerate(sd.query_hostapis()) if "WASAPI" in h["name"]), None)
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] != wasapi:
            continue
        if d["max_input_channels"] > 0:
            ins.append((i, d["name"]))
        if d["max_output_channels"] > 0:
            outs.append((i, d["name"]))
    return ins, outs


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.configure(bg=BG)
        self.resizable(False, False)
        try:
            self.iconbitmap(resource_path("thetomstock_reverb.ico"))
        except tk.TclError:
            pass
        self._style()
        self.engine = Engine()
        self.saved = self._load()
        self._build_ui()
        self.after(33, self._tick)
        self.after(50, self._dwm)
        self._update_found = None
        self._dl = None
        self._update_shown = False
        threading.Thread(target=self._check_update, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._start()

    def _check_update(self):
        """Spør GitHub om siste utgivelse. Feiler stille hvis du er uten nett."""
        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/releases/latest",
                headers={"User-Agent": "TheTomStock_Reverb", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.load(resp)
            tag = data["tag_name"]
            if version_tuple(tag) <= version_tuple(APP_VERSION):
                return
            page = data.get("html_url", "")
            if not page.startswith(f"https://github.com/{REPO}/"):
                page = f"https://github.com/{REPO}/releases/latest"
            asset = next((a for a in data.get("assets", []) if a.get("name") == EXE_NAME), {})
            digest = str(asset.get("digest", ""))
            sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
            self._update_found = {"tag": tag, "page": page, "url": asset.get("browser_download_url", ""),
                                  "sha": sha if re.fullmatch(r"[0-9a-fA-F]{64}", sha) else ""}
        except Exception:  # noqa: BLE001 - ingen nett eller GitHub nede, ikke et problem
            pass

    def _can_self_update(self):
        info = self._update_found
        return bool(getattr(sys, "frozen", False) and info["url"] and info["sha"]
                    and os.access(os.path.dirname(os.path.abspath(sys.executable)), os.W_OK))

    def _show_update(self):
        info = self._update_found
        self._dl = {"state": "idle", "pct": 0}
        box = tk.Frame(self, bg="#140f00", highlightbackground=GOLD, highlightcolor=GOLD, highlightthickness=1)
        self.upd_label = tk.Label(box, text=f"Ny versjon er klar: {info['tag']}", bg="#140f00", fg=GOLD,
                                  font=("Segoe UI", 9, "bold"))
        self.upd_label.pack(side="left", padx=(10, 8), pady=6)
        auto = self._can_self_update()
        self.upd_btn = tk.Button(box, text="Oppdater nå" if auto else "Last ned", bg="#050505", fg=HOT,
                                 relief="flat", highlightthickness=2, highlightbackground=ACCENT,
                                 activebackground="#1a0000", cursor="hand2",
                                 command=self._start_update if auto else lambda: webbrowser.open(info["page"]))
        self.upd_btn.pack(side="left", padx=(0, 8), pady=4)
        box.place(relx=1.0, x=-18, y=16, anchor="ne")

    def _start_update(self):
        info = self._update_found
        target = os.path.abspath(sys.executable)
        new_path = os.path.splitext(target)[0] + ".new.exe"
        self._swap = (new_path, target)
        self._dl = {"state": "downloading", "pct": 0}
        self.upd_btn.config(state="disabled")

        def work():
            try:
                download_update(info["url"], new_path, info["sha"], lambda pct: self._dl.update(pct=pct))
                self._dl["state"] = "ready"
            except Exception as exc:  # noqa: BLE001
                self._dl.update(state="error", msg=str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _poll_update(self):
        dl = getattr(self, "_dl", None)
        if not dl:
            return
        if dl["state"] == "downloading":
            self.upd_label.config(text=f"Laster ned … {dl['pct']} %")
        elif dl["state"] == "ready":
            dl["state"] = "applying"
            self.upd_label.config(text="Starter på nytt …")
            new_path, target = self._swap
            script = os.path.join(tempfile.gettempdir(), "TheTomStock_Reverb_update.bat")
            write_swap_script(new_path, target, os.getpid(), script)
            launch_swap_script(script)
            self._close()
            return True
        elif dl["state"] == "error":
            dl["state"] = "failed"
            page = self._update_found["page"]
            self.upd_label.config(text="Oppdateringen feilet. Last ned selv:", fg="#ff6b6b")
            self.upd_btn.config(state="normal", text="Last ned", command=lambda: webbrowser.open(page))

    def _dwm(self, win=None):
        """Runde hjørner og gull ramme fra Windows 11 (ignoreres stille på eldre Windows)."""
        try:
            import ctypes
            from ctypes import wintypes
            win = win or self
            win.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())

            def attr(n, v):
                val = ctypes.c_int(v)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), n, ctypes.byref(val), 4)

            attr(20, 1)           # mørk tittellinje
            attr(33, 2)           # runde hjørner
            attr(34, 0x0037AFD4)  # kantfarge (gull, BGR)
            attr(35, 0x00000000)  # tittellinje svart
            attr(36, 0x00D3EAF2)  # tittelfarge
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _style():
        st = ttk.Style()
        st.theme_use("clam")
        st.configure("TCombobox", fieldbackground="#111111", background="#111111", foreground=FG,
                     bordercolor=GOLD_DIM, lightcolor=GOLD_DIM, darkcolor=GOLD_DIM, arrowcolor=GOLD)
        st.map("TCombobox", fieldbackground=[("readonly", "#111111")], foreground=[("readonly", FG)])

    def _load(self):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}

    def _save(self):
        data = {k: self.engine.params[k] for k, *_ in KNOBS + ADV_KNOBS}
        data.update(in_dev=self.in_var.get(), out_dev=self.out_var.get(), block=self.block_var.get(),
                    exclusive=self.mon_var.get(), lowcut=self.engine.params["lowcut"],
                    comp=self.engine.params["comp"], gate=self.engine.params["gate"],
                    mode=self.mode)
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass

    def _build_ui(self):
        tk.Label(self, text="TheTomStock_Reverb", bg=BG, fg=FG, font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, sticky="w", padx=16, pady=(14, 0))
        head = tk.Frame(self, bg=BG)
        head.grid(row=1, column=0, sticky="we", padx=16)
        tk.Label(head, text="Dra knappene opp og ned for å endre. Dobbeltklikk på en knapp for å nullstille.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        sw = tk.Frame(head, bg=BG)
        sw.pack(side="right")
        tk.Label(sw, text="Visning", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self.mode = self.saved.get("mode", "enkel")
        if self.mode not in ("enkel", "avansert"):
            self.mode = "enkel"
        self.mode_btns = {}
        for m, text in (("enkel", "Enkel"), ("avansert", "Avansert")):
            btn = tk.Button(sw, text=text, width=9, relief="flat", bg="#050505", highlightthickness=2, bd=0,
                            activebackground="#1a0000", cursor="hand2", command=lambda m=m: self._set_mode(m))
            btn.pack(side="left", padx=2)
            self.mode_btns[m] = btn

        self.block_var = tk.IntVar(value=max(64, self.saved.get("block", 128)))
        self.mon_var = tk.BooleanVar(value=self.saved.get("exclusive", False))
        box = RoundBox(self)
        box.grid(row=2, column=0, padx=16, pady=12)
        inner = box.inner
        self.row0 = tk.Frame(inner, bg=PANEL)
        self.row0.grid(row=0, column=0)
        self.adv_frame = tk.Frame(inner, bg=PANEL)
        self.adv_frame.grid(row=1, column=0, sticky="we")
        tk.Frame(self.adv_frame, bg=GOLD_DIM, height=1).pack(fill="x", padx=14, pady=(2, 4))
        tk.Label(self.adv_frame, text="AVANSERT  ·  finjustering", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 7, "bold")).pack()
        self.row1 = tk.Frame(self.adv_frame, bg=PANEL)
        self.row1.pack()

        perf = tk.Frame(self.adv_frame, bg=PANEL)
        perf.pack(fill="x", padx=18, pady=(2, 10))
        line = tk.Frame(perf, bg=PANEL)
        line.pack(anchor="w")
        tk.Label(line, text="Forsinkelse", bg=PANEL, fg=MUTED).pack(side="left", padx=(0, 6))
        for text, b in (("Minst", 64), ("Lav", 128), ("Middels", 256), ("Mest", 512)):
            tk.Radiobutton(line, text=text, value=b, variable=self.block_var, bg=PANEL, fg=FG, selectcolor=BG,
                           activebackground=PANEL, activeforeground=FG, command=self._start).pack(side="left")
        tk.Label(line, text="  (knitrer lyden, velg en høyere)", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Checkbutton(perf, text="Ekstra rask modus (kan feile hvis et annet program bruker mikrofonen)",
                       variable=self.mon_var, bg=PANEL, fg=FG, selectcolor=BG, activebackground=PANEL,
                       activeforeground=FG, command=self._start).pack(anchor="w")

        self.knobs = {}
        legacy_gate = {0: -52.0, 1: -44.0, 2: -36.0}.get(self.saved.get("gate_level", 1), -44.0)
        for key, label, lo, hi, default, unit in KNOBS:
            val = self.saved.get(key, default)
            self.engine.update(key, val)
            self.knobs[key] = Knob(self.row0, label, lo, hi, default, unit,
                                   lambda v, key=key: self.engine.update(key, v), value=val, term=TERMS[key])
        for key, label, lo, hi, default, fmt in ADV_KNOBS:
            val = self.saved.get(key, legacy_gate if key == "gate_db" else default)
            self.engine.update(key, val)
            self.knobs[key] = Knob(self.row1, label, lo, hi, default, "",
                                   lambda v, key=key: self.engine.update(key, v), value=val, term=TERMS[key], fmt=fmt)
        # PÅ/AV rett under knappen den hører til
        self.toggles = [self._toggle_button(self.row1, key) for key in ("lowcut", "gate", "comp")]
        self._set_mode(self.mode)

        meters = tk.Frame(self, bg=BG)
        meters.grid(row=3, column=0, sticky="we", padx=16)
        self.meter_in = VUMeter(meters, "LYD INN")
        self.meter_in.pack(side="left")
        self.meter_out = VUMeter(meters, "LYD UT")
        self.meter_out.pack(side="right")

        dev = tk.Frame(self, bg=BG)
        dev.grid(row=4, column=0, sticky="we", padx=16, pady=(10, 0))
        self.ins, self.outs = list_devices()
        in_names = [n for _, n in self.ins]
        out_names = [n for _, n in self.outs]
        cable = self._cable(out_names)
        self.in_var = tk.StringVar(value=self.saved.get("in_dev") if self.saved.get("in_dev") in in_names
                                   else self._default(in_names, ("Mikrofon", "Microphone")))
        self.out_var = tk.StringVar(value=self.saved.get("out_dev") if self.saved.get("out_dev") in out_names
                                    else (cable or out_names[0]))
        self.in_cb = self._row(dev, 0, "Din mikrofon", self.in_var, in_names)
        self.out_cb = self._row(dev, 1, "Send lyden til", self.out_var, out_names)
        bottom = tk.Frame(self, bg=BG)
        bottom.grid(row=5, column=0, sticky="we", padx=16, pady=12)
        self.bypass_btn = tk.Button(bottom, text="Ekko: PÅ", width=12, bg="#050505", fg=HOT, relief="flat", highlightthickness=2, highlightbackground=ACCENT,
                                    activebackground="#1a0000", command=self._toggle_bypass)
        self.bypass_btn.pack(side="left")
        self.status = tk.Label(bottom, text="", bg=BG, fg=MUTED, anchor="w", justify="left")
        self.status.pack(side="left", padx=12)

        self.cable_box = tk.Frame(self, bg=BG)
        self.cable_box.grid(row=6, column=0, sticky="we", padx=16, pady=(0, 12))
        self.cable_msg = tk.Label(self.cable_box, bg=BG, font=("Segoe UI", 9), justify="left", anchor="w",
                                  wraplength=520)
        self.cable_msg.pack(side="top", anchor="w")
        self.cable_btns = tk.Frame(self.cable_box, bg=BG)
        self.cable_btns.pack(side="top", anchor="w", pady=(4, 0))
        tk.Button(self.cable_btns, text="Last ned VB-Cable", bg="#050505", fg=HOT, relief="flat", highlightthickness=2,
                  highlightbackground=ACCENT,
                  command=lambda: webbrowser.open(CABLE_URL)).pack(side="left")
        tk.Button(self.cable_btns, text="Sjekk på nytt", bg="#050505", fg=FG, relief="flat", highlightthickness=2,
                  highlightbackground=GOLD_DIM,
                  command=self._refresh_devices).pack(side="left", padx=8)
        link = tk.Label(self.cable_box, text="Last ned VB-Cable (gratis): vb-audio.com/Cable", bg=BG, fg=GOLD,
                        font=("Segoe UI", 9, "underline"), cursor="hand2")
        link.pack(side="top", anchor="w", pady=(6, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(CABLE_URL))
        self._update_cable_notice(cable)
        self.help_btn = tk.Button(self, text="?  Hjelp", bg="#050505", fg=GOLD, relief="flat", highlightthickness=2,
                                  highlightbackground=GOLD_DIM, activebackground="#1a1608", activeforeground=GOLD,
                                  cursor="hand2", command=self._help)
        self.help_btn.place(relx=1.0, rely=1.0, anchor="se", x=-18, y=-16)

    def _help(self):
        if getattr(self, "_help_win", None) is not None and self._help_win.winfo_exists():
            self._help_win.lift()
            self._help_win.focus_force()
            return
        win = tk.Toplevel(self)
        self._help_win = win
        win.title("Hjelp - TheTomStock_Reverb")
        try:
            win.iconbitmap(resource_path("thetomstock_reverb.ico"))
        except tk.TclError:
            pass
        win.configure(bg=BG)
        win.geometry("600x640")
        win.minsize(420, 360)
        win.transient(self)
        self.after(60, lambda: self._dwm(win))
        box = tk.Frame(win, bg=BG)
        box.pack(fill="both", expand=True, padx=14, pady=14)
        sb = tk.Scrollbar(box, troughcolor=BG, bg=GOLD_DIM, activebackground=GOLD, relief="flat", width=12)
        txt = tk.Text(box, bg=PANEL, fg=FG, wrap="word", relief="flat", padx=16, pady=12, font=("Segoe UI", 10),
                      highlightthickness=1, highlightbackground=GOLD_DIM, yscrollcommand=sb.set, cursor="arrow",
                      spacing1=2, spacing3=4)
        sb.config(command=txt.yview)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.tag_config("h1", font=("Segoe UI", 15, "bold"), foreground=FG, spacing3=8)
        txt.tag_config("h2", font=("Segoe UI", 11, "bold"), foreground=GOLD, spacing1=12, spacing3=4)
        txt.tag_config("b", font=("Segoe UI", 10, "bold"), foreground=HOT)
        txt.tag_config("link", foreground=GOLD, underline=True)
        txt.tag_bind("link", "<Button-1>", lambda e: webbrowser.open(CABLE_URL))
        txt.tag_bind("link", "<Enter>", lambda e: txt.config(cursor="hand2"))
        txt.tag_bind("link", "<Leave>", lambda e: txt.config(cursor="arrow"))
        for chunk in HELP_TEXT:
            kind, body = chunk
            if kind == "link":
                txt.insert("end", body, "link")
            else:
                txt.insert("end", body, kind or ())
        txt.config(state="disabled")

    @staticmethod
    def _cable(out_names):
        return next((n for n in out_names if "CABLE Input" in n), None)

    def _update_cable_notice(self, cable):
        if cable:
            self.cable_msg.config(fg="#4cd964", text="Klar! I TikTok LIVE Studio velger du «CABLE Output» "
                                                     "som mikrofon.")
            self.cable_btns.pack_forget()
        else:
            self.cable_msg.config(fg="#ffb347", text="Du mangler et gratis hjelpeprogram (VB-Cable) som sender "
                                                     "lyden til TikTok. Last det ned og installer det, start PC-en "
                                                     "på nytt, og trykk så «Sjekk på nytt».")
            self.cable_btns.pack(side="top", anchor="w", pady=(4, 0))

    def _refresh_devices(self):
        self.engine.stop()
        sd._terminate()
        sd._initialize()
        self.ins, self.outs = list_devices()
        in_names = [n for _, n in self.ins]
        out_names = [n for _, n in self.outs]
        self.in_cb["values"], self.out_cb["values"] = in_names, out_names
        if self.in_var.get() not in in_names:
            self.in_var.set(self._default(in_names, ("Mikrofon", "Microphone")))
        cable = self._cable(out_names)
        if cable:
            self.out_var.set(cable)
        elif self.out_var.get() not in out_names:
            self.out_var.set(out_names[0])
        self._update_cable_notice(cable)
        self._start()

    @staticmethod
    def _default(names, hints):
        for n in names:
            if any(h.lower() in n.lower() for h in hints):
                return n
        return names[0]

    def _row(self, parent, r, text, var, names):
        tk.Label(parent, text=text, bg=BG, fg=MUTED).grid(row=r, column=0, sticky="w", pady=4)
        cb = ttk.Combobox(parent, textvariable=var, values=names, state="readonly", width=52)
        cb.grid(row=r, column=1, sticky="we", padx=(10, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._start())
        parent.columnconfigure(1, weight=1)
        return cb

    def _set_mode(self, mode):
        self.mode = mode
        for m, btn in self.mode_btns.items():
            on = m == mode
            btn.config(fg=HOT if on else MUTED, highlightbackground=ACCENT if on else GOLD_DIM)
        for knob in self.knobs.values():
            knob.grid_forget()
        advanced = mode == "avansert"
        main = [k for k, *_ in KNOBS if advanced or k in SIMPLE_KEYS]
        pad = 4 if advanced else 43
        for i, key in enumerate(main):
            self.knobs[key].grid(row=0, column=i, padx=pad, pady=6)
        for i, (key, *_) in enumerate(ADV_KNOBS):
            self.knobs[key].grid(row=0, column=i, padx=22, pady=(2, 0))
        for i, btn in enumerate(self.toggles):
            btn.grid(row=1, column=i, pady=(0, 8))
        if advanced:
            self.adv_frame.grid()
        else:
            self.adv_frame.grid_remove()

    def _toggle_button(self, parent, key):
        self.engine.params[key] = bool(self.saved.get(key, True))
        btn = tk.Button(parent, width=8, bg="#050505", relief="flat", highlightthickness=2,
                        activebackground="#1a0000", cursor="hand2")

        def refresh():
            on = self.engine.params[key]
            btn.config(text="PÅ" if on else "AV", fg=HOT if on else MUTED,
                       highlightbackground=ACCENT if on else GOLD_DIM)

        def toggle():
            self.engine.params[key] = not self.engine.params[key]
            refresh()

        btn.config(command=toggle)
        refresh()
        return btn

    def _toggle_bypass(self):
        on = self.engine.params["bypass"]
        self.engine.params["bypass"] = not on
        self.bypass_btn.config(text="Ekko: PÅ" if on else "Ekko: AV", fg=HOT if on else MUTED, highlightbackground=ACCENT if on else GOLD_DIM)

    def _start(self):
        in_dev = next(i for i, n in self.ins if n == self.in_var.get())
        out_dev = next(i for i, n in self.outs if n == self.out_var.get())
        self.engine.start(in_dev, out_dev, self.block_var.get(), self.mon_var.get())

    def _tick(self):
        if self._update_found and not self._update_shown:
            self._update_shown = True
            self._show_update()
        if self._poll_update():
            return
        pin, pout = self.engine.peak_in, self.engine.peak_out
        self.engine.peak_in = self.engine.peak_out = 0.0
        self.meter_in.feed(pin)
        self.meter_out.feed(pout)
        lat = self.engine.latency_ms()
        if self.engine.error:
            self.status.config(text="Kunne ikke starte lyden. Sjekk at riktig mikrofon er valgt, "
                               "eller velg høyere forsinkelse (i Avansert visning).", fg="#ff6b6b", wraplength=420)
        elif lat is not None:
            self.status.config(text=f"Alt kjører · forsinkelse ca. {lat:.0f} ms", fg=MUTED, wraplength=0)
        self.after(33, self._tick)

    def _close(self):
        self._save()
        self.engine.stop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
