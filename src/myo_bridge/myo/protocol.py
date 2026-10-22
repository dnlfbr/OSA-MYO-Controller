"""Myo BLE protocol: UUIDs, enums, command builders and packet parsers.

Pure functions and data types only - no I/O. Everything here was cross-checked
against Thalmic's ``myohw.h`` (Apache-2.0) and the bleak-based implementations
pymyo, FreeMyo.py and dl-myo. See docs/protocol.md for the discrepancies and
how they were resolved.

Byte order: ``myohw.h`` says big-endian, but every working implementation (and
the firmware) uses **little-endian**. All formats here are ``<``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

# --------------------------------------------------------------------------- UUIDs

MYO_BASE_UUID = "d506{:04x}-a904-deb9-4748-2c7f4a124842"
STD_BASE_UUID = "0000{:04x}-0000-1000-8000-00805f9b34fb"


def myo_uuid(short: int) -> str:
    return MYO_BASE_UUID.format(short)


def std_uuid(short: int) -> str:
    return STD_BASE_UUID.format(short)


class UUIDS:
    """128-bit UUID strings (lower-case, as bleak reports them)."""

    CONTROL_SERVICE = myo_uuid(0x0001)
    INFO = myo_uuid(0x0101)  # read: FirmwareInfo (20 bytes)
    FIRMWARE = myo_uuid(0x0201)  # read: FirmwareVersion (8 bytes)
    COMMAND = myo_uuid(0x0401)  # write (with response)

    IMU_SERVICE = myo_uuid(0x0002)
    IMU_DATA = myo_uuid(0x0402)  # notify: 20 bytes
    MOTION_EVENT = myo_uuid(0x0502)  # indicate: 3 bytes

    CLASSIFIER_SERVICE = myo_uuid(0x0003)
    CLASSIFIER_EVENT = myo_uuid(0x0103)  # indicate: 3 (observed 6) bytes

    FV_SERVICE = myo_uuid(0x0004)  # undocumented "filtered value" (EMG mode 1)
    FV_DATA = myo_uuid(0x0104)  # notify: 17 bytes (8 x uint16 + mask)

    EMG_SERVICE = myo_uuid(0x0005)
    EMG0 = myo_uuid(0x0105)  # notify: 16 bytes = 2 samples x 8 int8
    EMG1 = myo_uuid(0x0205)
    EMG2 = myo_uuid(0x0305)
    EMG3 = myo_uuid(0x0405)

    BATTERY_SERVICE = std_uuid(0x180F)
    BATTERY_LEVEL = std_uuid(0x2A19)  # read/notify: 1 byte, percent
    DEVICE_NAME = std_uuid(0x2A00)
    MANUFACTURER = std_uuid(0x2A29)


EMG_UUIDS: tuple[str, str, str, str] = (UUIDS.EMG0, UUIDS.EMG1, UUIDS.EMG2, UUIDS.EMG3)

# --------------------------------------------------------------------------- constants

EMG_CHANNELS = 8
EMG_SAMPLE_RATE_HZ = 200
IMU_SAMPLE_RATE_HZ = 50
FV_SAMPLE_RATE_HZ = 50
FV_FULL_SCALE = 1024.0  # nominal top of the smooth (FV) values; pyomyo plots them on 0..1024

ORIENTATION_SCALE = 16384.0  # int16 -> unit quaternion
ACCELEROMETER_SCALE = 2048.0  # int16 -> g      (range +-16 g)
GYROSCOPE_SCALE = 16.0  # int16 -> deg/s  (range +-2000 deg/s)
EMG_SCALE = 128.0  # int8  -> -1..1

# --------------------------------------------------------------------------- enums


class EmgMode(IntEnum):
    NONE = 0x00
    SMOOTH = 0x01  # undocumented: 50 Hz rectified/filtered uint16 on FV_DATA
    FILTERED = 0x02  # 200 Hz filtered int8 on EMG0..3
    RAW = 0x03  # 200 Hz raw ADC int8 on EMG0..3


class ImuMode(IntEnum):
    NONE = 0x00
    DATA = 0x01  # quaternion + accel + gyro at 50 Hz
    EVENTS = 0x02  # motion events (taps) only
    ALL = 0x03  # data + events
    RAW = 0x04  # raw IMU data (undocumented scaling; treated like DATA)


class ClassifierMode(IntEnum):
    DISABLED = 0x00  # also resets the classifier state
    ENABLED = 0x01


class VibrationType(IntEnum):
    NONE = 0x00
    SHORT = 0x01
    MEDIUM = 0x02
    LONG = 0x03


class SleepMode(IntEnum):
    NORMAL = 0x00  # sleeps after a period of inactivity
    NEVER_SLEEP = 0x01


class UnlockType(IntEnum):
    LOCK = 0x00  # re-lock immediately
    TIMED = 0x01  # unlock, re-lock after timeout
    HOLD = 0x02  # stay unlocked until LOCK


class UserActionType(IntEnum):
    SINGLE = 0x00


class Pose(IntEnum):
    REST = 0x0000
    FIST = 0x0001
    WAVE_IN = 0x0002
    WAVE_OUT = 0x0003
    FINGERS_SPREAD = 0x0004
    DOUBLE_TAP = 0x0005  # called THUMB_TO_PINKY in old pyomyo
    UNKNOWN = 0xFFFF

    @property
    def label(self) -> str:
        return self.name.lower()


class Arm(IntEnum):
    UNKNOWN = 0x00  # pyomyo reports 0 as unknown too
    RIGHT = 0x01
    LEFT = 0x02
    UNKNOWN_FF = 0xFF

    @property
    def label(self) -> str:
        return "right" if self is Arm.RIGHT else "left" if self is Arm.LEFT else "unknown"


class XDirection(IntEnum):
    UNKNOWN = 0x00
    TOWARD_WRIST = 0x01
    TOWARD_ELBOW = 0x02
    UNKNOWN_FF = 0xFF

    @property
    def label(self) -> str:
        if self is XDirection.TOWARD_WRIST:
            return "wrist"
        if self is XDirection.TOWARD_ELBOW:
            return "elbow"
        return "unknown"


class ClassifierEventType(IntEnum):
    ARM_SYNCED = 0x01
    ARM_UNSYNCED = 0x02
    POSE = 0x03
    UNLOCKED = 0x04
    LOCKED = 0x05
    SYNC_FAILED = 0x06
    WARMUP_COMPLETED = 0x07  # seen in the wild (FreeMyo "seen once", MyoDiagnostics feed)


class SyncResult(IntEnum):
    UNKNOWN = 0x00
    FAILED_TOO_HARD = 0x01


class WarmupState(IntEnum):
    """ARM_SYNCED byte 3 (libmyo, firmware 1.5+): poses are less reliable while the band is cold."""
    UNKNOWN = 0x00
    COLD = 0x01
    WARM = 0x02


class WarmupResult(IntEnum):
    """WARMUP_COMPLETED byte 1 (libmyo); expected only after a cold sync."""
    UNKNOWN = 0x00
    SUCCESS = 0x01
    FAILED_TIMEOUT = 0x02


class MotionEventType(IntEnum):
    TAP = 0x00


class ClassifierModelType(IntEnum):
    BUILTIN = 0
    CUSTOM = 1


class SKU(IntEnum):
    UNKNOWN = 0
    BLACK = 1
    WHITE = 2


class HardwareRev(IntEnum):
    UNKNOWN = 0
    REV_C = 1  # Myo Alpha
    REV_D = 2  # Myo (retail)
    REV_S = 3  # seen in dl-myo


def _enum_or(enum_cls, value, default):
    try:
        return enum_cls(value)
    except ValueError:
        return default


# --------------------------------------------------------------------------- commands
# Each command: [command_id, payload_size, payload...]

CMD_SET_MODE = 0x01
CMD_VIBRATE = 0x03
CMD_DEEP_SLEEP = 0x04
CMD_SET_LED = 0x06  # undocumented in myohw.h, present in pyomyo/pymyo/dl-myo
CMD_VIBRATE2 = 0x07
CMD_SET_SLEEP_MODE = 0x09
CMD_UNLOCK = 0x0A
CMD_USER_ACTION = 0x0B

VIBRATE2_STEPS = 6


def cmd_set_mode(emg: EmgMode | int, imu: ImuMode | int, classifier: ClassifierMode | int) -> bytes:
    return struct.pack("<5B", CMD_SET_MODE, 3, int(emg), int(imu), int(classifier))


def cmd_vibrate(kind: VibrationType | int) -> bytes:
    return struct.pack("<3B", CMD_VIBRATE, 1, int(kind))


def cmd_vibrate2(steps: list[tuple[int, int]]) -> bytes:
    """steps: up to 6 x (duration_ms uint16, strength 0..255). Payload is 18 bytes (myohw.h)."""
    if len(steps) > VIBRATE2_STEPS:
        raise ValueError("vibrate2 accepts at most 6 steps")
    padded = list(steps) + [(0, 0)] * (VIBRATE2_STEPS - len(steps))
    flat = [v for step in padded for v in step]
    return struct.pack("<2B" + "HB" * VIBRATE2_STEPS, CMD_VIBRATE2, 18, *flat)


def cmd_set_sleep_mode(mode: SleepMode | int) -> bytes:
    return struct.pack("<3B", CMD_SET_SLEEP_MODE, 1, int(mode))


def cmd_unlock(kind: UnlockType | int) -> bytes:
    return struct.pack("<3B", CMD_UNLOCK, 1, int(kind))


def cmd_user_action(kind: UserActionType | int = UserActionType.SINGLE) -> bytes:
    return struct.pack("<3B", CMD_USER_ACTION, 1, int(kind))


def cmd_deep_sleep() -> bytes:
    """WARNING: the armband only wakes up again when plugged into USB."""
    return struct.pack("<2B", CMD_DEEP_SLEEP, 0)


def cmd_set_led(logo: tuple[int, int, int], bar: tuple[int, int, int]) -> bytes:
    vals = [max(0, min(255, int(v))) for v in (*logo, *bar)]
    return struct.pack("<8B", CMD_SET_LED, 6, *vals)


# --------------------------------------------------------------------------- packets

_IMU_STRUCT = struct.Struct("<10h")
_EMG_STRUCT = struct.Struct("<16b")
_FV_STRUCT = struct.Struct("<8Hb")
_FW_STRUCT = struct.Struct("<4H")
_INFO_STRUCT = struct.Struct("<6sH5B7x")
_MOTION_STRUCT = struct.Struct("<3B")


@dataclass(slots=True, frozen=True)
class ImuPacket:
    """One IMU notification (20 bytes). Raw int16 values, order as in myohw.h: w x y z."""

    quat: tuple[int, int, int, int]  # w, x, y, z
    accel: tuple[int, int, int]
    gyro: tuple[int, int, int]

    @property
    def quat_f(self) -> tuple[float, float, float, float]:
        s = ORIENTATION_SCALE
        return (self.quat[0] / s, self.quat[1] / s, self.quat[2] / s, self.quat[3] / s)

    @property
    def accel_g(self) -> tuple[float, float, float]:
        s = ACCELEROMETER_SCALE
        return (self.accel[0] / s, self.accel[1] / s, self.accel[2] / s)

    @property
    def gyro_dps(self) -> tuple[float, float, float]:
        s = GYROSCOPE_SCALE
        return (self.gyro[0] / s, self.gyro[1] / s, self.gyro[2] / s)


def parse_imu(data: bytes | bytearray | memoryview) -> ImuPacket:
    if len(data) < _IMU_STRUCT.size:
        raise ValueError(f"IMU packet too short: {len(data)} bytes")
    v = _IMU_STRUCT.unpack_from(data)
    return ImuPacket(quat=v[0:4], accel=v[4:7], gyro=v[7:10])


EmgSample = tuple[int, int, int, int, int, int, int, int]


def parse_emg(data: bytes | bytearray | memoryview) -> tuple[EmgSample, EmgSample]:
    """16 bytes -> two consecutive 8-channel samples (int8, -128..127)."""
    if len(data) < _EMG_STRUCT.size:
        raise ValueError(f"EMG packet too short: {len(data)} bytes")
    v = _EMG_STRUCT.unpack_from(data)
    return v[0:8], v[8:16]  # type: ignore[return-value]


@dataclass(slots=True, frozen=True)
class FvPacket:
    """Undocumented 'filtered value' packet (EMG mode 1): 8 x uint16 (0..1024-ish) + mask byte."""

    values: tuple[int, ...]
    mask: int


def parse_fv(data: bytes | bytearray | memoryview) -> FvPacket:
    if len(data) < 16:
        raise ValueError(f"FV packet too short: {len(data)} bytes")
    if len(data) >= _FV_STRUCT.size:
        v = _FV_STRUCT.unpack_from(data)
        return FvPacket(values=v[0:8], mask=v[8])
    v = struct.unpack_from("<8H", data)
    return FvPacket(values=v, mask=0)


@dataclass(slots=True, frozen=True)
class ClassifierEvent:
    type: ClassifierEventType | int
    arm: Arm = Arm.UNKNOWN
    x_direction: XDirection = XDirection.UNKNOWN
    pose: Pose = Pose.UNKNOWN
    sync_result: SyncResult = SyncResult.UNKNOWN
    warmup_state: WarmupState = WarmupState.UNKNOWN
    warmup_result: WarmupResult = WarmupResult.UNKNOWN
    raw: bytes = b""

    @property
    def label(self) -> str:
        t = self.type
        return t.name.lower() if isinstance(t, ClassifierEventType) else f"unknown_{int(t)}"


def parse_classifier(data: bytes | bytearray | memoryview) -> ClassifierEvent:
    """myohw.h defines 3 bytes; the device sends 6. On ARM_SYNCED byte 3 is the warm-up state
    (libmyo; zero on firmware that pads), bytes 4-5 a rotation we don't use."""
    raw = bytes(data)
    if len(raw) < 1:
        raise ValueError("empty classifier event")
    t = _enum_or(ClassifierEventType, raw[0], raw[0])
    b1 = raw[1] if len(raw) > 1 else 0
    b2 = raw[2] if len(raw) > 2 else 0
    if t is ClassifierEventType.ARM_SYNCED:
        return ClassifierEvent(
            t,
            arm=_enum_or(Arm, b1, Arm.UNKNOWN),
            x_direction=_enum_or(XDirection, b2, XDirection.UNKNOWN),
            warmup_state=_enum_or(WarmupState, raw[3], WarmupState.UNKNOWN) if len(raw) > 3
            else WarmupState.UNKNOWN,
            raw=raw,
        )
    if t is ClassifierEventType.POSE:
        pose_val = b1 | (b2 << 8)
        return ClassifierEvent(t, pose=_enum_or(Pose, pose_val, Pose.UNKNOWN), raw=raw)
    if t is ClassifierEventType.SYNC_FAILED:
        return ClassifierEvent(t, sync_result=_enum_or(SyncResult, b1, SyncResult.UNKNOWN), raw=raw)
    if t is ClassifierEventType.WARMUP_COMPLETED:
        return ClassifierEvent(t, warmup_result=_enum_or(WarmupResult, b1, WarmupResult.UNKNOWN), raw=raw)
    return ClassifierEvent(t, raw=raw)


@dataclass(slots=True, frozen=True)
class MotionEvent:
    type: MotionEventType | int
    tap_direction: int
    tap_count: int


def parse_motion(data: bytes | bytearray | memoryview) -> MotionEvent:
    raw = bytes(data)
    if len(raw) < 3:
        raw = raw + b"\x00" * (3 - len(raw))
    t, d, c = _MOTION_STRUCT.unpack_from(raw)
    return MotionEvent(_enum_or(MotionEventType, t, t), d, c)


@dataclass(slots=True, frozen=True)
class FirmwareVersion:
    major: int
    minor: int
    patch: int
    hardware_rev: HardwareRev | int

    def __str__(self) -> str:
        hw = self.hardware_rev
        hw_s = hw.name.lower() if isinstance(hw, HardwareRev) else str(hw)
        return f"{self.major}.{self.minor}.{self.patch} ({hw_s})"

    @property
    def short(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}.{int(self.hardware_rev)}"


def parse_firmware_version(data: bytes | bytearray | memoryview) -> FirmwareVersion:
    if len(data) < _FW_STRUCT.size:
        raise ValueError(f"firmware version too short: {len(data)} bytes")
    major, minor, patch, hw = _FW_STRUCT.unpack_from(data)
    return FirmwareVersion(major, minor, patch, _enum_or(HardwareRev, hw, hw))


@dataclass(slots=True, frozen=True)
class FirmwareInfo:
    serial_bytes: bytes
    unlock_pose: Pose | int
    classifier_type: ClassifierModelType | int
    classifier_index: int
    has_custom_classifier: bool
    stream_indicating: bool
    sku: SKU | int

    @property
    def serial(self) -> str:
        """Serial as a MAC-like string. The 6 bytes are stored little-endian, so they are
        reversed for display (dl-myo convention); MyoDiagnostics showed e.g. d2-b5-d9-be-cc-8f."""
        return "-".join(f"{b:02x}" for b in reversed(self.serial_bytes))


def parse_firmware_info(data: bytes | bytearray | memoryview) -> FirmwareInfo:
    if len(data) < _INFO_STRUCT.size:
        raise ValueError(f"firmware info too short: {len(data)} bytes")
    serial, pose, ctype, cidx, hcc, si, sku = _INFO_STRUCT.unpack_from(data)
    return FirmwareInfo(
        serial_bytes=bytes(serial),
        unlock_pose=_enum_or(Pose, pose, pose),
        classifier_type=_enum_or(ClassifierModelType, ctype, ctype),
        classifier_index=cidx,
        has_custom_classifier=bool(hcc),
        stream_indicating=bool(si),
        sku=_enum_or(SKU, sku, sku),
    )


def parse_battery(data: bytes | bytearray | memoryview) -> int:
    if len(data) < 1:
        raise ValueError("empty battery value")
    return int(data[0])
