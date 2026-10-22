# OSA MYO Controller: manuale d'uso

Di **Daniele Fabris** e **Simone Arganini**, 2026 · [www.oscillacreations.com](https://www.oscillacreations.com).
Progetto open source (licenza MIT), costruito anche sul lavoro di altri progetti open source:
li trovi nella finestra *About* dell'app (vedi *Barra in alto*) e con `osa-myo credits`.

OSA MYO Controller sostituisce Myo Connect sui Mac Apple Silicon. Fa tre cose:

1. **Si collega** a uno o più bracciali Myo, con il Bluetooth del Mac oppure con il dongle USB
   **BLED112** fornito con il Myo. Non serve Rosetta.
2. **Mostra** in tempo reale tutto quello che il bracciale misura, in una finestra simile a
   MyoDiagnostics: EMG degli 8 sensori, orientamento, accelerometro, giroscopio, gesti,
   batteria, segnale.
3. **Invia** tutti questi dati via **OSC** (UDP) a Max/MSP, Pure Data, SuperCollider,
   TouchDesigner o qualsiasi altro programma, e riceve comandi OSC (vibrazione, blocco,
   azzeramento dell'orientamento, nuovo sync, spegnimento…).

> Stato attuale: il collegamento con il Bluetooth del Mac è stato usato con bracciali veri.
> Le novità di questa versione (dongle BLED112, nuova vista 3D, scala EMG, `RE-SYNC`,
> `POWER OFF`, sblocco automatico dopo il sync, EMG smooth visibile, filtro dei tap, doppio
> tap → `SET ORIGIN`, nomi dei bracciali, finestre aggiuntive) sono state provate con
> bracciali e dongle **simulati** e con i test automatici, ma non ancora con l'hardware. La lista dei controlli
> da fare è in [hardware-tests.md](hardware-tests.md).

---

## 1. Installare e avviare

### Modo semplice: l'app (`OSA-MYO-Controller.dmg`)

Il file si trova in `dist/OSA-MYO-Controller.dmg` dentro la cartella del progetto.

1. Fai doppio clic su `OSA-MYO-Controller.dmg`. Si apre una finestra con `OSA MYO Controller.app` e un
   collegamento ad *Applicazioni*.
2. Trascina `OSA MYO Controller.app` su *Applicazioni*.
3. Apri *Applicazioni* e fai doppio clic su **OSA MYO Controller**.
4. Alla prima apertura macOS chiede il permesso di usare il **Bluetooth**. Clicca *Consenti*.

Se macOS dice che l'app "non può essere aperta perché lo sviluppatore non è verificato"
(succede se la copi su un altro Mac): clic destro sull'app → *Apri* → *Apri*. Oppure
*Impostazioni di Sistema → Privacy e sicurezza → Apri comunque*. L'app è firmata solo
localmente, non con un certificato Apple Developer.

All'avvio l'app apre il monitor e prova subito a collegarsi al primo Myo che trova.

### Bluetooth del Mac o dongle BLED112

L'app si collega in due modi. Si sceglie in *SETTINGS → CONNECTION → Bluetooth adapter*.

| Adattatore | Quando usarlo |
|---|---|
| **Built-in Bluetooth** (predefinito) | Il Bluetooth del Mac. Non c'è niente da collegare. |
| **BLED112 USB dongle** | La chiavetta USB blu fornita con il Myo. È una radio separata: non dipende dal Bluetooth di macOS e non chiede permessi. Utile se il Bluetooth del Mac dà problemi o se ci sono molti dispositivi Bluetooth intorno. Con una prolunga USB puoi anche avvicinarlo a chi suona. |
| **Simulated armbands** | Bracciali finti, per provare la catena OSC senza hardware. |

Per usare il dongle:

1. Inseriscilo in una porta USB del Mac (con un adattatore USB-C, se serve).
2. Apri *SETTINGS → CONNECTION* e scegli `BLED112 USB dongle` in *Bluetooth adapter*.
3. In *dongle port* lascia `auto-detect`. Sotto deve comparire
   `BLED112 detected on /dev/cu.usbmodem…`. Se non compare, premi `REFRESH`.
4. Premi `APPLY + SAVE`. Cambiare adattatore scollega tutti i bracciali: premi `CONNECT ALL`.

Un dongle regge fino a 3 bracciali insieme. Un dongle può essere usato da un solo programma
alla volta: chiudi il vecchio Myo Connect e le altre copie di OSA MYO Controller.

### Modo da terminale (per sviluppo e diagnosi)

Va usato **Terminal.app o iTerm**. Altri programmi (terminale di VS Code, l'app di Claude)
spesso non hanno il permesso Bluetooth e macOS chiude il processo senza messaggi.

```bash
cd OSA-MYO-Controller          # la cartella del progetto
source .venv/bin/activate
osa-myo run
```

I comandi principali:

| Comando | Cosa fa |
|---|---|
| `osa-myo scan` | cerca i Myo vicini e mostra nome, segnale (RSSI) e indirizzo |
| `osa-myo run` | apre il monitor, collega i bracciali e invia OSC |
| `osa-myo run --no-gui` | solo OSC, senza finestra (più leggero per i concerti) |
| `osa-myo run -n 2` | due bracciali: `/myo/1` e `/myo/2` |
| `osa-myo run --mock -n 2` | due bracciali **finti**, per provare senza hardware |
| `osa-myo run --transport bled112` | usa il dongle invece del Bluetooth del Mac |
| `osa-myo scan --transport bled112` | cerca i Myo con il dongle |
| `osa-myo ports` | elenca le porte seriali e indica quella del dongle |
| `osa-myo monitor` | apre la finestra senza collegarsi: usi tu SCAN e CONNECT |
| `osa-myo dump` | stampa i dati grezzi nel terminale (per diagnosi) |
| `osa-myo config-show` | mostra la configurazione in uso |
| `osa-myo credits` | autori, contatto e crediti open source |

Senza `--transport` i comandi usano l'adattatore scelto nelle impostazioni. Con `--port`
indichi una porta precisa del dongle, ad esempio `--port /dev/cu.usbmodem11`.

Per ricompilare l'app e il DMG dopo una modifica al codice:

```bash
sh packaging/build_app.sh
```

### Modo browser: la versione web (prima versione)

Nella cartella `web/` c'è OSA MYO Controller come pagina web: stesso protocollo, stessi indirizzi OSC,
monitor con la stessa grafica, ma **un solo bracciale** alla volta. Si collega con il
Bluetooth del computer tramite **Web Bluetooth**, quindi funziona in **Chrome o Edge** (Mac,
Windows, Linux, Android). Firefox, Safari e i browser di iPhone/iPad non lo supportano.

```bash
cd web
npm install          # solo la prima volta (serve Node.js 18 o più recente)
npm run dev          # poi apri http://localhost:5173 in Chrome
```

- La pagina ha la stessa disposizione dell'app: barra in alto (relay OSC, `SEND`, `SAVE LOG`),
  colonna a sinistra con il bracciale, il simulatore, batteria e collegamento, la striscia di
  stato e i pannelli Controls, Orientation, IMU, Gesture, EMG, Events.
- `CONNECT MYO` apre la finestra di Chrome con i Myo vicini: scegli il bracciale e conferma.
  La prima volta macOS chiede il permesso Bluetooth per Chrome.
- `DEMO` collega un bracciale **simulato** (c'è la scritta `SIMULATED`): serve per provare la
  pagina senza hardware.
- **OSC:** il browser non può inviare UDP. Apri un secondo terminale e avvia il relay:
  `cd web && npm run relay`. Poi premi `SEND` nella pagina (la spia diventa `OPEN`). L'OSC
  esce su `127.0.0.1:7400` e i comandi in ingresso arrivano su `7401`, come con l'app. Non
  usare insieme il relay e l'app per Mac: si contendono la porta 7401.
- `SAVE LOG` scarica un file di testo con versione, impostazioni ed eventi: è quello da
  allegare quando si segnala un problema.
- Rispetto all'app mancano: più bracciali insieme, il segnale RSSI (`LINK` mostra la quota di
  pacchetti ricevuti), il dongle BLED112, il file `config.toml` (le impostazioni restano nel
  browser).
- Stato: provata con il bracciale simulato e con i test automatici, **non ancora con un Myo
  vero**.

**Kit di prova da mandare a chi testa.** `cd web && npm run kit` (serve Deno 2:
`brew install deno`) crea un kit per sistema, con lo zip:
`dist/osa-myo-web-test-mac` con **`OSA-MYO-Controller-Web.app`** (Apple Silicon e Intel) e
`dist/osa-myo-web-test-windows` con **`OSA-MYO-Controller-Web.exe`**, più la guida `GUIDA.md`, il modulo
`RAPPORTO.md`, la patch Max e `VERSIONE.txt` (il commit da cui è stato fatto, `-dirty` se c'erano
modifiche non salvate in git).

- Chi prova non installa nulla oltre a Chrome o Edge: doppio clic sull'app, si apre Chrome sulla
  pagina con l'OSC già pronto. L'app non ha finestre e **si chiude da sola** pochi secondi dopo
  che si chiude la pagina.
- Nella pagina compare **OSC MONITOR**: una seconda pagina che mostra l'OSC in arrivo sulla 7400,
  senza Max (Max va chiuso mentre è aperta).
- Le app non sono firmate da Apple né da Microsoft: al primo avvio vanno sbloccate una volta
  (su macOS 15: Impostazioni di Sistema → Privacy e sicurezza → *Apri comunque*). La guida lo
  spiega passo per passo.
- Chi prova rimanda il file di `SAVE LOG` (contiene anche il registro dell'app) e il rapporto.

Dettagli (opzioni del relay, pubblicazione su un sito HTTPS): [web/README.md](../web/README.md).

---

## 2. Preparare il bracciale

Il Myo è visibile via Bluetooth solo quando è **sveglio**.

1. Caricalo con il cavo USB. Il logo lampeggia durante la carica.
2. Staccalo e muovilo o dagli un colpetto: il logo si accende di blu. Ora è visibile per
   circa 30 secondi.
3. Indossalo sull'avambraccio, nella parte più larga, con il logo sopra. Deve essere aderente.
   Il verso (logo verso il polso o verso il gomito) non importa: il bracciale lo rileva al
   sync.
4. Chiudi altre app che lo usano (vecchio Myo Connect, telefono). Un Myo già collegato a
   qualcos'altro non si vede.

### La sincronizzazione (sync)

Appena collegato, il bracciale invia subito EMG e movimento. Però **non riconosce i gesti**
finché non fai il gesto di sincronizzazione:

- tieni il bracciale addosso qualche minuto prima del sync: i sensori riconoscono meglio i
  gesti quando si sono scaldati sulla pelle;
- piega il polso verso l'esterno (*wave out*, lontano dal corpo), senza forzare, e tieni la
  posizione;
- quando il sync riesce il bracciale vibra e nel monitor compare `SYNCED`, con `L` o `R`
  (braccio sinistro o destro).

Dopo il sync l'app **sblocca** il bracciale da sola (lo fa anche a ogni collegamento). Così
ogni gesto viene riconosciuto e inviato via OSC, senza il doppio tocco di sblocco che serviva
con Myo Connect.

Se il sync non riesce, nel registro Events compare `sync_failed` con `failed_too_hard`: il
gesto era troppo forte. Rilassa la mano e riprova con un movimento più morbido.

Se nel registro, alla riga del sync, compare `cold`, il bracciale è ancora freddo: i gesti
diventano affidabili quando compare `warmup_completed`.

Se togli il bracciale, la sincronizzazione si perde.

### Rifare il sync (`RE-SYNC`)

Se i gesti vengono riconosciuti male, o dopo aver spostato il bracciale sul braccio, premi
`RE-SYNC` nei Controls (o invia `/myo/1/resync`). Il bracciale dimentica il sync, vibra
brevemente e aspetta un nuovo gesto di sync. EMG e movimento continuano ad arrivare.

### Spegnere il bracciale (`POWER OFF`)

`POWER OFF`, nell'ultima riga del pannello Controls, spegne il bracciale selezionato (sospensione
profonda). Prima chiede conferma. Il bracciale **si riaccende solo collegandolo al cavo
USB**, e l'app non prova a ricollegarlo. Usalo a fine giornata per non scaricare la batteria.

---

## 3. La finestra del monitor

![monitor](images/monitor.png)

La finestra si apre già della misura dello schermo e tutto sta dentro senza scorrere: a
sinistra la colonna dei bracciali con Battery e Link, poi Controls e Orientation, al centro
IMU e Gesture, a destra EMG ed Events. Se allarghi la finestra i grafici si ingrandiscono.
Per guardare più bracciali insieme apri altre finestre con `NEW WINDOW` (vedi sotto).

### Barra in alto

- **OSA MYO Controller** (la scritta a sinistra): un clic apre *About*, con versione, autori,
  contatto e i progetti e le librerie open source su cui si basa OSA MYO Controller. La stessa
  finestra è nel menu *OSA MYO Controller → About OSA MYO Controller*.
- **OSC OUT**: indirizzo e porta di destinazione (di solito `127.0.0.1` e `7400`). Cambiali e
  premi `APPLY`.
- **SEND**: accende o spegne l'invio OSC.
- Accanto, in grigio: adattatore (Bluetooth del Mac, dongle o simulato), preset, modo e porta
  di controllo in ingresso.
- **NEW WINDOW**: apre una finestra in più per un altro bracciale (vedi *Più bracciali sullo
  schermo*).
- **SETTINGS**: tutte le impostazioni (vedi sezione 6).
- **SAVE CONFIG**: salva le impostazioni attuali per la prossima volta, compresi la vista 3D,
  la scala EMG, i nomi dei bracciali e il doppio tap.

Se la finestra è stretta la scritta grigia viene tagliata: passaci sopra col mouse per
leggerla tutta.

### Colonna a sinistra: ARMBANDS e NEARBY

- Una scheda per ogni bracciale (`#1`, `#2`…). Il pallino è **verde** (con alone) quando
  trasmette, ciano quando è collegato, ambra quando si sta collegando, rame quando sta
  ricollegando, grigio scuro quando è scollegato. Mostra anche batteria e segnale. La scheda
  selezionata ha il bordo ciano.
- **Clic su una riga**: tutto il monitor passa a quel bracciale.
- **Doppio clic su una riga**: dai un nome al bracciale (vedi *Nomi dei bracciali*).
- **Clic destro su una riga**: `Rename…` (nome) e `Open in a new window` (finestra in più).
- **CONNECT ALL / DISCONNECT**: collega o scollega tutti.
- **SCAN**: elenca i Myo vicini con l'adattatore scelto. **Doppio clic** su uno per
  assegnarlo al bracciale selezionato.

### Intestazione

`STATUS` (scollegato, in connessione, streaming, in riconnessione), `SYNC`, `LOCK`, braccio
`L`/`R` con direzione del logo, nome, numero di serie, firmware. Passando col mouse sul nome
vedi anche il nome Bluetooth e l'indirizzo del bracciale.

### Battery e Link (in fondo alla colonna di sinistra)

- **BATTERY**: percentuale, barra e ora dell'ultima lettura. Sotto il 20 % la barra diventa rossa.
- **LINK**: qualità del segnale Bluetooth con lo storico dell'ultimo minuto.
- Sotto, i numeri di controllo: `EMG Hz` (deve stare a circa 200), `IMU Hz` (circa 50),
  `DROP` (campioni EMG persi, deve restare a 0), `LAT ms` (ritardo tra arrivo del dato e
  invio OSC), `OSC` (messaggi inviati).

### Controls (comandi manuali)

| Pulsante | Effetto |
|---|---|
| `CONNECT` / `DISCONNECT` | collega o scollega solo questo bracciale |
| `POWER OFF` | spegne il bracciale; si riaccende solo con il cavo USB (vedi sezione 2) |
| `RE-SYNC` | fa dimenticare il sync al bracciale: rifai il gesto di sync |
| `UNLOCK` / `LOCK` | sblocca o blocca il riconoscimento dei gesti (l'app sblocca da sola dopo ogni sync) |
| `SHORT` / `MEDIUM` / `LONG` | fa vibrare il bracciale |
| `SET ORIGIN` | azzera l'orientamento: la direzione attuale diventa "avanti" (servono dati IMU: con `IMU evt` o `off` non fa nulla e lo dice nella barra in basso) |
| `CLEAR` | toglie l'azzeramento |
| `MODES` | tre menu sulla stessa riga (cosa fa ogni voce: vedi *Le modalità EMG e IMU*, oppure passa col mouse sulla voce): |
| · `EMG …` | `EMG raw` (grezzo, 200 Hz), `EMG filt.` (più pulito), `EMG smooth` (inviluppo a 50 Hz, non documentato), `EMG off` |
| · `IMU …` | `IMU all` (movimento + tap), `IMU data` (solo movimento), `IMU evt` (solo tap, niente movimento), `IMU raw`, `IMU off` |
| · `POSE …` | `POSE on` per riconoscere i gesti, `POSE off` per non riconoscerli |
| `NEVER SLEEP` | impedisce al bracciale di addormentarsi durante l'uso |

### Orientation

Un avambraccio con la mano e il bracciale, che si muove come il tuo braccio. Il pod color
**rame** è quello con il logo. Sotto il disegno, una riga dice in che verso è indossato il
bracciale (lo rileva il sync) e se manca ancora `SET ORIGIN`. Più in basso trovi `ROLL`
(rotazione dell'avambraccio su se stesso), `PITCH` (braccio su e giù), `YAW` (direzione
sinistra/destra) in gradi, e il quaternione `x y z w`.

Per allinearlo al braccio:

1. fai il sync, così l'app sa se il logo guarda il polso o il gomito;
2. punta il braccio verso lo schermo e premi `SET ORIGIN`;
3. ora il modello punta dentro lo schermo e segue il braccio, visto da sopra la tua spalla.

Il menu **VIEW** cambia il punto di vista:

| Vista | Come lo vedi |
|---|---|
| `BEHIND` (predefinita) | da sopra la spalla: il braccio punta dentro lo schermo |
| `SIDE` | di lato, da destra: alzando il braccio si alza il modello |
| `TOP` | dall'alto: il braccio punta verso l'alto dello schermo |
| `MIRROR` | di fronte, come in uno specchio |

**FLIP** scambia mano e gomito nel disegno. Serve solo se il modello punta al contrario,
ad esempio quando il sync non ha detto in che verso è indossato il bracciale.

### IMU

Tre grafici che scorrono: `GYRO` giroscopio (velocità di rotazione), `ACCEL` accelerometro
(in g; da fermo vedi circa 1 g, cioè la gravità) e `QUAT` quaternione. Colori degli assi:
x rame, y ambra, z ciano, w grigio chiaro.

Se la modalità IMU non manda dati di movimento (`IMU evt` o `IMU off`), IMU e Orientation
restano fermi e un riquadro al centro spiega perché. Lo stesso vale per l'EMG.

### EMG

Gli 8 sensori muscolari (`POD 0`…`POD 7`), valori da −128 a 127. A riposo il segnale grezzo
resta entro pochi punti; con il pugno stretto può arrivare vicino al massimo. Dipende molto
dalla persona, dalla posizione e da quanto è stretto il bracciale.

| Comando | Effetto |
|---|---|
| primo menu (`2 s`) | quanti secondi mostrare (da 0.5 a 10) |
| secondo menu (`±64`) | ampiezza uguale per tutti i pod, da ±2 a ±128. Per vedere il segnale a riposo usa ±8 o ±16 |
| `AUTO` | ogni pod si adatta da solo al proprio segnale: si allarga subito quando il segnale cresce e si stringe piano quando cala. L'etichetta `POD n ±x` mostra la scala del momento |
| `PAUSE` | ferma l'immagine (l'invio OSC continua) |

Con `EMG smooth` i grafici mostrano l'inviluppo calcolato dal bracciale: valori da 0 a circa
1024, 50 al secondo, sempre positivi. Il secondo menu passa allora a una scala da 16 a 2048
(predefinita 1024).

### Gesture

I pittogrammi dei 5 gesti riconosciuti dal Myo: `fist` (pugno), `wave_in` (polso verso
l'interno), `wave_out` (polso verso l'esterno), `fingers_spread` (dita aperte),
`double_tap` (due colpetti di pollice e medio). Il gesto attuale si illumina in ciano ed
è scritto in grande sotto `CURRENT POSE`. Le barre color rame mostrano l'attività di ogni
sensore (`RMS`, oppure l'inviluppo con `EMG smooth`: lo dice la scritta sopra le barre).

Il pulsante **`2× TAP → ORIGIN`** in alto fa sì che il gesto `double_tap` di questo
bracciale faccia `SET ORIGIN` (vedi *Doppio tap = SET ORIGIN*).

### Events

Il registro di tutto quello che succede, con l'ora (ora in grigio, bracciale in rame, tipo
di evento in ciano, errori in rosso): collegamenti, sync (con braccio, verso e
riscaldamento), gesti, batteria, azzeramenti, errori. Qui compaiono anche gli avvisi sul file
di configurazione (vedi sezione 6).

Ogni `tap` riporta la sua forza (`strength_g`); i tap scartati dal filtro sono in grigio, con
il motivo (`ignored`). Ogni azzeramento (`zero`) dice chi l'ha chiesto quando non è stato il
pulsante: `"by": "double tap"` oppure `"by": "OSC"`.

Chiudendo la finestra l'app scollega i bracciali e li rimette in modalità di sospensione
normale, così non si scaricano.

### Nomi dei bracciali

Il Mac non può cambiare il nome scritto dentro il bracciale, quindi il nome si dà nel
monitor: **doppio clic** sulla riga del bracciale nella colonna a sinistra (oppure clic
destro → `Rename…`, oppure *SETTINGS → DEVICES → NAME*). Al massimo 32 caratteri; lascialo
vuoto per tornare al nome Bluetooth. Il nome compare nella colonna a sinistra,
nell'intestazione e nelle finestre in più. Premi `SAVE CONFIG` per tenerlo. Gli indirizzi OSC
non cambiano: usano sempre il numero (`/myo/1`, `/myo/2`…).

### Più bracciali sullo schermo (`NEW WINDOW`)

`NEW WINDOW` nella barra in alto (oppure clic destro su un bracciale → `Open in a new
window`) apre una finestra per un bracciale: una riga di stato (braccio, batteria, segnale,
frequenze EMG e IMU), il pulsante `SET ORIGIN`, Orientation, Gesture ed EMG. Il menu in alto a
sinistra cambia bracciale. Puoi aprirne quante vuoi; due stanno affiancate su uno schermo da
1440 pixel. Si chiudono insieme alla finestra principale.

### Le modalità EMG e IMU

Ogni bracciale manda solo quello che chiedono le sue tre modalità (`MODES` in Controls).

| Modalità | Cosa manda il bracciale | Cosa vedi | OSC |
|---|---|---|---|
| `EMG raw` | 8 sensori, 200 campioni al secondo, grezzi | grafici EMG ±64, barre RMS | `/emg/raw`, `/emg/rms`, `/emg/mav` |
| `EMG filt.` | come raw, ma filtrati dal bracciale | come raw | come raw |
| `EMG smooth` | l'inviluppo (intensità) di ogni sensore calcolato dal bracciale, 50 al secondo, 0…1024 circa. Modalità non documentata | grafici EMG 0…1024, barre dall'inviluppo | `/emg/smooth` |
| `EMG off` | niente | EMG vuoto, con un avviso | niente |
| `IMU all` | movimento (orientamento, accelerazione, rotazione, 50 al secondo) **e** tap | tutto | `/quat`, `/euler`, `/accel`, `/gyro`, `/tap` |
| `IMU data` | solo movimento | IMU, Orientation | come all, senza `/tap` |
| `IMU evt` | **solo i tap**, nessun dato di movimento | IMU e Orientation fermi, con un avviso; i tap in Events | `/tap` |
| `IMU raw` | non documentata, trattata come `data` | | |
| `IMU off` | niente, neanche i tap | IMU e Orientation fermi, con un avviso | niente |
| `POSE on` / `off` | sync, gesti, blocco | Gesture, intestazione | `/pose`, `/sync`, `/arm`… |

`EMG smooth` è la modalità più leggera per il Bluetooth (8 valori 50 volte al secondo invece
di 200) e dà già l'intensità del muscolo: comoda per controllare parametri, ma senza il
segnale grezzo. Non è documentata da Thalmic: se un bracciale non la manda, dopo 2 secondi il
pannello EMG lo dice; in quel caso usa `EMG filt.` o `EMG raw`.

Se usavi già OSA MYO Controller, il tuo file di configurazione ha il flusso `fv` (cioè
`/emg/smooth`) spento: accendilo in *SETTINGS → STREAMS*. Quando serve, un avviso in Events
te lo ricorda.

### I tap e la soglia

Un **tap** è un colpetto sul bracciale (o un colpo secco del braccio) che il bracciale
riconosce da solo con l'accelerometro. Ha una direzione e un numero (1 o 2 colpi) e arriva
solo con `IMU evt` o `IMU all`. Non è il gesto `double_tap` di Gesture: quello lo riconosce il
classificatore dai muscoli (pollice e medio battuti due volte).

Il rilevatore del bracciale non si può regolare e scatta facilmente, quindi OSA MYO Controller ha un
filtro in *SETTINGS → PROCESSING*:

- **tap threshold** (in g): scarta i tap più deboli della soglia. La forza è il salto più
  grande dell'accelerazione intorno al tap, misurato dai dati di movimento: serve
  `IMU all`. Con `IMU evt` non ci sono dati di movimento e tutti i tap passano. Per trovare la
  soglia: guarda in Events la `strength_g` dei tap che vuoi tenere e di quelli che vuoi
  scartare, e scegli un valore in mezzo. `off` = nessuna soglia.
- **tap cooldown** (in ms): scarta i tap che arrivano troppo vicini al precedente. `off` =
  nessun limite.

I tap scartati non partono via OSC e restano in Events, in grigio, con il motivo. Con la
soglia attiva un tap parte 60 ms dopo, il tempo di misurarne la forza.

### Doppio tap = SET ORIGIN

Con **`2× TAP → ORIGIN`** acceso (pannello Gesture, oppure *SETTINGS → DEVICES → 2× TAP =
ORIGIN*), il gesto `double_tap` fa `SET ORIGIN` per quel bracciale, che vibra una volta per
confermare. Così chi suona può riallineare lo yaw senza toccare il computer.

Serve: `POSE on`, bracciale sincronizzato e sbloccato, e dati di movimento (`IMU data` o
`IMU all`). Ogni gesto vale una volta sola: le ripetizioni entro un secondo vengono ignorate.
In Events compare un `zero` con `"by": "double tap"`. È spento di default; `SAVE CONFIG` lo
ricorda per ogni bracciale.

Senza dati di movimento recenti (`IMU evt` o `off`, oppure flusso interrotto) l'origine resta
com'era, il bracciale non vibra e in Events compare l'avviso `double tap: no IMU data, origin
not set`. Vale anche per il pulsante `SET ORIGIN` (avviso nella barra in basso) e per
`/myo/<id>/zero`: un orientamento vecchio darebbe un'origine sbagliata.

---

## 4. I dati OSC in uscita

Destinazione predefinita: `127.0.0.1`, porta `7400`. `<id>` è il numero del bracciale
(1, 2…).

| Indirizzo | Valori | Significato | Frequenza |
|---|---|---|---|
| `/myo/<id>/emg/raw` | 8 interi, −128…127 | EMG grezzo degli 8 sensori | 200 al secondo |
| `/myo/<id>/emg/norm` | 8 decimali, −1…1 | EMG diviso per 128 (spento di default) | 200 al secondo |
| `/myo/<id>/emg/rms` | 8 decimali, 0…1 | intensità di ogni muscolo (media su 50 ms) | 50 al secondo |
| `/myo/<id>/emg/mav` | 1 decimale, 0…1 | attività muscolare complessiva | 50 al secondo |
| `/myo/<id>/emg/smooth` | 8 interi, 0…1024 circa | inviluppo calcolato dal bracciale, solo con `EMG smooth` | 50 al secondo |
| `/myo/<id>/quat` | w x y z | orientamento (quaternione), con azzeramento | 50 al secondo |
| `/myo/<id>/euler` | roll pitch yaw | orientamento in radianti | 50 al secondo |
| `/myo/<id>/euler/deg` | roll pitch yaw | in gradi (spento di default) | 50 al secondo |
| `/myo/<id>/accel` | x y z | accelerazione in g | 50 al secondo |
| `/myo/<id>/gyro` | x y z | rotazione in gradi al secondo | 50 al secondo |
| `/myo/<id>/pose` | testo | `rest fist wave_in wave_out fingers_spread double_tap` | quando cambia |
| `/myo/<id>/pose/id` | intero | 0 riposo, 1 pugno, 2 wave_in, 3 wave_out, 4 dita aperte, 5 double_tap | quando cambia |
| `/myo/<id>/sync` | 0/1 | sincronizzato | quando cambia |
| `/myo/<id>/lock` | 0/1 | bloccato | quando cambia |
| `/myo/<id>/arm` | testo | `left`, `right`, `unknown` | quando cambia |
| `/myo/<id>/battery` | intero | batteria in % | quando cambia |
| `/myo/<id>/status` | testo | stato della connessione | quando cambia |
| `/myo/<id>/tap` | 2 interi | colpetto: direzione, numero; solo con `IMU evt` o `all`, dopo il filtro dei tap | a ogni tap |

Cose da sapere:

- **Lo yaw deriva.** Il Myo non ha bussola, quindi la direzione orizzontale si sposta piano
  nel tempo e all'accensione è casuale. Prima di ogni brano premi `SET ORIGIN` o invia
  `/myo/1/zero`. Roll e pitch invece sono stabili.
- **L'EMG arriva a pacchetti** di 4 campioni ogni 20 ms. Per la latenza minima imposta
  "EMG samples per bundle" a 1 nelle impostazioni.
- Ogni flusso si può spegnere in *SETTINGS → STREAMS* per alleggerire la rete.
- Esiste un preset **myomapper** con gli stessi indirizzi del vecchio MyoMapper
  (`/myo1/orientation/quaternion`…), utile per vecchie patch.

L'elenco completo, con tutte le scale, è nel [README](../README.md).

---

## 5. Comandi OSC in ingresso

L'app ascolta sulla porta `7401`. Al posto di `<id>` puoi scrivere `all` per tutti i
bracciali.

| Messaggio | Effetto |
|---|---|
| `/myo/1/vibrate 1` (o 2, 3) | vibrazione corta, media, lunga |
| `/myo/1/zero` | azzera l'orientamento (come SET ORIGIN; servono dati IMU recenti) |
| `/myo/1/zero/clear` | toglie l'azzeramento |
| `/myo/1/lock` / `/myo/1/unlock` | blocca o sblocca i gesti |
| `/myo/1/resync` | rifà il sync (come RE-SYNC): poi serve il gesto di sync |
| `/myo/1/poweroff 1` | spegne il bracciale (come POWER OFF). Senza l'argomento `1` viene ignorato, così un messaggio sbagliato non spegne niente |
| `/myo/1/mode 3 3 1` | modalità EMG, IMU, classificatore |
| `/myo/1/sleep 1` | non addormentarti (0 = normale) |
| `/myo/1/led 0 255 255` | colore del logo |
| `/myo/all/vibrate 2` | fa vibrare tutti i bracciali |

---

## 6. Impostazioni (SETTINGS)

- **CONNECTION**: l'adattatore (*Built-in Bluetooth*, *BLED112 USB dongle*, *Simulated
  armbands*), la porta del dongle (`auto-detect` o una porta precisa, con `REFRESH` per
  rileggere l'elenco) e quanti secondi dura una ricerca (*scan timeout*). Vedi sezione 1.
- **OSC**: indirizzo e porta di destinazione, preset (`default` o `myomapper`), modalità
  (`vector` = un messaggio per tipo di dato; `axis` = un messaggio per ogni canale, ad
  esempio `/myo/1/accel/x`), campioni EMG per pacchetto, frequenza dei dati IMU, porta dei
  comandi in ingresso.
- **STREAMS**: una casella per ogni indirizzo OSC (`fv` è `/emg/smooth`).
- **PROCESSING**: finestra RMS in millisecondi; modalità di `SET ORIGIN` (`yaw` azzera solo la
  direzione, `full` azzera tutta la posizione); `tap threshold` e `tap cooldown`, il filtro
  dei tap (vedi sezione 3, *I tap e la soglia*).
- **DEVICES**: una riga per bracciale: `NAME` (il nome mostrato nel monitor), `SELECTOR` (nome
  o indirizzo mostrato da SCAN), `SERIAL` (il numero di serie a cui è legato), `NEVER SLEEP` e
  `2× TAP = ORIGIN`.

`APPLY` applica subito senza riavviare. `APPLY + SAVE` salva anche su file.

### Due bracciali sempre nello stesso ordine

Quando un bracciale si collega, l'app ne registra il **numero di serie**. Se poi salvi la
configurazione, `MYO 1` sarà sempre quel bracciale fisico, anche se li accendi in ordine
diverso. Per sciogliere il legame, cancella il seriale in *SETTINGS → DEVICES*.

Il numero di serie funziona con entrambi gli adattatori. Un indirizzo scelto con SCAN invece
vale solo per l'adattatore con cui l'hai trovato: il Bluetooth del Mac mostra un codice lungo
(UUID), il dongle l'indirizzo del bracciale (`XX:XX:XX:XX:XX:XX`). Se cambi adattatore, l'app
ignora l'indirizzo e ritrova il bracciale dal numero di serie.

### Il file di configurazione

Il file è `~/Library/Application Support/osa-myo-controller/config.toml`. Un esempio commentato è in
`config.example.toml`.

Il salvataggio è sicuro: l'app scrive prima un file temporaneo e poi lo sostituisce, così un
salvataggio interrotto non lascia un file a metà. Se all'avvio il file non si può leggere,
l'app non si blocca: lo rinomina in `config.toml.broken-<data-ora>` (nella stessa cartella),
parte con le impostazioni predefinite e lo scrive nel registro Events. Un valore non valido
(ad esempio una porta fuori intervallo) torna al suo valore predefinito, con un avviso
in Events. Controlla le impostazioni e premi `SAVE CONFIG`.

---

## 7. Usarlo con Max/MSP

1. Avvia OSA MYO Controller e collega il bracciale.
2. Apri `examples/myo_receiver.maxpat` in Max.
3. La patch riceve con `udpreceive 7400` e smista con `route /myo/1/emg/raw …` verso
   multislider e number box.
4. In basso ci sono messaggi pronti per inviare comandi (`udpsend 127.0.0.1 7401`).
5. Per il secondo bracciale duplica la catena e cambia `/myo/1/` in `/myo/2/`.

Senza Max puoi controllare che i dati arrivino con:

```bash
python examples/osc_receiver.py 7400
```

---

## 8. Come funziona dentro (in breve)

```
Myo ──Bluetooth LE──▶ trasporto (Bluetooth del Mac / CoreBluetooth, oppure dongle BLED112)
                          │
                          ▼
                  decodifica del protocollo Myo
                          │
                          ▼
         elaborazione: scale, quaternione → angoli, azzeramento, RMS
                     │                         │
                     ▼                         ▼
         invio OSC (UDP, porta 7400)   buffer per il monitor (60 fps)
                     ▲
         comandi OSC in ingresso (porta 7401)
```

- Il Bluetooth e l'OSC girano su un thread separato, che la grafica non rallenta mai.
- L'EMG passa senza ritardi aggiuntivi: dal dato Bluetooth al pacchetto OSC servono meno di
  un millisecondo.
- Con il dongle, l'app parla con la chiavetta attraverso la porta seriale USB (protocollo
  BGAPI di Bluegiga). Un solo dongle serve tutti i bracciali, fino a 3.
- Se il collegamento cade, l'app riprova da sola (dopo 1, 2, 4, 8 secondi, poi ogni 8).
  Se stacchi il dongle, i bracciali passano in riconnessione e tornano quando lo
  reinserisci. Dopo `POWER OFF` l'app non riprova.
- Mentre è collegato, il bracciale non va in sospensione. Alla chiusura torna normale.

---

## 9. Problemi frequenti

| Problema | Soluzione |
|---|---|
| L'app non si avviava più dopo aver salvato le impostazioni | Risolto. Se il file di configurazione è illeggibile, l'app lo mette da parte (`config.toml.broken-…`) e parte con i valori predefiniti (sezione 6). |
| Lo SCAN non trova niente | Il bracciale dorme: muovilo o collegalo e scollegalo dall'USB. Chiudi altre app che lo usano. Con il dongle: in *SETTINGS → CONNECTION* deve comparire "BLED112 detected". |
| L'app si chiude subito, senza messaggi | Manca il permesso Bluetooth: *Impostazioni → Privacy e sicurezza → Bluetooth*, attiva OSA MYO Controller (o Terminal). Con il dongle questo permesso non serve. |
| Si collega ma va in timeout | *Impostazioni → Bluetooth*: se il Myo è nell'elenco, "Dimentica dispositivo". Spegni e riaccendi il Bluetooth. Oppure prova il dongle. |
| Arrivano EMG e movimento ma nessun gesto | Fai il gesto di sync (wave out e tieni). Se `SYNC` resta spento, premi `RE-SYNC` e riprova. |
| I gesti vengono riconosciuti male | Bracciale aderente, nella parte più larga dell'avambraccio, logo sopra. Tienilo addosso qualche minuto prima del sync. Poi `RE-SYNC` e di nuovo il gesto di sync. `LOCK` deve risultare sbloccato. Se ancora non va, prova `EMG filtered` invece di `raw`. |
| `sync_failed` nel registro Events | Il gesto era troppo forte: rilassa la mano e riprova più morbido, tenendo la posizione. |
| Il modello 3D non segue il braccio | Fai il sync, punta il braccio verso lo schermo e premi `SET ORIGIN`. Se mano e gomito sono invertiti premi `FLIP`. Scegli il punto di vista con `VIEW`. |
| Il grafico EMG sembra piatto | `SCALE` a ±8 o ±16, oppure `AUTO`. |
| `EMG smooth` non mostra niente | Il firmware del bracciale non manda questa modalità non documentata (il pannello EMG lo dice dopo 2 secondi): usa `EMG filt.` o `EMG raw`. |
| `/emg/smooth` non arriva in Max | Accendi il flusso `fv` in *SETTINGS → STREAMS* (nelle configurazioni salvate prima di questa versione è spento). |
| IMU e Orientation sono fermi | Con `IMU evt` il bracciale manda solo i tap, niente movimento: scegli `IMU all` (o `IMU data`). |
| Troppi tap | Imposta `tap threshold` (con `IMU all`) e/o `tap cooldown` in *SETTINGS → PROCESSING*; in Events trovi la forza di ogni tap. |
| Il doppio tap non azzera | `2× TAP → ORIGIN` acceso per quel bracciale? Servono `POSE on`, sync fatto, bracciale sbloccato e `IMU data` o `all`. In Events deve comparire il gesto `double_tap`. Se compare `no IMU data, origin not set`, scegli `IMU all` o `IMU data`. |
| Il bracciale non si accende più | Dopo `POWER OFF` (o a batteria scarica) si sveglia solo collegandolo al cavo USB. |
| Il dongle non viene trovato | *SETTINGS → CONNECTION → REFRESH*, oppure `osa-myo ports`: deve comparire una porta `/dev/cu.usbmodem…` segnata come BLED112. Prova un'altra porta USB, senza hub. |
| "in use by another program" | Il dongle è già aperto da un altro programma (vecchio Myo Connect, un'altra copia di OSA MYO Controller). Chiudilo e riprova. |
| Lo yaw si sposta | È normale: premi SET ORIGIN prima di suonare. |
| `DROP` sale | Avvicina il Mac (o il dongle, con una prolunga USB), allontana hub USB 3, riduci le interferenze. |
| Max non riceve | Controlla porta 7400 in Max e in OSA MYO Controller, e che `send` sia attivo. |
| "Address already in use" sulla porta 7401 | Un'altra copia di OSA MYO Controller è aperta, o Max ascolta sulla 7401. |

Per vedere più dettagli in terminale aggiungi `-v` a qualsiasi comando.
