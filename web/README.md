# OSA MYO Controller web

The browser version of OSA MYO Controller: the same Myo protocol, processing and OSC addresses as the
Python bridge, running in a web page. It talks to the armband with **Web Bluetooth**, shows a
one-band monitor (EMG 8 pods, IMU strips, arm view, gestures, events), and
sends OSC through a small local **relay** because browsers can't send UDP. The monitor has the
macOS app's layout: toolbar, sidebar (band, simulator, battery, link), header strip, then
Controls / Orientation, IMU / Gesture, EMG / Events.

![The web version with the simulated armband](../docs/images/web.png)

By **Daniele Fabris** and **Simone Arganini**, 2026 · [www.oscillacreations.com](https://www.oscillacreations.com).
MIT licence. Credits: the *ABOUT* panel (the same list as `osa-myo credits`).

> **Status (2026-10):** first version. Protocol, processing, OSC encoding and the relay are
> covered by unit tests (the Python test vectors) and the monitor has been run against the
> built-in simulated armband. **Not yet tried with a real Myo over Web Bluetooth.**

## What it needs

- **Chrome or Edge** (desktop: macOS, Windows, Linux; also Chrome on Android). Firefox and
  Safari have no Web Bluetooth; iPhone and iPad browsers neither.
- The page served over **HTTPS** or from **localhost** (Web Bluetooth's rule).
- Node.js 18+ to build it and to run the OSC relay.
- On macOS the browser asks for Bluetooth permission the first time (System Settings →
  Privacy & Security → Bluetooth must allow Chrome).

## Run it

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

Open it in Chrome and press **CONNECT MYO**: Chrome's chooser lists the Myo armbands in range
(wake the band first, see the main README, *Getting the armband into a connectable state*).
**DEMO** runs a simulated armband, marked `SIMULATED`, with no hardware.

**SAVE LOG** (toolbar) downloads `osa-myo-web-log-<date>.txt`: build tag, browser,
settings, every event and a stats line every 10 s. Ask testers for it.

`npm run build` writes a static site to `web/dist/` (relative paths): serve it from any HTTPS
host, for example GitHub Pages, or locally with `npm run preview`.

## OSC

Browsers can only open WebSockets, so the page sends each OSC packet over a WebSocket to
`relay/myo-osc-relay.mjs`, which sends it on, unchanged, as one UDP datagram:

```bash
cd web
npm run relay        # ws://127.0.0.1:8765  ->  OSC 127.0.0.1:7400, control in :7401
```

(The test kit's app runs the relay itself.) Then press **SEND** in the page (the lamp says `OPEN`). Options:

```bash
node relay/myo-osc-relay.mjs --osc-host 192.168.1.20 --osc-port 9000 --control-port 7401
```

| Option | Default | |
|---|---|---|
| `--ws-port` | 8765 | WebSocket for the page (listens on 127.0.0.1 only) |
| `--osc-host`, `--osc-port` | 127.0.0.1, 7400 | where the OSC goes |
| `--control-port` | 7401 | UDP port for control messages to the page; `0` = none |
| `--control-host` | 0.0.0.0 | interface for the control port |
| `--allow-origin` | (any) | accept only pages from this origin, e.g. `https://example.github.io` |

- The UDP target is chosen on the relay's command line, never by the page, so a web page
  can't use the relay to send UDP elsewhere.
- Run either the Python bridge or this relay: both use the control port 7401.
- Addresses, types and rates are the Python bridge's default preset (vector mode): `/myo/1/emg/raw`
  (bundles of 4 samples), `/emg/rms`, `/emg/mav`, `/emg/smooth`, `/quat`, `/euler`, `/accel`,
  `/gyro`, `/pose`, `/pose/id`, `/arm`, `/xdir`, `/sync`, `/lock`, `/battery`, `/status`,
  `/tap`, `/firmware`; *SETTINGS* switches streams on and off and sets the IMU and RMS rates.
  See the main README, *OSC output*.
- Control messages work as in the Python bridge: `/myo/1/vibrate`, `/zero`, `/zero/clear`,
  `/lock`, `/unlock`, `/mode`, `/sleep`, `/led`, `/action`, `/resync`, `/poweroff 1`
  (`/myo/all/...` too).
- An HTTPS page that connects to `ws://127.0.0.1` may trigger Chrome's *local network access*
  prompt: allow it.

## Test kit

```bash
npm run kit          # needs Deno 2 (brew install deno); the macOS app is built on macOS only
```

Builds one kit per system for testers, with nothing to install but Chrome:

| | |
|---|---|
| `../dist/osa-myo-web-test-mac(.zip)` | `OSA-MYO-Controller-Web.app` (universal: Apple Silicon + Intel), ~64 MB zipped |
| `../dist/osa-myo-web-test-windows(.zip)` | `OSA-MYO-Controller-Web.exe`, ~33 MB zipped |
| both | `GUIDA.md` and `RAPPORTO.md` (the tester's guide and report form, Italian), `VERSIONE.txt`, `extra/myo_receiver.maxpat` |

The app (`kit/launcher.mjs`, entry `kit/main.mjs`) is compiled with `deno compile`, the built page
embedded in it. A double-click:

- serves the page on http://127.0.0.1:5180 and opens Chrome (else Edge, else the default
  browser); a second double-click while it runs just opens another page;
- runs the OSC relay in the same process (8765, or the next free port: the page reads the
  relay's address from `/__kit` and follows it);
- serves the OSC monitor page (`monitor.html`, the page's *OSC MONITOR* button), which listens
  on the OSC port only while it is open;
- quits by itself 8 s after the last page closes (the page holds `/__alive`, an event stream),
  or 3 minutes after start if no page ever opens; no window, no Dock icon;
- adds its own log to the page's *SAVE LOG*; errors it can't show in the page are dialogs.

Options, for a terminal: `--port 5180`, `--osc-host`, `--osc-port`, `--ws-port`,
`--control-port`, `--control-host`, `--no-relay`, `--no-open`, `--stay` (don't quit by itself).
`node kit/serve.mjs` runs the same app under Node from `dist/` (after `npm run build`).

The build tag (git commit, `-dirty` with uncommitted changes) is in *ABOUT*, the saved logs and
`VERSIONE.txt`. The apps are not signed by Apple or Microsoft: testers have to allow them once
(the guide says how). `CODESIGN_IDENTITY="Developer ID Application: …" npm run kit` signs the
Mac app with a Developer ID; notarizing it is not scripted yet.

## Differences from the macOS app

- One armband, always `/myo/1/...`. Several bands at once need the macOS app.
- No RSSI (Web Bluetooth doesn't report it for a connected device): shown as `n/a`; the LINK
  history shows the share of expected packets received each second instead.
- The sidebar's NEARBY / SCAN is the browser's own chooser (CONNECT MYO); a SIMULATOR block
  (DEMO, TAP, LINK LOSS) takes its place.
- No BLED112 dongle (it would need Web Serial; not done yet).
- Settings and the origin per band are kept in the browser's local storage, not in
  `config.toml`.
- The tap filter, double tap → origin, the unlock after sync, `RESYNC` and `POWER OFF` behave
  as in the app.

## Layout of the code

```
web/
  index.html              the monitor markup
  src/myo/protocol.ts     protocol.py: UUIDs, commands, parsers
  src/myo/device.ts       device.py: connect, configure, keep-alive, reconnect, commands
  src/myo/webbluetooth.ts Web Bluetooth transport (one GATT operation at a time)
  src/myo/mock.ts         simulated armband (DEMO and tests)
  src/processing/         pipeline.py, quaternion.py, envelope, scaling
  src/osc/                OSC encoder/decoder, sender (default preset), relay client
  src/bridge.ts           engine.py for one band: tap filter, origin, control messages
  src/ui/                 monitor, canvas plots, arm view, settings, styles, fonts
  src/credits.ts          credits.py (a test keeps them in step)
  monitor.html, src/monitor.ts  the test kit's OSC monitor page
  relay/relay.mjs         WebSocket -> OSC/UDP relay, no dependencies (a module)
  relay/myo-osc-relay.mjs the relay from the command line
  kit/launcher.mjs        the test kit's app: page server, relay, OSC monitor, auto-quit
  kit/main.mjs, serve.mjs its entries: compiled (page embedded) and Node (page from dist/)
  kit/GUIDA.md, RAPPORTO.md  the tester's guide and report form (Italian)
  scripts/make-kit.mjs    npm run kit
  tests/                  vitest: the Python test vectors, device, OSC, bridge, relay
```

```bash
npm test             # vitest
npm run build        # type-check + production build
```

If the repository is in a synced folder (Dropbox, iCloud), exclude `web/node_modules/` and
`web/dist/` from syncing.
