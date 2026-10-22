// End to end: page -> WebSocket -> relay -> UDP, and control UDP -> relay -> page.
import { spawn } from "node:child_process";
import dgram from "node:dgram";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { decodePacket, encodeMessage, int } from "../src/osc/osc";

const RELAY = fileURLToPath(new URL("../relay/myo-osc-relay.mjs", import.meta.url));
const [WS, OSC, CTL] = [18765, 17400, 17401];
let proc: ReturnType<typeof spawn>;

beforeAll(async () => {
  proc = spawn(process.execPath, [RELAY, "--ws-port", String(WS), "--osc-port", String(OSC), "--control-port", String(CTL)]);
  await new Promise<void>((resolve, reject) => {
    proc.stdout!.on("data", (d) => String(d).includes("myo-osc-relay") && resolve());
    proc.on("exit", (c) => reject(new Error(`relay exited ${c}`)));
  });
});
afterAll(() => proc?.kill());

describe("relay", () => {
  it("forwards OSC both ways", async () => {
    const udp = dgram.createSocket("udp4");
    await new Promise<void>((r) => udp.bind(OSC, "127.0.0.1", r));
    const got = new Promise<Buffer>((r) => udp.once("message", (m) => r(m)));

    const ws = new WebSocket(`ws://127.0.0.1:${WS}`);
    ws.binaryType = "arraybuffer";
    await new Promise((r) => (ws.onopen = r));
    const pkt = encodeMessage("/myo/1/tap", [int(2), int(1)]);
    ws.send(pkt);
    expect(new Uint8Array(await got)).toEqual(pkt);

    const back = new Promise<ArrayBuffer>((r) => (ws.onmessage = (e) => r(e.data as ArrayBuffer)));
    const ctl = encodeMessage("/myo/1/vibrate", [int(2)]);
    udp.send(ctl, CTL, "127.0.0.1");
    expect(decodePacket(new Uint8Array(await back))).toEqual([{ address: "/myo/1/vibrate", args: [2] }]);
    ws.close();
    udp.close();
  });
});
