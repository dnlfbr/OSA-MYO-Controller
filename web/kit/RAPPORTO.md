# Rapporto di prova — OSA MYO Controller web

Spunta `[x]` cosa funziona, lascia `[ ]` cosa non hai provato e scrivi sotto cosa non va.
Allega il file di **SAVE LOG** e gli screenshot.

## Chi e con cosa

- Nome:
- Data:
- Versione del kit (da `VERSIONE.txt`):
- Computer e sistema (es. MacBook Air M2, macOS 15.1 / PC Windows 11):
- Browser e versione (Chrome → Impostazioni → Informazioni su Chrome):
- Bluetooth: integrato / chiavetta (quale):
- Myo: firmware (riga FIRMWARE in alto), batteria all'inizio:

## Avvio

- [ ] doppio clic su OSA-MYO-Controller-Web: si apre Chrome con la pagina
- [ ] il blocco al primo avvio (macOS *Apri comunque* / Windows SmartScreen) si supera come da guida
- [ ] chiudendo la pagina l'app si chiude da sola; un nuovo doppio clic la riapre
- [ ] DEMO funziona (tutti i pannelli si muovono, compare `SIMULATED`)

Note:

## Collegamento

- [ ] CONNECT MYO trova il Myo nella finestra di Chrome
- [ ] passa a `STREAMING` (in quanti secondi? ___ )
- [ ] 10 minuti stabili: EMG Hz ___  IMU Hz ___  DROP ___  LINK ___ %
- [ ] fuori portata → `RECONNECTING` → torna a `STREAMING` da solo
- [ ] DISCONNECT e nuova connessione

Note:

## Sincronizzazione e comandi

- [ ] *wave out* sincronizza: SYNC acceso, `UNLOCKED`, ARM L / R
- [ ] il Myo vibra da solo alla sincronizzazione? sì / no
- [ ] VIBRATE short / medium / long
- [ ] UNLOCK / LOCK
- [ ] RE-SYNC
- [ ] MODES: EMG smooth / raw, IMU evt / all
- [ ] NEVER SLEEP
- [ ] POWER OFF (alla fine)

Note:

## Orientamento

- [ ] SET ORIGIN: la mano punta dentro lo schermo
- [ ] alzare il braccio / girarlo / ruotare l'avambraccio: il modello segue nello stesso verso
- [ ] qualcosa è a specchio? cosa:
- testo sotto il disegno dopo la sync (`band +x → wrist` / `→ elbow`):
- logo verso il polso o verso il gomito?
- [ ] FLIP serviva? sì / no

Note:

## EMG

- valori tipici a riposo: ___   con il pugno: ___   (scala usata: ___ )
- con `EMG smooth`: a riposo ___   pugno ___   (arriva a 1024? la supera?)
- [ ] AUTO adatta ogni pod e torna indietro dopo il pugno

Note:

## Pose e colpetti

| posa | riconosciuta? | note |
|---|---|---|
| fist (pugno) | | |
| wave in | | |
| wave out | | |
| spread (mano aperta) | | |
| double tap | | |

- [ ] `2× TAP → ORIGIN`: vibra una volta e azzera l'orientamento
- `strength_g` dei colpetti leggeri: ___   forti: ___
- camminare / muovere il braccio / appoggiarlo sul tavolo genera colpetti finti? sì / no

Note:

## OSC

- [ ] SEND → spia `OPEN`
- [ ] OSC MONITOR (o Max) riceve `/myo/1/...`
- [ ] la patch `myo_receiver.maxpat` mostra i dati
- [ ] da Max `/myo/1/vibrate 1` fa vibrare il Myo
- latenza percepita (gesto → suono): ottima / accettabile / troppa

Note:

## Grafica e uso

- la pagina sta nello schermo? risoluzione:
- qualcosa di illeggibile, tagliato o poco chiaro:
- cosa manca rispetto all'app per Mac (se la conosci):

## Errori

Copia qui i messaggi d'errore (pagina, finestre di errore, console di Chrome) e cosa stavi facendo:

```

```
