# Changelog

All notable changes to OSA MYO Controller (called myo-bridge until 2026-10). Format: Keep a Changelog; versions: SemVer.

## [Unreleased]

### Renamed to OSA MYO Controller, open-source release
- Project, repository and app are now **OSA MYO Controller** (`OSA-MYO-Controller` on GitHub).
  pip distribution `osa-myo-controller`; command `osa-myo` (`myo-bridge` stays as an alias);
  the Python package keeps the import name `myo_bridge`.
- Config folder `osa-myo-controller`; an existing `myo-bridge` config is still read and is
  written to the new folder on the next save. `OSA_MYO_CONFIG` (or the old `MYO_BRIDGE_CONFIG`).
- App bundle `OSA MYO Controller.app` (`OSA-MYO-Controller.dmg`); web test kit
  `OSA-MYO-Controller-Web.app` / `.exe`.
- GUI polish (desktop and web): gesture names fit their tiles, EMG channel tags on a veil,
  events wrap with a hanging indent, settings labels and hints wrap, fixed number locale (6.00),
  columns rebalanced; the web styles now live in `web/src/ui/` with self-hosted fonts.
- README rewritten, with screenshots.

### Web version (first version)
- `web/`: myo-bridge as a web page for Chrome / Edge, over **Web Bluetooth**. A TypeScript port
  of `protocol.py`, `device.py` (configure order, keep-alive, battery poll, reconnect with
  back-off, unlock after sync, `RESYNC`, `POWER OFF`), the processing pipeline (quaternion,
  origin, RMS, tap strength) and the OSC sender (default preset, EMG bundles, rate limits),
  plus a simulated armband. Unit tests reuse the Python test vectors (vitest, 58 tests).
- One-band monitor: connect, battery, status /
  sync / lock / arm, EMG 8 pods (window, scale, AUTO, PAUSE; smooth EMG), IMU strips, arm view
  (the app's cameras and flip), gestures with RMS bars, events, mode selectors, `SET ORIGIN`,
  vibrate, never-sleep, settings (streams, rates, RMS window, origin mode, tap filter, double
  tap → origin) and an About panel with the same credits as `credits.py` (a test keeps them
  in step). `DEMO` runs the simulated armband, marked `SIMULATED`.
- `web/relay/myo-osc-relay.mjs`: dependency-free Node relay, WebSocket on 127.0.0.1 → one UDP
  datagram per OSC packet to a target fixed on its command line; control datagrams on 7401 go
  back to the page and are applied like the Python bridge's `/myo/<id>/...` commands.
- The monitor follows the macOS app's layout and look: toolbar with the relay URL, `SEND` and
  `SAVE LOG`; sidebar with the band, a simulator block, BATTERY and LINK (packet share per
  second, no RSSI in browsers); header strip with MYO badge, status, SYNC / LOCK pills and L/R
  arm chips; the Controls grid; plots with the app's left axis, ticks and grid; the event box
  and status bar. Narrower windows stack the sidebar on top and use two columns, then one.
- `SAVE LOG` downloads the session log (build tag, browser, settings, events, stats).
- `npm run kit`: test kits for testers, `MyoBridgeWeb.app` (macOS, universal) and
  `MyoBridgeWeb.exe` (Windows), compiled with Deno, nothing to install but Chrome. A
  double-click serves the page on 127.0.0.1:5180, runs the OSC relay (next free port if 8765
  is taken; the page follows it), opens Chrome, and quits a few seconds after the last page
  closes. The page gets an *OSC MONITOR* button (`monitor.html`: the OSC arriving on 7400,
  without Max) and *SAVE LOG* includes the app's log. With the Max patch, an Italian guide
  (`GUIDA.md`) and report form (`RAPPORTO.md`); the build tag is the git commit.
- The relay is a module (`relay/relay.mjs`) used by the command line and the kit app; its
  control port is bound only once the WebSocket listens.
- Fixed: in a browser without Web Bluetooth the page stopped at start (a removed button).
- Not hardware-verified yet. Not in the web version: several bands, RSSI, BLED112, `config.toml`.

### Credits
- About window (click the toolbar wordmark, or *MyoBridge → About Myo Bridge*): version,
  authors Daniele Fabris and Simone Arganini (2026), contact www.oscillacreations.com, and the
  open-source projects, libraries and fonts myo-bridge is built on, with their licences.
  `myo-bridge credits` prints the same; the bundle's Finder info carries the copyright.
- Authors added to `pyproject.toml` and the LICENSE copyright line.

### Second round of field feedback
- EMG mode `smooth` is shown in the monitor: the EMG grid plots the band's 50 Hz envelope on a
  0..1024 scale (16…2048, its own setting), the activity bars follow it and LINK counts its
  packets. `/emg/smooth` (stream `fv`) is now on by default; when a band streams smooth EMG
  that the configuration does not send, the event feed says so.
- Panels that stay empty say why: EMG off, smooth EMG not arriving (firmware without the
  undocumented mode), IMU `evt` (tap events only, no motion data), IMU off, no data. Each MODES
  item has a tooltip that says what it sends; the selectors fit their longest item.
- Tap filter (*SETTINGS → PROCESSING*, `tap_threshold_g`, `tap_cooldown_ms`): the strength of
  each tap is measured from the IMU stream (largest change of acceleration between 50 Hz
  samples around the tap, needs IMU mode `all`) and logged as `strength_g`; weaker taps and
  taps within the cooldown are dropped, greyed in the event feed with the reason. With a
  threshold a tap is sent 60 ms after the band reports it.
- Double tap → origin: per band (`2× TAP → ORIGIN` in Gesture, *SETTINGS → DEVICES*,
  `double_tap_origin`) the double-tap pose sets the origin and the band vibrates once; one
  origin per gesture. `zero` log entries say who set it (`double tap`, `OSC`).
- `SET ORIGIN` (button, double tap, `/myo/<id>/zero`) needs IMU data from the last second:
  with IMU `evt` / `off` or a stopped stream it no longer takes the last, stale frame; the
  status bar or the event feed says `no IMU data, origin not set`.
- Band names: double-click a slot (or right-click → *Rename…*, or *SETTINGS → DEVICES →
  NAME*); saved as `label` in `[[devices]]`, at most 32 characters, tabs and line breaks
  become spaces. macOS can't rename the band.
- Extra windows: `NEW WINDOW` (or right-click a slot → *Open in a new window*) shows any band
  with its status line, `SET ORIGIN`, Orientation, Gesture and EMG; minimum about 700 × 740,
  so two fit side by side.
- Header fields have fixed widths, so the window no longer widens once data arrives; the
  address moved into the device name's tooltip.
- Fixed: the Controls mode selectors showed the defaults instead of the selected band's modes
  until another band was selected.
- The mock sends taps of random strength (IMU `evt` / `all`) and a smooth EMG envelope.
- Docs: README (*Streaming modes and taps*), Italian manual, example config and hardware
  checklist.

### Field fixes after the first hardware session
- Fixed: after a setting was saved, every launch crashed until `config.toml` was deleted. With
  `from __future__ import annotations` the dataclass field types are strings, so nested tables
  (`[osc]`, `[gui]`…) were loaded back as plain dicts. Loading now resolves the type hints,
  coerces every value to its field's type, ignores unknown keys, resets invalid or
  out-of-range values to their defaults and sets a file that cannot be parsed aside as
  `config.toml.broken-<date-time>`; it never raises because of the file. What happened is
  logged and shown in the event feed. Saving is atomic (temp file + fsync + rename).
- Orientation panel rewritten: a forearm with hand and band (copper logo pod) in software 3D
  with depth sorting and a ground shadow, in the Myo sensor frame (x along the forearm, z out
  of the logo pod, world z up). The sync's x-direction turns the model so the hand stays
  forward; `FLIP` does it by hand; `VIEW` behind (over the shoulder, default) / side / top /
  mirror, saved in `[gui] orient_view`; a hint line shows the band direction and asks for
  `SET ORIGIN`.
- EMG grid: fixed scales ±2…±128 (default ±64); `AUTO` scales each pod to its own signal
  (instant attack to the 99.5th percentile, slow release) with the range in the pod tag; the
  saved scale, autoscale and window are restored at start.
- Poses: the bridge sends `unlock(hold)` on connect and after every `arm_synced`
  (`unlock_on_sync`), so poses are reported without the double-tap unlock. `RE-SYNC` button and
  `/myo/<id>/resync` reset the onboard classifier (off, then on) for a new sync gesture.
  The sync event reports the warm-up state (cold / warm, byte 3 of `arm_synced`) and
  `warmup_completed` its result.
- `POWER OFF` button (with confirmation) and `/myo/<id>/poweroff 1`: deep sleep, no reconnect;
  the band wakes only on USB power.
- BLED112 dongle reworked and selectable: *SETTINGS → CONNECTION* (adapter, port with
  auto-detect and `REFRESH`, dongle status, scan timeout), applied live (`Bridge.set_transport`
  rebuilds the slots); `--transport` / `--port` on `scan`, `dump` and `run`; new `ports`
  command. Transport: waiters registered before each command, serialised GAP and ATT
  procedures, read completion handled with or without a trailing `procedure_completed`,
  indications needing a confirmation confirmed, procedures aborted at once on link loss,
  exclusive port open with a clear "in use by another program" error, clean slate on open,
  recovery after unplug/replug, VID:PID detection of `/dev/cu.*` ports. Exercised end to end
  against a simulated dongle (`tests/test_bled112.py`); not hardware-verified.
- Addresses are adapter-specific (CoreBluetooth UUID vs MAC): a selector from the other adapter
  is ignored, a selector that is not found falls back to the slot's serial.
- `MyoDevice.connect()` leaves no half-open link when configuration fails; a bleak disconnect we
  asked for no longer triggers the reconnect loop.
- Event feed timestamps are wall-clock times; the monitor's info line names the adapter.
- Monitor fits the screen: the bottom row is gone (Battery and Link under Nearby in the
  sidebar, Gesture under IMU, Events under EMG), Controls compacted to six rows (`POWER OFF`
  beside `NEVER SLEEP`, the three modes on one row), lower minimum heights; the window opens
  sized to the free screen area. Minimum size went from 1687 × 1163 to 1439 × 739. The toolbar
  info line gives way (full text in its tooltip) so `SETTINGS` / `SAVE CONFIG` never overflow.
- Docs: Italian manual, README, protocol notes (unlock, re-sync, frames, BGAPI details) and
  the hardware checklist updated.

### GUI redesign
- New theme: near-black surfaces, hairlines, copper/amber/cyan accents, spectrum
  stripe on every panel, glow instead of shadow, 8 px spacing grid, 12 px card / 6 px control
  radii, bundled OFL fonts by role: Sora wordmark, Archivo titles, IBM Plex Mono data and
  labels, Newsreader italic hints (`src/myo_bridge/gui/fonts/`, converted from woff2).
- Layout aligned on one grid: header, Controls + Orientation column, IMU, EMG; Battery + Link
  column under Controls, Gesture and Events beside it. EMG and IMU are single panels.
- Pose tiles are drawn pictograms instead of emoji; event feed is colour-coded.
- App icon: a Myo armband (ring of 8 pods), `packaging/make_icon.py`
  renders the PNG and `MyoBridge.icns`; the window icon is set at start-up.

### M5 - packaging, docs, Max example, BLED112 backend
- `packaging/myo-bridge.spec` + `build_app.sh`: PyInstaller one-dir `MyoBridge.app` (arm64,
  `NSBluetoothAlwaysUsageDescription` in Info.plist, ad-hoc signed; CLI reachable through the
  bundle binary).
- README: install, macOS Bluetooth permission, connectable state and first sync, full OSC
  table with scalings and rates, control table, MyoMapper preset, configuration, latency,
  troubleshooting, known unknowns, references with licences. `docs/protocol.md` with the GATT
  table, commands, scaling, classifier events, Euler convention and the disagreement table.
- `examples/myo_receiver.maxpat`: udpreceive 7400 routed to every default stream + control
  messages to 7401.
- BLED112 dongle transport (`transport = "bled112"`): BGAPI framing module with unit tests,
  shared dongle with multiple connections, UUID->handle discovery, notify/indicate
  subscriptions. Not hardware-verified.
- `--version` works without a sub-command.

### M4 - multi-device rules, settings, config persistence
- Slot binding rules: selector (name / UUID) > serial recorded from MyoInfo > first free band
  by RSSI; a band already streaming in another slot is never taken; serial-locked slots try
  each visible Myo and release the wrong ones without touching their sleep mode.
- SETTINGS dialog (OSC target, preset, message mode, bundle size, rate limits, per-stream
  toggles, control input, RMS window, SET ORIGIN mode, per-slot selector/serial/sleep, slot
  count) applied live to the running bridge; APPLY + SAVE and SAVE CONFIG write config.toml
  (including the orientation zero reference per slot).
- `config.example.toml` documenting every key.
- Fixed: IMU/RMS OSC rate limiters were shared between bands, so a second armband could be
  starved of `/quat`, `/euler`, `/accel`, `/gyro` messages. Limiters are now per device id.

### M3 - monitor GUI
- PySide6 + pyqtgraph monitor following the MyoDiagnostics layout: header strip (status, sync,
  lock, arm/x-direction, serial, firmware), battery, Bluetooth signal with RSSI history and link
  stats (EMG/IMU rate, dropped packets, notification-to-OSC latency, OSC counters), Manual
  Overrides (unlock/lock, vibrate x3, SET ORIGIN / CLEAR, EMG/IMU/classifier mode, sleep toggle),
  software-projected 3D cuboid with roll/pitch/yaw and quaternion, three IMU strips, 8-pod EMG
  grid (window, scale, autoscale, pause), gesture feed with pod activity bars, event feed.
- Armband Manager sidebar: one row per slot, SCAN list with RSSI, double-click to bind a found
  device to the selected slot, CONNECT ALL / DISCONNECT.
- OSC target editable from the toolbar; SAVE CONFIG writes config.toml.
- The asyncio bridge runs on a background thread; the GUI drains ring buffers on a 60 Hz timer
  and never touches BLE. Closing the window restores the armbands' normal sleep mode.
- `myo-bridge monitor` (GUI without auto-connect); `run` opens the GUI unless `--no-gui`.

### M2 - processing, OSC output, mock device
- Processing: int16/int8 scaling, quaternion -> Euler (Z-Y-X, Thalmic convention), orientation
  zero reference (yaw-only or full), RMS envelope with configurable window, latency estimate.
- OSC sender (python-osc): `default` and `myomapper` namespace presets, `vector` and `axis`
  message modes, EMG bundling (N samples per datagram), phase-tolerant rate limiters for
  IMU/RMS streams, per-stream toggles.
- OSC control server on 7401: vibrate, lock/unlock, zero, mode, sleep, led, action; `/myo/all/…`.
- Bridge engine wiring N device slots to processing and OSC; `myo-bridge run --no-gui [--mock]`.
- `examples/osc_receiver.py`; tests for quaternion math, envelope, namespace, sender, engine.

### M1 - BLE transport, protocol, device, dump CLI
- `myo/protocol.py`: UUIDs, commands and parsers verified against myohw.h and four
  independent implementations (little-endian everywhere, w-x-y-z quaternion, classifier events
  parsed from the first 3 bytes, 18-byte vibrate2 payload).
- bleak (CoreBluetooth) transport and a mock transport behind one `Transport` interface.
- `MyoDevice`: configure (never-sleep, modes), subscriptions, serialised command writes,
  reconnect with backoff, sleep-mode restore on shutdown, rate and drop statistics.
- CLI: `scan`, `dump`, `config-show`.
