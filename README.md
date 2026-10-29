# TheTomStock_Reverb

Gi stemmen din reverb (romklang) i sanntid, for eksempel i TikTok LIVE Studio.
Mikrofonen går gjennom appen og ut til en virtuell lydkabel (VB-Cable), som TikTok bruker som mikrofon.

![ikon](thetomstock_reverb.ico)

## Funksjoner

- Reverb (Freeverb via Spotify `pedalboard`) med knapper for romstørrelse, demping, bredde, mengde og miks
- Lavkutt-filter (90 Hz), støyfilter (tre styrker) og kompressor, alle kan slås av og på
- Begrenser på den ferdige lyden, og jevn endring av knapper uten klikk
- Appen sjekker ved oppstart om det finnes en nyere versjon på GitHub (én vanlig forespørsel til api.github.com, ingenting sendes om deg). «Oppdater nå» laster ned den nye .exe-en, kontrollerer SHA-256-sjekksummen fra utgivelsen, bytter filen og starter på nytt
- Retro VU-målere for inn- og utnivå, og en enkel hjelpeside i appen

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
- Appen inneholder ikke en virtuell lyddriver. Det trengs en, derfor VB-Cable.
