/** Per-device processing state: scaling, orientation reference, envelope, latest values.
 * Port of processing/pipeline.py; times are seconds (performance.now() / 1000 in the app). */

import * as P from "../myo/protocol";
import * as Q from "./quaternion";
import { RmsEnvelope } from "./envelope";
import { emgNorm } from "./scaling";

export interface ImuFrame {
  t: number;
  quatRaw: P.Quat; // scaled, un-referenced
  quat: P.Quat; // with zero reference applied
  euler: Q.Euler; // radians, from quat
  accel: P.Vec3; // g
  gyro: P.Vec3; // deg/s
}

/** Smooth EMG (mode 1, uint16) -> 0..1 per pod, like the RMS bars of the other modes. */
export const fvActivity = (values: number[]): number[] => values.map((v) => Math.min(1, v / P.FV_FULL_SCALE));

/** Software gate for the band's tap events. The firmware's tap detector can't be tuned, so a tap
 * is kept only if its strength (see DeviceProcessor.tapStrength) reaches thresholdG and
 * cooldownMs has passed since the last kept tap. 0 = off. */
export class TapFilter {
  private lastT = -1e9;

  constructor(public thresholdG = 0, public cooldownMs = 0) {}

  /** [keep, reason if dropped]. Without IMU data the strength is unknown: the tap is kept. */
  decide(t: number, strengthG: number | null): [boolean, string] {
    if (this.cooldownMs > 0 && (t - this.lastT) * 1000 < this.cooldownMs)
      return [false, `within ${this.cooldownMs.toFixed(0)} ms of the last tap`];
    if (this.thresholdG > 0 && strengthG !== null && strengthG < this.thresholdG)
      return [false, `weaker than ${this.thresholdG.toFixed(2)} g`];
    this.lastT = t;
    return [true, ""];
  }
}

export interface ProcessingParams {
  rmsWindowMs: number;
  zeroMode: Q.ZeroMode;
  tapThresholdG: number;
  tapCooldownMs: number;
}

export const defaultParams = (): ProcessingParams => ({
  rmsWindowMs: 50,
  zeroMode: "yaw",
  tapThresholdG: 0,
  tapCooldownMs: 0,
});

const JOLT_CAPACITY = 100; // (t, g) pairs, 2 s at 50 Hz

export class DeviceProcessor {
  readonly params: ProcessingParams;
  readonly reference: Q.OrientationReference;
  readonly rms: RmsEnvelope;
  readonly taps: TapFilter;
  lastImu: ImuFrame | null = null;
  lastEmgRaw: P.EmgSample | null = null;
  lastEmgNorm: number[] | null = null;
  lastEmgT = 0;
  private jolt: Array<[number, number]> = [];

  constructor(params: Partial<ProcessingParams> = {}) {
    this.params = { ...defaultParams(), ...params };
    this.reference = new Q.OrientationReference(this.params.zeroMode);
    this.rms = new RmsEnvelope(P.EMG_CHANNELS, this.rmsSamples());
    this.taps = new TapFilter(this.params.tapThresholdG, this.params.tapCooldownMs);
  }

  private rmsSamples(): number {
    return Math.max(1, Math.round((this.params.rmsWindowMs * P.EMG_SAMPLE_RATE_HZ) / 1000));
  }

  setRmsWindowMs(ms: number): void {
    this.params.rmsWindowMs = ms;
    this.rms.setWindow(this.rmsSamples());
  }

  // ---- EMG
  pushEmg(sample: P.EmgSample, t: number): number[] {
    const norm = emgNorm(sample);
    this.rms.push(norm);
    this.lastEmgRaw = sample;
    this.lastEmgNorm = norm;
    this.lastEmgT = t;
    return norm;
  }

  // ---- IMU
  pushImu(pkt: P.ImuPacket, t: number): ImuFrame {
    const quatRaw = Q.normalize(P.quatF(pkt));
    const quat = this.reference.apply(quatRaw);
    const frame: ImuFrame = { t, quatRaw, quat, euler: Q.toEuler(quat), accel: P.accelG(pkt), gyro: P.gyroDps(pkt) };
    const prev = this.lastImu;
    this.lastImu = frame;
    if (prev !== null && t - prev.t < 0.1) {
      // sample-to-sample change, gaps skipped
      const d = Math.hypot(frame.accel[0] - prev.accel[0], frame.accel[1] - prev.accel[1], frame.accel[2] - prev.accel[2]);
      this.jolt.push([t, d]);
      if (this.jolt.length > JOLT_CAPACITY) this.jolt.shift();
    }
    return frame;
  }

  /** Strength of a knock between t0 and t1: the largest sample-to-sample change of the
   * acceleration vector (g), from the 50 Hz IMU stream. Gravity and slow arm movement barely
   * change it, a knock on the band does. null when no IMU samples arrived in that time. */
  tapStrength(t0: number, t1: number): number | null {
    let best: number | null = null;
    for (const [t, j] of this.jolt) if (t >= t0 && t <= t1 && (best === null || j > best)) best = j;
    return best;
  }

  imuLive(now: number, withinS = 0.25): boolean {
    return this.lastImu !== null && now - this.lastImu.t <= withinS;
  }

  setTapFilter(thresholdG: number, cooldownMs: number): void {
    this.params.tapThresholdG = this.taps.thresholdG = thresholdG;
    this.params.tapCooldownMs = this.taps.cooldownMs = cooldownMs;
  }

  setZeroMode(mode: Q.ZeroMode): void {
    this.params.zeroMode = this.reference.mode = mode;
  }

  /** Use the latest orientation as the new reference. Returns the stored reference. */
  zero(): P.Quat | null {
    if (this.lastImu === null) return null;
    this.reference.setZero(this.lastImu.quatRaw);
    return this.reference.reference;
  }

  clearZero(): void {
    this.reference.clear();
  }
}
