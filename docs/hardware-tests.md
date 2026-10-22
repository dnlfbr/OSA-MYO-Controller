# Hardware test checklists

Nothing in this project is "verified on hardware" until you have run these. The mock device
only proves the software path. Run every command from **Terminal.app or iTerm** (not from an
IDE or the Claude desktop app's shell): macOS kills any process that touches CoreBluetooth
when its parent app has no `NSBluetoothAlwaysUsageDescription`. The first run shows a
"would like to use Bluetooth" prompt for the terminal app; allow it (System Settings >
Privacy & Security > Bluetooth).

```bash
cd "<project folder>"
source .venv/bin/activate
```

## M1 - BLE connection, commands, parsing (`scan`, `dump`)

Wake the Myo first: plug it into USB for a second or tap the logo; the logo pulses blue while it
advertises. Then:

```bash
osa-myo scan
```

- [ ] A line with name `Myo` (or your custom name), an RSSI around -40..-70 and a UUID.
      If nothing appears: see README troubleshooting (sleeping Myo, stale pairing).

```bash
osa-myo dump --duration 60
```

Look at the output and tick:

- [ ] `log connected: ... fw=1.5.xxxx (rev_d)` - firmware reads as **1.5.something** with rev_d
      (retail unit). Any other number means byte order or struct layout is wrong - report it.
- [ ] `serial=xx-xx-xx-xx-xx-xx` - compare with the MAC Myo Connect/MyoDiagnostics used to show.
      If it is the same bytes in the opposite order, tell me (the display order is a guess).
- [ ] `batt NN%` matches the LED/charger expectation.
- [ ] `imu quat ... |q|=1.000` - the norm must stay within 0.98..1.02. If not, scaling is wrong.
- [ ] With the Myo flat on a table, logo up, `w` should dominate (> 0.7); `acc` ≈ (0, 0, ±1) g
      (gravity on one axis, ~1.0). Tell me **which axis** carries gravity and its sign.
- [ ] Turn the band 90° about its long axis: a different accel axis gets the ±1 g.
- [ ] Spin it slowly: `gyro` values of a few hundred deg/s on the rotation axis, back to ~0 at rest.
- [ ] `stats emg 200.0 sps (per char [n n n n])` - 200 ±3 samples/s, the four counters grow at
      the same pace, `dropped~0` after 60 s (a few at the start are fine). Report the numbers.
- [ ] At rest, EMG values are small (|v| < 15). Make a fist: several channels reach ±80..127.
- [ ] Perform the sync gesture (wave out, hold until the vibration): a `class arm_synced
      arm=right|left xdir=wrist|elbow` line appears, then `unlocked`, then poses as you gesture:
      `pose pose=fist`, `wave_in`, `wave_out`, `fingers_spread`, `double_tap`, back to `rest`.
      Note the `raw=... (N B)` length printed: I expect 6 bytes.
- [ ] Remove the band: `arm_unsynced`.
- [ ] Double-tap the band while unlocked: `locked`; the `lock=` field in stats follows.
- [ ] Shake/tap quickly with IMU mode 3 (default): optional `motion` lines (tap events).
- [ ] After the 60 s it prints `shutting down (restoring sleep mode)`. Leave the Myo alone:
      it must go to sleep (logo off) within ~1 minute. If it stays awake, sleep restore failed.

Optional checks:

```bash
osa-myo dump --emg 1 --show-emg --duration 10     # undocumented 50 Hz "smooth" mode
osa-myo dump --emg 2 --duration 10                 # filtered 200 Hz mode
```

- [ ] mode 1: `fv` lines with 8 values 0..~1024 at ~50/s. mode 2: same as raw but smoother.

Also try `scan` while the Myo is already connected to another app: it should not be listed.

## M2 - OSC output (`run --no-gui`)

Terminal 1: `python examples/osc_receiver.py 7400` (or open `examples/myo_receiver.maxpat` in Max).
Terminal 2: `osa-myo run --no-gui` (add `-v` for details). Then:

- [ ] Receiver shows `/myo/1/emg/raw` at ~200 msg/s (8 ints), `/myo/1/quat`, `/euler`, `/accel`,
      `/gyro` at ~50 msg/s, `/emg/rms` and `/emg/mav` at ~50 msg/s.
- [ ] `/myo/1/status streaming`, `/myo/1/firmware 1.5.x.y`, `/myo/1/battery NN` on connect.
- [ ] Sync gesture -> `/myo/1/sync 1`, `/myo/1/arm right|left`, `/myo/1/xdir wrist|elbow`,
      then `/myo/1/lock 0`; poses -> `/myo/1/pose fist` + `/myo/1/pose/id 1`, etc.
- [ ] Hold the arm still: `/myo/1/euler` yaw drifts slowly over minutes (expected; the IMU has
      no magnetometer). Send `/myo/1/zero` from Max (port 7401) -> yaw snaps to 0; roll/pitch unchanged.
- [ ] Rotate the forearm about its own axis -> **roll** changes; raise/lower the hand -> **pitch**;
      swing left/right -> **yaw**. If the axes come out permuted or inverted, tell me which, and
      whether the band was worn with the logo toward the wrist or the elbow.
- [ ] Send `/myo/1/vibrate 2` -> medium vibration. `/myo/1/lock` -> `/myo/1/lock 1` comes back.
      `/myo/1/mode 2 1 1` -> EMG becomes filtered (smoother trace), IMU data only.
- [ ] The stats line printed every 5 s: `emg 200sps drop 0`, `lat` (notification -> datagram)
      under 2 ms. Report the numbers after a 10 minute run; `drop` must stay 0 or tiny.
- [ ] Walk 5-8 m away until the link drops: `/myo/1/status reconnecting`; come back: it
      reconnects on its own and streams again (`status streaming`, EMG resumes).

## M3 - monitor GUI (`run` / `monitor`)

Start from Terminal.app: `osa-myo run` (auto-connects the first Myo found) or
`osa-myo monitor` then SCAN, double-click your Myo, CONNECT.

- [ ] Window opens dark-themed; sidebar row turns green "STREAMING · PRIMARY · NN%" within ~5 s.
- [ ] Header: STATUS STREAMING, serial `xx-xx-xx-xx-xx-xx` matches the sticker inside the band
      (reverse order is a known unknown: tell me if it is reversed), firmware `1.5.x.y`.
- [ ] BATTERYLIFE matches the LED/Myo app value; BLUETOOTHSIGNAL bars update about once a second
      and drop when you walk away (RSSI after connect depends on CoreBluetooth; if the bars never
      change, report it and I will fall back to scan RSSI).
- [ ] EMG grid: flat +-5..10 at rest, +-100 on a fist, pod numbers follow the band around the arm
      (pod0 next to the logo?). Change window to 0.5 s and scale to +-32; "auto" fits the trace; PAUSE freezes.
- [ ] ORIENTATION 3D: the orange face must point toward your hand. Rotate the forearm about its
      axis -> ROLL; raise the hand -> PITCH; turn left/right -> YAW. Press SET ORIGIN while pointing
      forward -> YAW reads ~0; CLEAR restores raw yaw. Report any permuted or inverted axis.
- [ ] IMU strips: accelerometer shows ~1 g on one axis at rest; gyro returns to 0 when still.
- [ ] Gesture feed: hint "perform the sync gesture" disappears after wave-out-and-hold; tiles light
      up for fist / wave_in / wave_out / fingers_spread / double_tap; event feed logs each
      `pose`, `arm_synced`, `unlocked`, `locked`, `battery_level`, `warmup_completed`.
- [ ] Manual Overrides: SHORT/MEDIUM/LONG vibrate as named; LOCK -> header says LOCKED and
      poses stop; UNLOCK -> they resume. EMG mode "filtered" smooths the trace, "off" flattens it
      (EMG Hz goes to 0, DROP must not count while off). IMU "events" -> strips freeze, taps still log.
- [ ] Signal panel: EMG Hz ~200, IMU Hz ~50, DROP 0 over a 10 minute session, LAT under ~2 ms;
      status bar "gui ~60 fps" with two armbands streaming.
- [ ] Two armbands: `osa-myo run -n 2`; both rows green; clicking a row switches every panel
      to that band; OSC ids `/myo/1/...` and `/myo/2/...` stay bound to the same physical band
      after a reconnect (compare serials).
- [ ] Close the window: status bar says "disconnecting"; within a minute of being still the
      Myo's LED pulse shows it went to sleep (sleep mode restored).

## M4 - two armbands, settings, config

- [ ] `osa-myo run -n 2` with both bands on: both rows green. Open SETTINGS > DEVICES: each
      slot shows the serial it got. APPLY + SAVE. Quit, swap the bands' power-on order (or move
      one out of range during startup) and `osa-myo run` again: `/myo/1/...` still comes
      from the same physical band (compare serials in the header). If a slot reports
      "no Myo with serial ... among N found", tell me what the header showed for that band.
- [ ] SETTINGS > OSC: preset `myomapper` + APPLY: Max receives `/myo1/orientation/quaternion`
      etc. immediately, no restart. Back to `default`. Mode `axis`: `/myo/1/accel/x`.
- [ ] STREAMS: untick `emg_raw`, tick `emg_norm`: receiver switches streams live.
- [ ] PROCESSING: SET ORIGIN mode `full`, press SET ORIGIN with the arm in a pose: quaternion
      reads ~1 0 0 0 and the cuboid is level; `yaw` mode: only YAW returns to 0.
- [ ] Press SET ORIGIN, SAVE CONFIG, quit, restart: YAW starts from the saved reference
      (`zero_quat` in config.toml) instead of raw heading.
- [ ] Send `/myo/all/vibrate 1` from Max: both bands buzz. `/myo/2/zero`: only band 2 re-centres.

## M5 - packaged app, Max patch, dongle

- [ ] `sh packaging/build_app.sh`, then double-click `dist/OSA MYO Controller.app` from Finder: macOS
      asks for Bluetooth permission once; the monitor opens and connects the band (no terminal).
      If it bounces and quits, open Console.app, filter "osa-myo-controller", and send me the crash reason.
- [ ] Open `examples/myo_receiver.maxpat` in Max with `osa-myo run` going: multisliders move
      with the EMG, number boxes follow the orientation, pose message updates; click
      `/myo/1/vibrate 3` -> long buzz; `/myo/1/zero` -> yaw box reads ~0.
- [ ] (Only with a BLED112 dongle) see *Field fixes - BLED112 dongle* below.
- [ ] After every session: the band's logo stops pulsing within a minute of being still
      (sleep mode restored) and it wakes on tap for the next run.

## Field fixes - after the first hardware session

These cover the fixes made after the first run with real bands. They were tested only with
the mock and a simulated dongle.

### Settings and config file

- [ ] Change a setting (e.g. OSC port), APPLY + SAVE, quit, start the app again: it starts and
      keeps the setting (this used to crash until `config.toml` was deleted).
- [ ] Quit, add a broken line such as `port = "abc"` under `[osc]` in
      `~/Library/Application Support/osa-myo-controller/config.toml`, start: the app starts, the event
      feed shows a warning naming `osc.port`, the port is back to 7400.
- [ ] Replace the whole file with garbage (`[[[`), start: the app starts with the defaults, the
      event feed says the file could not be read and a `config.toml.broken-<date-time>` copy
      sits next to it.

### Arm view (Orientation)

- [ ] Before the sync the hint under the drawing says `band direction: not synced yet`. After
      the sync it says `band +x → wrist (sync)` or `→ elbow`; note which, and whether the logo
      was toward the wrist or the elbow.
- [ ] VIEW `BEHIND`: point at the screen, SET ORIGIN: the hand points into the screen. Raise
      the arm: the model rises. Turn the arm left: the model turns left. Rotate the forearm
      (palm up / palm down): the model rolls the same way. Report anything mirrored.
- [ ] `SIDE`, `TOP`, `MIRROR` behave as their tooltips say. SAVE CONFIG keeps the view.
- [ ] If the hand points back at you after SET ORIGIN, FLIP fixes it: tell me the
      x-direction the sync reported, so the default can be corrected.
- [ ] Hold the band still in three positions (flat logo up, on its side, hanging) during
      `osa-myo dump --duration 20` and send me the output: the quaternion must rotate the
      accelerometer's gravity onto the vertical in all three (checks the quaternion order and
      the frame the arm view assumes).

### EMG scale

- [ ] SCALE ±8 or ±16 shows the resting signal clearly; ±128 holds a full fist. Note typical
      peak values at rest and on a fist.
- [ ] AUTO: each `POD n ±x` tag shows its own range; a fist widens the ranges within a second,
      they shrink back over a few seconds after release. SAVE CONFIG keeps scale and AUTO.

### Sync, unlock, poses

- [ ] The bridge sends unlock on every connect: note whether `unlocked` appears in the feed.
- [ ] Sync: `arm_synced` (with `warmup` cold or warm if the firmware reports it), then
      `unlocked`. Poses arrive without any double-tap. Note whether the band vibrates by itself
      on sync (the bridge does not send a vibration then).
- [ ] If the sync event said `cold`: does a `warmup_completed` with `success` follow after a
      few minutes? Are poses noticeably better after it?
- [ ] A forced sync gesture: `sync_failed` with `failed_too_hard`?
- [ ] RE-SYNC: a short buzz, `SYNC` turns off, `arm_unsynced` in the feed; a new wave out syncs
      again. Same with `/myo/1/resync` over OSC.
- [ ] Pose reliability with EMG `raw 200 Hz` (default) versus `filtered`: same, better or
      worse? (No source says raw mode affects the classifier; this settles it.)

### Power off

- [ ] POWER OFF asks for confirmation; after it the logo goes dark, the slot shows
      disconnected and the log shows no reconnect attempts.
- [ ] The band is not listed by `scan` even when moved or tapped; plugging it into USB wakes it.
- [ ] `/myo/1/poweroff` without an argument is ignored; `/myo/1/poweroff 1` switches it off.

### BLED112 dongle

- [ ] Plug the dongle in. `osa-myo ports` lists a `/dev/cu.usbmodem…` port marked
      `<- BLED112`. SETTINGS > CONNECTION shows `BLED112 detected on /dev/cu.usbmodem…`.
- [ ] `osa-myo scan --transport bled112` lists the Myo with a MAC address and an RSSI.
      Report the first error verbatim if anything fails: this backend has never seen hardware.
- [ ] In the GUI choose `BLED112 USB dongle`, APPLY + SAVE, CONNECT ALL: the band streams with
      EMG Hz ~200, IMU Hz ~50, DROP 0 over 10 minutes; battery and LINK update.
- [ ] Sync, poses, vibrate, LOCK/UNLOCK, RE-SYNC and POWER OFF work as with the built-in
      Bluetooth.
- [ ] Two bands on one dongle (`-n 2`): both stream, DROP stays 0 (report EMG Hz per band).
- [ ] Walk out of range: `reconnecting`, then back to streaming. Unplug the dongle: both bands
      go to `reconnecting`; plug it back: they stream again without restarting the app.
- [ ] With the old Myo Connect (or a second copy of the bridge) holding the dongle, connecting
      fails with `in use by another program`.
- [ ] Switch back to `Built-in Bluetooth`: slots bound by serial find the same bands again.

## Field feedback, second round - modes, taps, names, windows

Tested only with the mock. Use the packaged app or Terminal.app.

### EMG smooth and IMU evt

- [ ] Controls → MODES `EMG smooth`: the EMG grid switches to a 0..1024 scale and moves; LINK
      shows EMG Hz ~50. Note typical values at rest and on a fist (the scale's nominal top is
      1024: does a fist reach it, or pass it?). If nothing arrives, the panel says so after
      2 s: tell me the firmware version shown in the header.
- [ ] With `fv` on in SETTINGS → STREAMS, Max receives `/myo/1/emg/smooth` (8 ints, 50/s).
      Untick it: the event feed warns on the next connect.
- [ ] `IMU evt`: IMU and Orientation show the note "the band sends only tap events" and stay
      still; knocks on the band appear in Events as `tap` with `strength_g` `n/a`.

### Taps

- [ ] `IMU all`, threshold off: knock lightly on the pods ten times, then firmly ten times.
      Note the `strength_g` of each kind and send me the numbers (they set a sensible default).
      Does any firm knock show a small value or `n/a`? (Then the IMU samples arrive later
      than the tap event and the measuring window must grow.)
- [ ] Set `tap threshold` between the two groups: light knocks are greyed with `ignored`, firm
      ones are sent to `/myo/1/tap` (check the delay feels fine: about 60 ms more).
- [ ] `tap cooldown` 300 ms: a quick double knock gives one tap.
- [ ] Do walking, arm swings or putting the arm down on a table trigger taps? With which
      strength?

### Double tap → origin

- [ ] Gesture → `2× TAP → ORIGIN` on. After sync, turn the body, make the double-tap pose:
      the band vibrates once, Orientation's yaw goes back to 0, Events shows `zero` with
      `"by": "double tap"`. Holding or repeating the pose within a second sets it once.
- [ ] Off: the double tap is only a pose. SAVE CONFIG keeps the toggle per band.
- [ ] IMU `evt`: the double tap only logs `double tap: no IMU data, origin not set`, no
      vibration; `SET ORIGIN` shows the same in the status bar; `/myo/1/zero` logs `OSC: …`.

### Names and windows

- [ ] Double-click a band in the sidebar, give it a name: sidebar, header and extra windows
      show it; SAVE CONFIG, restart: the name is still there. The band itself keeps its
      Bluetooth name (scan shows it).
- [ ] Two bands: NEW WINDOW shows the second band while the main window shows the first; both
      stream at full rate (EMG Hz ~200 each, DROP 0), GUI FPS stays near 60. Two extra windows
      side by side on the laptop screen fit without overlapping.
