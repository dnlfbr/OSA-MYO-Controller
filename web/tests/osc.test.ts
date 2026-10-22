import { describe, expect, it } from "vitest";
import { decodePacket, encodeBundle, encodeMessage, float, int } from "../src/osc/osc";
import { OscSender, RateLimiter } from "../src/osc/sender";

const hex = (b: Uint8Array) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");

describe("OSC encoding", () => {
  it("encodes a message like python-osc", () => {
    // /a ,ifs 1 0.5 "hi"
    expect(hex(encodeMessage("/a", [int(1), float(0.5), "hi"]))).toBe(
      "2f610000" + "2c696673" + "00000000" + "00000001" + "3f000000" + "68690000");
  });

  it("round-trips messages and bundles", () => {
    const m1 = encodeMessage("/myo/1/emg/raw", [-128, 0, 127].map(int));
    const m2 = encodeMessage("/myo/1/pose", ["fist"]);
    const msgs = decodePacket(encodeBundle([m1, m2]));
    expect(msgs).toEqual([{ address: "/myo/1/emg/raw", args: [-128, 0, 127] }, { address: "/myo/1/pose", args: ["fist"] }]);
    expect(decodePacket(encodeMessage("/x", []))).toEqual([{ address: "/x", args: [] }]);
  });

  it("bundle header is #bundle + immediately", () => {
    const b = encodeBundle([encodeMessage("/x", [])]);
    expect(hex(b.subarray(0, 16))).toBe("2362756e646c6500" + "0000000000000001");
  });
});

describe("OscSender", () => {
  it("rate limiter: jittery 50 Hz passes, 200 Hz is cut to 50 Hz (tests/test_osc.py)", () => {
    let lim = new RateLimiter(50);
    let n = 0;
    for (let i = 0; i < 100; i++) if (lim.allow(i * 0.02 + (((i * 7919) % 11) / 10 - 0.5) * 0.001)) n++; // +-0.5 ms
    expect(n).toBe(100);
    lim = new RateLimiter(50);
    n = 0;
    for (let i = 0; i < 200; i++) if (lim.allow(i * 0.005)) n++;
    expect(n).toBeGreaterThanOrEqual(49);
    expect(n).toBeLessThanOrEqual(51);
    expect(new RateLimiter(0).allow(1) && new RateLimiter(0).allow(1)).toBe(true);
  });

  it("bundles 4 EMG samples per packet with the default addresses", () => {
    const packets: Uint8Array[] = [];
    const osc = new OscSender((p) => packets.push(p));
    for (let i = 0; i < 8; i++) osc.emg([i, 0, 0, 0, 0, 0, 0, 0], Array(8).fill(0));
    expect(packets.length).toBe(2);
    const msgs = decodePacket(packets[0]);
    expect(msgs.length).toBe(4); // emg_raw on, emg_norm off by default
    expect(msgs[3]).toEqual({ address: "/myo/1/emg/raw", args: [3, 0, 0, 0, 0, 0, 0, 0] });
  });

  it("sends pose, tap and integers with the Python types", () => {
    const packets: Uint8Array[] = [];
    const osc = new OscSender((p) => packets.push(p), 2);
    osc.pose("fist", 1);
    osc.tap(3, 2);
    osc.integer("battery", 80);
    osc.streams.battery = false;
    osc.integer("battery", 79);
    expect(packets.flatMap((p) => decodePacket(p))).toEqual([
      { address: "/myo/2/pose", args: ["fist"] },
      { address: "/myo/2/pose/id", args: [1] },
      { address: "/myo/2/tap", args: [3, 2] },
      { address: "/myo/2/battery", args: [80] },
    ]);
  });

  it("imu streams in one bundle, rate limited", () => {
    const packets: Uint8Array[] = [];
    const osc = new OscSender((p) => packets.push(p), 1, 25);
    const v = { quat: [1, 0, 0, 0], quatRaw: [1, 0, 0, 0], euler: [0, 0, 0], eulerDeg: [0, 0, 0], eulerNorm: [0.5, 0.5, 0.5],
      accel: [0, 0, 1], gyro: [0, 0, 0] };
    for (let i = 0; i < 10; i++) osc.imu(v, i * 0.02);
    expect(packets.length).toBe(5);
    expect(decodePacket(packets[0]).map((m) => m.address)).toEqual(["/myo/1/quat", "/myo/1/euler", "/myo/1/accel", "/myo/1/gyro"]);
  });

  it("sends nothing without a sink", () => {
    const osc = new OscSender(null);
    expect(osc.wants("pose")).toBe(false);
    expect(osc.emg(Array(8).fill(0), Array(8).fill(0))).toBe(false);
  });
});
