/**
 * Myo BLE protocol: UUIDs, enums, command builders and packet parsers.
 *
 * TypeScript port of src/myo_bridge/myo/protocol.py — keep the two in step. Pure functions and
 * data only, no I/O. Cross-checked against Thalmic's myohw.h (Apache-2.0) and the open
 * implementations listed in the README; docs/protocol.md explains the discrepancies.
 *
 * Byte order: myohw.h says big-endian, every working implementation (and the firmware) uses
 * little-endian. All DataView reads here pass `true`.
 */

// --------------------------------------------------------------------------- UUIDs

const hex4 = (n: number) => n.toString(16).padStart(4, "0");
export const myoUuid = (short: number) => `d506${hex4(short)}-a904-deb9-4748-2c7f4a124842`;
export const stdUuid = (short: number) => `0000${hex4(short)}-0000-1000-8000-00805f9b34fb`;

/** 128-bit UUID strings, lower case (as Web Bluetooth and bleak report them). */
export const UUIDS = {
  CONTROL_SERVICE: myoUuid(0x0001),
  INFO: myoUuid(0x0101), // read: FirmwareInfo (20 bytes)
  FIRMWARE: myoUuid(0x0201), // read: FirmwareVersion (8 bytes)
  COMMAND: myoUuid(0x0401), // write (with response)

  IMU_SERVICE: myoUuid(0x0002),
  IMU_DATA: myoUuid(0x0402), // notify: 20 bytes
  MOTION_EVENT: myoUuid(0x0502), // indicate: 3 bytes

  CLASSIFIER_SERVICE: myoUuid(0x0003),
  CLASSIFIER_EVENT: myoUuid(0x0103), // indicate: 3 (observed 6) bytes

  FV_SERVICE: myoUuid(0x0004), // undocumented "filtered value" (EMG mode 1)
  FV_DATA: myoUuid(0x0104), // notify: 17 bytes (8 x uint16 + mask)

  EMG_SERVICE: myoUuid(0x0005),
  EMG0: myoUuid(0x0105), // notify: 16 bytes = 2 samples x 8 int8
  EMG1: myoUuid(0x0205),
  EMG2: myoUuid(0x0305),
  EMG3: myoUuid(0x0405),

  BATTERY_SERVICE: stdUuid(0x180f),
  BATTERY_LEVEL: stdUuid(0x2a19), // read/notify: 1 byte, percent
  DEVICE_NAME: stdUuid(0x2a00),
  MANUFACTURER: stdUuid(0x2a29),
} as const;

export const EMG_UUIDS = [UUIDS.EMG0, UUIDS.EMG1, UUIDS.EMG2, UUIDS.EMG3] as const;

/** The service that owns each characteristic (Web Bluetooth looks characteristics up per service). */
export const SERVICE_OF: Record<string, string> = {
  [UUIDS.INFO]: UUIDS.CONTROL_SERVICE,
  [UUIDS.FIRMWARE]: UUIDS.CONTROL_SERVICE,
  [UUIDS.COMMAND]: UUIDS.CONTROL_SERVICE,
  [UUIDS.IMU_DATA]: UUIDS.IMU_SERVICE,
  [UUIDS.MOTION_EVENT]: UUIDS.IMU_SERVICE,
  [UUIDS.CLASSIFIER_EVENT]: UUIDS.CLASSIFIER_SERVICE,
  [UUIDS.FV_DATA]: UUIDS.FV_SERVICE,
  [UUIDS.EMG0]: UUIDS.EMG_SERVICE,
  [UUIDS.EMG1]: UUIDS.EMG_SERVICE,
  [UUIDS.EMG2]: UUIDS.EMG_SERVICE,
  [UUIDS.EMG3]: UUIDS.EMG_SERVICE,
  [UUIDS.BATTERY_LEVEL]: UUIDS.BATTERY_SERVICE,
};

/** Every service the app touches: Web Bluetooth only exposes services named at pairing. */
export const ALL_SERVICES = [
  UUIDS.CONTROL_SERVICE, UUIDS.IMU_SERVICE, UUIDS.CLASSIFIER_SERVICE, UUIDS.FV_SERVICE,
  UUIDS.EMG_SERVICE, UUIDS.BATTERY_SERVICE,
];

// --------------------------------------------------------------------------- constants

export const EMG_CHANNELS = 8;
export const EMG_SAMPLE_RATE_HZ = 200;
export const IMU_SAMPLE_RATE_HZ = 50;
export const FV_SAMPLE_RATE_HZ = 50;
export const FV_FULL_SCALE = 1024; // nominal top of the smooth (FV) values

export const ORIENTATION_SCALE = 16384; // int16 -> unit quaternion
export const ACCELEROMETER_SCALE = 2048; // int16 -> g      (range +-16 g)
export const GYROSCOPE_SCALE = 16; // int16 -> deg/s  (range +-2000 deg/s)
export const EMG_SCALE = 128; // int8  -> -1..1

// --------------------------------------------------------------------------- enums

export const EmgMode = { NONE: 0x00, SMOOTH: 0x01, FILTERED: 0x02, RAW: 0x03 } as const;
export const ImuMode = { NONE: 0x00, DATA: 0x01, EVENTS: 0x02, ALL: 0x03, RAW: 0x04 } as const;
export const ClassifierMode = { DISABLED: 0x00, ENABLED: 0x01 } as const;
export const VibrationType = { NONE: 0x00, SHORT: 0x01, MEDIUM: 0x02, LONG: 0x03 } as const;
export const SleepMode = { NORMAL: 0x00, NEVER_SLEEP: 0x01 } as const;
export const UnlockType = { LOCK: 0x00, TIMED: 0x01, HOLD: 0x02 } as const;
export const UserActionType = { SINGLE: 0x00 } as const;

export const Pose = {
  REST: 0x0000,
  FIST: 0x0001,
  WAVE_IN: 0x0002,
  WAVE_OUT: 0x0003,
  FINGERS_SPREAD: 0x0004,
  DOUBLE_TAP: 0x0005, // THUMB_TO_PINKY in old pyomyo
  UNKNOWN: 0xffff,
} as const;

export const Arm = { UNKNOWN: 0x00, RIGHT: 0x01, LEFT: 0x02, UNKNOWN_FF: 0xff } as const;
export const XDirection = { UNKNOWN: 0x00, TOWARD_WRIST: 0x01, TOWARD_ELBOW: 0x02, UNKNOWN_FF: 0xff } as const;

export const ClassifierEventType = {
  ARM_SYNCED: 0x01,
  ARM_UNSYNCED: 0x02,
  POSE: 0x03,
  UNLOCKED: 0x04,
  LOCKED: 0x05,
  SYNC_FAILED: 0x06,
  WARMUP_COMPLETED: 0x07,
} as const;

export const SyncResult = { UNKNOWN: 0x00, FAILED_TOO_HARD: 0x01 } as const;
/** ARM_SYNCED byte 3 (libmyo, firmware 1.5+): poses are less reliable while the band is cold. */
export const WarmupState = { UNKNOWN: 0x00, COLD: 0x01, WARM: 0x02 } as const;
/** WARMUP_COMPLETED byte 1 (libmyo); expected only after a cold sync. */
export const WarmupResult = { UNKNOWN: 0x00, SUCCESS: 0x01, FAILED_TIMEOUT: 0x02 } as const;
export const MotionEventType = { TAP: 0x00 } as const;
export const ClassifierModelType = { BUILTIN: 0, CUSTOM: 1 } as const;
export const SKU = { UNKNOWN: 0, BLACK: 1, WHITE: 2 } as const;
export const HardwareRev = { UNKNOWN: 0, REV_C: 1, REV_D: 2, REV_S: 3 } as const;

type Values<T> = T[keyof T];
export type EmgModeValue = Values<typeof EmgMode>;
export type ImuModeValue = Values<typeof ImuMode>;
export type ClassifierModeValue = Values<typeof ClassifierMode>;
export type PoseValue = Values<typeof Pose>;
export type ArmValue = Values<typeof Arm>;
export type XDirectionValue = Values<typeof XDirection>;

/** Enum member name for a value, or undefined (the Python IntEnum(value) lookup). */
export function enumName<T extends Record<string, number>>(e: T, value: number): keyof T | undefined {
  for (const k in e) if (e[k] === value) return k;
  return undefined;
}

const has = (e: Record<string, number>, v: number) => Object.values(e).includes(v);
const or = (e: Record<string, number>, v: number, dflt: number) => (has(e, v) ? v : dflt);

export const poseLabel = (p: number): string =>
  (enumName(Pose, p) ?? "UNKNOWN").toString().toLowerCase();
export const armLabel = (a: number): string =>
  a === Arm.RIGHT ? "right" : a === Arm.LEFT ? "left" : "unknown";
export const xDirectionLabel = (x: number): string =>
  x === XDirection.TOWARD_WRIST ? "wrist" : x === XDirection.TOWARD_ELBOW ? "elbow" : "unknown";

// --------------------------------------------------------------------------- commands
// Each command: [command_id, payload_size, payload...]

export const CMD_SET_MODE = 0x01;
export const CMD_VIBRATE = 0x03;
export const CMD_DEEP_SLEEP = 0x04;
export const CMD_SET_LED = 0x06; // undocumented in myohw.h, present in pyomyo/pymyo/dl-myo
export const CMD_VIBRATE2 = 0x07;
export const CMD_SET_SLEEP_MODE = 0x09;
export const CMD_UNLOCK = 0x0a;
export const CMD_USER_ACTION = 0x0b;

export const VIBRATE2_STEPS = 6;

const u8 = (v: number) => v & 0xff;

export const cmdSetMode = (emg: number, imu: number, classifier: number) =>
  Uint8Array.of(CMD_SET_MODE, 3, u8(emg), u8(imu), u8(classifier));
export const cmdVibrate = (kind: number) => Uint8Array.of(CMD_VIBRATE, 1, u8(kind));
export const cmdSetSleepMode = (mode: number) => Uint8Array.of(CMD_SET_SLEEP_MODE, 1, u8(mode));
export const cmdUnlock = (kind: number) => Uint8Array.of(CMD_UNLOCK, 1, u8(kind));
export const cmdUserAction = (kind: number = UserActionType.SINGLE) =>
  Uint8Array.of(CMD_USER_ACTION, 1, u8(kind));
/** WARNING: the armband only wakes up again when plugged into USB. */
export const cmdDeepSleep = () => Uint8Array.of(CMD_DEEP_SLEEP, 0);

/** steps: up to 6 x [duration_ms uint16, strength 0..255]. Payload is 18 bytes (myohw.h). */
export function cmdVibrate2(steps: Array<[number, number]>): Uint8Array {
  if (steps.length > VIBRATE2_STEPS) throw new RangeError("vibrate2 accepts at most 6 steps");
  const out = new Uint8Array(2 + 3 * VIBRATE2_STEPS);
  const dv = new DataView(out.buffer);
  out[0] = CMD_VIBRATE2;
  out[1] = 18;
  steps.forEach(([ms, strength], i) => {
    dv.setUint16(2 + 3 * i, ms, true);
    out[4 + 3 * i] = u8(strength);
  });
  return out;
}

export function cmdSetLed(logo: [number, number, number], bar: [number, number, number]): Uint8Array {
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.trunc(v)));
  return Uint8Array.of(CMD_SET_LED, 6, ...[...logo, ...bar].map(clamp));
}

// --------------------------------------------------------------------------- packets

export type Bytes = Uint8Array | DataView | ArrayBuffer;

function view(data: Bytes): DataView {
  if (data instanceof DataView) return data;
  if (data instanceof ArrayBuffer) return new DataView(data);
  return new DataView(data.buffer, data.byteOffset, data.byteLength);
}

function bytesOf(data: Bytes): Uint8Array {
  const v = view(data);
  return new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
}

export type Vec3 = [number, number, number];
export type Quat = [number, number, number, number];

/** One IMU notification (20 bytes). Raw int16 values, order as in myohw.h: w x y z. */
export interface ImuPacket {
  quat: Quat; // raw int16, w x y z
  accel: Vec3;
  gyro: Vec3;
}

export const quatF = (p: ImuPacket): Quat => p.quat.map((v) => v / ORIENTATION_SCALE) as Quat;
export const accelG = (p: ImuPacket): Vec3 => p.accel.map((v) => v / ACCELEROMETER_SCALE) as Vec3;
export const gyroDps = (p: ImuPacket): Vec3 => p.gyro.map((v) => v / GYROSCOPE_SCALE) as Vec3;

export function parseImu(data: Bytes): ImuPacket {
  const dv = view(data);
  if (dv.byteLength < 20) throw new RangeError(`IMU packet too short: ${dv.byteLength} bytes`);
  const v = Array.from({ length: 10 }, (_, i) => dv.getInt16(2 * i, true));
  return { quat: v.slice(0, 4) as Quat, accel: v.slice(4, 7) as Vec3, gyro: v.slice(7, 10) as Vec3 };
}

export type EmgSample = number[]; // 8 x int8

/** 16 bytes -> two consecutive 8-channel samples (int8, -128..127). */
export function parseEmg(data: Bytes): [EmgSample, EmgSample] {
  const dv = view(data);
  if (dv.byteLength < 16) throw new RangeError(`EMG packet too short: ${dv.byteLength} bytes`);
  const v = Array.from({ length: 16 }, (_, i) => dv.getInt8(i));
  return [v.slice(0, 8), v.slice(8, 16)];
}

/** Undocumented 'filtered value' packet (EMG mode 1): 8 x uint16 (0..1024-ish) + mask byte. */
export interface FvPacket {
  values: number[];
  mask: number;
}

export function parseFv(data: Bytes): FvPacket {
  const dv = view(data);
  if (dv.byteLength < 16) throw new RangeError(`FV packet too short: ${dv.byteLength} bytes`);
  const values = Array.from({ length: 8 }, (_, i) => dv.getUint16(2 * i, true));
  return { values, mask: dv.byteLength >= 17 ? dv.getInt8(16) : 0 };
}

export interface ClassifierEvent {
  type: number; // ClassifierEventType value, or an unknown byte
  arm: number;
  xDirection: number;
  pose: number;
  syncResult: number;
  warmupState: number;
  warmupResult: number;
  raw: Uint8Array;
}

export const classifierLabel = (ev: { type: number }): string => {
  const n = enumName(ClassifierEventType, ev.type);
  return n ? n.toString().toLowerCase() : `unknown_${ev.type}`;
};

export function makeClassifierEvent(type: number, fields: Partial<ClassifierEvent> = {}): ClassifierEvent {
  return {
    type,
    arm: Arm.UNKNOWN,
    xDirection: XDirection.UNKNOWN,
    pose: Pose.UNKNOWN,
    syncResult: SyncResult.UNKNOWN,
    warmupState: WarmupState.UNKNOWN,
    warmupResult: WarmupResult.UNKNOWN,
    raw: new Uint8Array(0),
    ...fields,
  };
}

/** myohw.h defines 3 bytes; the device sends 6. On ARM_SYNCED byte 3 is the warm-up state
 * (libmyo; zero on firmware that pads), bytes 4-5 a rotation we don't use. */
export function parseClassifier(data: Bytes): ClassifierEvent {
  const raw = bytesOf(data).slice();
  if (raw.length < 1) throw new RangeError("empty classifier event");
  const t = raw[0];
  const b1 = raw.length > 1 ? raw[1] : 0;
  const b2 = raw.length > 2 ? raw[2] : 0;
  switch (t) {
    case ClassifierEventType.ARM_SYNCED:
      return makeClassifierEvent(t, {
        arm: or(Arm, b1, Arm.UNKNOWN),
        xDirection: or(XDirection, b2, XDirection.UNKNOWN),
        warmupState: raw.length > 3 ? or(WarmupState, raw[3], WarmupState.UNKNOWN) : WarmupState.UNKNOWN,
        raw,
      });
    case ClassifierEventType.POSE:
      return makeClassifierEvent(t, { pose: or(Pose, b1 | (b2 << 8), Pose.UNKNOWN), raw });
    case ClassifierEventType.SYNC_FAILED:
      return makeClassifierEvent(t, { syncResult: or(SyncResult, b1, SyncResult.UNKNOWN), raw });
    case ClassifierEventType.WARMUP_COMPLETED:
      return makeClassifierEvent(t, { warmupResult: or(WarmupResult, b1, WarmupResult.UNKNOWN), raw });
    default:
      return makeClassifierEvent(t, { raw });
  }
}

export interface MotionEvent {
  type: number;
  tapDirection: number;
  tapCount: number;
}

export function parseMotion(data: Bytes): MotionEvent {
  const b = bytesOf(data);
  return { type: b[0] ?? 0, tapDirection: b[1] ?? 0, tapCount: b[2] ?? 0 };
}

export interface FirmwareVersion {
  major: number;
  minor: number;
  patch: number;
  hardwareRev: number;
}

export const firmwareShort = (fw: FirmwareVersion) => `${fw.major}.${fw.minor}.${fw.patch}.${fw.hardwareRev}`;
export const firmwareString = (fw: FirmwareVersion) => {
  const hw = enumName(HardwareRev, fw.hardwareRev);
  return `${fw.major}.${fw.minor}.${fw.patch} (${hw ? hw.toString().toLowerCase() : fw.hardwareRev})`;
};

export function parseFirmwareVersion(data: Bytes): FirmwareVersion {
  const dv = view(data);
  if (dv.byteLength < 8) throw new RangeError(`firmware version too short: ${dv.byteLength} bytes`);
  return {
    major: dv.getUint16(0, true),
    minor: dv.getUint16(2, true),
    patch: dv.getUint16(4, true),
    hardwareRev: dv.getUint16(6, true),
  };
}

export interface FirmwareInfo {
  serialBytes: Uint8Array;
  unlockPose: number;
  classifierType: number;
  classifierIndex: number;
  hasCustomClassifier: boolean;
  streamIndicating: boolean;
  sku: number;
}

/** Serial as a MAC-like string. The 6 bytes are stored little-endian, so they are reversed for
 * display (dl-myo convention); MyoDiagnostics showed e.g. d2-b5-d9-be-cc-8f. */
export const serialString = (info: FirmwareInfo) =>
  Array.from(info.serialBytes).reverse().map((b) => b.toString(16).padStart(2, "0")).join("-");

export function parseFirmwareInfo(data: Bytes): FirmwareInfo {
  const dv = view(data);
  if (dv.byteLength < 20) throw new RangeError(`firmware info too short: ${dv.byteLength} bytes`);
  const b = bytesOf(data);
  return {
    serialBytes: b.slice(0, 6),
    unlockPose: dv.getUint16(6, true),
    classifierType: b[8],
    classifierIndex: b[9],
    hasCustomClassifier: b[10] !== 0,
    streamIndicating: b[11] !== 0,
    sku: b[12],
  };
}

export function parseBattery(data: Bytes): number {
  const b = bytesOf(data);
  if (b.length < 1) throw new RangeError("empty battery value");
  return b[0];
}
