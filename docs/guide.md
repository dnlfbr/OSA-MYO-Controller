# OSA MYO Controller: user guide

Everything the [README](../README.md) leaves out: permissions, the monitor, streaming modes,
the full OSC tables, configuration, the BLED112 dongle, packaging and troubleshooting.
Italian manual: [MANUALE.md](MANUALE.md). Protocol notes: [protocol.md](protocol.md).

- [macOS Bluetooth permission](#macos-bluetooth-permission)
- [Getting the armband into a connectable state](#getting-the-armband-into-a-connectable-state)
- [Commands](#commands)
- [The monitor](#the-monitor)
- [Streaming modes and taps](#streaming-modes-and-taps)
- [OSC output](#osc-output)
- [OSC input (control)](#osc-input-control)
- [Configuration](#configuration)
- [Max/MSP example](#maxmsp-example)
- [Latency and data rates](#latency-and-data-rates)
- [BLED112 dongle](#bled112-dongle)
- [Building the .app](#building-the-app)
- [Troubleshooting](#troubleshooting)
- [Known unknowns](#known-unknowns)

## macOS Bluetooth permission

macOS kills, with no error message, any process that touches CoreBluetooth unless the
**application that launched it** declares `NSBluetoothAlwaysUsageDescription` in its
`Info.plist` and the user has granted Bluetooth access in *System Settings → Privacy &
Security → Bluetooth*.

- **Terminal.app and iTerm2** declare it. Run `osa-myo` from one of them; the first run
  pops the permission dialog. Accept it.
- **Editors and other hosts** (VS Code's integrated terminal, Jupyter, launch-from-IDE, AI
  agents' shells) often do not. The symptom is a silent crash on `scan`, and
  *Console.app* shows `TCC ... attempted to access privacy-sensitive data without a usage
  description`. Start from a real terminal instead.
- **OSA MYO Controller.app** (see *Building the .app*) carries the key itself and can be double-clicked.

If you accidentally clicked *Don't allow*, re-enable the terminal in the Bluetooth privacy pane.

## Getting the armband into a connectable state

The Myo advertises over BLE only while it is **awake**. A Myo that has been idle sleeps and
stops advertising; it wakes up when it is moved, tapped, or plugged into USB. The
*deep sleep* state (entered when the battery dies or when a tool sends the deep-sleep command)
can only be left by plugging it into USB.

1. Charge the band (USB micro, the logo pulses while charging).
2. Put it on, logo on the top of the forearm (either orientation works; the band reports it).
3. Unplug and move it: the logo glows blue, it is now advertising for ~30 s.
4. Run `osa-myo scan`. It should list `Myo` (or the name you gave it in Myo Connect).

A Myo connected to another host (an old Myo Connect, a phone) does not advertise. Quit that
app first. macOS sometimes keeps a stale pairing: see *Troubleshooting*.

**First sync.** After connecting, the band streams EMG and IMU immediately but reports no
poses and `arm unknown` until you perform the **sync gesture**: flex the wrist *outwards*
(wave out, away from the body), without forcing, and hold until the band vibrates. The monitor
shows `SYNCED`, the arm (`L`/`R`) and the x-direction (logo toward wrist or elbow). The only
failure the firmware reports is `sync_failed` / `failed_too_hard`: the gesture was too strong,
relax and try again more gently. Wear the band for a few minutes first: the sync event says
whether the band is still `cold`, and poses get reliable once `warmup_completed` arrives. Sync
is lost when the band is taken off.

After every sync, and on every connect, the bridge sends *unlock (hold)* so that every pose is
reported without Myo Connect's double-tap unlock (`unlock_on_sync`, on by default). `RE-SYNC`
in the monitor or `/myo/<id>/resync` resets the onboard classifier (off, then on): the band
forgets the arm and waits for a new sync gesture while EMG and IMU keep streaming.

## Commands

```bash
osa-myo scan                         # list armbands with RSSI and address
osa-myo dump --duration 10           # print parsed packets, rates and drop counters
osa-myo run                          # monitor GUI + OSC to 127.0.0.1:7400, control on 7401
osa-myo run --no-gui                 # headless: OSC only
osa-myo run -n 2                     # two armbands, ids /myo/1 and /myo/2
osa-myo run --mock -n 2              # no hardware: simulated bands
osa-myo run --osc-host 192.168.1.20 --osc-port 9000 --preset myomapper
osa-myo monitor                      # GUI without auto-connect: SCAN, then double-click a band
osa-myo config-show                  # effective configuration as TOML
osa-myo credits                      # authors, contact, open-source credits
osa-myo ports                        # serial ports; the BLED112 is marked
osa-myo scan --transport bled112     # same commands through the dongle (--port to pick one)
```

`scan`, `dump` and `run` use the adapter saved in the settings unless `--transport` is given.

`run -d "Myo-left" -d "Myo-right"` binds slots to named bands; `-d` also accepts the
address from `scan` (a CoreBluetooth UUID, or the MAC with the dongle) or the serial printed
in the monitor header.

`python examples/osc_receiver.py 7400` prints every incoming address with its rate and latest
values. Useful to verify the stream before opening Max.

## The monitor

![The monitor with two simulated armbands](images/monitor.png)

A sidebar with the armbands on the left, then three columns, no bottom row: the window opens sized to the
screen's free area and its minimum (about 1440 × 740) fits a 13" laptop without scrolling.

| Region | What it shows / does |
|---|---|
| Sidebar | one row per slot (`MYO 1`, `MYO 2`…) with name, state dot, battery, RSSI; double-click a row to rename it, right-click for *Rename…* / *Open in a new window*; `SCAN` lists nearby bands with RSSI, double-click binds one to the selected slot; `CONNECT ALL` / `DISCONNECT`; Battery and Link panels at the bottom |
| Header strip | `STATUS` (disconnected / connecting / connected / streaming / reconnecting), `SYNC`, `LOCK`, arm `L`/`R` with x-direction, device name (its tooltip: Bluetooth name and address), serial, firmware |
| Battery | % with segmented bar, time of last read (polled every 30 s + notifications) |
| Link | RSSI as % with 60 s history; EMG Hz, IMU Hz, dropped EMG samples, notification-to-OSC latency, OSC message count |
| Controls | `CONNECT`/`DISCONNECT` this slot; `POWER OFF` (deep sleep after a confirmation: the band wakes only on USB power, no reconnect); `RE-SYNC`; `UNLOCK`/`LOCK`; vibrate `SHORT`/`MEDIUM`/`LONG`; `SET ORIGIN` (orientation zero, needs IMU data) / `CLEAR`; EMG, IMU, classifier mode on one row (each item's tooltip says what it sends); `NEVER SLEEP` toggle |
| Orientation | a forearm with hand and band (copper pod = logo pod) in software 3D; `VIEW` `BEHIND` (over the shoulder, default) / `SIDE` / `TOP` / `MIRROR`; the sync's x-direction turns the model so the hand stays forward, `FLIP` does it by hand; a hint line shows the band direction and asks for `SET ORIGIN`; roll / pitch / yaw in degrees, quaternion x y z w |
| IMU | scrolling gyroscope (±500 deg/s), accelerometer (±5 g), quaternion (−1..1) |
| EMG | 8 scrolling pods; window 0.5–10 s, fixed scale ±2..±128, per-pod `AUTO` (instant attack to the 99.5th percentile, slow release; the tag shows each pod's range), pause. In EMG mode `smooth` the band's 50 Hz envelope on a 0..1024 scale (16…2048) |
| Gesture | pose tiles, current pose, per-pod activity bars (RMS, or the smooth envelope); `2× TAP → ORIGIN` toggle |
| Events | wall-clock timestamped log: `status`, `arm_synced` (arm, x-direction, warm-up), `unlocked`, `pose`, `battery_level`, `tap` (with its strength; dropped taps greyed), `zero` (with who set it), `warmup_completed`, `sync_failed`…, and configuration warnings |
| Toolbar | wordmark (click: *About*, authors and credits, also in the app menu); OSC host/port with `APPLY`, send on/off, active adapter, `NEW WINDOW`, `SETTINGS` (everything in `config.toml`, applied live), `SAVE CONFIG` (also keeps the arm view, EMG scale, names and toggles) |

A panel that stays empty because of the band's mode says why (EMG off, IMU `evt` sends no
motion data, no data from the band…); see *Streaming modes and taps*.

**Names.** macOS cannot rename the band itself (CoreBluetooth gives no write access to its
name), so a slot gets a name in the monitor: double-click its row in the sidebar (or
right-click → *Rename…*, or `SETTINGS → DEVICES → NAME`), up to 32 characters, empty = the
Bluetooth name. It is shown in the sidebar, the header and the extra windows; `SAVE CONFIG`
keeps it as `label` in `[[devices]]`. OSC addresses keep the slot number.

![A band in its own window](images/band-window.png)

**More bands on screen.** `NEW WINDOW` (or right-click a slot → *Open in a new window*) opens
a window for one band: a status line (arm, battery, RSSI, EMG and IMU rates), `SET ORIGIN`,
Orientation, Gesture and EMG. Its menu switches band. Open as many as needed: at about
700 × 740 minimum, two fit side by side on a 1440 px screen. They close with the main window.

The GUI runs on its own thread and only reads ring buffers; BLE and OSC run on an asyncio loop
that is never blocked by repaints. Closing the window restores the bands' normal sleep mode.

## Streaming modes and taps

Each band streams what its three modes ask for: Controls → `MODES`, `emg_mode` / `imu_mode` /
`classifier_mode` per slot in `config.toml`, or `/myo/<id>/mode`. Each item's tooltip says the
same as this table.

| Mode | The band sends | Monitor | OSC |
|---|---|---|---|
| EMG `off` | no muscle data | EMG empty, with a note | — |
| EMG `smooth` | its own envelope of each pod, 50 Hz, uint16 ≈ 0..1024 (undocumented mode 1) | EMG on a 0..1024 scale, activity bars from it | `/emg/smooth` (stream `fv`) |
| EMG `filt.` | 200 Hz int8 samples, filtered by the band | EMG ±64, activity bars from the RMS | `/emg/raw`, `/norm`, `/rms`, `/mav` |
| EMG `raw` | 200 Hz int8 samples, unfiltered | as `filt.` | as `filt.` |
| IMU `off` | nothing, no taps either | IMU and Orientation still, with a note | — |
| IMU `data` | orientation, accelerometer, gyroscope, 50 Hz | IMU, Orientation | `/quat`, `/euler…`, `/accel`, `/gyro` |
| IMU `evt` | tap events only, **no motion data** | IMU and Orientation still, with a note; taps in Events | `/tap` |
| IMU `all` | motion data and tap events | all of the above | all of the above |
| IMU `raw` | undocumented, handled like `data` | | |
| POSE `on` / `off` | classifier events: sync, poses, lock | Gesture, header | `/pose`, `/sync`, `/arm`… |

`smooth` is the lightest EMG mode on the radio (8 values at 50 Hz instead of 200 Hz) and is
already an envelope: good for driving parameters, no raw samples. It is undocumented: if a
band's firmware does not send it, the EMG panel says so after 2 s; use `filt.` or `raw`. A
`config.toml` saved before this version keeps `fv = false` in `[osc.streams]`: switch it on
in `SETTINGS → STREAMS` (the event feed warns when a band streams smooth EMG that is not sent).

**Taps** are the band's own accelerometer event: a knock on the band, or a jolt of the arm,
with a direction and a count (1 or 2). They arrive only in IMU mode `evt` or `all`. They are
not the `2× TAP` pose, which is an EMG gesture recognised by the classifier (thumb and middle
finger tapped together twice). The firmware's tap detector cannot be tuned and fires easily, so
the bridge filters taps in `SETTINGS → PROCESSING` (`[processing]`):

- `tap threshold` (g): drops taps whose knock is weaker. The strength is the largest
  sample-to-sample change of the acceleration around the tap, from the 50 Hz IMU stream, so it
  needs IMU mode `all`; with `evt` there is no motion data, and every tap is kept. Each tap in
  the event feed shows its `strength_g`: tap the way you want to be counted and the way you
  don't, then pick a value between the two. 0 = off.
- `tap cooldown` (ms): drops taps closer than this to the previous kept one. 0 = off.

Dropped taps are not sent; they stay in the event feed, greyed, with the reason (`ignored`).
A tap that waits for the threshold is sent 60 ms after the band reports it.

**Double tap → origin.** With `2× TAP → ORIGIN` on (Gesture panel, `SETTINGS → DEVICES`, or
`double_tap_origin`), the `double_tap` pose does `SET ORIGIN` for that band, which vibrates
once to confirm: the performer re-aligns the yaw without touching the computer. It needs POSE
`on`, a synced band and IMU data (`data` or `all`). One origin per gesture: repeats within 1 s
are ignored. The event feed logs it as `zero` with `"by": "double tap"`.

Every `SET ORIGIN` (button, double tap, `/myo/<id>/zero`) needs IMU data from the last second.
With IMU `evt` or `off`, or when the stream has stopped, the origin stays as it was (an old
orientation would give a wrong one), the band does not vibrate and the status bar or the event
feed says `no IMU data, origin not set`.

## OSC output

Default target `127.0.0.1:7400` (UDP). One message per data type ("vector" mode); switch to
"axis" mode for one message per channel/axis (`/myo/1/emg/raw/0`, `/myo/1/accel/x`…). All
floats are 32-bit OSC floats, all ints 32-bit OSC ints.

`<id>` is the slot number (1, 2…), **not** a property of the band. A slot can be locked to a
particular band by its serial (see *Configuration*).

### Default preset

| Address | Args | Scaling | Rate |
|---|---|---|---|
| `/myo/<id>/emg/raw` | i×8 | raw int8 from the band, −128..127 (filtered mode: −128..127 rectified-ish, see protocol doc) | 200 Hz, bundled 4 samples per datagram (configurable) |
| `/myo/<id>/emg/norm` | f×8 | `raw / 128` → −1..1 | 200 Hz, same bundles |
| `/myo/<id>/emg/rms` | f×8 | RMS of `norm` over a sliding window (default 50 ms) → 0..1 | 50 Hz (rate-limited) |
| `/myo/<id>/emg/mav` | f | mean of the 8 RMS values → 0..1, one "muscle activity" number | 50 Hz |
| `/myo/<id>/emg/smooth` | i×8 | the band's own envelope per pod (undocumented), ≈ 0..1024; only in EMG mode 1 (smooth); stream `fv`, on by default | 50 Hz |
| `/myo/<id>/quat` | f×4 | **w x y z**, `int16 / 16384`, renormalised, orientation zero applied | 50 Hz |
| `/myo/<id>/quat/raw` | f×4 | as above without the zero reference | 50 Hz |
| `/myo/<id>/euler` | f×3 | roll, pitch, yaw in **radians** (Z-Y-X / Tait-Bryan, Thalmic hello-myo convention), zero applied | 50 Hz |
| `/myo/<id>/euler/deg` | f×3 | same in degrees | 50 Hz |
| `/myo/<id>/euler/norm` | f×3 | `(angle + π) / 2π` → 0..1 | 50 Hz |
| `/myo/<id>/accel` | f×3 | `int16 / 2048` → **g** (≈ ±16 g range) | 50 Hz |
| `/myo/<id>/gyro` | f×3 | `int16 / 16` → **deg/s** (≈ ±2000 deg/s range) | 50 Hz |
| `/myo/<id>/pose` | s | `rest fist wave_in wave_out fingers_spread double_tap unknown` | on change |
| `/myo/<id>/pose/id` | i | 0 rest, 1 fist, 2 wave_in, 3 wave_out, 4 fingers_spread, 5 double_tap, 255 unknown | on change |
| `/myo/<id>/arm` | s | `left`, `right`, `unknown` | on sync / unsync |
| `/myo/<id>/xdir` | s | `wrist`, `elbow`, `unknown` (which way the logo/x-axis points) | on sync / unsync |
| `/myo/<id>/sync` | i | 1 synced, 0 unsynced / sync failed | on change |
| `/myo/<id>/lock` | i | 1 locked (no poses), 0 unlocked | on change |
| `/myo/<id>/battery` | i | 0..100 % | on change, polled every 30 s |
| `/myo/<id>/rssi` | i | dBm (last scan value until CoreBluetooth reports live RSSI) | 1 Hz |
| `/myo/<id>/status` | s | `disconnected connecting connected streaming reconnecting` | on change |
| `/myo/<id>/tap` | i i | tap direction, tap count (IMU mode *all* / *events*), after the tap filter (see *Streaming modes and taps*) | on event |
| `/myo/<id>/firmware` | s | e.g. `1.5.1970.2` | once per connect |

The quaternion is the band's **absolute** orientation from its sensor fusion (gravity +
gyro, no magnetometer): roll and pitch are stable, **yaw drifts** slowly and is arbitrary at
power-up. Use `SET ORIGIN` or `/myo/<id>/zero` to re-centre it (default: yaw only, so
roll/pitch stay gravity-referenced; `zero_mode = "full"` makes the current pose the identity).

Every stream can be switched off in `SETTINGS → STREAMS` or `[osc.streams]`.

### `myomapper` preset

Compatible with the addresses of Balandino Di Donato's **MyoMapper** so existing patches keep
working (`--preset myomapper`). Note the missing slash: `/myo1/…`.

| Address | Args | Content |
|---|---|---|
| `/myo<id>/emg/raw` | i×8 | raw int8 |
| `/myo<id>/emg/scaled` | f×8 | raw/128 |
| `/myo<id>/emg/scaled/abs/mavg` | f×8 | RMS per pod (MyoMapper used a moving average of the rectified signal) |
| `/myo<id>/emg/scaled/abs/mav/mavg` | f | mean activity |
| `/myo<id>/orientation/quaternion` | f×4 | w x y z |
| `/myo<id>/orientation/raw` | f×3 | roll pitch yaw, radians |
| `/myo<id>/orientation/scaled` | f×3 | 0..1 |
| `/myo<id>/acceleration/raw` | f×3 | g |
| `/myo<id>/gyro/raw` | f×3 | deg/s |
| `/myo<id>/pose` | i s | pose id **and** name in one message (MyoMapper style) |
| `/myo<id>/battery`, `/rssi`, `/status`, `/sync`, `/lock`, `/arm`, `/xdir`, `/firmware`, `/tap` | | as in the default preset |

Inbound `/myo<id>/Yaw/calibrate` is accepted as an alias of `/myo/<id>/zero`.

## OSC input (control)

The bridge listens on `0.0.0.0:7401` (UDP). `<id>` is a slot number or `all`.

| Address | Args | Effect |
|---|---|---|
| `/myo/<id>/vibrate` | `1` short, `2` medium, `3` long; `>3` = duration in ms | vibrate |
| `/myo/<id>/lock` | | lock (no pose events) |
| `/myo/<id>/unlock` | optional `0` lock, `1` timed, `2` hold (default) | unlock |
| `/myo/<id>/zero` | | set the orientation reference (SET ORIGIN; needs IMU data from the last second) |
| `/myo/<id>/zero/clear` | | clear it |
| `/myo/<id>/mode` | `emg imu classifier` | set streaming modes: EMG 0 off / 1 smooth / 2 filtered / 3 raw; IMU 0 off / 1 data / 2 events / 3 all / 4 raw; classifier 0 / 1 |
| `/myo/<id>/sleep` | `0` normal, `1` never sleep | sleep mode |
| `/myo/<id>/led` | `r g b [r g b]` | logo (and bar) colour, undocumented command |
| `/myo/<id>/action` | | "user action" (resets the inactivity timer, like a wave) |
| `/myo/<id>/resync` | | reset the classifier: the performer makes the sync gesture again |
| `/myo/<id>/poweroff` | `1` (required) | deep sleep: the band wakes only on USB power; without the `1` the message is ignored |

## Configuration

`config.toml` is looked up in the current directory, then in
`~/Library/Application Support/osa-myo-controller/config.toml` (a config from the
earlier `myo-bridge` folder is still read); `--config path` overrides. Everything
is optional. [`config.example.toml`](config.example.toml) lists every key; the essentials:

```toml
transport = "bleak"          # bleak (built-in Bluetooth) | bled112 (USB dongle) | mock
dongle_port = ""             # BLED112 serial port, "" = auto-detect
scan_timeout_s = 6.0

[[devices]]                  # one table per slot -> /myo/1, /myo/2 ...
label = ""                   # name shown in the monitor (Rename); "" = the Bluetooth name
selector = ""                # name or UUID from `scan`; empty = first free band
serial = ""                  # filled in on connect; keep it to lock the slot to that band
emg_mode = 3                 # 0 off, 1 smooth (50 Hz, undocumented), 2 filtered, 3 raw
imu_mode = 3                 # 0 off, 1 data, 2 events, 3 all, 4 raw
classifier_mode = 1
never_sleep = true
double_tap_origin = false    # the double-tap pose sets the origin (SET ORIGIN)
zero_quat = []               # saved SET ORIGIN reference (w x y z)

[osc]
host = "127.0.0.1"
port = 7400
preset = "default"           # default | myomapper
mode = "vector"              # vector | axis
emg_bundle_samples = 4       # 1 = one datagram per sample (lowest latency, 200 datagrams/s per band)
imu_rate_hz = 50.0           # 0 = every packet
rms_rate_hz = 50.0

[osc.streams]
emg_raw = true
emg_norm = false
fv = true                    # /emg/smooth (EMG mode smooth)
# ... one key per stream

[osc_in]
enabled = true
port = 7401

[processing]
rms_window_ms = 50.0
zero_mode = "yaw"            # yaw | full
tap_threshold_g = 0.0        # drop weaker taps (needs IMU mode all); 0 = off
tap_cooldown_ms = 0.0        # drop taps closer than this to the last kept one; 0 = off

[gui]
emg_scale = 64.0             # ±2 … ±128
emg_autoscale = false
orient_view = "behind"       # behind | side | top | mirror
```

Loading never fails because of the file: a file that cannot be parsed is renamed to
`config.toml.broken-<date-time>` and the defaults are used; a value of the wrong type or out of
range is reset to its default. Both cases are logged and shown in the monitor's event feed.
Saving writes a temporary file and renames it, so an interrupted save cannot truncate the
configuration.

**Slot binding rules** (`devices`): a slot with a `selector` connects to that name/address; a
slot with a `serial` tries every visible band until the serial matches (this is the only
identifier that survives moving to another Mac or to the other adapter: CoreBluetooth addresses
are per-computer UUIDs, the dongle sees MAC addresses). An address seen through the other
adapter is ignored, and a selector that is not found falls back to the serial. Otherwise the
slot takes the strongest free band. A band streaming in one slot is never taken by another.
After a link loss the slot reconnects to the same band with 1-2-4-8 s backoff (then every 8 s);
after `POWER OFF` it does not.

## Max/MSP example

[`examples/myo_receiver.maxpat`](examples/myo_receiver.maxpat): `udpreceive 7400` →
`route /myo/1/emg/raw …` → multisliders / unpack / number boxes for every default stream,
plus `udpsend 127.0.0.1 7401` with ready-made control messages. Change the `1` in the `route`
object for the second band, or duplicate the chain. EMG bundles arrive as consecutive messages
with the same timestamp; `udpreceive` unpacks OSC bundles automatically.

Minimal Python receiver: [`examples/osc_receiver.py`](examples/osc_receiver.py).

## Latency and data rates

- EMG: the band sends 200 samples/s per pod as 100 notifications/s of 2 samples, round-robin
  over four characteristics. Each notification is unpacked with one `struct.unpack` into
  preallocated tuples, appended to a numpy ring and to a pending OSC bundle. The bundle is
  flushed every `emg_bundle_samples` samples (4 → one 20 ms datagram with 4 `/emg/raw` + 4
  `/emg/norm` messages). Set it to 1 for per-sample datagrams.
- IMU: 50 packets/s, one datagram per packet with all enabled IMU streams bundled.
- Measured with the mock on an M-series Mac: notification-to-datagram latency 0.2–0.5 ms,
  GUI 60 fps with two bands, 0 dropped samples. Real BLE adds the connection interval (the
  Myo asks for 7.5 ms) and CoreBluetooth's notification batching.
- The monitor's `DROP` counter estimates missing EMG samples per second from the expected
  200 sps; `LAT` is the running mean from notification to OSC send.

## BLED112 dongle

The Bluegiga **BLED112** USB dongle (the one that shipped with the Myo, and what Myo Connect
itself used) is an alternative to the Mac's Bluetooth: a separate radio driven over a serial
port with BGAPI, independent from CoreBluetooth and from macOS's Bluetooth permission.

- Choose it in *SETTINGS → CONNECTION* (adapter, port with `auto-detect` and `REFRESH`, a line
  saying whether a BLED112 is plugged in), with `--transport bled112 [--port /dev/cu.usbmodem…]`
  on the command line, or with `transport = "bled112"` / `dongle_port` in `config.toml`.
  Switching adapter disconnects every band; slots bound by serial find their band again.
- Auto-detection looks for USB VID:PID `2458:0001` (or a "BLED112" / "Low Energy Dongle"
  description) and uses the `/dev/cu.*` node. `osa-myo ports` lists the candidates.
- The port is opened exclusively: if Myo Connect or another copy of the bridge holds it, the
  error says so instead of both programs fighting over the dongle.
- One dongle serves up to 3 bands (stock firmware), sharing one reader thread. On open the
  bridge stops any scan and drops links left over by a previous run.
- Robustness: responses and events are matched by waiters registered before each command;
  scans and connects are serialised; ATT procedures are serialised per link and abort at once
  on a link loss; indications that need a confirmation get one; unplugging the dongle turns
  every band into *reconnecting* until it is plugged back in.
- Requires `pyserial` (the `dongle` extra; bundled in the .app).

Status: exercised end to end against a simulated dongle that emulates the BGAPI firmware and
the Myo's GATT table (`tests/test_bled112.py`: scan, discovery, streaming, two bands, link
loss, unplug/replug, power off, errors). **Not hardware-verified yet.**

## Building the .app

```bash
sh packaging/build_app.sh          # -> "dist/OSA MYO Controller.app" + dist/OSA-MYO-Controller.dmg
```

The bundle's `Info.plist` contains `NSBluetoothAlwaysUsageDescription`, so double-clicking it
asks for Bluetooth permission once and then works without a terminal. It opens the monitor and
auto-connects the configured slots; the CLI is still available as
`"dist/OSA MYO Controller.app/Contents/MacOS/osa-myo-controller" scan`. Set `CODESIGN_IDENTITY` to sign with a
Developer ID for distribution. py2app works as well (`py2app` with the same plist keys) but is
not maintained here.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `scan` finds nothing | Band asleep: move/tap it, or plug into USB and unplug. Band connected to another app: quit it. Bluetooth off. |
| Process dies silently on `scan` | Launched from a host without Bluetooth usage description (see *macOS Bluetooth permission*). Use Terminal.app or the .app. |
| `connect failed: … timeout` repeatedly | macOS holds a stale pairing: *System Settings → Bluetooth*, forget the Myo if listed; toggle Bluetooth off/on. Old trick from FreeMyo: let the band's battery run flat to clear its own bond table. |
| Connects, no EMG | EMG mode 0 or band locked? Check `SETTINGS → DEVICES` modes and `UNLOCK`. In `dump` look for `emg` lines. |
| EMG `smooth` shows nothing | The band's firmware does not send this undocumented mode (the EMG panel says so after 2 s): use `filt.` or `raw`. |
| `/emg/smooth` does not arrive | A config saved before smooth EMG was sent by default has `fv = false`: `SETTINGS → STREAMS`. |
| IMU and Orientation stand still | IMU mode `evt` sends tap events only (by design) or `off`: use `all` (or `data`). |
| Taps fire too easily | The firmware's detector can't be tuned: `tap threshold` (IMU mode `all`) and/or `tap cooldown` in `SETTINGS → PROCESSING`; the event feed shows each tap's `strength_g`. |
| Double tap does not set the origin | `2× TAP → ORIGIN` on for that band? POSE `on`, band synced and unlocked, IMU `data` or `all`; the event feed shows the `double_tap` pose. `no IMU data, origin not set` in the event feed: IMU `evt` / `off`, or the stream stopped. |
| Poses never arrive | Not synced: perform wave-out-and-hold. `arm unknown` in the header means unsynced. If `SYNC` stays off, press `RE-SYNC` and sync again. |
| Poses are unreliable | Snug fit on the widest part of the forearm; wear it a few minutes before syncing (`cold` in the sync event); `RE-SYNC`; check `LOCK` shows unlocked. Comparing EMG `filtered` with `raw` is a hardware test still to do (see *Known unknowns*). |
| `sync_failed` / `failed_too_hard` | The sync gesture was too strong: relax the hand and hold a gentler wave out. |
| Arm view points the wrong way | Sync (gives the x-direction), point at the screen, `SET ORIGIN`; `FLIP` if hand and elbow are swapped; pick the camera with `VIEW`. |
| EMG looks flat | Scale ±8 / ±16, or `AUTO`. |
| Band does not wake up | After `POWER OFF` (deep sleep) or a flat battery only USB power wakes it. |
| No BLED112 found | `osa-myo ports` / `REFRESH` in *SETTINGS → CONNECTION*; try another USB port without a hub. |
| `cannot open … in use by another program` | Quit Myo Connect or the other copy of the controller that holds the dongle. |
| Yaw drifts | Expected (no magnetometer). Use `SET ORIGIN` / `/myo/1/zero` before each piece. |
| `DROP` counts up | Distance / interference: move the Mac closer, remove USB 3 hubs next to the antenna. Also try `emg_mode = 2`. |
| Band goes to sleep mid-performance | `never_sleep` is sent on connect and refreshed every 10 s; check the `SLEEP` button says `NEVER SLEEP`. |
| OSC arrives in bursts | EMG bundles of 4 = 20 ms. Set `emg_bundle_samples = 1`. |
| `Address already in use` on 7401 | Another instance or Max `udpreceive 7401`. Change `[osc_in] port`. |

Verbose logging: add `-v` to any command.

## Known unknowns

Things that only a physical armband can confirm. Each has a check in
[docs/hardware-tests.md](docs/hardware-tests.md).

1. **Byte order.** `myohw.h` says big-endian; every implementation uses little-endian. We use
   little-endian. Firmware must read `1.5.x.y` and the quaternion norm must be ≈ 1.
2. **Quaternion order.** The header's struct is `w x y z`; pyomyosc reorders as if the band sent
   `x y z w`. We keep `w x y z`: at rest, lying flat, `w` must dominate.
3. **Euler axis mapping** (roll about the forearm, pitch up/down, yaw heading) and sign.
4. **Classifier event length.** Header: 3 bytes; the band sends 6. We parse the first 3 and,
   on `arm_synced`, byte 3 as the warm-up state (libmyo: unknown / cold / warm). Event `0x07`
   (absent from the header) is parsed as the warm-up result (unknown / success / timeout).
5. **Serial byte order.** We print the 6 bytes reversed (`d2-b5-…`) like MyoDiagnostics; the
   sticker inside the band tells.
6. **RSSI after connecting.** bleak's CoreBluetooth backend exposes `readRSSI`; if it does not
   update, the last scan value is shown.
7. **vibrate2 length** (18 bytes per header) and the undocumented `set_led` command.
8. **Sleep restore**: the band must sleep after quitting.
9. **BLED112 backend** end to end (tested against a simulated dongle only).
10. **Unlock gating.** Only the SDK documents that a locked band withholds poses; the bridge
    unlocks (hold) on connect and after each sync anyway, which is harmless if the firmware
    does not gate.
11. **Re-sync by toggling the classifier.** `myohw.h` says disabling the classifier resets its
    state; whether the band emits `arm_unsynced` (the bridge reports it anyway) and needs a new
    sync gesture must be checked.
12. **Raw EMG and the classifier.** No source says EMG mode 3 (raw) degrades pose recognition;
    some libraries pair the classifier with mode 2 (filtered). Compare both on hardware.
13. **Smooth EMG** (mode 1, undocumented): whether every firmware sends it, and its range
    (nominally 0..1024; the plot scale goes up to 2048).
14. **Tap strength.** The threshold's scale (largest change of acceleration between two 50 Hz
    samples around the tap) has to be calibrated on a band; motion and tap events may also
    arrive with different delays.
