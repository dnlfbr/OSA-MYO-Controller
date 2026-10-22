# OSA MYO Controller web — kit di prova

Grazie per la prova! Questo kit contiene la **versione web** di OSA MYO Controller: legge un bracciale
**Myo** via Bluetooth dal browser, mostra i segnali (EMG, IMU, orientamento, gesti) e li manda in
**OSC** a Max, Pure Data, TouchDesigner ecc.

È una **prima versione mai provata con un Myo vero**: ci interessa soprattutto cosa non funziona.
Ci vogliono circa 30–45 minuti. Alla fine mandaci il file di log e il modulo `RAPPORTO.md`
compilato (vedi *Cosa mandarci*).

La versione del kit è scritta in `VERSIONE.txt`: citala nel rapporto.

---

## 1. Cosa serve

- Un computer **macOS** (11 o più recente, Apple Silicon o Intel) o **Windows 10/11**, con
  Bluetooth (va bene quello integrato). Usa la cartella del kit per il tuo sistema:
  `osa-myo-web-test-mac` o `osa-myo-web-test-windows`.
- **Google Chrome** o **Microsoft Edge** aggiornati. Safari e Firefox non hanno Web Bluetooth:
  non funzionano. Non serve installare altro.
- Un **Myo carico** (cavo micro‑USB). Se il Myo è collegato a un altro programma (il vecchio
  Myo Connect, l'app OSA MYO Controller per Mac, un telefono) chiudilo prima: un Myo collegato non si fa
  vedere da nessun altro.
- Per l'OSC: Max (c'è una patch pronta in `extra/`), oppure il **monitor OSC** compreso nell'app.

## 2. Avvio

Doppio clic su **`OSA-MYO-Controller-Web`** (`OSA-MYO-Controller-Web.app` su Mac, `OSA-MYO-Controller-Web.exe` su Windows).
Non si apre nessuna finestra sua: si apre **Chrome** sulla pagina **http://127.0.0.1:5180** e
l'OSC è già pronto. L'app resta attiva in sottofondo finché la pagina è aperta e **si chiude da
sola** pochi secondi dopo che chiudi la pagina. Per ricominciare, doppio clic di nuovo. Un
doppio clic mentre è già attiva apre solo un'altra pagina.

Se Chrome non si apre da solo, apri quell'indirizzo a mano in Chrome o Edge (entro 3 minuti,
poi l'app si chiude). Non aprire i file della cartella con il browser: la pagina funziona solo
da quell'indirizzo.

**macOS, la prima volta.** L'app non è firmata da Apple, quindi macOS la blocca:
1. doppio clic: compare *"Impossibile verificare che OSA-MYO-Controller-Web non contenga malware"* (o
   *"sviluppatore non identificato"*) → **Fine** (non *Sposta nel cestino*);
2. apri **Impostazioni di Sistema → Privacy e sicurezza**, scorri fino a *Sicurezza*: c'è
   *"OSA-MYO-Controller-Web è stato bloccato…"* → **Apri comunque** → conferma con la password;
3. doppio clic di nuovo → **Apri**. Dalle volte successive parte e basta.

Su macOS 14 o precedenti basta anche: clic destro sull'app → **Apri** → **Apri**. In alternativa,
dal Terminale: `xattr -dr com.apple.quarantine ` e trascina l'app nella finestra, poi Invio.

Al primo **CONNECT MYO**, macOS chiede il permesso Bluetooth **per Chrome**: consenti
(Impostazioni di Sistema → Privacy e sicurezza → Bluetooth → Chrome attivo).

**Windows, la prima volta.** SmartScreen dice *"Windows ha protetto il PC"* → **Ulteriori
informazioni** → **Esegui comunque**. Se l'antivirus mette l'exe in quarantena, ripristinalo e
scrivilo nel rapporto. Se Windows Firewall chiede l'accesso di rete per OSA-MYO-Controller-Web, puoi
consentire le reti private (serve solo per comandare il Myo da un altro computer) o annullare.

## 3. Prima prova senza bracciale: DEMO

Nella colonna di sinistra, **SIMULATOR → DEMO**. Parte un Myo simulato (in alto compare
`STATUS · SIMULATED`): tutti i pannelli si muovono. Serve a vedere che pagina e OSC funzionano
prima di usare il Myo vero. **TAP** simula un colpetto, **LINK LOSS** una perdita di segnale.
Premi di nuovo DEMO per fermarlo.

## 4. Collegare il Myo

1. Indossa il Myo sull'avambraccio, logo verso l'alto.
2. Sveglialo: staccalo dal cavo e muovilo, il logo si accende. Resta visibile per ~30 s; se
   torna a dormire, muovilo di nuovo. Se non si accende proprio, collegalo all'USB un attimo.
3. **CONNECT MYO**: Chrome apre una finestrina con i Myo vicini. Scegli il tuo → **Associa /
   Connetti**.
4. In pochi secondi lo stato diventa `STREAMING`: EMG e IMU si muovono, a sinistra **LINK** vicino
   al 100 %, `EMG HZ` ~200, `IMU HZ` ~50.
5. **Sincronizza**: fai il gesto *wave out* (mano aperta piegata verso l'esterno) e tienilo un
   attimo. `SYNC` si accende, `LOCK` diventa `UNLOCKED`, `ARM` mostra L o R. Da qui arrivano le pose.

Se Chrome non mostra nessun Myo: è addormentato o collegato altrove (punto 1 di *Cosa serve*).

## 5. L'OSC

1. Nella barra in alto spunta **SEND**: la spia accanto deve dire `OPEN`.
2. L'OSC esce su **127.0.0.1 porta 7400**, indirizzi `/myo/1/...` (gli stessi dell'app per Mac:
   `/emg/raw`, `/emg/rms`, `/quat`, `/euler`, `/accel`, `/gyro`, `/pose`, `/tap`, `/battery`…).
3. Per controllare senza Max: **OSC MONITOR** nella barra in alto apre una seconda pagina con ogni
   indirizzo ricevuto sulla 7400, messaggi al secondo e ultimi valori. Chiudi Max prima: una sola
   applicazione alla volta può ricevere sulla 7400 (il monitor lo dice, `PORT BUSY`). Chiusa la
   pagina del monitor, la porta torna libera per Max.
4. In Max: apri `extra/myo_receiver.maxpat` (il commento in alto parla di `osa-myo run`, l'app
   per Mac: con il kit web basta che la pagina sia aperta e SEND acceso). I messaggi in basso a
   destra si cliccano per comandare il Myo.
5. Max può comandare la pagina mandando OSC alla porta **7401**: `/myo/1/vibrate 1`, `/myo/1/zero`,
   `/myo/1/resync`, `/myo/1/lock`, `/myo/1/unlock`. Non tenere aperta allo stesso tempo l'app
   OSA MYO Controller per Mac: usa anche lei la porta 7401.

Per mandare l'OSC a un altro computer serve avviare l'app dal Terminale (o dal Prompt dei comandi)
con indirizzo e porta di destinazione:

- Mac: `OSA-MYO-Controller-Web.app/Contents/MacOS/OSA-MYO-Controller-Web --osc-host 192.168.1.20 --osc-port 9000`
- Windows: `OSA-MYO-Controller-Web.exe --osc-host 192.168.1.20 --osc-port 9000`

## 6. Cosa provare

Spunta nel `RAPPORTO.md` cosa funziona e scrivi cosa no. In ordine:

**Collegamento**
- CONNECT MYO trova il Myo, si collega, passa a `STREAMING`.
- Per 10 minuti: `EMG HZ` ~200, `IMU HZ` ~50, `DROP` resta 0 (o quasi), LINK vicino al 100 %.
- Allontanati finché il segnale cade: lo stato va in `RECONNECTING` e poi torna `STREAMING` da solo.
- DISCONNECT e di nuovo CONNECT MYO.

**Comandi (pannello CONTROLS)**
- VIBRATE `SHORT / MEDIUM / LONG`: il Myo vibra.
- `UNLOCK` / `LOCK`, `RE-SYNC` (breve vibrazione, SYNC si spegne, rifai *wave out*).
- MODES: `EMG smooth` (scala 0..1024, ~50 Hz), `EMG raw`, `IMU evt` (solo colpetti), `IMU all`.
- `NEVER SLEEP`: con il Myo fermo non si addormenta.
- `POWER OFF` (alla fine della prova!): chiede conferma, il logo si spegne, non si ricollega.
  Per riaccenderlo va collegato all'USB.

**Orientamento**
- VIEW `BEHIND`, punta il braccio verso lo schermo, **SET ORIGIN**: la mano del modello punta
  dentro lo schermo. Alza il braccio, giralo a destra e sinistra, ruota l'avambraccio: il modello
  segue nello stesso verso? Segnala qualunque movimento a specchio. Se la mano punta verso di te,
  prova **FLIP** e scrivi cosa dice il testo sotto il disegno (`band +x → wrist` o `→ elbow`).

**EMG**
- SCALE ±8 / ±16 a riposo, ±128 con il pugno chiuso. Annota i valori tipici.
- `AUTO`: ogni pod si adatta al suo segnale; con il pugno le scale si allargano, poi tornano.

**Pose e colpetti**
- Dopo la sincronizzazione: pugno (*fist*), *wave in*, *wave out*, mano aperta (*spread*),
  doppio tocco pollice‑medio (*double tap*). Il riquadro GESTURE e `/myo/1/pose` le riconoscono?
- `2× TAP → ORIGIN` acceso: il doppio tocco vibra una volta e azzera l'orientamento.
- Colpetti leggeri e forti sul bracciale: in EVENTS compaiono come `tap` con `strength_g`.
  Annota i valori tipici delle due serie.

**OSC**
- SEND acceso: OSC MONITOR o Max ricevono i messaggi `/myo/1/...`.
- Da Max, `/myo/1/vibrate 1` fa vibrare il Myo.

## 7. Cosa mandarci

1. **SAVE LOG** (in alto a destra): scarica un file `osa-myo-web-log-<data>.txt` con tutto
   quello che è successo, compreso il registro dell'app. Premilo alla fine della prova e
   **subito** quando succede qualcosa di strano (prima di chiudere la pagina).
2. **`RAPPORTO.md`** compilato (si apre con qualsiasi editor di testo).
3. **Screenshot** della pagina quando qualcosa non va (anche della console di Chrome:
   *Visualizza → Opzioni sviluppatore → Console* se ci sono righe rosse).
4. Se compare una finestra di errore dell'app: uno screenshot.

## 8. Problemi frequenti

| Problema | Cosa fare |
|---|---|
| macOS: *"non può essere aperta"* / *"malware"* | vedi *macOS, la prima volta* (sezione 2) |
| Windows: *"Windows ha protetto il PC"* | **Ulteriori informazioni** → **Esegui comunque** |
| *"Port 5180 is used by another program"* | un altro programma usa la porta: chiudilo e riprova |
| la pagina dice *"Impossibile raggiungere il sito"* | l'app si è chiusa (la pagina era stata chiusa): doppio clic di nuovo su OSA-MYO-Controller-Web |
| CONNECT MYO non fa nulla / *Web Bluetooth not available* | usa Chrome o Edge, indirizzo **127.0.0.1:5180** |
| la finestrina di Chrome è vuota | Myo addormentato o collegato ad altro: sveglialo, chiudi Myo Connect / l'app per Mac |
| macOS: niente Bluetooth | Impostazioni di Sistema → Privacy e sicurezza → Bluetooth → attiva Chrome, riavvia Chrome |
| SEND resta su `NO RELAY` | l'app si è chiusa o è bloccata: ricarica la pagina; se non va, doppio clic su OSA-MYO-Controller-Web |
| OSC MONITOR dice `PORT BUSY` | chiudi Max (o il programma che ascolta sulla 7400) e ricarica il monitor |
| `RSSI n/a` | normale: il browser non dà la potenza del segnale; LINK è la quota di pacchetti ricevuti |

Grazie! — Daniele Fabris e Simone Arganini · www.oscillacreations.com
