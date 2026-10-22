// Same vectors as tests/test_processing.py.
import { describe, expect, it } from "vitest";
import * as P from "../src/myo/protocol";
import { RmsEnvelope } from "../src/processing/envelope";
import { DeviceProcessor, TapFilter, fvActivity } from "../src/processing/pipeline";
import { emgNorm, vecNorm } from "../src/processing/scaling";

const close = (a: number[], b: number[], digits = 6) => a.forEach((v, i) => expect(v).toBeCloseTo(b[i], digits));

const imuPacket = (accelG: P.Vec3, quat: P.Quat = [1, 0, 0, 0]): P.ImuPacket => ({
  quat: quat.map((q) => Math.round(q * P.ORIENTATION_SCALE)) as P.Quat,
  accel: accelG.map((a) => Math.round(a * P.ACCELEROMETER_SCALE)) as P.Vec3,
  gyro: [0, 0, 0],
});

describe("scaling and envelope", () => {
  it("emg norm range", () => {
    close(emgNorm([-128, 0, 127, 64, -64, 1, -1, 32]), [-1, 0, 0.9921875, 0.5, -0.5, 1 / 128, -1 / 128, 0.25]);
  });

  it("vec norm clamps", () => {
    expect(vecNorm([2000, -500, 3000], 1000)).toEqual([1, -0.5, 1]);
  });

  it("rms envelope on a constant signal", () => {
    const env = new RmsEnvelope(8, 10);
    for (let i = 0; i < 25; i++) env.push(Array(8).fill(0.5));
    close(env.values, Array(8).fill(0.5));
    expect(env.mean).toBeCloseTo(0.5);
  });

  it("rms envelope window and sine", () => {
    const env = new RmsEnvelope(1, 200);
    for (let i = 0; i < 400; i++) env.push([Math.sin((2 * Math.PI * i) / 20)]);
    expect(Math.abs(env.values[0] - 1 / Math.SQRT2)).toBeLessThan(1e-3);
    env.setWindow(5);
    expect(env.values).toEqual([0]);
  });

  it("smooth EMG activity", () => {
    close(fvActivity([0, 256, 512, 1024, 3000, 0, 0, 0]), [0, 0.25, 0.5, 1, 1, 0, 0, 0]);
  });
});

describe("processor", () => {
  it("imu and zero", () => {
    const proc = new DeviceProcessor({ rmsWindowMs: 50, zeroMode: "yaw" });
    expect(proc.rms.window).toBe(10); // 50 ms @ 200 Hz
    const w = Math.sqrt(0.5);
    const pkt: P.ImuPacket = { quat: [Math.trunc(w * 16384), 0, 0, Math.trunc(w * 16384)], accel: [0, 0, 2048], gyro: [0, 0, 160] };
    const fr = proc.pushImu(pkt, 1.0);
    expect(fr.euler[2]).toBeCloseTo(Math.PI / 2, 3);
    expect(fr.accel).toEqual([0, 0, 1]);
    expect(fr.gyro).toEqual([0, 0, 10]);
    expect(proc.zero()).not.toBeNull();
    const fr2 = proc.pushImu(pkt, 1.02);
    expect(fr2.euler[2]).toBeCloseTo(0, 3);
    expect(fr2.quatRaw).toEqual(fr.quatRaw); // raw is untouched
    proc.clearZero();
    expect(proc.pushImu(pkt, 1.04).euler[2]).toBeCloseTo(Math.PI / 2, 3);
  });

  it("emg", () => {
    const proc = new DeviceProcessor();
    expect(proc.pushEmg(Array(8).fill(64), 0)).toEqual(Array(8).fill(0.5));
    expect(proc.lastEmgRaw).toEqual(Array(8).fill(64));
    close(proc.rms.values, Array(8).fill(0.5));
  });

  it("tap filter threshold and cooldown", () => {
    const f = new TapFilter(0.5, 200);
    expect(f.decide(0.0, 0.8)).toEqual([true, ""]);
    expect(f.decide(0.1, 2.0)).toEqual([false, "within 200 ms of the last tap"]);
    expect(f.decide(0.5, 0.3)).toEqual([false, "weaker than 0.50 g"]);
    expect(f.decide(0.6, null)).toEqual([true, ""]); // strength unknown (no IMU data): kept
    expect(f.decide(0.75, 1.0)[0]).toBe(false); // the cooldown counts from the last kept tap
    expect(f.decide(0.85, 1.0)[0]).toBe(true);
    expect(new TapFilter().decide(0, 0.01)).toEqual([true, ""]); // both off
  });

  it("tap strength is the largest jump of acceleration", () => {
    const proc = new DeviceProcessor();
    expect(proc.tapStrength(0, 10)).toBeNull();
    expect(proc.imuLive(0)).toBe(false);
    for (let i = 0; i < 50; i++) proc.pushImu(imuPacket(i === 25 ? [0.9, 0, 1] : [0, 0, 1]), i * 0.02);
    expect(Math.abs(proc.tapStrength(0.38, 0.56)! - 0.9)).toBeLessThan(0.01);
    expect(Math.abs(proc.tapStrength(0.0, 0.4)!)).toBeLessThan(0.01);
    expect(proc.imuLive(1.0)).toBe(true);
    expect(proc.imuLive(2.0)).toBe(false);
    proc.pushImu(imuPacket([0, 0, 2]), 5.0); // after a gap in the stream: no jump measured across it
    expect(proc.tapStrength(4.9, 5.1)).toBeNull();
    proc.setTapFilter(0.4, 100);
    expect(proc.taps.thresholdG).toBe(0.4);
    expect(proc.params.tapCooldownMs).toBe(100);
  });
});
