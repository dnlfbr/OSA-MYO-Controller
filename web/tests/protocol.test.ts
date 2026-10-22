// Same vectors as tests/test_protocol.py.
import { describe, expect, it } from "vitest";
import * as P from "../src/myo/protocol";

const bytes = (...b: number[]) => Uint8Array.from(b);
const i16 = (...v: number[]) => {
  const b = new Uint8Array(v.length * 2);
  const dv = new DataView(b.buffer);
  v.forEach((x, i) => dv.setInt16(2 * i, x, true));
  return b;
};

describe("protocol", () => {
  it("uuids follow base", () => {
    expect(P.UUIDS.CONTROL_SERVICE).toBe("d5060001-a904-deb9-4748-2c7f4a124842");
    expect(P.UUIDS.COMMAND).toBe("d5060401-a904-deb9-4748-2c7f4a124842");
    expect(P.UUIDS.EMG3).toBe("d5060405-a904-deb9-4748-2c7f4a124842");
    expect(P.UUIDS.CLASSIFIER_EVENT).toBe("d5060103-a904-deb9-4748-2c7f4a124842");
    expect(P.UUIDS.BATTERY_LEVEL).toBe("00002a19-0000-1000-8000-00805f9b34fb");
  });

  it("every characteristic has a service and every service is requested", () => {
    for (const uuid of [P.UUIDS.INFO, P.UUIDS.FIRMWARE, P.UUIDS.COMMAND, P.UUIDS.IMU_DATA, P.UUIDS.MOTION_EVENT,
      P.UUIDS.CLASSIFIER_EVENT, P.UUIDS.FV_DATA, ...P.EMG_UUIDS, P.UUIDS.BATTERY_LEVEL]) {
      expect(P.ALL_SERVICES).toContain(P.SERVICE_OF[uuid]);
    }
  });

  it("command bytes match myohw.h", () => {
    expect(P.cmdSetMode(3, 3, 1)).toEqual(bytes(0x01, 0x03, 0x03, 0x03, 0x01));
    expect(P.cmdSetMode(P.EmgMode.FILTERED, P.ImuMode.NONE, P.ClassifierMode.DISABLED)).toEqual(bytes(0x01, 3, 2, 0, 0));
    expect(P.cmdVibrate(P.VibrationType.LONG)).toEqual(bytes(0x03, 0x01, 0x03));
    expect(P.cmdSetSleepMode(P.SleepMode.NEVER_SLEEP)).toEqual(bytes(0x09, 0x01, 0x01));
    expect(P.cmdUnlock(P.UnlockType.HOLD)).toEqual(bytes(0x0a, 0x01, 0x02));
    expect(P.cmdUserAction()).toEqual(bytes(0x0b, 0x01, 0x00));
    expect(P.cmdDeepSleep()).toEqual(bytes(0x04, 0x00));
    expect(P.cmdSetLed([255, 0, 0], [0, 0, 255])).toEqual(bytes(0x06, 6, 255, 0, 0, 0, 0, 255));
  });

  it("vibrate2 is an 18 byte payload", () => {
    const b = P.cmdVibrate2([[100, 255], [50, 128]]);
    expect(b.length).toBe(20);
    expect([b[0], b[1]]).toEqual([0x07, 18]);
    const dv = new DataView(b.buffer);
    expect([dv.getUint16(2, true), b[4]]).toEqual([100, 255]);
    expect([dv.getUint16(5, true), b[7]]).toEqual([50, 128]);
    expect(b.slice(8)).toEqual(new Uint8Array(12));
    expect(() => P.cmdVibrate2(Array(7).fill([1, 1]))).toThrow();
  });

  it("parses IMU scaling and order", () => {
    // w=16384 (1.0), x=-8192 (-0.5), y=0, z=4096 (0.25); accel 2048 -> 1 g; gyro 160 -> 10 dps
    const data = i16(16384, -8192, 0, 4096, 2048, 0, -2048, 160, -16, 0);
    const pkt = P.parseImu(data);
    expect(pkt.quat).toEqual([16384, -8192, 0, 4096]);
    expect(P.quatF(pkt)).toEqual([1.0, -0.5, 0.0, 0.25]);
    expect(P.accelG(pkt)).toEqual([1.0, 0.0, -1.0]);
    expect(P.gyroDps(pkt)).toEqual([10.0, -1.0, 0.0]);
    expect(() => P.parseImu(data.slice(0, 19))).toThrow();
  });

  it("parses EMG as two int8 samples", () => {
    const s1 = [-128, -1, 0, 1, 127, 10, -10, 5];
    const s2 = [1, 2, 3, 4, 5, 6, 7, 8];
    const data = new Uint8Array(Int8Array.from([...s1, ...s2]).buffer);
    const [a, b] = P.parseEmg(data);
    expect(a).toEqual(s1);
    expect(b).toEqual(s2);
    expect(() => P.parseEmg(data.slice(0, 15))).toThrow();
  });

  it("parses smooth EMG (FV)", () => {
    const data = new Uint8Array(17);
    const dv = new DataView(data.buffer);
    [100, 200, 300, 400, 500, 600, 700, 800].forEach((v, i) => dv.setUint16(2 * i, v, true));
    data[16] = 3;
    const pkt = P.parseFv(data);
    expect(pkt.values).toEqual([100, 200, 300, 400, 500, 600, 700, 800]);
    expect(pkt.mask).toBe(3);
    expect(P.parseFv(data.slice(0, 16)).mask).toBe(0);
  });

  it.each([[bytes(0x01, 0x02, 0x01)], [bytes(0x01, 0x02, 0x01, 0, 0, 0)]])("classifier arm synced, 3 or 6 bytes", (raw) => {
    const ev = P.parseClassifier(raw);
    expect(ev.type).toBe(P.ClassifierEventType.ARM_SYNCED);
    expect(ev.arm).toBe(P.Arm.LEFT);
    expect(ev.xDirection).toBe(P.XDirection.TOWARD_WRIST);
    expect(P.armLabel(ev.arm)).toBe("left");
    expect(P.xDirectionLabel(ev.xDirection)).toBe("wrist");
    expect(P.classifierLabel(ev)).toBe("arm_synced");
    expect(ev.warmupState).toBe(P.WarmupState.UNKNOWN);
  });

  it("classifier warm-up", () => {
    let ev = P.parseClassifier(bytes(0x01, 0x01, 0x02, 0x01, 0x00, 0x40));
    expect(ev.arm).toBe(P.Arm.RIGHT);
    expect(ev.xDirection).toBe(P.XDirection.TOWARD_ELBOW);
    expect(ev.warmupState).toBe(P.WarmupState.COLD);
    expect(P.parseClassifier(bytes(0x01, 0x01, 0x01, 0x02, 0, 0)).warmupState).toBe(P.WarmupState.WARM);
    expect(P.parseClassifier(bytes(0x01, 0x01, 0x01, 0x09, 0, 0)).warmupState).toBe(P.WarmupState.UNKNOWN);
    ev = P.parseClassifier(bytes(0x07, 0x01, 0, 0, 0, 0));
    expect(P.classifierLabel(ev)).toBe("warmup_completed");
    expect(ev.warmupResult).toBe(P.WarmupResult.SUCCESS);
    expect(P.parseClassifier(bytes(0x07, 0x02)).warmupResult).toBe(P.WarmupResult.FAILED_TIMEOUT);
  });

  it("classifier pose is uint16 LE", () => {
    let ev = P.parseClassifier(bytes(0x03, 0x05, 0x00, 0, 0, 0));
    expect(ev.pose).toBe(P.Pose.DOUBLE_TAP);
    expect(P.poseLabel(ev.pose)).toBe("double_tap");
    ev = P.parseClassifier(bytes(0x03, 0xff, 0xff));
    expect(ev.pose).toBe(P.Pose.UNKNOWN);
  });

  it("classifier other events", () => {
    expect(P.classifierLabel(P.parseClassifier(bytes(0x02, 0, 0)))).toBe("arm_unsynced");
    expect(P.classifierLabel(P.parseClassifier(bytes(0x04, 0, 0)))).toBe("unlocked");
    expect(P.classifierLabel(P.parseClassifier(bytes(0x05, 0, 0)))).toBe("locked");
    const ev = P.parseClassifier(bytes(0x06, 0x01, 0));
    expect(P.classifierLabel(ev)).toBe("sync_failed");
    expect(ev.syncResult).toBe(P.SyncResult.FAILED_TOO_HARD);
    expect(P.classifierLabel(P.parseClassifier(bytes(0x07, 0, 0)))).toBe("warmup_completed");
    expect(P.classifierLabel(P.parseClassifier(bytes(0x42, 0, 0)))).toBe("unknown_66"); // must not throw
    expect(() => P.parseClassifier(new Uint8Array(0))).toThrow();
  });

  it("parses motion", () => {
    expect(P.parseMotion(bytes(0x00, 0x02, 0x01))).toEqual({ type: P.MotionEventType.TAP, tapDirection: 2, tapCount: 1 });
  });

  it("parses firmware version", () => {
    const b = new Uint8Array(8);
    const dv = new DataView(b.buffer);
    [1, 5, 1970, 2].forEach((v, i) => dv.setUint16(2 * i, v, true));
    const fw = P.parseFirmwareVersion(b);
    expect([fw.major, fw.minor, fw.patch]).toEqual([1, 5, 1970]);
    expect(fw.hardwareRev).toBe(P.HardwareRev.REV_D);
    expect(P.firmwareShort(fw)).toBe("1.5.1970.2");
    expect(P.firmwareString(fw)).toBe("1.5.1970 (rev_d)");
  });

  it("parses firmware info", () => {
    const b = new Uint8Array(20);
    b.set([0x8f, 0xcc, 0xbe, 0xd9, 0xb5, 0xd2], 0);
    new DataView(b.buffer).setUint16(6, 0x0005, true);
    b.set([1, 2, 1, 0, 2], 8);
    const info = P.parseFirmwareInfo(b);
    expect(P.serialString(info)).toBe("d2-b5-d9-be-cc-8f");
    expect(info.unlockPose).toBe(P.Pose.DOUBLE_TAP);
    expect(info.classifierType).toBe(P.ClassifierModelType.CUSTOM);
    expect(info.classifierIndex).toBe(2);
    expect(info.hasCustomClassifier).toBe(true);
    expect(info.streamIndicating).toBe(false);
    expect(info.sku).toBe(P.SKU.WHITE);
  });

  it("parses battery", () => {
    expect(P.parseBattery(bytes(0x5b))).toBe(91);
    expect(() => P.parseBattery(new Uint8Array(0))).toThrow();
  });
});
