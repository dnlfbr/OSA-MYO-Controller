/** Bridge: one armband wired to processing, OSC out and the event log.
 *
 * The browser counterpart of engine.py for a single slot: the same tap filter timing, double
 * tap -> SET ORIGIN, OSC messages and control commands. The UI reads the ring buffers below on
 * each animation frame. */

import * as P from "./myo/protocol";
import { MyoDevice, errText, type DeviceConfig, type DeviceState } from "./myo/device";
import { monotonic, type Transport } from "./myo/transport";
import { DeviceProcessor, fvActivity, type ImuFrame, type ProcessingParams } from "./processing/pipeline";
import * as Q from "./processing/quaternion";
import { OscSender } from "./osc/sender";
import type { OscMessage } from "./osc/osc";

// a tap event is judged on the IMU samples from TAP_PRE_S before to TAP_POST_S after it (the
// sample holding the knock can reach us after the event)
export const TAP_PRE_S = 0.12, TAP_POST_S = 0.06;
export const DOUBLE_TAP_ORIGIN_GAP_S = 1.0; // one origin per double tap, however the classifier repeats it
export const ORIGIN_FRESH_S = 1.0; // SET ORIGIN needs IMU data this recent: a stale frame is no origin
export const NO_ORIGIN = "no IMU data, origin not set (IMU mode data or all)";

export interface LogEntry {
  t: number;
  kind: string; // pose, arm_synced, tap, battery_level, status, log, warning, zero, ...
  text: string;
  data?: Record<string, unknown>;
}

/** Fixed-size ring of numbers per channel, for the plots. */
export class Ring {
  readonly data: Float32Array[];
  head = 0; // next write index
  count = 0;

  constructor(readonly channels: number, readonly size: number) {
    this.data = Array.from({ length: channels }, () => new Float32Array(size));
  }

  push(values: ArrayLike<number>): void {
    for (let c = 0; c < this.channels; c++) this.data[c][this.head] = values[c];
    this.head = (this.head + 1) % this.size;
    if (this.count < this.size) this.count++;
  }

  clear(): void {
    this.head = this.count = 0;
  }
}

export interface BridgeOptions {
  device?: Partial<DeviceConfig>;
  processing?: Partial<ProcessingParams>;
  doubleTapOrigin?: boolean;
  clock?: () => number;
}

export class Bridge {
  readonly device: MyoDevice;
  readonly processor: DeviceProcessor;
  readonly osc: OscSender;
  doubleTapOrigin: boolean;
  readonly clock: () => number;

  // plot buffers (the UI decides how many samples to draw)
  readonly emg = new Ring(8, 200 * 10); // 10 s of raw EMG at 200 Hz
  readonly fv = new Ring(8, 50 * 10); // 10 s of smooth EMG at 50 Hz
  readonly gyro = new Ring(3, 50 * 10);
  readonly accel = new Ring(3, 50 * 10);
  readonly quat = new Ring(4, 50 * 10);
  activity: number[] = new Array(8).fill(0); // RMS or smooth level per pod, 0..1
  lastFrame: ImuFrame | null = null;
  lastPoseT = 0;
  log: LogEntry[] = [];
  readonly maxLog = 500;
  onLog: (e: LogEntry) => void = () => undefined;
  onZero: (ref: P.Quat | null) => void = () => undefined; // to keep the origin across reloads
  private lastOriginTap = -1e9;

  constructor(transport: Transport, opts: BridgeOptions = {}) {
    this.clock = opts.clock ?? monotonic;
    this.device = new MyoDevice(transport, 1, opts.device, this.clock);
    this.processor = new DeviceProcessor(opts.processing);
    this.osc = new OscSender(null, this.device.id);
    this.doubleTapOrigin = opts.doubleTapOrigin ?? false;
    this.wire();
  }

  emit(kind: string, text: string, data?: Record<string, unknown>, t = this.clock()): void {
    const e: LogEntry = { t, kind, text, data };
    this.log.push(e);
    if (this.log.length > this.maxLog) this.log.splice(0, this.log.length - this.maxLog);
    this.onLog(e);
  }

  note(kind: "warning" | "info", text: string): void {
    this.emit(kind, text);
  }

  /** What the user should know about where this band's EMG goes ('' = nothing; engine.emg_hint). */
  emgHint(): string {
    if (this.device.config.emgMode === P.EmgMode.SMOOTH && this.osc.enabled && this.osc.sink && !this.osc.streams.fv)
      return "EMG smooth is shown in the monitor but not sent: switch on the 'fv' stream for /emg/smooth";
    return "";
  }

  private wire(): void {
    const dev = this.device, proc = this.processor, osc = this.osc;

    dev.onEmg.connect((sample, t) => {
      const norm = proc.pushEmg(sample, t);
      this.emg.push(sample);
      osc.emg(sample, norm);
      const rms = proc.rms.values;
      this.activity = rms;
      osc.emgRms(rms, rms.reduce((a, b) => a + b, 0) / rms.length, this.clock());
    });

    // EMG mode smooth: the band's own 50 Hz envelope instead of samples
    dev.onFv.connect((pkt) => {
      this.fv.push(pkt.values);
      this.activity = fvActivity(pkt.values);
      osc.fv(pkt.values);
    });

    dev.onImu.connect((pkt, t) => {
      const fr = proc.pushImu(pkt, t);
      this.lastFrame = fr;
      this.gyro.push(fr.gyro);
      this.accel.push(fr.accel);
      this.quat.push([fr.quat[1], fr.quat[2], fr.quat[3], fr.quat[0]]); // x y z w, as plotted
      osc.imu({
        quat: fr.quat, quatRaw: fr.quatRaw, euler: fr.euler, eulerDeg: Q.toDegrees(fr.euler),
        eulerNorm: Q.toUnitRange(fr.euler), accel: fr.accel, gyro: fr.gyro,
      }, t);
    });

    dev.onClassifier.connect((ev, t) => {
      let data: Record<string, unknown> = {};
      switch (ev.type) {
        case P.ClassifierEventType.POSE:
          osc.pose(P.poseLabel(ev.pose), ev.pose);
          this.lastPoseT = t;
          data = { pose: P.poseLabel(ev.pose) };
          break;
        case P.ClassifierEventType.ARM_SYNCED:
          osc.string("arm", P.armLabel(ev.arm));
          osc.string("xdir", P.xDirectionLabel(ev.xDirection));
          osc.integer("sync", 1);
          data = { arm: P.armLabel(ev.arm), x_direction: P.xDirectionLabel(ev.xDirection) };
          // poses improve after a few minutes on the skin
          if (ev.warmupState === P.WarmupState.COLD) data.warmup = "cold, poses get reliable once warm";
          else if (ev.warmupState === P.WarmupState.WARM) data.warmup = "warm";
          break;
        case P.ClassifierEventType.WARMUP_COMPLETED:
          data = { warmup_result: String(P.enumName(P.WarmupResult, ev.warmupResult) ?? "unknown").toLowerCase() };
          break;
        case P.ClassifierEventType.ARM_UNSYNCED:
          osc.string("arm", "unknown");
          osc.string("xdir", "unknown");
          osc.integer("sync", 0);
          osc.pose("rest", P.Pose.REST);
          break;
        case P.ClassifierEventType.UNLOCKED:
          osc.integer("lock", 0);
          break;
        case P.ClassifierEventType.LOCKED:
          osc.integer("lock", 1);
          break;
        case P.ClassifierEventType.SYNC_FAILED:
          osc.integer("sync", 0);
          data = { sync_result: String(P.enumName(P.SyncResult, ev.syncResult) ?? "unknown").toLowerCase() };
          break;
      }
      const label = P.classifierLabel(ev);
      this.emit(label, label, data, t);
      if (ev.type === P.ClassifierEventType.POSE && ev.pose === P.Pose.DOUBLE_TAP && this.doubleTapOrigin)
        this.doubleTapToOrigin(t);
    });

    dev.onMotion.connect((ev, t) => {
      if (ev.type !== P.MotionEventType.TAP) {
        this.emit("motion", `motion event ${ev.type}`, { type: ev.type }, t);
        return;
      }
      this.tap(ev, t);
    });

    dev.onBattery.connect((level) => {
      osc.integer("battery", level);
      this.emit("battery_level", `battery ${level}%`, { battery_level: level });
    });

    dev.onRssi.connect((rssi) => osc.integer("rssi", rssi));

    dev.onState.connect((state: DeviceState) => {
      osc.string("status", state);
      if (state === "streaming" && dev.firmware) osc.string("firmware", P.firmwareShort(dev.firmware));
      this.emit("status", state, { status: state });
      if (state === "streaming") {
        const hint = this.emgHint();
        if (hint) this.note("warning", hint);
      }
    });

    dev.onLog.connect((msg) => this.emit("log", msg));
  }

  /** A tap from the band's firmware: through the tap filter (threshold, cooldown) to OSC. The
   * strength comes from the IMU stream, so it is known only in IMU mode "all". */
  private tap(ev: P.MotionEvent, t: number): void {
    const proc = this.processor;
    const taps = proc.taps;
    const measured = proc.imuLive(t);

    const report = (kept: boolean, why: string) => {
      const s = measured ? proc.tapStrength(t - TAP_PRE_S, t + TAP_POST_S) : null;
      const data: Record<string, unknown> = {
        direction: ev.tapDirection, count: ev.tapCount, strength_g: s !== null ? Math.round(s * 100) / 100 : "n/a",
      };
      if (!kept) data.ignored = why;
      else if (taps.thresholdG > 0 && !measured) data.threshold = "not applied: needs IMU data (IMU mode all)";
      this.emit("tap", `tap dir=${ev.tapDirection} count=${ev.tapCount}`, data, t);
    };

    if (taps.thresholdG > 0 && measured) {
      setTimeout(() => { // wait for the IMU samples just after the knock
        const s = proc.tapStrength(t - TAP_PRE_S, t + TAP_POST_S);
        const [kept, why] = taps.decide(t, s);
        if (kept) this.osc.tap(ev.tapDirection, ev.tapCount);
        report(kept, why);
      }, TAP_POST_S * 1000);
      return;
    }
    const [kept, why] = taps.decide(t, null); // no threshold to check: send at once
    if (kept) this.osc.tap(ev.tapDirection, ev.tapCount);
    if (measured) setTimeout(() => report(kept, why), TAP_POST_S * 1000); // log the strength, to pick a threshold
    else report(kept, why);
  }

  /** Double-tap pose = SET ORIGIN, so the performer can re-align the yaw away from the computer. */
  private doubleTapToOrigin(t: number): void {
    if (t - this.lastOriginTap < DOUBLE_TAP_ORIGIN_GAP_S) return;
    this.lastOriginTap = t;
    if (this.setOrigin("double tap", t)) this.device.vibrate(P.VibrationType.SHORT).catch(() => undefined); // felt on the arm
    else this.note("warning", `double tap: ${NO_ORIGIN}`);
  }

  /** Current orientation becomes the origin (SET ORIGIN). False without IMU data from the last
   * second (IMU mode events or off, stream stopped): a stale frame is no origin. */
  setOrigin(source = "", now = this.clock()): boolean {
    if (!this.processor.imuLive(now, ORIGIN_FRESH_S)) return false;
    const ref = this.processor.zero();
    if (!ref) return false;
    const data: Record<string, unknown> = { reference: ref.map((v) => Math.round(v * 1e4) / 1e4) };
    if (source) data.by = source;
    this.emit("zero", "orientation zero set", data);
    this.onZero(ref);
    return true;
  }

  /** SET ORIGIN from the UI or OSC: warns when there is nothing to set it from. */
  zero(source = ""): void {
    if (!this.setOrigin(source)) this.note("warning", `${source || "SET ORIGIN"}: ${NO_ORIGIN}`);
  }

  clearZero(): void {
    this.processor.clearZero();
    this.onZero(null);
  }

  /** /myo/<id|all>/<command> from the control port (osc/server.py). */
  async control(m: OscMessage): Promise<void> {
    const parts = m.address.replace(/^\/+/, "").split("/");
    let target: string, cmd: string;
    if (parts[0] === "myo") [target, cmd] = [parts[1] ?? "", parts.slice(2).join("/")];
    else if (/^myo\d*$/.test(parts[0]) && parts[1] === "Yaw" && parts[2] === "calibrate") [target, cmd] = [parts[0].slice(3), "zero"];
    else return;
    if (target !== "all" && target !== "" && Number(target) !== this.device.id) return;
    const a = m.args.map((v) => (typeof v === "number" ? v : typeof v === "string" ? Number(v) : v.value));
    const dev = this.device;
    try {
      switch (cmd) {
        case "zero": return this.zero("OSC");
        case "zero/clear": return this.clearZero();
        case "resync": return await dev.resync();
        case "poweroff": // needs the argument 1, so a stray message can't switch bands off
          if (a[0] === 1) await dev.powerOff();
          else this.emit("log", "OSC control: poweroff ignored (send it with the argument 1)");
          return;
      }
      if (!dev.transport.isConnected) return;
      switch (cmd) {
        case "vibrate": {
          const kind = a.length ? Math.trunc(a[0]) : 1;
          if (kind >= 1 && kind <= 3) await dev.vibrate(kind);
          else if (kind > 3) await dev.vibrate2([[Math.min(65535, kind), 255]]); // duration ms at full strength
          return;
        }
        case "lock": return await dev.lock();
        case "unlock": {
          const kind = a.length ? Math.trunc(a[0]) : 2;
          return await dev.unlock([0, 1, 2].includes(kind) ? kind : 2);
        }
        case "mode":
          if (a.length >= 3) await dev.setMode(a[0], a[1], a[2]);
          return;
        case "sleep": return await dev.setSleepMode(a.length && a[0] ? 1 : 0);
        case "led":
          if (a.length >= 3) {
            const rgb = a.slice(0, 3) as [number, number, number];
            await dev.setLed(rgb, a.length >= 6 ? (a.slice(3, 6) as [number, number, number]) : rgb);
          }
          return;
        case "action": return await dev.userAction();
      }
      this.emit("log", `OSC control: unknown address ${m.address}`);
    } catch (e) {
      this.note("warning", `OSC control ${cmd} failed: ${errText(e)}`);
    }
  }
}
