/** OSC output: the same addresses, types and rate limits as osc/sender.py with the "default"
 * namespace in vector mode, written to any packet sink (the WebSocket relay).
 *
 * EMG samples are accumulated into a bundle of `emgBundleSamples` samples; IMU-derived streams
 * and the RMS envelope pass through a per-stream rate limiter. */

import { encodeBundle, encodeMessage, float, int, type OscArg } from "./osc";

/** Stream key -> address template ({id} = band number), osc/namespace.py DEFAULT. */
export const DEFAULT_NAMESPACE: Record<string, string> = {
  emg_raw: "/myo/{id}/emg/raw",
  emg_norm: "/myo/{id}/emg/norm",
  emg_rms: "/myo/{id}/emg/rms",
  emg_mav: "/myo/{id}/emg/mav",
  fv: "/myo/{id}/emg/smooth",
  quat: "/myo/{id}/quat",
  quat_raw: "/myo/{id}/quat/raw",
  euler: "/myo/{id}/euler",
  euler_deg: "/myo/{id}/euler/deg",
  euler_norm: "/myo/{id}/euler/norm",
  accel: "/myo/{id}/accel",
  gyro: "/myo/{id}/gyro",
  pose: "/myo/{id}/pose",
  pose_id: "/myo/{id}/pose/id",
  arm: "/myo/{id}/arm",
  xdir: "/myo/{id}/xdir",
  sync: "/myo/{id}/sync",
  lock: "/myo/{id}/lock",
  battery: "/myo/{id}/battery",
  rssi: "/myo/{id}/rssi",
  status: "/myo/{id}/status",
  tap: "/myo/{id}/tap",
  firmware: "/myo/{id}/firmware",
};

/** config.py osc.streams defaults. */
export const DEFAULT_STREAMS: Record<string, boolean> = {
  emg_raw: true, emg_norm: false, emg_rms: true, emg_mav: true,
  quat: true, quat_raw: false, euler: true, euler_deg: false, euler_norm: false,
  accel: true, gyro: true, pose: true, arm: true, sync: true, lock: true,
  battery: true, rssi: true, status: true, tap: true, firmware: true, fv: true,
};

/** Phase-locked rate limiter: a packet that arrives slightly early (jitter) is still accepted, so
 * a 50 Hz input through a 50 Hz limit passes every packet instead of every other one. 0 Hz =
 * unlimited. */
export class RateLimiter {
  minDt = 0;
  private next = 0;

  constructor(hz: number) {
    this.setRate(hz);
  }

  setRate(hz: number): void {
    this.minDt = hz > 0 ? 1 / hz : 0;
  }

  allow(now: number): boolean {
    const dt = this.minDt;
    if (dt === 0) return true;
    if (now >= this.next - 0.25 * dt) {
      this.next = Math.max(this.next, now) + dt;
      return true;
    }
    return false;
  }
}

export type PacketSink = (packet: Uint8Array) => void;

export class OscSender {
  enabled = true;
  streams: Record<string, boolean> = { ...DEFAULT_STREAMS };
  emgBundleSamples = 4;
  sentMessages = 0;
  sentPackets = 0;
  private imuLimit: RateLimiter;
  private rmsLimit: RateLimiter;
  private emgPending: Uint8Array[] = [];
  private emgPendingN = 0;

  constructor(public sink: PacketSink | null = null, readonly id = 1, imuRateHz = 50, rmsRateHz = 50) {
    this.imuLimit = new RateLimiter(imuRateHz);
    this.rmsLimit = new RateLimiter(rmsRateHz);
  }

  setSink(sink: PacketSink | null): void {
    this.sink = sink;
    this.emgPending = [];
    this.emgPendingN = 0;
  }

  setRates(imuRateHz: number, rmsRateHz: number): void {
    this.imuLimit.setRate(imuRateHz);
    this.rmsLimit.setRate(rmsRateHz);
  }

  wants(stream: string): boolean {
    return this.enabled && this.sink !== null && !!this.streams[stream] && stream in DEFAULT_NAMESPACE;
  }

  address(stream: string): string {
    return DEFAULT_NAMESPACE[stream].replace("{id}", String(this.id));
  }

  private msg(stream: string, args: OscArg[]): Uint8Array {
    this.sentMessages++;
    return encodeMessage(this.address(stream), args);
  }

  private emit(msgs: Uint8Array[]): void {
    if (!msgs.length || !this.sink) return;
    this.sink(msgs.length === 1 ? msgs[0] : encodeBundle(msgs));
    this.sentPackets++;
  }

  // ---------------------------------------------------------------- EMG (bundled)
  /** Queue one EMG sample; flush when the bundle is full. Returns true on flush. */
  emg(raw: number[], norm: number[]): boolean {
    const msgs: Uint8Array[] = [];
    if (this.wants("emg_raw")) msgs.push(this.msg("emg_raw", raw.map(int)));
    if (this.wants("emg_norm")) msgs.push(this.msg("emg_norm", norm.map(float)));
    if (!msgs.length) return false;
    this.emgPending.push(...msgs);
    if (++this.emgPendingN >= Math.max(1, this.emgBundleSamples)) {
      this.emit(this.emgPending);
      this.emgPending = [];
      this.emgPendingN = 0;
      return true;
    }
    return false;
  }

  emgRms(rms: number[], mav: number, now: number): void {
    if (!(this.wants("emg_rms") || this.wants("emg_mav")) || !this.rmsLimit.allow(now)) return;
    const msgs: Uint8Array[] = [];
    if (this.wants("emg_rms")) msgs.push(this.msg("emg_rms", rms.map(float)));
    if (this.wants("emg_mav")) msgs.push(this.msg("emg_mav", [float(mav)]));
    this.emit(msgs);
  }

  fv(values: number[]): void {
    if (this.wants("fv")) this.emit([this.msg("fv", values.map(int))]);
  }

  // ---------------------------------------------------------------- IMU (rate limited)
  imu(v: { quat: number[]; quatRaw: number[]; euler: number[]; eulerDeg: number[]; eulerNorm: number[];
           accel: number[]; gyro: number[] }, now: number): void {
    if (!this.imuLimit.allow(now)) return;
    const msgs: Uint8Array[] = [];
    const add = (stream: string, values: number[]) => {
      if (this.wants(stream)) msgs.push(this.msg(stream, values.map(float)));
    };
    add("quat", v.quat);
    add("quat_raw", v.quatRaw);
    add("euler", v.euler);
    add("euler_deg", v.eulerDeg);
    add("euler_norm", v.eulerNorm);
    add("accel", v.accel);
    add("gyro", v.gyro);
    this.emit(msgs);
  }

  // ---------------------------------------------------------------- events
  pose(label: string, id: number): void {
    if (!this.wants("pose")) return;
    this.emit([this.msg("pose", [label])]);
    this.emit([this.msg("pose_id", [int(id)])]);
  }

  string(stream: string, value: string): void {
    if (this.wants(stream)) this.emit([this.msg(stream, [value])]);
  }

  integer(stream: string, value: number): void {
    if (this.wants(stream)) this.emit([this.msg(stream, [int(value)])]);
  }

  tap(direction: number, count: number): void {
    if (this.wants("tap")) this.emit([this.msg("tap", [int(direction), int(count)])]);
  }
}
