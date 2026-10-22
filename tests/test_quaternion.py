import math

import pytest

from myo_bridge.processing import quaternion as Q


@pytest.mark.parametrize("rpy", [(0, 0, 0), (0.3, -0.2, 1.0), (-1.2, 0.9, -2.5), (0.1, 1.4, 3.0)])
def test_euler_roundtrip(rpy):
    q = Q.from_euler(*rpy)
    assert abs(sum(c * c for c in q) - 1.0) < 1e-9
    r, p, y = Q.to_euler(q)
    assert (r, p, y) == pytest.approx(rpy, abs=1e-9)


def test_identity_and_axes():
    assert Q.to_euler(Q.IDENTITY) == (0.0, 0.0, 0.0)
    q = Q.from_euler(0, 0, math.pi / 2)  # 90 deg yaw
    assert Q.to_euler(q)[2] == pytest.approx(math.pi / 2)
    assert Q.rotate_vector(q, (1, 0, 0)) == pytest.approx((0, 1, 0), abs=1e-9)


def test_multiply_conjugate_inverse():
    q = Q.from_euler(0.4, -0.3, 2.0)
    r = Q.multiply(Q.conjugate(q), q)
    assert r == pytest.approx(Q.IDENTITY, abs=1e-9)


def test_normalize_raw_myo_values():
    q = Q.normalize((16384 / 16384, 100 / 16384, -200 / 16384, 50 / 16384))
    assert abs(sum(c * c for c in q) - 1.0) < 1e-12
    assert Q.normalize((0, 0, 0, 0)) == Q.IDENTITY


def test_degrees_and_unit_range():
    e = (math.pi, -math.pi / 2, 0.0)
    assert Q.to_degrees(e) == pytest.approx((180.0, -90.0, 0.0))
    assert Q.to_unit_range(e) == pytest.approx((0.0, 0.25, 0.5))  # +pi wraps to 0.0


def test_yaw_reference_recentres_heading_only():
    ref = Q.OrientationReference("yaw")
    q = Q.from_euler(0.2, 0.1, 1.3)
    ref.set_zero(q)
    r, p, y = Q.to_euler(ref.apply(q))
    assert y == pytest.approx(0.0, abs=1e-9)
    assert (r, p) == pytest.approx((0.2, 0.1), abs=1e-9)
    # a later heading change shows up relative to the zero
    q2 = Q.from_euler(0.2, 0.1, 1.3 + 0.5)
    assert Q.to_euler(ref.apply(q2))[2] == pytest.approx(0.5, abs=1e-9)
    ref.clear()
    assert ref.apply(q2) == q2


def test_full_reference():
    ref = Q.OrientationReference("full")
    q = Q.from_euler(0.2, 0.1, 1.3)
    ref.set_zero(q)
    assert Q.to_euler(ref.apply(q)) == pytest.approx((0, 0, 0), abs=1e-9)
