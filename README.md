# TheTomStock_Reverb

Gi stemmen din reverb (romklang) i sanntid, for eksempel i TikTok LIVE Studio.
Mikrofonen går gjennom appen og ut til en virtuell lydkabel (VB-Cable), som TikTok bruker som mikrofon.

![ikon](thetomstock_reverb.ico)

## Funksjoner

- Reverb (Freeverb via Spotify `pedalboard`) med knapper for romstørrelse, demping, bredde, mengde og miks
- Lavkutt-filter (90 Hz), støyfilter (tre styrker) og kompressor, alle kan slås av og på
- Begrenser på den ferdige lyden, og jevn endring av knapper uten klikk
- Appen sjekker ved oppstart om det finnes en nyere versjon på GitHub (én vanlig forespørsel til api.github.com, ingenting sendes om deg). «Oppdater nå» laster ned den nye .exe-en, kontrollerer SHA-256-sjekksummen fra utgivelsen, bytter filen og starter på nytt
- **Enkel** visning med fire knapper, eller **Avansert** visning med alle knapper og en rad med finjustering (lavkutt-frekvens, støygrense, kompressorstyrke, lys/mørk klang og ekko-start)
- «Hør meg selv»: spill den ferdige lyden også i hodetelefonene dine mens den sendes til TikTok, med eget volum
- Valg av inngangskanal (kanal 1, kanal 2 eller begge) for lydkort med flere innganger
- Mykt støyfilter som fader jevnt inn og ut i stedet for å klippe lyden
- Retro VU-målere for inn- og utnivå, og en enkel hjelpeside i appen

- **Stream Deck**: skru på knappene, slå funksjoner av og på og lagre egne lydoppsett på tastene (se under)

## Stream Deck

Appen har en kontrollport som bare virker på din egen PC, og et plugin som bruker den. Du trenger Stream Deck-programmet fra Elgato (versjon 6.4 eller nyere). Alle modeller fungerer. På Stream Deck + kan dreieknappene styre knappene i appen direkte.

1. Last ned `com.thetomstock.reverb.streamDeckPlugin` fra **Releases** og dobbeltklikk på den.
2. Start TheTomStock_Reverb. Appen må være åpen for at tastene skal virke.
3. Finn kategorien **TheTomStock Reverb** til høyre i Stream Deck-programmet og dra handlinger inn på tastene:
   - **Knapp**: velg knapp, og om tasten skal skru opp, skru ned, sette en verdi eller nullstille. Hold tasten inne for å skru videre.
   - **Av/på**: ekko, hør meg selv, lavkutt, støyfilter eller kompressor. Tasten viser om funksjonen er på.
   - **Lydoppsett**: still inn lyden i appen og trykk «Bruk lyden som står i appen nå», så lagres den på tasten. Tasten lyser rødt når oppsettet er aktivt.

Vil du heller bruke en vanlig Stream Deck-handling («Nettsted» eller en HTTP-forespørsel) uten pluginet, kan du kalle adressene under. Appen bruker port 8765, eller den neste ledige opp til 8774 hvis 8765 er opptatt.

| Adresse | Gjør |
| --- | --- |
| `http://127.0.0.1:8765/state` | viser alle knapper og brytere |
| `/set?pct_wet=40&pct_room=80&echo=on` | setter flere knapper (0-100 % av skalaen) og brytere |
| `/step?knob=wet&steps=2` | skrur opp (negativt tall skrur ned), ett steg er 2 % |
| `/reset?knob=wet` | tilbake til standard (uten `knob` nullstilles alle) |
| `/toggle?name=echo` | bytter en bryter: `echo`, `monitor`, `lowcut`, `gate`, `comp` (legg til `&state=on` eller `off`) |
| `/mode?name=avansert` | bytter visning (`enkel` eller `avansert`) |

Knappene heter `in_gain`, `room`, `damping`, `wet`, `dry`, `width`, `out_gain`, `lc_freq`, `gate_db`, `comp_amt`, `tone`, `predelay` og `mon_vol`. Porten tar bare imot forespørsler fra programmer på PC-en din, ikke fra nettsider.

Pluginet ligger i `streamdeck/com.thetomstock.reverb.sdPlugin`. Det er skrevet i vanlig JavaScript uten byggetrinn, og Stream Deck-programmet har med det som trengs for å kjøre det.

## Slik bruker du den (for deg som bare vil prøve)

1. Gå til **Releases** her på GitHub og last ned `TheTomStock_Reverb.exe`. Du trenger ikke Python.
2. Installer **VB-Cable** (gratis): <https://vb-audio.com/Cable/>. Pakk ut filen, høyreklikk
   `VBCABLE_Setup_x64` og velg *Kjør som administrator*. Start PC-en på nytt.
3. Start `TheTomStock_Reverb.exe`. Velg mikrofonen din. «Send lyden til» skal stå på **CABLE Input**.
4. I TikTok LIVE Studio velger du **CABLE Output** som mikrofon.
5. Bruk hodetelefoner, så du slipper ekko fra høyttalerne.

Trykk **? Hjelp** i appen for en enkel forklaring av alle knappene.

Windows kan vise «Ukjent utgiver» første gang fordi appen ikke er signert. Trykk *Mer info* og *Kjør likevel*.

## Kjøre fra kildekoden (for utviklere)

Krever Python 3.12 på Windows.

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python thetomstock_reverb.py
```

## Bygge en egen .exe

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --icon thetomstock_reverb.ico --add-data "thetomstock_reverb.ico;." --name TheTomStock_Reverb thetomstock_reverb.py
```

Ferdig fil havner i `dist/`.

## Teknisk

- Lyd inn/ut: `sounddevice` (WASAPI). Reverb og begrenser: `pedalboard` (Freeverb).
- Gjeldende forsinkelse vises i appen. Små buffere gir lavere forsinkelse, men kan få lyden til å knitre.
- Kontrollport for Stream Deck: `control_server.py` (HTTP på 127.0.0.1). Kommandoene kjøres på appens hovedtråd.
- Appen inneholder ikke en virtuell lyddriver. Det trengs en, derfor VB-Cable.
