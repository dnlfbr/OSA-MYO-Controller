# Myo BLE protocol as implemented by OSA MYO Controller

Source of truth: Thalmic's `myohw.h` (Apache-2.0, 2015), cross-checked against pymyo,
pyomyo, FreeMyo.py, dl-myo and myonnaise. Code: `src/myo_bridge/myo/protocol.py`.
Everything is **little-endian** (see *Disagreements*).

## GATT layout

Base UUID `d506XXXX-a904-deb9-4748-2c7f4a124842`, `XXXX` below.

| Service | Characteristic | UUID | Props | Payload |
|---|---|---|---|---|
| Control `0001` | MyoInfo | `0101` | read | 20 bytes `<6sH5B7x`: serial[6], unlock_pose u16, active_classifier_type, active_classifier_index, has_custom_classifier, stream_indicating, sku |
| | FirmwareVersion | `0201` | read | `<4H`: major, minor, patch, hardware_rev |
| | Command | `0401` | write | `[cmd, payload_len, payload…]` |
| IMU `0002` | IMUData | `0402` | notify | 20 bytes `<10h`: quat w x y z, accel x y z, gyro x y z |
| | MotionEvent | `0502` | indicate | `<3B`: type, tap_direction, tap_count |
| Classifier `0003` | ClassifierEvent | `0103` | indicate | `<B2s`…: type, then per type (see below) |
| FV `0004` | FVData | `0104` | notify | 17 bytes `<8Hb`: 8 × u16 "preprocessed EMG", mask. Undocumented, EMG mode 1 |
| EMG `0005` | EmgData0..3 | `0105 0205 0305 0405` | notify | 16 bytes `<16b`: two consecutive samples × 8 pods |
| Battery `180F` | BatteryLevel | `2A19` | read, notify | u8 % |
| Generic Access `1800` | DeviceName | `2A00` | read | UTF-8 |

Discovery: the band advertises the control service UUID `d5060001-…` (complete 128-bit list)
and a local name (`Myo` or the user-set name). We treat a device as a Myo if either matches.

## Commands (write to `0401`, with response)

| Cmd | Id | Payload | Notes |
|---|---|---|---|
| set_mode | `0x01` | `emg, imu, classifier` (3) | EMG 0 none, 1 "send_emg" (FV, 50 Hz), 2 filtered, 3 raw; IMU 0 none, 1 data, 2 events, 3 all, 4 raw; classifier 0/1 |
| vibrate | `0x03` | `type` (1) | 1 short, 2 medium, 3 long |
| deep_sleep | `0x04` | none | **never sent automatically**: only on `POWER OFF` / `/poweroff 1`. Only USB wakes the band; it may drop the link before acknowledging |
| set_led | `0x06` | `logo r g b, bar r g b` (6) | undocumented, used by Myo Connect |
| vibrate2 | `0x07` | 6 × (`duration u16 ms`, `strength u8`) = 18 | header length 18 (pymyo sends 20) |
| set_sleep_mode | `0x09` | `mode` (1) | 0 normal, 1 never sleep |
| unlock | `0x0A` | `type` (1) | 0 lock, 1 timed, 2 hold |
| user_action | `0x0B` | `type` (1) | 0 single |

Writes are serialised on one lock with 20 ms spacing (MioConnect's `MESSAGE_DELAY`). On
connect: read firmware, info, name, battery; subscribe IMU, EMG0-3, FV, classifier, motion,
battery; `set_sleep_mode(1)`; `set_mode(emg, imu, cls)`; `unlock(hold)` when the classifier is
on; `vibrate(short)`. After every `arm_synced`: `unlock(hold)` (see *Lock and poses*). A
keep-alive re-sends `set_sleep_mode(1)` every 10 s (myonnaise). On disconnect:
`set_mode(0,0,0)`, `set_sleep_mode(0)`, then drop the link.

Re-sync (`RE-SYNC`, `/resync`): `set_mode(emg, imu, 0)`, 300 ms, `set_mode(emg, imu, 1)`,
`vibrate(short)`. `myohw.h` says that disabling the classifier resets its internal state, so
the band forgets the arm and waits for a new sync gesture; the bridge reports `arm_unsynced`
itself in case the firmware stays silent. No library or SDK call does this; it is a hardware
check.

Power off (`POWER OFF`, `/poweroff 1`): stop the reconnect loop, `deep_sleep`, drop the link.

## Scaling

| Quantity | Raw | Scale | Unit |
|---|---|---|---|
| orientation | int16 ×4 | ÷ 16384 | unit quaternion (w x y z) |
| accelerometer | int16 ×3 | ÷ 2048 | g |
| gyroscope | int16 ×3 | ÷ 16 | deg/s |
| EMG | int8 ×8 | ÷ 128 for `norm` | −1..1 |
| FV | u16 ×8 | none | 0..~1024 reported by pyomyo |

Rates: IMU 50 Hz; EMG 200 samples/s delivered as 100 notifications/s (2 samples each)
rotating over the 4 EMG characteristics; FV 50 Hz.

## Classifier events (`0103`)

First byte = type; the next bytes depend on it. The header defines a 3-byte struct; the band
sends 6 (`<B2s`, `<6B` in other implementations). We read `type` and then:

| Type | Name | Fields |
|---|---|---|
| 1 | arm_synced | arm (1 right, 2 left, 255 unknown), x_direction (1 toward wrist, 2 toward elbow); byte 3 warm-up state (0 unknown, 1 cold, 2 warm; libmyo, firmware 1.5+); bytes 4-5 a rotation u16, not decoded |
| 2 | arm_unsynced | |
| 3 | pose | pose u16 LE: 0 rest, 1 fist, 2 wave_in, 3 wave_out, 4 fingers_spread, 5 double_tap, 0xFFFF unknown |
| 4 | unlocked | |
| 5 | locked | |
| 6 | sync_failed | sync_result (1 = failed too hard) |
| 7 | warmup_completed | warm-up result: 0 unknown, 1 success, 2 failed (timeout). Not in the 2015 header; libmyo's `warmup_completed` event, expected only after a cold sync |

### Lock and poses

The SDK's locking policy says that poses are withheld while the band is locked (*standard*)
or always sent (*none*). Nothing shows whether the firmware itself withholds them: myo-raw,
pyomyo and Open-Myo never send `unlock` and still get poses after a sync. FreeMyo and
MyoBridge (vroland) send `unlock(hold)`, `0A 01 02`. We send it on connect (a band still synced
from an earlier link sends no new `arm_synced`) and after every `arm_synced`; it is harmless if
the firmware does not gate. `unlock_on_sync = False` (device config) turns this off.
`LOCK` / `/lock` sends `0A 01 00`.

Motion events (`0502`): type 0 = tap, with direction and count (the meaning of the
direction values is not documented). The detector runs on the band and `myohw.h` has no
setting for it. The bridge estimates each tap's strength from the IMU stream (largest change
of the acceleration vector between consecutive 50 Hz samples, from 120 ms before to 60 ms
after the event) and filters taps in software on strength and spacing (`tap_threshold_g`,
`tap_cooldown_ms`). Taps arrive in IMU mode 2 (events, no motion data) or 3 (all).

## Euler angles

`roll = atan2(2(wx + yz), 1 − 2(x² + y²))`, `pitch = asin(2(wy − zx))`,
`yaw = atan2(2(wz + xy), 1 − 2(y² + z²))`, the formulas from Thalmic's `hello-myo` sample.
Roll is rotation about the forearm (x) axis, pitch about y, yaw about the vertical (z).

Orientation zero: mode `yaw` stores `yaw_only(q)` and applies `conj(ref) · q`, so only the
heading is re-centred; mode `full` stores `q` itself. MyoMapper's `Yaw/calibrate` corresponds
to `yaw`.

## Frames and the arm view

- Sensor frame: +x along the forearm, toward the wrist or toward the elbow (the sync's
  `x_direction`; the SDK does not compensate it); +z out of the logo pod (band normal); y
  completes the right-handed frame. Thalmic's Unity sample maps Myo (x, y, z) to Unity
  (right, up, forward) as (y, z, −x), consistent with this.
- World frame: +z up (gravity); the heading is arbitrary until `SET ORIGIN`, and drifts.
- The quaternion rotates sensor vectors into the world: `r = q · p · q⁻¹` (MyoMex).
- The monitor's arm model has +x toward the hand and +z out of the logo pod. When the band's
  +x points to the elbow the model is turned 180° about z (and the heading by 180°, so the hand
  still points forward after `SET ORIGIN`); `FLIP` does the same by hand. The default camera
  (`BEHIND`) looks over the wearer's shoulder along the zeroed forward direction.
- Accelerometer sign at rest is not documented (a MEMS normally reads +1 g on the axis that
  points up). Hardware check: the quaternion must rotate the at-rest accelerometer onto the
  world vertical in every pose; this also confirms the w x y z order.

## Disagreements between sources and what we do

| Topic | Sources | Decision | Hardware check |
|---|---|---|---|
| Byte order | header says big-endian; all implementations LE | LE | firmware reads 1.5.x.y, quaternion norm ≈ 1 |
| Quaternion field order | header / pymyo / dl-myo: w x y z; pyomyosc reorders assuming x y z w | w x y z | w ≈ 1 when the band is flat and still |
| Classifier payload length | header 3; pymyo `<B2s`; others 6 | parse first 3, accept ≥ 3; on `arm_synced` byte 3 = warm-up state (libmyo; only one Android library decodes bytes 3-5) | `dump` logs the raw bytes |
| Unlock | SDK-level gating; several libraries never unlock | `unlock(hold)` on connect and after each sync | poses arrive without a double tap |
| EMG mode with the classifier | pyomyo pairs the classifier with mode 2, raw mode 3 with classifier off; no source says mode 3 degrades poses | default mode 3 with classifier on | compare pose reliability in modes 2 and 3 |
| vibrate2 length | header 18; pymyo 20; dl-myo 3 | 18 | optional |
| Command write type | header "write"; implementations write-with-response | with response | — |
| Sleep | myonnaise re-sends every 10 s; others once | once + 10 s keep-alive, restore on exit | band stays awake 10 min, sleeps after quit |
| EMG mode 1 | undocumented; pyomyo: rectified ~0–1024 at 50 Hz on `0104` | supported as `emg_mode = 1` → `/emg/smooth` and the monitor's EMG grid (0..1024 scale) | range / rate, whether every firmware sends it |
| Pose 5 | header double_tap; pyomyo "thumb_to_pinky" | double_tap | — |
| Address | CoreBluetooth per-Mac UUID vs MAC | selector accepts name, UUID, serial | — |
| pyomyo "works without dongle" | its code is BLED112-only | bleak is the default; BLED112 is a selectable adapter | — |

## macOS notes

- Any process using CoreBluetooth must be launched by an app that declares
  `NSBluetoothAlwaysUsageDescription`; otherwise TCC kills it with SIGABRT. Terminal.app and
  iTerm2 do; the packaged `OSA MYO Controller.app` does.
- bleak exposes *indicate* characteristics through `start_notify` as well.
- CoreBluetooth caches GATT databases; after a firmware change forget the device in
  System Settings → Bluetooth.

## BLED112 (BGAPI)

`src/myo_bridge/transport/bgapi.py` frames packets (`[type|len_hi, len_lo, class, id,
payload]`) and `bled112_transport.py` drives `gap_discover`, `gap_connect_direct`
(interval 7.5 ms), `attclient_find_information` to map UUIDs to handles (and each `2902`
descriptor to the preceding value handle), `attclient_read_by_handle`,
`attclient_attribute_write` (commands and CCC subscriptions: `0100` notify, `0200`
indicate for the classifier and motion characteristics) and `connection_disconnect`.
Several connections share one dongle, keyed by connection handle.

Port and lifecycle:

- USB VID:PID `2458:0001`. On macOS use the `/dev/cu.usbmodem…` node (pyserial's `list_ports`
  reports it; the `tty.` twin is skipped). The dongle is a CDC device: 115200 baud, no flow
  control, and the baud rate does not matter.
- The port is opened with `exclusive=True` (POSIX lock). A port held by Myo Connect or another
  program fails with `EBUSY` / a lock error, and the message says so.
- One `Dongle` per port, shared by every band, with a reader thread that hands packets to the
  asyncio loop (`call_soon_threadsafe`). On open, a clean slate: `gap_end_procedure`,
  `gap_set_mode(0, 0)`, `connection_disconnect` for handles 0-2 (errors ignored); a port that
  does not answer is not a BLED112. The stock firmware allows 3 connections.
- If the reader fails (dongle unplugged), the pending command fails and every link is reported
  lost, so the bands go to *reconnecting* and come back when the dongle does.

Procedures:

- A waiter for the expected response or event is registered **before** the command is sent,
  so a fast answer cannot be missed. Commands are serialised; a non-zero result in a response
  raises (BGAPI error names in `bgapi.error_name`).
- Scan: `gap_set_scan_parameters`, `gap_discover(2)` (observation), stop with
  `gap_end_procedure`; scans and connects share one GAP lock because the dongle refuses one
  while the other is running. A `find` stops scanning as soon as the wanted band is seen.
- Connect: `gap_connect_direct`, then the `connection_status` event for that address with flags
  `connected | completed` (`& 0x05`). On timeout `gap_end_procedure` cancels the attempt.
  A device without the Myo control service is disconnected ("not a Myo").
- ATT procedures run one at a time per connection (the stack refuses a second one while one is
  pending). Writes and `find_information` end with `attclient_procedure_completed`. A read ends
  with `attclient_attribute_value` type 0; a `procedure_completed` without a value means the
  read failed; a success completion trailing the value (if some firmware sends one) is
  swallowed for 50 ms so the next write cannot take it.
- `attclient_attribute_value` types: 0 read, 1 notify, 2 indicate (confirmed by the stack),
  3 read_by_type, 4 read_blob, 5 indicate needing a confirmation: answered at once with
  `attclient_indicate_confirm`.
- A `connection_disconnected` event resolves the link's `lost` future: every pending procedure
  on it fails immediately instead of waiting for its timeout, and `on_disconnect` starts the
  reconnect loop (not for a disconnect we asked for).
