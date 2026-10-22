"""OSC output: builds datagrams with python-osc and sends them on a UDP socket.

Design points for the EMG hot path: one pre-bound socket, builders reused per call,
EMG samples are accumulated into a bundle of ``emg_bundle_samples`` samples and flushed
in one datagram; IMU-derived streams pass through a per-stream rate limiter.
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Iterable

from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_bundle_builder import IMMEDIATELY, OscBundleBuilder
from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

from myo_bridge.osc.namespace import Namespace

log = logging.getLogger(__name__)

_T_INT = OscMessageBuilder.ARG_TYPE_INT
_T_FLOAT = OscMessageBuilder.ARG_TYPE_FLOAT
_T_STR = OscMessageBuilder.ARG_TYPE_STRING


def _msg(address: str, args: Iterable, typ: str | None) -> OscMessage:
    b = OscMessageBuilder(address)
    if typ is None:
        for a in args:
            b.add_arg(a)
    else:
        for a in args:
            b.add_arg(a, typ)
    return b.build()


class RateLimiter:
    """Phase-locked rate limiter: a packet that arrives slightly early (jitter) is still
    accepted, so a 50 Hz input through a 50 Hz limit passes every packet instead of every
    other one. 0 Hz = unlimited."""

    __slots__ = ("min_dt", "_next")

    def __init__(self, hz: float) -> None:
        self._next = 0.0
        self.set_rate(hz)

    def set_rate(self, hz: float) -> None:
        self.min_dt = 1.0 / hz if hz and hz > 0 else 0.0

    def allow(self, now: float) -> bool:
        dt = self.min_dt
        if dt == 0.0:
            return True
        if now >= self._next - 0.25 * dt:
            self._next = max(self._next, now) + dt
            return True
        return False


class OscSender:
    def __init__(self, host: str = "127.0.0.1", port: int = 7400, namespace: Namespace | None = None,
                 streams: dict[str, bool] | None = None, emg_bundle_samples: int = 4,
                 imu_rate_hz: float = 50.0, rms_rate_hz: float = 50.0, enabled: bool = True) -> None:
        self.namespace = namespace or Namespace()
        self.streams: dict[str, bool] = dict(streams or {})
        self.enabled = enabled
        self.emg_bundle_samples = max(1, int(emg_bundle_samples))
        # one limiter per device id: two bands at 50 Hz must not share a 50 Hz budget
        self.imu_rate_hz = imu_rate_hz
        self.rms_rate_hz = rms_rate_hz
        self._imu_limits: dict[int, RateLimiter] = {}
        self._rms_limits: dict[int, RateLimiter] = {}
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        self._target = (host, port)
        self._emg_pending: dict[int, OscBundleBuilder] = {}
        self._emg_pending_n: dict[int, int] = {}
        self.sent_messages = 0
        self.sent_datagrams = 0
        self.send_errors = 0
        self._addr_cache: dict[tuple[str, int], str] = {}
        self._axis_cache: dict[tuple[str, int], tuple[str, ...]] = {}

    # ---------------------------------------------------------------- config
    @property
    def target(self) -> tuple[str, int]:
        return self._target

    def set_target(self, host: str, port: int) -> None:
        self._target = (host, int(port))

    def set_rates(self, imu_rate_hz: float, rms_rate_hz: float) -> None:
        self.imu_rate_hz, self.rms_rate_hz = imu_rate_hz, rms_rate_hz
        for lim in self._imu_limits.values():
            lim.set_rate(imu_rate_hz)
        for lim in self._rms_limits.values():
            lim.set_rate(rms_rate_hz)

    def _imu_limit(self, device_id: int) -> RateLimiter:
        lim = self._imu_limits.get(device_id)
        if lim is None:
            lim = self._imu_limits[device_id] = RateLimiter(self.imu_rate_hz)
        return lim

    def _rms_limit(self, device_id: int) -> RateLimiter:
        lim = self._rms_limits.get(device_id)
        if lim is None:
            lim = self._rms_limits[device_id] = RateLimiter(self.rms_rate_hz)
        return lim

    def set_namespace(self, namespace: Namespace) -> None:
        self.namespace = namespace
        self._addr_cache.clear()
        self._axis_cache.clear()
        self._emg_pending.clear()
        self._emg_pending_n.clear()

    def set_stream(self, stream: str, on: bool) -> None:
        self.streams[stream] = on

    def wants(self, stream: str) -> bool:
        return self.enabled and self.streams.get(stream, False) and self.namespace.has(stream)

    def _addr(self, stream: str, did: int) -> str:
        key = (stream, did)
        a = self._addr_cache.get(key)
        if a is None:
            a = self._addr_cache[key] = self.namespace.address(stream, did)
        return a

    def _axes(self, stream: str, did: int) -> tuple[str, ...]:
        key = (stream, did)
        a = self._axis_cache.get(key)
        if a is None:
            a = self._axis_cache[key] = self.namespace.axis_addresses(stream, did)
        return a

    # ---------------------------------------------------------------- low level
    def _send_dgram(self, dgram: bytes) -> None:
        try:
            self._sock.sendto(dgram, self._target)
            self.sent_datagrams += 1
        except (BlockingIOError, InterruptedError):
            self.send_errors += 1
        except OSError as e:
            self.send_errors += 1
            if self.send_errors % 100 == 1:
                log.warning("OSC send failed (%s) to %s", e, self._target)

    def send(self, address: str, args: Iterable = (), typ: str | None = None) -> None:
        m = _msg(address, args, typ)
        self.sent_messages += 1
        self._send_dgram(m.dgram)

    def send_bundle(self, messages: list[OscMessage]) -> None:
        b = OscBundleBuilder(IMMEDIATELY)
        for m in messages:
            b.add_content(m)
        self.sent_messages += len(messages)
        self._send_dgram(b.build().dgram)

    def _vector(self, stream: str, did: int, values: Iterable, typ: str) -> list[OscMessage]:
        """Messages for a vector stream according to the namespace mode."""
        if self.namespace.mode == "axis":
            return [_msg(a, (v,), typ) for a, v in zip(self._axes(stream, did), values)]
        return [_msg(self._addr(stream, did), values, typ)]

    # ---------------------------------------------------------------- EMG (bundled)
    def emg(self, did: int, raw: tuple, norm: tuple, t_notified: float = 0.0) -> bool:
        """Queue one EMG sample; flush when the bundle is full. Returns True on flush."""
        msgs: list[OscMessage] = []
        if self.wants("emg_raw"):
            msgs += self._vector("emg_raw", did, raw, _T_INT)
        if self.wants("emg_norm"):
            msgs += self._vector("emg_norm", did, norm, _T_FLOAT)
        if not msgs:
            return False
        if self.emg_bundle_samples == 1:
            if len(msgs) == 1:
                self.sent_messages += 1
                self._send_dgram(msgs[0].dgram)
            else:
                self.send_bundle(msgs)
            return True
        b = self._emg_pending.get(did)
        if b is None:
            b = self._emg_pending[did] = OscBundleBuilder(IMMEDIATELY)
            self._emg_pending_n[did] = 0
        for m in msgs:
            b.add_content(m)
        self.sent_messages += len(msgs)
        n = self._emg_pending_n[did] + 1
        if n >= self.emg_bundle_samples:
            self._send_dgram(b.build().dgram)
            del self._emg_pending[did]
            self._emg_pending_n[did] = 0
            return True
        self._emg_pending_n[did] = n
        return False

    def flush_emg(self, did: int | None = None) -> None:
        ids = [did] if did is not None else list(self._emg_pending)
        for i in ids:
            b = self._emg_pending.pop(i, None)
            if b is not None and self._emg_pending_n.get(i, 0):
                self._send_dgram(b.build().dgram)
            self._emg_pending_n[i] = 0

    def emg_rms(self, did: int, rms: tuple, mav: float, now: float) -> None:
        if not (self.wants("emg_rms") or self.wants("emg_mav")):
            return
        if not self._rms_limit(did).allow(now):
            return
        msgs: list[OscMessage] = []
        if self.wants("emg_rms"):
            msgs += self._vector("emg_rms", did, rms, _T_FLOAT)
        if self.wants("emg_mav"):
            msgs.append(_msg(self._addr("emg_mav", did), (mav,), _T_FLOAT))
        self._emit(msgs)

    def fv(self, did: int, values: tuple) -> None:
        if self.wants("fv"):
            self._emit(self._vector("fv", did, values, _T_INT))

    # ---------------------------------------------------------------- IMU (rate limited)
    def imu(self, did: int, quat, quat_raw, euler, euler_deg, euler_norm, accel, gyro, now: float) -> None:
        if not self._imu_limit(did).allow(now):
            return
        msgs: list[OscMessage] = []
        if self.wants("quat"):
            msgs += self._vector("quat", did, quat, _T_FLOAT)
        if self.wants("quat_raw"):
            msgs += self._vector("quat_raw", did, quat_raw, _T_FLOAT)
        if self.wants("euler"):
            msgs += self._vector("euler", did, euler, _T_FLOAT)
        if self.wants("euler_deg"):
            msgs += self._vector("euler_deg", did, euler_deg, _T_FLOAT)
        if self.wants("euler_norm"):
            msgs += self._vector("euler_norm", did, euler_norm, _T_FLOAT)
        if self.wants("accel"):
            msgs += self._vector("accel", did, accel, _T_FLOAT)
        if self.wants("gyro"):
            msgs += self._vector("gyro", did, gyro, _T_FLOAT)
        self._emit(msgs)

    def _emit(self, msgs: list[OscMessage]) -> None:
        if not msgs:
            return
        if len(msgs) == 1:
            self.sent_messages += 1
            self._send_dgram(msgs[0].dgram)
        else:
            self.send_bundle(msgs)

    # ---------------------------------------------------------------- events
    def pose(self, did: int, pose_label: str, pose_id: int) -> None:
        if self.namespace.is_myomapper:
            if self.wants("pose"):
                self.send(self._addr("pose", did), (pose_id, pose_label))
            return
        if self.wants("pose"):
            self.send(self._addr("pose", did), (pose_label,), _T_STR)
            self.send(self._addr("pose_id", did), (pose_id,), _T_INT)

    def string(self, stream: str, did: int, value: str) -> None:
        if self.wants(stream):
            self.send(self._addr(stream, did), (value,), _T_STR)

    def integer(self, stream: str, did: int, value: int) -> None:
        if self.wants(stream):
            self.send(self._addr(stream, did), (int(value),), _T_INT)

    def tap(self, did: int, direction: int, count: int) -> None:
        if self.wants("tap"):
            self.send(self._addr("tap", did), (direction, count), _T_INT)

    def close(self) -> None:
        self.flush_emg()
        try:
            self._sock.close()
        except OSError:
            pass
