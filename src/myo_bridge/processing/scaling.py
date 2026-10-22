"""Unit conversions for every OSC stream. Documented in README "Scaling".

Raw units as the device sends them -> physical units:
  quaternion : int16 / 16384            -> unit quaternion
  accel      : int16 / 2048             -> g        (range +-16 g)
  gyro       : int16 / 16               -> deg/s    (range +-2000 deg/s)
  emg        : int8                     -> raw -128..127 ; norm = raw / 128 -> -1..1
"""

from __future__ import annotations

from myo_bridge.myo import protocol as P

EMG_NORM = 1.0 / P.EMG_SCALE


def emg_norm(sample) -> tuple[float, ...]:
    return tuple(v * EMG_NORM for v in sample)


def clamp_unit(v: float) -> float:
    return -1.0 if v < -1.0 else 1.0 if v > 1.0 else v


def vec_norm(v, full_scale: float) -> tuple[float, float, float]:
    """Scale a 3-vector so that +-full_scale maps to +-1 (clamped)."""
    return (clamp_unit(v[0] / full_scale), clamp_unit(v[1] / full_scale), clamp_unit(v[2] / full_scale))
