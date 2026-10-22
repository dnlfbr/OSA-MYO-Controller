import { describe, expect, it } from "vitest";
import * as P from "../src/myo/protocol";
import { MockTransport } from "../src/myo/mock";
import { sleep } from "../src/myo/transport";
import { Bridge } from "../src/bridge";
import { decodePacket, encodeMessage, float, int } from "../src/osc/osc";

const fast = { keepaliveS: 0, batteryPollS: 0, rssiPollS: 0, commandSpacingS: 0 };

describe("Bridge", () => {
  it("streams OSC from the mock, sets and clears the origin", async () => {
    const tr = new MockTransport({ seed: 11 });
    const packets: Uint8Array[] = [];
    const b = new Bridge(tr, { device: fast });
    b.osc.setSink((p) => packets.push(p));
    let stored: P.Quat | null | undefined;
    b.onZero = (q) => (stored = q);
    await b.device.connect();
    await sleep(1100);
    const addrs = new Set(packets.flatMap((p) => decodePacket(p).map((m) => m.address)));
    for (const a of ["/myo/1/emg/raw", "/myo/1/emg/rms", "/myo/1/quat", "/myo/1/euler", "/myo/1/status", "/myo/1/sync", "/myo/1/arm"])
      expect(addrs).toContain(a);
    expect(b.emg.count).toBeGreaterThan(150);
    expect(b.quat.count).toBeGreaterThan(40);

    b.zero("UI");
    expect(stored).not.toBeNull();
    expect(b.log.at(-1)!.kind).toBe("zero");
    expect(Math.abs(b.lastFrame ? 0 : 1)).toBe(0);
    await sleep(60);
    expect(Math.abs(b.lastFrame!.euler[2])).toBeLessThan(0.1); // yaw re-centred
    b.clearZero();
    expect(stored).toBeNull();
    await b.device.disconnect();
  }, 10000);

  it("SET ORIGIN without IMU data warns instead", async () => {
    const tr = new MockTransport({ seed: 12 });
    const b = new Bridge(tr, { device: { ...fast, imuMode: P.ImuMode.EVENTS } });
    await b.device.connect();
    await sleep(100);
    b.zero();
    expect(b.log.at(-1)).toMatchObject({ kind: "warning" });
    expect(b.log.at(-1)!.text).toContain("no IMU data");
    await b.device.disconnect();
  });

  it("applies control messages like the Python control server", async () => {
    const tr = new MockTransport({ seed: 13 });
    const b = new Bridge(tr, { device: fast });
    await b.device.connect();
    const ctl = (addr: string, ...args: Parameters<typeof encodeMessage>[1]) =>
      Promise.all(decodePacket(encodeMessage(addr, args)).map((m) => b.control(m)));
    await ctl("/myo/1/vibrate", int(3));
    expect(tr.vibrations.at(-1)).toBe(3);
    await ctl("/myo/all/lock");
    expect(b.device.locked).toBe(true);
    await ctl("/myo/2/unlock"); // another band: ignored
    expect(b.device.locked).toBe(true);
    await ctl("/myo/1/mode", int(1), int(3), int(1));
    expect(tr.emgMode).toBe(P.EmgMode.SMOOTH);
    await ctl("/myo/1/poweroff"); // without the argument 1: ignored
    expect(b.device.state).toBe("streaming");
    await ctl("/myo/1/vibrate", float(500)); // > 3: duration in ms
    expect(tr.commands.at(-1)![0]).toBe(P.CMD_VIBRATE2);
    await ctl("/myo/1/poweroff", int(1));
    expect(b.device.state).toBe("disconnected");
  });

  it("double tap sets the origin when enabled", async () => {
    const tr = new MockTransport({ seed: 14, posePeriodS: 100 });
    const b = new Bridge(tr, { device: fast, doubleTapOrigin: true });
    await b.device.connect();
    await sleep(900);
    const before = tr.vibrations.length;
    tr.triggerPose(P.Pose.DOUBLE_TAP);
    tr.triggerPose(P.Pose.DOUBLE_TAP); // repeated by the classifier: one origin only
    await sleep(50);
    expect(b.log.filter((e) => e.kind === "zero").length).toBe(1);
    expect(tr.vibrations.length).toBe(before + 1);
    await b.device.disconnect();
  });
});
