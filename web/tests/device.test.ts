// Port of tests/test_device.py, against the TypeScript mock (real timers, like the asyncio tests).
import { describe, expect, it } from "vitest";
import * as P from "../src/myo/protocol";
import { MyoDevice, type DeviceConfig, type DeviceState } from "../src/myo/device";
import { MockTransport } from "../src/myo/mock";
import { TransportError, sleep } from "../src/myo/transport";

const cfg = (kw: Partial<DeviceConfig> = {}): Partial<DeviceConfig> => ({
  keepaliveS: 0, batteryPollS: 0, rssiPollS: 0, commandSpacingS: 0, reconnectBackoffS: [0.05, 0.05], ...kw,
});

describe("MyoDevice", () => {
  it("connects, configures, streams and shuts down", async () => {
    const tr = new MockTransport({ seed: 1 });
    const dev = new MyoDevice(tr, 1, cfg());
    const states: DeviceState[] = [];
    const emg: P.EmgSample[] = [], imu: P.ImuPacket[] = [], cls: P.ClassifierEvent[] = [];
    dev.onState.connect((s) => states.push(s));
    dev.onEmg.connect((s) => emg.push(s));
    dev.onImu.connect((p) => imu.push(p));
    dev.onClassifier.connect((e) => cls.push(e));

    await dev.connect();
    expect(dev.state).toBe("streaming");
    expect(P.firmwareShort(dev.firmware!)).toBe("1.5.1970.2");
    expect(P.serialString(dev.info!)).toBe("d2-b5-d9-be-cc-01");
    expect(dev.battery).toBe(87);
    // configure order: never_sleep, then set_mode, unlock (classifier on), then vibrate
    expect(tr.commands[0]).toEqual(P.cmdSetSleepMode(P.SleepMode.NEVER_SLEEP));
    expect(tr.commands[1]).toEqual(P.cmdSetMode(3, 3, 1));
    expect(tr.commands[2]).toEqual(P.cmdUnlock(P.UnlockType.HOLD));
    expect(tr.commands[3]).toEqual(P.cmdVibrate(P.VibrationType.SHORT));

    await sleep(1200);
    expect(emg.length).toBeGreaterThanOrEqual(180);
    expect(emg.every((s) => s.length === 8)).toBe(true);
    expect(imu.length).toBeGreaterThanOrEqual(45);
    expect(dev.synced).toBe(true);
    expect(dev.arm).toBe(P.Arm.RIGHT);
    expect(dev.locked).toBe(false);
    expect(cls.some((e) => e.type === P.ClassifierEventType.ARM_SYNCED)).toBe(true);
    expect(dev.stats.emgDropped).toBe(0);
    expect(dev.stats.emgPerChar[0]).toBeGreaterThan(10);

    await dev.disconnect();
    expect(dev.state).toBe("disconnected");
    expect(tr.commands.at(-2)).toEqual(P.cmdSetMode(0, 0, 0));
    expect(tr.commands.at(-1)).toEqual(P.cmdSetSleepMode(P.SleepMode.NORMAL));
    expect(tr.sleepMode).toBe(P.SleepMode.NORMAL);
    expect(states).toEqual(["connecting", "connected", "streaming", "disconnected"]);
  });

  it("reconnects after a link loss", async () => {
    const tr = new MockTransport({ seed: 2 });
    const dev = new MyoDevice(tr, 1, cfg());
    const states: DeviceState[] = [];
    dev.onState.connect((s) => states.push(s));
    await dev.connect();
    tr.simulateLinkLoss();
    expect(dev.state).toBe("reconnecting");
    await sleep(500);
    expect(dev.state).toBe("streaming");
    expect(states).toContain("reconnecting");
    await dev.disconnect();
  });

  it("does not reconnect when disabled", async () => {
    const tr = new MockTransport({ seed: 3 });
    const dev = new MyoDevice(tr, 1, cfg({ reconnect: false }));
    await dev.connect();
    tr.simulateLinkLoss();
    await sleep(200);
    expect(dev.state).toBe("disconnected");
  });

  it("sends commands and tracks the lock state", async () => {
    const tr = new MockTransport({ seed: 4 });
    const dev = new MyoDevice(tr, 1, cfg());
    await dev.connect();
    await dev.vibrate(P.VibrationType.LONG);
    expect(tr.vibrations.at(-1)).toBe(3);
    await dev.lock();
    expect(dev.locked).toBe(true);
    await dev.unlock();
    expect(dev.locked).toBe(false);
    await dev.setMode(P.EmgMode.FILTERED, P.ImuMode.DATA, P.ClassifierMode.DISABLED);
    expect(tr.emgMode).toBe(P.EmgMode.FILTERED);
    expect(dev.config.imuMode).toBe(P.ImuMode.DATA);
    await dev.disconnect();
  });

  it("drop counter sees missing notifications", async () => {
    const tr = new MockTransport({ seed: 5, dropEvery: 10 });
    const dev = new MyoDevice(tr, 1, cfg());
    await dev.connect();
    await sleep(2300);
    expect(dev.stats.emgDropped).toBeGreaterThanOrEqual(10);
    await dev.disconnect();
  });

  it("connect failure throws and resets the state", async () => {
    const dev = new MyoDevice(new MockTransport({ failConnect: true }), 1, cfg());
    await expect(dev.connect()).rejects.toBeInstanceOf(TransportError);
    expect(dev.state).toBe("disconnected");
  });

  it("resync unlocks after sync, power off stays off", async () => {
    const tr = new MockTransport({ seed: 6 });
    const dev = new MyoDevice(tr, 1, cfg());
    const events: number[] = [];
    dev.onClassifier.connect((e) => events.push(e.type));
    await dev.connect();
    const unlock = P.cmdUnlock(P.UnlockType.HOLD);
    const count = () => tr.commands.filter((c) => c.join() === unlock.join()).length;
    expect(count()).toBe(1); // on connect: a band still synced from before sends no ARM_SYNCED
    await sleep(1000);
    expect(dev.synced).toBe(true);
    expect(count()).toBe(2); // and after each sync: poses need an unlocked band

    const n = tr.commands.length;
    await dev.resync();
    expect(dev.synced).toBe(false);
    expect(events).toContain(P.ClassifierEventType.ARM_UNSYNCED);
    expect(tr.commands.slice(n, n + 2)).toEqual([P.cmdSetMode(3, 3, 0), P.cmdSetMode(3, 3, 1)]);
    await sleep(1000);
    expect(dev.synced).toBe(true); // the mock syncs again once the classifier is back on

    await dev.powerOff();
    expect(tr.commands.at(-1)).toEqual(P.cmdDeepSleep());
    expect(dev.state).toBe("disconnected");
    expect(tr.isConnected).toBe(false);
    expect(dev.synced).toBe(false);
    await sleep(200);
    expect(dev.state).toBe("disconnected"); // no reconnect after a power off
  });

  it("unlock on sync can be disabled", async () => {
    const tr = new MockTransport({ seed: 7 });
    const dev = new MyoDevice(tr, 1, cfg({ unlockOnSync: false }));
    await dev.connect();
    await sleep(1000);
    expect(dev.synced).toBe(true);
    expect(tr.commands.some((c) => c.join() === P.cmdUnlock(P.UnlockType.HOLD).join())).toBe(false);
    await dev.disconnect();
  });
}, 20000);
