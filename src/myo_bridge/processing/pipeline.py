"""Per-device processing state: scaling, orientation reference, envelope, latest values.

One instance per MyoDevice; fed by the device events on the asyncio thread, read by the
OSC sender (same thread) and by the GUI (snapshots are tuples, so reads are atomic enough).
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field

from myo_bridge.myo import protocol as P
from myo_bridge.processing import quaternion as Q
from myo_bridge.processing.envelope import RmsEnvelope
from myo_bridge.processing.scaling import emg_norm


@dataclass
class ImuFrame:
    t: float
    quat_raw: Q.Quat  # scaled, un-referenced
    quat: Q.Quat  # with zero reference applied
    euler: Q.Euler  # radians, from quat
    accel: tuple[float, float, float]  # g
    gyro: tuple[float, float, float]  # deg/s


def fv_activity(values) -> tuple[float, ...]:
    """Smooth EMG (mode 1, uint16) -> 0..1 per pod, like the RMS bars of the other modes."""
    return tuple(min(1.0, v / P.FV_FULL_SCALE) for v in values)


@dataclass
class TapFilter:
    """Software gate for the band's tap events. The firmware's tap detector can't be tuned, so a
    tap is kept only if its strength (see ``DeviceProcessor.tap_strength``) reaches
    ``threshold_g`` and ``cooldown_ms`` has passed since the last kept tap. 0 = off."""

    threshold_g: float = 0.0
    cooldown_ms: float = 0.0
    _last_t: float = field(default=-1e9, repr=False)

    def decide(self, t: float, strength_g: float | None) -> tuple[bool, str]:
        """(keep, reason if dropped). Without IMU data the strength is unknown: the tap is kept."""
        if self.cooldown_ms > 0 and (t - self._last_t) * 1000.0 < self.cooldown_ms:
            return False, f"within {self.cooldown_ms:.0f} ms of the last tap"
        if self.threshold_g > 0 and strength_g is not None and strength_g < self.threshold_g:
            return False, f"weaker than {self.threshold_g:.2f} g"
        self._last_t = t
        return True, ""


@dataclass
class ProcessingParams:
    rms_window_ms: float = 50.0
    zero_mode: str = "yaw"
    tap_threshold_g: float = 0.0
    tap_cooldown_ms: float = 0.0


@dataclass
class DeviceProcessor:
    params: ProcessingParams = field(default_factory=ProcessingParams)

    def __post_init__(self) -> None:
        self.reference = Q.OrientationReference(self.params.zero_mode)
        self.rms = RmsEnvelope(P.EMG_CHANNELS, self._rms_samples())
        self.last_imu: ImuFrame | None = None
        self.last_emg_raw: P.EmgSample | None = None
        self.last_emg_norm: tuple[float, ...] | None = None
        self.last_emg_t: float = 0.0
        self.accel_jolt: deque[tuple[float, float]] = deque(maxlen=100)  # (t, g), 2 s at 50 Hz
        self.taps = TapFilter(self.params.tap_threshold_g, self.params.tap_cooldown_ms)
        self.emg_latency_ms: float = 0.0  # time from notification to OSC send, EMA
        self._lat_alpha = 0.05

    def _rms_samples(self) -> int:
        return max(1, int(round(self.params.rms_window_ms * P.EMG_SAMPLE_RATE_HZ / 1000.0)))

    def set_rms_window_ms(self, ms: float) -> None:
        self.params.rms_window_ms = ms
        self.rms.set_window(self._rms_samples())

    # ---- EMG
    def push_emg(self, sample: P.EmgSample, t: float) -> tuple[float, ...]:
        norm = emg_norm(sample)
        self.rms.push(norm)
        self.last_emg_raw = sample
        self.last_emg_norm = norm
        self.last_emg_t = t
        return norm

    def note_emg_sent(self, t_notified: float) -> None:
        lat = (time.monotonic() - t_notified) * 1000.0
        self.emg_latency_ms += self._lat_alpha * (lat - self.emg_latency_ms)

    # ---- IMU
    def push_imu(self, pkt: P.ImuPacket, t: float) -> ImuFrame:
        q_raw = Q.normalize(pkt.quat_f)
        q = self.reference.apply(q_raw)
        frame = ImuFrame(t=t, quat_raw=q_raw, quat=q, euler=Q.to_euler(q),
                         accel=pkt.accel_g, gyro=pkt.gyro_dps)
        prev = self.last_imu
        self.last_imu = frame
        if prev is not None and t - prev.t < 0.1:  # sample-to-sample change, gaps skipped
            self.accel_jolt.append((t, math.dist(frame.accel, prev.accel)))
        return frame

    def tap_strength(self, t0: float, t1: float) -> float | None:
        """Strength of a knock between t0 and t1: the largest sample-to-sample change of the
        acceleration vector (g), from the 50 Hz IMU stream. Gravity and slow arm movement barely
        change it, a knock on the band does. None when no IMU samples arrived in that time."""
        vals = [j for t, j in self.accel_jolt if t0 <= t <= t1]
        return max(vals) if vals else None

    def imu_live(self, now: float, within_s: float = 0.25) -> bool:
        return self.last_imu is not None and now - self.last_imu.t <= within_s

    def set_tap_filter(self, threshold_g: float, cooldown_ms: float) -> None:
        self.params.tap_threshold_g = self.taps.threshold_g = threshold_g
        self.params.tap_cooldown_ms = self.taps.cooldown_ms = cooldown_ms

    def zero(self) -> Q.Quat | None:
        """Use the latest orientation as the new reference. Returns the stored reference."""
        if self.last_imu is None:
            return None
        self.reference.set_zero(self.last_imu.quat_raw)
        return self.reference.reference

    def clear_zero(self) -> None:
        self.reference.clear()
