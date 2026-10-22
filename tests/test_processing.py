import math
import struct

import pytest

from myo_bridge.myo import protocol as P
from myo_bridge.processing.envelope import RmsEnvelope
from myo_bridge.processing.pipeline import DeviceProcessor, ProcessingParams, TapFilter, fv_activity
from myo_bridge.processing.scaling import emg_norm, vec_norm


def test_emg_norm_range():
    assert emg_norm((-128, 0, 127, 64, -64, 1, -1, 32)) == pytest.approx(
        (-1.0, 0.0, 0.9921875, 0.5, -0.5, 1 / 128, -1 / 128, 0.25))


def test_vec_norm_clamps():
    assert vec_norm((2000, -500, 3000), 1000.0) == (1.0, -0.5, 1.0)


def test_rms_envelope_constant_signal():
    env = RmsEnvelope(8, 10)
    for _ in range(25):
        env.push((0.5,) * 8)
    assert env.values == pytest.approx((0.5,) * 8)
    assert env.mean == pytest.approx(0.5)


def test_rms_envelope_window_and_sine():
    env = RmsEnvelope(1, 200)
    for i in range(400):
        env.push((math.sin(2 * math.pi * i / 20),))
    assert env.values[0] == pytest.approx(1 / math.sqrt(2), abs=1e-3)
    env.set_window(5)
    assert env.values == (0.0,)


def test_processor_imu_and_zero():
    proc = DeviceProcessor(ProcessingParams(rms_window_ms=50, zero_mode="yaw"))
    assert proc.rms.window == 10  # 50 ms @ 200 Hz
    # quaternion for yaw = 90deg: w=cos45, z=sin45
    w = z = math.sqrt(0.5)
    pkt = P.parse_imu(struct.pack("<10h", int(w * 16384), 0, 0, int(z * 16384), 0, 0, 2048, 0, 0, 160))
    fr = proc.push_imu(pkt, 1.0)
    assert fr.euler[2] == pytest.approx(math.pi / 2, abs=1e-3)
    assert fr.accel == (0.0, 0.0, 1.0) and fr.gyro == (0.0, 0.0, 10.0)
    ref = proc.zero()
    assert ref is not None
    fr2 = proc.push_imu(pkt, 1.02)
    assert fr2.euler[2] == pytest.approx(0.0, abs=1e-3)
    assert fr2.quat_raw == fr.quat_raw  # raw is untouched
    proc.clear_zero()
    assert proc.push_imu(pkt, 1.04).euler[2] == pytest.approx(math.pi / 2, abs=1e-3)


def test_processor_emg():
    proc = DeviceProcessor()
    norm = proc.push_emg((64,) * 8, 0.0)
    assert norm == (0.5,) * 8
    assert proc.last_emg_raw == (64,) * 8
    assert proc.rms.values == pytest.approx((0.5,) * 8)


def test_tap_filter_threshold_and_cooldown():
    f = TapFilter(threshold_g=0.5, cooldown_ms=200)
    assert f.decide(0.0, 0.8) == (True, "")
    assert f.decide(0.1, 2.0) == (False, "within 200 ms of the last tap")
    assert f.decide(0.5, 0.3) == (False, "weaker than 0.50 g")
    assert f.decide(0.6, None) == (True, "")  # strength unknown (no IMU data): kept
    assert not f.decide(0.75, 1.0)[0]  # the cooldown counts from the last kept tap
    assert f.decide(0.85, 1.0)[0]
    assert TapFilter().decide(0.0, 0.01) == (True, "")  # both off


def _imu(accel_g, quat=(1.0, 0.0, 0.0, 0.0)):
    return P.ImuPacket(quat=tuple(round(q * P.ORIENTATION_SCALE) for q in quat),
                       accel=tuple(round(a * P.ACCELEROMETER_SCALE) for a in accel_g), gyro=(0, 0, 0))


def test_tap_strength_is_the_largest_jump_of_acceleration():
    proc = DeviceProcessor(ProcessingParams())
    assert proc.tap_strength(0.0, 10.0) is None and not proc.imu_live(0.0)
    for i in range(50):  # 1 s at 50 Hz at rest (1 g), a knock of 0.9 g at t = 0.5
        proc.push_imu(_imu((0.9, 0.0, 1.0) if i == 25 else (0.0, 0.0, 1.0)), i * 0.02)
    assert proc.tap_strength(0.38, 0.56) == pytest.approx(0.9, abs=0.01)
    assert proc.tap_strength(0.0, 0.4) == pytest.approx(0.0, abs=0.01)
    assert proc.imu_live(1.0) and not proc.imu_live(2.0)
    proc.push_imu(_imu((0.0, 0.0, 2.0)), 5.0)  # after a gap in the stream: no jump measured across it
    assert proc.tap_strength(4.9, 5.1) is None
    proc.set_tap_filter(0.4, 100)
    assert proc.taps.threshold_g == 0.4 and proc.params.tap_cooldown_ms == 100


def test_smooth_emg_activity():
    assert fv_activity((0, 256, 512, 1024, 3000, 0, 0, 0)) == pytest.approx((0, 0.25, 0.5, 1, 1, 0, 0, 0))
