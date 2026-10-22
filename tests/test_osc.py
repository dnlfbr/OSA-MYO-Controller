import asyncio
import socket

import pytest
from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_message import OscMessage
from pythonosc.parsing import osc_types

from myo_bridge.osc.namespace import AXIS_SUFFIXES, DEFAULT, MYOMAPPER, Namespace
from myo_bridge.osc.sender import OscSender


def _listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(1.0)
    return s


def _recv_all(s):
    out = []
    try:
        while True:
            data, _ = s.recvfrom(65535)
            out.append(data)
    except socket.timeout:
        pass
    return out


def _decode(dgram):
    if OscBundle.dgram_is_bundle(dgram):
        b = OscBundle(dgram)
        return [(m.address, m.params) for m in b]
    m = OscMessage(dgram)
    return [(m.address, m.params)]


def test_namespace_tables_are_complete():
    for key in ("emg_raw", "emg_norm", "emg_rms", "quat", "euler", "accel", "gyro", "pose", "arm",
                "xdir", "sync", "lock", "battery", "rssi", "status"):
        assert key in DEFAULT
    ns = Namespace("default", "vector")
    assert ns.address("emg_raw", 2) == "/myo/2/emg/raw"
    assert ns.axis_addresses("accel", 1) == ("/myo/1/accel/x", "/myo/1/accel/y", "/myo/1/accel/z")
    assert len(ns.axis_addresses("emg_raw", 1)) == 8
    mm = Namespace("myomapper")
    assert mm.address("quat", 1) == "/myo1/orientation/quaternion"
    assert mm.address("euler_norm", 3) == "/myo3/orientation/scaled"
    assert mm.is_myomapper and not mm.has("pose_id")
    with pytest.raises(ValueError):
        Namespace("nope")
    for k in AXIS_SUFFIXES:
        assert k in DEFAULT
    assert set(MYOMAPPER) <= set(DEFAULT)


def test_sender_vector_mode_and_types():
    s = _listener()
    port = s.getsockname()[1]
    tx = OscSender("127.0.0.1", port, Namespace(), {"quat": True, "accel": True, "gyro": False,
                                                    "pose": True, "battery": True},
                   emg_bundle_samples=1, imu_rate_hz=0)
    tx.imu(1, (1, 0, 0, 0), (1, 0, 0, 0), (0, 0, 0), (0, 0, 0), (0.5, 0.5, 0.5), (0, 0, 1), (1, 2, 3), 0.0)
    tx.pose(1, "fist", 1)
    tx.integer("battery", 1, 77)
    tx.integer("rssi", 1, -50)  # disabled -> nothing
    msgs = [m for d in _recv_all(s) for m in _decode(d)]
    assert ("/myo/1/quat", [1.0, 0.0, 0.0, 0.0]) in msgs
    assert ("/myo/1/accel", [0.0, 0.0, 1.0]) in msgs
    assert not any(a == "/myo/1/gyro" for a, _ in msgs)
    assert ("/myo/1/pose", ["fist"]) in msgs and ("/myo/1/pose/id", [1]) in msgs
    assert ("/myo/1/battery", [77]) in msgs
    assert not any("rssi" in a for a, _ in msgs)
    tx.close()


def test_sender_emg_bundles_and_axis_mode():
    s = _listener()
    port = s.getsockname()[1]
    tx = OscSender("127.0.0.1", port, Namespace("default", "axis"),
                   {"emg_raw": True, "emg_norm": True}, emg_bundle_samples=4)
    flushed = [tx.emg(1, (i,) * 8, (i / 128,) * 8) for i in range(4)]
    assert flushed == [False, False, False, True]
    dgrams = _recv_all(s)
    assert len(dgrams) == 1 and OscBundle.dgram_is_bundle(dgrams[0])
    msgs = _decode(dgrams[0])
    assert len(msgs) == 4 * 16  # 4 samples x (8 raw + 8 norm) axis messages
    assert ("/myo/1/emg/raw/0", [0]) in msgs and ("/myo/1/emg/raw/7", [3]) in msgs
    assert ("/myo/1/emg/norm/0", [3 / 128]) in msgs
    # partial bundle is flushed on close
    tx.emg(1, (9,) * 8, (0.07,) * 8)
    tx.close()
    assert len(_recv_all(s)) == 1


def test_sender_rate_limit_and_myomapper_pose():
    s = _listener()
    port = s.getsockname()[1]
    tx = OscSender("127.0.0.1", port, Namespace("myomapper"), {"euler": True, "pose": True},
                   emg_bundle_samples=1, imu_rate_hz=10)
    for i in range(10):
        tx.imu(2, (1, 0, 0, 0), (1, 0, 0, 0), (0, 0, 0.1 * i), (0, 0, 0), (0.5, 0.5, 0.5),
               (0, 0, 1), (0, 0, 0), i * 0.05)  # 20 Hz input
    tx.pose(2, "wave_out", 3)
    msgs = [m for d in _recv_all(s) for m in _decode(d)]
    euler = [m for m in msgs if m[0] == "/myo2/orientation/raw"]
    assert 4 <= len(euler) <= 6
    assert ("/myo2/pose", [3, "wave_out"]) in msgs
    tx.close()


def test_sender_disabled_sends_nothing():
    s = _listener()
    tx = OscSender("127.0.0.1", s.getsockname()[1], Namespace(), {"battery": True}, enabled=False)
    tx.integer("battery", 1, 5)
    assert _recv_all(s) == []


def test_rate_limiter_phase_tolerant():
    from myo_bridge.osc.sender import RateLimiter
    lim = RateLimiter(50)
    # 50 Hz input with +-0.5 ms jitter must all pass
    import random
    rng = random.Random(0)
    passed = sum(lim.allow(i * 0.02 + rng.uniform(-0.0005, 0.0005)) for i in range(100))
    assert passed == 100
    lim = RateLimiter(50)
    passed = sum(lim.allow(i * 0.005) for i in range(200))  # 200 Hz input -> 50 Hz
    assert 49 <= passed <= 51
    assert RateLimiter(0).allow(1.0) and RateLimiter(0).allow(1.0)
