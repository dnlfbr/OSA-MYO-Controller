"""Mock Myo: a Transport that behaves like an armband and emits synthetic data.

Timing and packet layout mirror the real device: IMU at 50 Hz (20 bytes), EMG as
16-byte notifications (2 samples) at 100 notifications/s round-robin over the four EMG
characteristics, classifier events as 6-byte indications, battery as 1 byte. Commands
written to the COMMAND characteristic are honoured (modes, vibrate, sleep, lock).
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import re
import struct
import time

from myo_bridge.myo import protocol as P
from myo_bridge.transport.base import (
    DisconnectCallback,
    NotifyCallback,
    Scanner,
    ScanResult,
    Transport,
    TransportError,
)

log = logging.getLogger(__name__)

MOCK_ADDRESSES = ["MOCK-0001", "MOCK-0002", "MOCK-0003"]


class MockScanner(Scanner):
    backend_name = "mock"

    def __init__(self, count: int = 2) -> None:
        self.count = count

    async def scan(self, timeout: float = 5.0, myo_only: bool = True) -> list[ScanResult]:
        await asyncio.sleep(min(timeout, 0.2))
        return [ScanResult(address=MOCK_ADDRESSES[i], name=f"Mock Myo {i + 1}",
                           rssi=-50 - 8 * i, is_myo=True) for i in range(self.count)]

    async def find(self, selector: str | None, timeout: float = 10.0) -> ScanResult | None:
        results = await self.scan(0.1)
        if not selector:
            return results[0]
        sel = selector.lower()
        for r in results:
            if r.address.lower() == sel or (r.name or "").lower() == sel:
                return r
        return None


class MockTransport(Transport):
    """Synthetic armband. ``seed`` makes the data stream reproducible."""

    backend_name = "mock"

    def __init__(self, seed: int | None = None, pose_period_s: float = 4.0,
                 drop_every: int = 0, disconnect_after_s: float = 0.0) -> None:
        self._rng = random.Random(seed)
        self._connected = False
        self._address = ""
        self._subs: dict[str, NotifyCallback] = {}
        self._on_disconnect: DisconnectCallback | None = None
        self._task: asyncio.Task | None = None
        self.pose_period_s = pose_period_s
        self.drop_every = drop_every  # drop every Nth EMG notification (0 = none)
        self.disconnect_after_s = disconnect_after_s  # simulate a link loss once
        self._disconnect_done = False

        # armband state
        self.emg_mode = P.EmgMode.NONE
        self.imu_mode = P.ImuMode.NONE
        self.classifier_mode = P.ClassifierMode.DISABLED
        self.sleep_mode = P.SleepMode.NORMAL
        self.locked = True
        self.battery = 87
        self.vibrations: list[int] = []
        self.commands: list[bytes] = []
        self.name = "Mock Myo"
        self.serial = bytes([0x8F, 0xCC, 0xBE, 0xD9, 0xB5, 0xD2])
        self.firmware = (1, 5, 1970, 2)
        self.rssi = -55
        self.yaw_rate_dps = 20.0

    # ------------------------------------------------------------------ Transport API
    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def address(self) -> str:
        return self._address

    async def connect(self, address: str, on_disconnect: DisconnectCallback | None = None,
                      timeout: float = 20.0) -> None:
        await asyncio.sleep(0.05)
        m = re.search(r"(\d+)$", address)
        if m:  # MOCK-0002 -> displayed serial d2-b5-d9-be-cc-02 so slots can be told apart by serial
            self.serial = bytes([int(m.group(1)) & 0xFF, 0xCC, 0xBE, 0xD9, 0xB5, 0xD2])
        if address.lower().startswith("fail"):
            raise TransportError("mock: connection refused")
        self._address = address
        self._on_disconnect = on_disconnect
        self._connected = True
        self._task = asyncio.create_task(self._stream(), name=f"mock-{address}")

    async def disconnect(self) -> None:
        self._connected = False
        if self._task:
            self._task.cancel()
            self._task = None
        self._subs.clear()

    def simulate_link_loss(self) -> None:
        """Drop the link as if the armband went out of range."""
        self._connected = False
        if self._task:
            self._task.cancel()
            self._task = None
        self._subs.clear()
        if self._on_disconnect:
            self._on_disconnect()

    def _require(self) -> None:
        if not self._connected:
            raise TransportError("mock: not connected")

    async def read(self, uuid: str) -> bytes:
        self._require()
        await asyncio.sleep(0.005)
        if uuid == P.UUIDS.FIRMWARE:
            return struct.pack("<4H", *self.firmware)
        if uuid == P.UUIDS.INFO:
            return struct.pack("<6sH5B7x", self.serial, 5, 0, 0, 0, 0, 1)
        if uuid == P.UUIDS.BATTERY_LEVEL:
            return bytes([self.battery])
        if uuid == P.UUIDS.DEVICE_NAME:
            return self.name.encode()
        if uuid == P.UUIDS.MANUFACTURER:
            return b"Thalmic Labs"
        raise TransportError(f"mock: unknown characteristic {uuid}")

    async def write(self, uuid: str, data: bytes, response: bool = True) -> None:
        self._require()
        if uuid != P.UUIDS.COMMAND:
            raise TransportError(f"mock: characteristic {uuid} is not writable")
        await asyncio.sleep(0.003)
        self.commands.append(bytes(data))
        cmd = data[0]
        if cmd == P.CMD_SET_MODE:
            self.emg_mode = P.EmgMode(data[2])
            self.imu_mode = P.ImuMode(data[3])
            self.classifier_mode = P.ClassifierMode(data[4])
            if self.classifier_mode is P.ClassifierMode.ENABLED:
                self._schedule_sync()
        elif cmd == P.CMD_VIBRATE:
            self.vibrations.append(data[2])
        elif cmd == P.CMD_SET_SLEEP_MODE:
            self.sleep_mode = P.SleepMode(data[2])
        elif cmd == P.CMD_UNLOCK:
            kind = P.UnlockType(data[2])
            self.locked = kind is P.UnlockType.LOCK
            self._emit_classifier(P.ClassifierEventType.LOCKED if self.locked
                                  else P.ClassifierEventType.UNLOCKED)
        elif cmd == P.CMD_DEEP_SLEEP:
            self.simulate_link_loss()

    async def subscribe(self, uuid: str, callback: NotifyCallback) -> None:
        self._require()
        self._subs[uuid] = callback

    async def unsubscribe(self, uuid: str) -> None:
        self._subs.pop(uuid, None)

    async def get_rssi(self) -> int | None:
        return self.rssi + self._rng.randint(-3, 3) if self._connected else None

    async def get_name(self) -> str | None:
        return self.name

    # ------------------------------------------------------------------ synthetic data
    def _notify(self, uuid: str, data: bytes) -> None:
        cb = self._subs.get(uuid)
        if cb:
            cb(data)

    def _emit_classifier(self, t: P.ClassifierEventType, b1: int = 0, b2: int = 0, b3: int = 0) -> None:
        self._notify(P.UUIDS.CLASSIFIER_EVENT, bytes([int(t), b1, b2, b3, 0, 0]))

    def _schedule_sync(self) -> None:
        async def _sync():
            await asyncio.sleep(0.8)
            if self._connected and self.classifier_mode is P.ClassifierMode.ENABLED:
                self._emit_classifier(P.ClassifierEventType.ARM_SYNCED, int(P.Arm.RIGHT),
                                      int(P.XDirection.TOWARD_WRIST), int(P.WarmupState.COLD))
                self._emit_classifier(P.ClassifierEventType.WARMUP_COMPLETED, int(P.WarmupResult.SUCCESS))
                self.locked = False
                self._emit_classifier(P.ClassifierEventType.UNLOCKED)
        asyncio.create_task(_sync())

    async def _stream(self) -> None:
        rng = self._rng
        t0 = time.monotonic()
        imu_period = 1.0 / P.IMU_SAMPLE_RATE_HZ
        emg_period = 2.0 / P.EMG_SAMPLE_RATE_HZ  # one notification = 2 samples
        next_imu = next_emg = t0
        next_pose = t0 + self.pose_period_s
        next_batt = t0 + 20.0
        next_tap = t0 + rng.uniform(3.0, 6.0)
        spike: tuple[float, float, float] | None = None  # knock added to the next IMU sample
        fv_env = [0.0] * 8  # smooth EMG envelope
        emg_char = 0
        emg_n = 0
        pose = P.Pose.REST
        poses = [P.Pose.FIST, P.Pose.WAVE_IN, P.Pose.WAVE_OUT, P.Pose.FINGERS_SPREAD,
                 P.Pose.DOUBLE_TAP, P.Pose.REST, P.Pose.REST]
        # per-pose channel gains (which pods "light up")
        gains = {
            P.Pose.REST: [0.06] * 8,
            P.Pose.FIST: [0.6, 0.7, 0.5, 0.4, 0.5, 0.7, 0.6, 0.5],
            P.Pose.WAVE_IN: [0.1, 0.1, 0.5, 0.8, 0.6, 0.1, 0.1, 0.1],
            P.Pose.WAVE_OUT: [0.6, 0.8, 0.2, 0.1, 0.1, 0.1, 0.5, 0.7],
            P.Pose.FINGERS_SPREAD: [0.4, 0.3, 0.4, 0.3, 0.4, 0.3, 0.4, 0.3],
            P.Pose.DOUBLE_TAP: [0.2, 0.2, 0.3, 0.3, 0.3, 0.3, 0.2, 0.2],
        }
        try:
            while True:
                now = time.monotonic()
                t = now - t0
                if self.disconnect_after_s and not self._disconnect_done and t > self.disconnect_after_s:
                    self._disconnect_done = True
                    self.simulate_link_loss()
                    return
                if now >= next_imu:
                    next_imu += imu_period
                    if self.imu_mode in (P.ImuMode.DATA, P.ImuMode.ALL, P.ImuMode.RAW):
                        yaw = math.radians(self.yaw_rate_dps * t) % (2 * math.pi)
                        pitch = 0.3 * math.sin(0.5 * t)
                        roll = 0.2 * math.sin(0.33 * t)
                        q = _euler_to_quat(roll, pitch, yaw)
                        gx, gy, gz = (roll - 0.2 * math.sin(0.33 * (t - 0.02))) / 0.02, \
                            (pitch - 0.3 * math.sin(0.5 * (t - 0.02))) / 0.02, \
                            math.radians(self.yaw_rate_dps)
                        # gravity in sensor frame (approx) + noise
                        acc = (-math.sin(pitch), math.sin(roll) * math.cos(pitch),
                               math.cos(roll) * math.cos(pitch))
                        if spike is not None:
                            acc, spike = tuple(a + s for a, s in zip(acc, spike)), None
                        raw = [int(max(-32768, min(32767, v * P.ORIENTATION_SCALE))) for v in q]
                        raw += [int(max(-32768, min(32767, (a + rng.gauss(0, 0.01)) * P.ACCELEROMETER_SCALE)))
                                for a in acc]
                        raw += [int(max(-32768, min(32767, math.degrees(g) * P.GYROSCOPE_SCALE)))
                                for g in (gx, gy, gz)]
                        self._notify(P.UUIDS.IMU_DATA, struct.pack("<10h", *raw))
                if now >= next_emg:
                    next_emg += emg_period
                    emg_n += 1
                    if self.emg_mode in (P.EmgMode.FILTERED, P.EmgMode.RAW):
                        g = gains.get(pose, gains[P.Pose.REST])
                        vals = []
                        for _s in range(2):
                            for ch in range(8):
                                v = rng.gauss(0, 1) * g[ch] * 100 * (1 + 0.3 * math.sin(2 * math.pi * 1.5 * t))
                                vals.append(int(max(-128, min(127, v))))
                        if not (self.drop_every and emg_n % self.drop_every == 0):
                            self._notify(P.EMG_UUIDS[emg_char], struct.pack("<16b", *vals))
                        emg_char = (emg_char + 1) & 3
                    elif self.emg_mode is P.EmgMode.SMOOTH and emg_n % 2 == 0:  # 50 Hz envelope
                        g = gains.get(pose, gains[P.Pose.REST])
                        for ch in range(8):
                            fv_env[ch] += 0.25 * (abs(rng.gauss(0, 1)) * g[ch] * 900 - fv_env[ch])
                        vals = [int(min(65535, v)) for v in fv_env]
                        self._notify(P.UUIDS.FV_DATA, struct.pack("<8Hb", *vals, 0))
                if now >= next_pose:
                    next_pose = now + self.pose_period_s * rng.uniform(0.6, 1.4)
                    if self.classifier_mode is P.ClassifierMode.ENABLED:
                        pose = rng.choice(poses)
                        self._emit_classifier(P.ClassifierEventType.POSE, int(pose) & 0xFF, int(pose) >> 8)
                if now >= next_tap:  # a knock on the band, of random strength
                    next_tap = now + rng.uniform(3.0, 8.0)
                    if self.imu_mode in (P.ImuMode.EVENTS, P.ImuMode.ALL):
                        strength = rng.uniform(0.1, 2.0)
                        d = [rng.gauss(0, 1) for _ in range(3)]
                        n = math.sqrt(sum(x * x for x in d)) or 1.0
                        spike = tuple(strength * x / n for x in d)
                        self._notify(P.UUIDS.MOTION_EVENT,
                                     bytes([int(P.MotionEventType.TAP), rng.randint(0, 5), rng.choice((1, 1, 2))]))
                if now >= next_batt:
                    next_batt = now + 20.0
                    self.battery = max(1, self.battery - 1)
                    self._notify(P.UUIDS.BATTERY_LEVEL, bytes([self.battery]))
                await asyncio.sleep(max(0.0, min(next_imu, next_emg) - time.monotonic()))
        except asyncio.CancelledError:
            pass


def _euler_to_quat(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return (
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    )
