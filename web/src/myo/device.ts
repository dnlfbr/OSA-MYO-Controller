/** MyoDevice: connection state machine, configuration, streaming and command API.
 *
 * Port of src/myo_bridge/myo/device.py — keep the two in step. Transport-agnostic: parses
 * notifications with ./protocol and fans typed events out to listeners (UI, OSC out). */

import * as P from "./protocol";
import { Signal, TransportError, monotonic, sleep, type Transport } from "./transport";

export type DeviceState = "disconnected" | "connecting" | "connected" | "streaming" | "reconnecting";

export interface DeviceConfig {
  emgMode: P.EmgModeValue;
  imuMode: P.ImuModeValue;
  classifierMode: P.ClassifierModeValue;
  neverSleep: boolean;
  keepaliveS: number; // re-send never_sleep (myonnaise); 0 disables
  batteryPollS: number;
  rssiPollS: number;
  reconnect: boolean;
  reconnectBackoffS: number[];
  commandSpacingS: number; // MioConnect-style pause between writes
  vibrateOnConnect: boolean;
  unlockOnSync: boolean; // unlock(hold) after each sync so every pose is reported
}

export const defaultDeviceConfig = (): DeviceConfig => ({
  emgMode: P.EmgMode.RAW,
  imuMode: P.ImuMode.ALL,
  classifierMode: P.ClassifierMode.ENABLED,
  neverSleep: true,
  keepaliveS: 10,
  batteryPollS: 30,
  rssiPollS: 1,
  reconnect: true,
  reconnectBackoffS: [1, 2, 4, 8],
  commandSpacingS: 0.02,
  vibrateOnConnect: true,
  unlockOnSync: true,
});

export class DeviceStats {
  tConnect = 0;
  emgNotifications = 0;
  emgPerChar = [0, 0, 0, 0];
  emgSamples = 0;
  imuPackets = 0;
  fvPackets = 0;
  classifierEvents = 0;
  motionEvents = 0;
  lastEmgT = 0;
  lastImuT = 0;
  emgRateHz = 0; // samples/s measured over the last second
  imuRateHz = 0;
  fvRateHz = 0; // smooth EMG packets/s (EMG mode 1)
  emgDropped = 0; // estimated per 1 s window: expected 200 sps minus received
  emgExpectedHz = 0; // 0 while EMG is off
  winT0 = 0;
  winEmg = 0;
  winImu = 0;
  winFv = 0;

  tickWindow(now: number): void {
    if (this.winT0 === 0) {
      this.winT0 = now;
      return;
    }
    const dt = now - this.winT0;
    if (dt >= 1) {
      this.emgRateHz = this.winEmg / dt;
      this.imuRateHz = this.winImu / dt;
      this.fvRateHz = this.winFv / dt;
      if (this.emgExpectedHz && this.winEmg) {
        const missing = this.emgExpectedHz * dt - this.winEmg;
        if (missing > 3) this.emgDropped += Math.trunc(missing); // tolerate jitter at the window edge
      }
      this.winT0 = now;
      this.winEmg = this.winImu = this.winFv = 0;
    }
  }
}

export class MyoDevice {
  state: DeviceState = "disconnected";
  stats = new DeviceStats();
  readonly config: DeviceConfig;

  // device facts
  address = "";
  name: string | null = null;
  firmware: P.FirmwareVersion | null = null;
  info: P.FirmwareInfo | null = null;
  battery: number | null = null;
  rssi: number | null = null;
  arm: number = P.Arm.UNKNOWN;
  xDirection: number = P.XDirection.UNKNOWN;
  synced = false;
  locked = true;
  pose: number = P.Pose.REST;
  lastImu: P.ImuPacket | null = null;
  lastEmg: P.EmgSample | null = null;

  // events
  readonly onState = new Signal<[DeviceState]>();
  readonly onEmg = new Signal<[P.EmgSample, number]>(); // one 8-channel sample, t (s)
  readonly onEmgPacket = new Signal<[[P.EmgSample, P.EmgSample], number]>();
  readonly onFv = new Signal<[P.FvPacket, number]>();
  readonly onImu = new Signal<[P.ImuPacket, number]>();
  readonly onClassifier = new Signal<[P.ClassifierEvent, number]>();
  readonly onMotion = new Signal<[P.MotionEvent, number]>();
  readonly onBattery = new Signal<[number]>();
  readonly onRssi = new Signal<[number]>();
  readonly onLog = new Signal<[string]>();

  private cmdChain: Promise<unknown> = Promise.resolve();
  private timers: ReturnType<typeof setInterval>[] = [];
  private userDisconnect = false;
  private reconnecting = false;

  constructor(readonly transport: Transport, readonly id = 1, config: Partial<DeviceConfig> = {},
              private readonly clock: () => number = monotonic) {
    this.config = { ...defaultDeviceConfig(), ...config };
  }

  // ------------------------------------------------------------------ state helpers
  private setState(s: DeviceState): void {
    if (s !== this.state) {
      this.state = s;
      this.onState.emit(s);
    }
  }

  private log(msg: string): void {
    this.onLog.emit(msg);
  }

  get label(): string {
    return this.name || this.address || `myo${this.id}`;
  }

  // ------------------------------------------------------------------ lifecycle
  async connect(timeoutS = 20): Promise<void> {
    this.userDisconnect = false;
    this.setState("connecting");
    try {
      await this.transport.connect(() => this.onTransportDisconnect(), timeoutS);
    } catch (e) {
      this.setState("disconnected");
      throw e;
    }
    this.address = this.transport.address;
    this.stats = new DeviceStats();
    this.stats.tConnect = this.clock();
    this.setState("connected");
    try {
      await this.configure();
    } catch (e) {
      // don't keep a half-configured link: the next attempt would open a second one
      if (this.transport.isConnected) {
        try {
          await this.transport.disconnect();
        } catch {
          /* already gone */
        }
        this.setState("disconnected");
      }
      throw e;
    }
    this.setState("streaming");
    this.startBackground();
  }

  private async configure(): Promise<void> {
    const t = this.transport;
    const cfg = this.config;
    // identity
    try {
      this.firmware = P.parseFirmwareVersion(await t.read(P.UUIDS.FIRMWARE));
    } catch (e) {
      this.log(`firmware read failed: ${errText(e)}`);
    }
    try {
      this.info = P.parseFirmwareInfo(await t.read(P.UUIDS.INFO));
    } catch (e) {
      this.log(`info read failed: ${errText(e)}`);
    }
    this.name = (await t.getName()) || this.name;
    try {
      this.battery = P.parseBattery(await t.read(P.UUIDS.BATTERY_LEVEL));
      this.onBattery.emit(this.battery);
    } catch (e) {
      this.log(`battery read failed: ${errText(e)}`);
    }
    this.log(`connected: ${this.label} fw=${this.firmware ? P.firmwareString(this.firmware) : "?"} ` +
      `serial=${this.info ? P.serialString(this.info) : "?"} battery=${this.battery ?? "?"}%`);

    // subscriptions first, so no packet is lost once modes are set
    await t.subscribe(P.UUIDS.IMU_DATA, (d) => this.onImuBytes(d));
    for (let i = 0; i < P.EMG_UUIDS.length; i++) await t.subscribe(P.EMG_UUIDS[i], this.emgHandler(i));
    await this.optionalSubscribe(P.UUIDS.FV_DATA, (d) => this.onFvBytes(d), "FV subscribe skipped");
    await t.subscribe(P.UUIDS.CLASSIFIER_EVENT, (d) => this.onClassifierBytes(d));
    await this.optionalSubscribe(P.UUIDS.MOTION_EVENT, (d) => this.onMotionBytes(d), "motion subscribe skipped");
    await this.optionalSubscribe(P.UUIDS.BATTERY_LEVEL, (d) => this.onBatteryBytes(d), "battery notify skipped");

    // modes
    if (cfg.neverSleep) await this.setSleepMode(P.SleepMode.NEVER_SLEEP);
    await this.setMode(cfg.emgMode, cfg.imuMode, cfg.classifierMode);
    // a band still synced from before (a reconnect) sends no new ARM_SYNCED
    if (cfg.classifierMode && cfg.unlockOnSync) await this.unlock(P.UnlockType.HOLD);
    if (cfg.vibrateOnConnect) await this.vibrate(P.VibrationType.SHORT);
  }

  private async optionalSubscribe(uuid: string, cb: (d: DataView) => void, what: string): Promise<void> {
    try {
      await this.transport.subscribe(uuid, cb);
    } catch (e) {
      this.log(`${what}: ${errText(e)}`);
    }
  }

  private startBackground(): void {
    this.cancelBackground();
    const cfg = this.config;
    const every = (s: number, fn: () => Promise<void>) =>
      this.timers.push(setInterval(() => {
        if (this.state === "streaming") fn().catch(() => undefined);
      }, s * 1000));
    if (cfg.keepaliveS > 0 && cfg.neverSleep) every(cfg.keepaliveS, () => this.setSleepMode(P.SleepMode.NEVER_SLEEP));
    if (cfg.batteryPollS > 0)
      every(cfg.batteryPollS, async () => this.onBatteryBytes(await this.transport.read(P.UUIDS.BATTERY_LEVEL)));
    if (cfg.rssiPollS > 0)
      every(cfg.rssiPollS, async () => {
        const rssi = await this.transport.getRssi();
        if (rssi !== null && rssi !== this.rssi) {
          this.rssi = rssi;
          this.onRssi.emit(rssi);
        }
      });
  }

  private cancelBackground(): void {
    for (const t of this.timers) clearInterval(t);
    this.timers = [];
  }

  private onTransportDisconnect(): void {
    this.cancelBackground();
    if (this.userDisconnect || !this.config.reconnect) {
      this.setState("disconnected");
      return;
    }
    this.setState("reconnecting");
    if (this.reconnecting) return; // the link dropped during a reconnect attempt: that loop keeps trying
    void this.reconnectLoop();
  }

  private async reconnectLoop(): Promise<void> {
    this.reconnecting = true;
    try {
      const backoff = this.config.reconnectBackoffS;
      for (let attempt = 1; !this.userDisconnect; attempt++) {
        // after the listed delays, keep trying at the max backoff until the user gives up
        await sleep(1000 * backoff[Math.min(attempt, backoff.length) - 1]);
        if (this.userDisconnect) return;
        this.log(`reconnect attempt ${attempt}`);
        try {
          await this.connect();
          this.log("reconnected");
          return;
        } catch (e) {
          this.log(`reconnect failed: ${errText(e)}`);
          if (!this.userDisconnect) this.setState("reconnecting");
        }
      }
    } finally {
      this.reconnecting = false;
    }
  }

  /** Graceful shutdown: let the armband sleep again, stop streams, drop the link. */
  async disconnect(restoreSleep = true): Promise<void> {
    this.userDisconnect = true;
    this.cancelBackground();
    if (this.transport.isConnected) {
      try {
        if (restoreSleep) {
          await this.setMode(P.EmgMode.NONE, P.ImuMode.NONE, P.ClassifierMode.DISABLED);
          await this.setSleepMode(P.SleepMode.NORMAL);
        }
      } catch (e) {
        this.log(`shutdown commands failed: ${errText(e)}`);
      }
      await this.transport.disconnect();
    }
    this.setState("disconnected");
  }

  // ------------------------------------------------------------------ commands
  private command(data: Uint8Array): Promise<void> {
    const run = async () => {
      await this.transport.write(P.UUIDS.COMMAND, data, true);
      if (this.config.commandSpacingS) await sleep(this.config.commandSpacingS * 1000);
    };
    const p = this.cmdChain.then(run, run);
    this.cmdChain = p.catch(() => undefined);
    return p;
  }

  async setMode(emg: number, imu: number, classifier: number): Promise<void> {
    const cfg = this.config;
    cfg.emgMode = emg as P.EmgModeValue;
    cfg.imuMode = imu as P.ImuModeValue;
    cfg.classifierMode = classifier as P.ClassifierModeValue;
    await this.command(P.cmdSetMode(emg, imu, classifier));
    this.stats.emgExpectedHz =
      emg === P.EmgMode.FILTERED || emg === P.EmgMode.RAW ? P.EMG_SAMPLE_RATE_HZ : 0;
    this.log(`mode emg=${String(P.enumName(P.EmgMode, emg))} imu=${String(P.enumName(P.ImuMode, imu))} ` +
      `classifier=${String(P.enumName(P.ClassifierMode, classifier))}`);
  }

  vibrate(kind: number = P.VibrationType.SHORT) {
    return this.command(P.cmdVibrate(kind));
  }

  vibrate2(steps: Array<[number, number]>) {
    return this.command(P.cmdVibrate2(steps));
  }

  setSleepMode(mode: number) {
    return this.command(P.cmdSetSleepMode(mode));
  }

  unlock(kind: number = P.UnlockType.HOLD) {
    return this.command(P.cmdUnlock(kind));
  }

  lock() {
    return this.command(P.cmdUnlock(P.UnlockType.LOCK));
  }

  userAction() {
    return this.command(P.cmdUserAction());
  }

  setLed(logo: [number, number, number], bar: [number, number, number]) {
    return this.command(P.cmdSetLed(logo, bar));
  }

  /** Reset the onboard classifier (classifier off, then on again): the band forgets the arm and
   * waits for a new sync gesture. EMG and IMU keep streaming. */
  async resync(): Promise<void> {
    const cfg = this.config;
    await this.command(P.cmdSetMode(cfg.emgMode, cfg.imuMode, P.ClassifierMode.DISABLED));
    const wasSynced = this.synced;
    this.clearSync();
    // tell the listeners (OSC /sync 0, UI) even if the firmware stays silent
    if (wasSynced) this.onClassifier.emit(P.makeClassifierEvent(P.ClassifierEventType.ARM_UNSYNCED), this.clock());
    await sleep(300);
    cfg.classifierMode = P.ClassifierMode.ENABLED;
    await this.command(P.cmdSetMode(cfg.emgMode, cfg.imuMode, P.ClassifierMode.ENABLED));
    this.log("classifier reset: make the sync gesture (wave out and hold)");
    await this.vibrate(P.VibrationType.SHORT);
  }

  /** Switch the band off (deep sleep). The link drops and the band stays off until it is plugged
   * into USB power; no reconnect is attempted. */
  async powerOff(): Promise<void> {
    this.userDisconnect = true;
    this.cancelBackground();
    if (this.transport.isConnected) {
      try {
        await this.command(P.cmdDeepSleep());
      } catch (e) {
        this.log(`deep sleep: ${errText(e)}`); // the band may drop the link before acknowledging
      }
      if (this.transport.isConnected) {
        try {
          await this.transport.disconnect();
        } catch {
          /* already gone */
        }
      }
    }
    this.clearSync();
    this.setState("disconnected");
    this.log("powered off: plug the band into USB to wake it up");
  }

  private clearSync(): void {
    this.synced = false;
    this.arm = P.Arm.UNKNOWN;
    this.xDirection = P.XDirection.UNKNOWN;
    this.pose = P.Pose.REST;
    this.locked = true;
  }

  /** Run a command from a notification callback without blocking it. */
  private spawn(p: Promise<unknown>): void {
    p.catch((e) => this.log(`command failed: ${errText(e)}`));
  }

  // ------------------------------------------------------------------ notification handlers
  private emgHandler(charIndex: number) {
    return (data: DataView) => {
      const now = this.clock();
      let s1: P.EmgSample, s2: P.EmgSample;
      try {
        [s1, s2] = P.parseEmg(data);
      } catch {
        return;
      }
      const st = this.stats;
      st.emgNotifications++;
      st.emgPerChar[charIndex]++;
      st.emgSamples += 2;
      st.winEmg += 2;
      st.lastEmgT = now;
      st.tickWindow(now);
      this.lastEmg = s2;
      this.onEmgPacket.emit([s1, s2], now);
      if (this.onEmg.size) {
        this.onEmg.emit(s1, now);
        this.onEmg.emit(s2, now);
      }
    };
  }

  private onImuBytes(data: DataView): void {
    const now = this.clock();
    let pkt: P.ImuPacket;
    try {
      pkt = P.parseImu(data);
    } catch {
      return;
    }
    const st = this.stats;
    st.imuPackets++;
    st.winImu++;
    st.lastImuT = now;
    st.tickWindow(now);
    this.lastImu = pkt;
    this.onImu.emit(pkt, now);
  }

  private onFvBytes(data: DataView): void {
    const now = this.clock();
    let pkt: P.FvPacket;
    try {
      pkt = P.parseFv(data);
    } catch {
      return;
    }
    const st = this.stats;
    st.fvPackets++;
    st.winFv++;
    st.tickWindow(now);
    this.onFv.emit(pkt, now);
  }

  private onClassifierBytes(data: DataView): void {
    const now = this.clock();
    let ev: P.ClassifierEvent;
    try {
      ev = P.parseClassifier(data);
    } catch {
      return;
    }
    this.stats.classifierEvents++;
    switch (ev.type) {
      case P.ClassifierEventType.ARM_SYNCED:
        this.synced = true;
        this.arm = ev.arm;
        this.xDirection = ev.xDirection;
        if (this.config.unlockOnSync) this.spawn(this.unlock(P.UnlockType.HOLD));
        break;
      case P.ClassifierEventType.ARM_UNSYNCED:
        this.synced = false;
        this.arm = P.Arm.UNKNOWN;
        this.xDirection = P.XDirection.UNKNOWN;
        this.pose = P.Pose.REST;
        break;
      case P.ClassifierEventType.POSE:
        this.pose = ev.pose;
        break;
      case P.ClassifierEventType.UNLOCKED:
        this.locked = false;
        break;
      case P.ClassifierEventType.LOCKED:
        this.locked = true;
        break;
      case P.ClassifierEventType.SYNC_FAILED:
        this.synced = false;
        break;
    }
    this.onClassifier.emit(ev, now);
  }

  private onMotionBytes(data: DataView): void {
    const now = this.clock();
    const ev = P.parseMotion(data);
    this.stats.motionEvents++;
    this.onMotion.emit(ev, now);
  }

  private onBatteryBytes(data: DataView): void {
    let level: number;
    try {
      level = P.parseBattery(data);
    } catch {
      return;
    }
    if (level !== this.battery) {
      this.battery = level;
      this.onBattery.emit(level);
    }
  }
}

export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));
export { TransportError };
