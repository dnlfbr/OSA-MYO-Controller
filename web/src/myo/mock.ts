/** Mock Myo: a Transport that behaves like an armband and emits synthetic data.
 *
 * Port of src/myo_bridge/myo/mock.py. Timing and packet layout mirror the real device: IMU at
 * 50 Hz (20 bytes), EMG as 16-byte notifications (2 samples) at 100 notifications/s round-robin
 * over the four EMG characteristics, smooth EMG at 50 Hz, classifier events as 6-byte
 * indications, battery as 1 byte. Commands written to COMMAND are honoured (modes, vibrate,
 * sleep, lock, deep sleep). Used by the "Demo" button and by the tests. */

import * as P from "./protocol";
import { fromEuler } from "../processing/quaternion";
import { TransportError, monotonic, sleep, type DisconnectCallback, type NotifyCallback, type Transport } from "./transport";

/** Small seeded PRNG (mulberry32) so a seed gives a reproducible stream. */
export function rng(seed = Date.now()) {
  let a = seed >>> 0;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const gauss = () => {
    const u = 1 - next();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * next());
  };
  const uniform = (lo: number, hi: number) => lo + (hi - lo) * next();
  const int = (lo: number, hi: number) => Math.floor(uniform(lo, hi + 1));
  const choice = <T>(xs: readonly T[]): T => xs[Math.floor(next() * xs.length)];
  return { next, gauss, uniform, int, choice };
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

// per-pose channel gains (which pods "light up")
const GAINS: Record<number, number[]> = {
  [P.Pose.REST]: Array(8).fill(0.06),
  [P.Pose.FIST]: [0.6, 0.7, 0.5, 0.4, 0.5, 0.7, 0.6, 0.5],
  [P.Pose.WAVE_IN]: [0.1, 0.1, 0.5, 0.8, 0.6, 0.1, 0.1, 0.1],
  [P.Pose.WAVE_OUT]: [0.6, 0.8, 0.2, 0.1, 0.1, 0.1, 0.5, 0.7],
  [P.Pose.FINGERS_SPREAD]: [0.4, 0.3, 0.4, 0.3, 0.4, 0.3, 0.4, 0.3],
  [P.Pose.DOUBLE_TAP]: [0.2, 0.2, 0.3, 0.3, 0.3, 0.3, 0.2, 0.2],
};
const POSES = [P.Pose.FIST, P.Pose.WAVE_IN, P.Pose.WAVE_OUT, P.Pose.FINGERS_SPREAD, P.Pose.DOUBLE_TAP,
  P.Pose.REST, P.Pose.REST];

export interface MockOptions {
  seed?: number;
  posePeriodS?: number;
  dropEvery?: number; // drop every Nth EMG notification (0 = none)
  failConnect?: boolean;
}

export class MockTransport implements Transport {
  readonly backendName = "mock";
  readonly address = "MOCK-0001";
  private connected = false;
  private subs = new Map<string, NotifyCallback>();
  private onDisconnect: DisconnectCallback | undefined;
  private timer: ReturnType<typeof setInterval> | undefined;
  private r: ReturnType<typeof rng>;

  // armband state
  emgMode: number = P.EmgMode.NONE;
  imuMode: number = P.ImuMode.NONE;
  classifierMode: number = P.ClassifierMode.DISABLED;
  sleepMode: number = P.SleepMode.NORMAL;
  locked = true;
  battery = 87;
  vibrations: number[] = [];
  commands: Uint8Array[] = [];
  name = "Mock Myo";
  serial = Uint8Array.of(0x01, 0xcc, 0xbe, 0xd9, 0xb5, 0xd2); // shown as d2-b5-d9-be-cc-01
  firmware = [1, 5, 1970, 2];
  rssi = -55;
  yawRateDps = 20;
  readonly posePeriodS: number;
  readonly dropEvery: number;
  private readonly failConnect: boolean;

  constructor(opts: MockOptions = {}) {
    this.r = rng(opts.seed);
    this.posePeriodS = opts.posePeriodS ?? 4;
    this.dropEvery = opts.dropEvery ?? 0;
    this.failConnect = opts.failConnect ?? false;
  }

  // ------------------------------------------------------------------ Transport API
  get isConnected(): boolean {
    return this.connected;
  }

  async connect(onDisconnect?: DisconnectCallback): Promise<void> {
    await sleep(50);
    if (this.failConnect) throw new TransportError("mock: connection refused");
    this.onDisconnect = onDisconnect;
    this.connected = true;
    this.startStream();
  }

  async disconnect(): Promise<void> {
    this.stop();
  }

  /** Drop the link as if the armband went out of range. */
  simulateLinkLoss(): void {
    this.stop();
    this.onDisconnect?.();
  }

  private stop(): void {
    this.connected = false;
    clearInterval(this.timer);
    this.timer = undefined;
    this.subs.clear();
  }

  private require(): void {
    if (!this.connected) throw new TransportError("mock: not connected");
  }

  async read(uuid: string): Promise<DataView> {
    this.require();
    await sleep(5);
    const out = (b: Uint8Array) => new DataView(b.buffer);
    switch (uuid) {
      case P.UUIDS.FIRMWARE: {
        const b = new Uint8Array(8);
        const dv = new DataView(b.buffer);
        this.firmware.forEach((v, i) => dv.setUint16(2 * i, v, true));
        return dv;
      }
      case P.UUIDS.INFO: {
        const b = new Uint8Array(20);
        b.set(this.serial, 0);
        new DataView(b.buffer).setUint16(6, P.Pose.DOUBLE_TAP, true);
        b[12] = P.SKU.BLACK;
        return out(b);
      }
      case P.UUIDS.BATTERY_LEVEL:
        return out(Uint8Array.of(this.battery));
      case P.UUIDS.DEVICE_NAME:
        return out(new TextEncoder().encode(this.name));
    }
    throw new TransportError(`mock: unknown characteristic ${uuid}`);
  }

  async write(uuid: string, data: Uint8Array): Promise<void> {
    this.require();
    if (uuid !== P.UUIDS.COMMAND) throw new TransportError(`mock: characteristic ${uuid} is not writable`);
    await sleep(3);
    this.commands.push(Uint8Array.from(data));
    switch (data[0]) {
      case P.CMD_SET_MODE:
        this.emgMode = data[2];
        this.imuMode = data[3];
        this.classifierMode = data[4];
        if (this.classifierMode === P.ClassifierMode.ENABLED) this.scheduleSync();
        break;
      case P.CMD_VIBRATE:
        this.vibrations.push(data[2]);
        break;
      case P.CMD_SET_SLEEP_MODE:
        this.sleepMode = data[2];
        break;
      case P.CMD_UNLOCK:
        this.locked = data[2] === P.UnlockType.LOCK;
        this.emitClassifier(this.locked ? P.ClassifierEventType.LOCKED : P.ClassifierEventType.UNLOCKED);
        break;
      case P.CMD_DEEP_SLEEP:
        this.simulateLinkLoss();
        break;
    }
  }

  async subscribe(uuid: string, callback: NotifyCallback): Promise<void> {
    this.require();
    this.subs.set(uuid, callback);
  }

  async getName(): Promise<string | null> {
    return this.name;
  }

  async getRssi(): Promise<number | null> {
    return this.connected ? this.rssi + this.r.int(-3, 3) : null;
  }

  // ------------------------------------------------------------------ synthetic data
  private notify(uuid: string, data: Uint8Array): void {
    this.subs.get(uuid)?.(new DataView(data.buffer, data.byteOffset, data.byteLength));
  }

  private emitClassifier(t: number, b1 = 0, b2 = 0, b3 = 0): void {
    this.notify(P.UUIDS.CLASSIFIER_EVENT, Uint8Array.of(t, b1, b2, b3, 0, 0));
  }

  private scheduleSync(): void {
    setTimeout(() => {
      if (this.connected && this.classifierMode === P.ClassifierMode.ENABLED) {
        this.emitClassifier(P.ClassifierEventType.ARM_SYNCED, P.Arm.RIGHT, P.XDirection.TOWARD_WRIST, P.WarmupState.COLD);
        this.emitClassifier(P.ClassifierEventType.WARMUP_COMPLETED, P.WarmupResult.SUCCESS);
        this.locked = false;
        this.emitClassifier(P.ClassifierEventType.UNLOCKED);
      }
    }, 800);
  }

  /** Force a pose now (the Demo panel's buttons); the classifier must be on. */
  triggerPose(pose: number): void {
    if (!this.connected || this.classifierMode !== P.ClassifierMode.ENABLED) return;
    this.pose = pose;
    this.emitClassifier(P.ClassifierEventType.POSE, pose & 0xff, pose >> 8);
  }

  /** Force a knock on the band now (strength in g). */
  triggerTap(strength = 1.2): void {
    this.pendingTap = strength;
  }

  private pose: number = P.Pose.REST;
  private pendingTap: number | null = null;

  private startStream(): void {
    const r = this.r;
    const t0 = monotonic();
    const imuPeriod = 1 / P.IMU_SAMPLE_RATE_HZ;
    const emgPeriod = 2 / P.EMG_SAMPLE_RATE_HZ; // one notification = 2 samples
    let nextImu = t0, nextEmg = t0;
    let nextPose = t0 + this.posePeriodS;
    let nextBatt = t0 + 20;
    let nextTap = t0 + r.uniform(3, 6);
    let spike: P.Vec3 | null = null; // knock added to the next IMU sample
    const fvEnv = new Array(8).fill(0);
    let emgChar = 0, emgN = 0;
    const imuOn = () => [P.ImuMode.DATA, P.ImuMode.ALL, P.ImuMode.RAW].includes(this.imuMode as 1);
    const eventsOn = () => this.imuMode === P.ImuMode.EVENTS || this.imuMode === P.ImuMode.ALL;

    const knock = (strength: number) => {
      const d = [r.gauss(), r.gauss(), r.gauss()];
      const n = Math.hypot(...d) || 1;
      spike = d.map((x) => (strength * x) / n) as P.Vec3;
      this.notify(P.UUIDS.MOTION_EVENT, Uint8Array.of(P.MotionEventType.TAP, r.int(0, 5), r.choice([1, 1, 2])));
    };

    const tick = () => {
      if (!this.connected) return;
      const now = monotonic();
      const t = now - t0;
      // catch up on every period that elapsed (timers in background tabs fire late)
      while (now >= nextImu) {
        nextImu += imuPeriod;
        if (!imuOn()) continue;
        const ts = nextImu - t0;
        const yaw = ((this.yawRateDps * ts * Math.PI) / 180) % (2 * Math.PI);
        const pitch = 0.3 * Math.sin(0.5 * ts);
        const roll = 0.2 * Math.sin(0.33 * ts);
        const q = fromEuler(roll, pitch, yaw);
        const gx = (roll - 0.2 * Math.sin(0.33 * (ts - 0.02))) / 0.02;
        const gy = (pitch - 0.3 * Math.sin(0.5 * (ts - 0.02))) / 0.02;
        const gz = (this.yawRateDps * Math.PI) / 180;
        // gravity in sensor frame (approx) + noise
        let acc: P.Vec3 = [-Math.sin(pitch), Math.sin(roll) * Math.cos(pitch), Math.cos(roll) * Math.cos(pitch)];
        if (spike) {
          const s: P.Vec3 = spike;
          acc = acc.map((a, i) => a + s[i]) as P.Vec3;
          spike = null;
        }
        const b = new Uint8Array(20);
        const dv = new DataView(b.buffer);
        const i16 = (v: number) => clamp(Math.trunc(v), -32768, 32767);
        q.forEach((v, i) => dv.setInt16(2 * i, i16(v * P.ORIENTATION_SCALE), true));
        acc.forEach((a, i) => dv.setInt16(8 + 2 * i, i16((a + r.gauss() * 0.01) * P.ACCELEROMETER_SCALE), true));
        [gx, gy, gz].forEach((g, i) => dv.setInt16(14 + 2 * i, i16(((g * 180) / Math.PI) * P.GYROSCOPE_SCALE), true));
        this.notify(P.UUIDS.IMU_DATA, b);
      }
      while (now >= nextEmg) {
        nextEmg += emgPeriod;
        emgN++;
        const g = GAINS[this.pose] ?? GAINS[P.Pose.REST];
        if (this.emgMode === P.EmgMode.FILTERED || this.emgMode === P.EmgMode.RAW) {
          const b = new Int8Array(16);
          for (let i = 0; i < 16; i++)
            b[i] = clamp(Math.trunc(r.gauss() * g[i % 8] * 100 * (1 + 0.3 * Math.sin(2 * Math.PI * 1.5 * t))), -128, 127);
          if (!(this.dropEvery && emgN % this.dropEvery === 0))
            this.notify(P.EMG_UUIDS[emgChar], new Uint8Array(b.buffer));
          emgChar = (emgChar + 1) & 3;
        } else if (this.emgMode === P.EmgMode.SMOOTH && emgN % 2 === 0) {
          // 50 Hz envelope
          const b = new Uint8Array(17);
          const dv = new DataView(b.buffer);
          for (let ch = 0; ch < 8; ch++) {
            fvEnv[ch] += 0.25 * (Math.abs(r.gauss()) * g[ch] * 900 - fvEnv[ch]);
            dv.setUint16(2 * ch, Math.min(65535, Math.trunc(fvEnv[ch])), true);
          }
          this.notify(P.UUIDS.FV_DATA, b);
        }
      }
      if (now >= nextPose) {
        nextPose = now + this.posePeriodS * r.uniform(0.6, 1.4);
        if (this.classifierMode === P.ClassifierMode.ENABLED) this.triggerPose(r.choice(POSES));
      }
      if (this.pendingTap !== null) {
        if (eventsOn()) knock(this.pendingTap);
        this.pendingTap = null;
      } else if (now >= nextTap) {
        // a knock on the band, of random strength
        nextTap = now + r.uniform(3, 8);
        if (eventsOn()) knock(r.uniform(0.1, 2));
      }
      if (now >= nextBatt) {
        nextBatt = now + 20;
        this.battery = Math.max(1, this.battery - 1);
        this.notify(P.UUIDS.BATTERY_LEVEL, Uint8Array.of(this.battery));
      }
    };
    this.timer = setInterval(tick, 5);
  }
}
