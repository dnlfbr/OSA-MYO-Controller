"""Quaternion helpers. Quaternions are (w, x, y, z) tuples, as the Myo sends them."""

from __future__ import annotations

import math

Quat = tuple[float, float, float, float]
Euler = tuple[float, float, float]

IDENTITY: Quat = (1.0, 0.0, 0.0, 0.0)


def normalize(q: Quat) -> Quat:
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n == 0.0:
        return IDENTITY
    return (w / n, x / n, y / n, z / n)


def conjugate(q: Quat) -> Quat:
    w, x, y, z = q
    return (w, -x, -y, -z)


def multiply(a: Quat, b: Quat) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def to_euler(q: Quat) -> Euler:
    """(roll, pitch, yaw) in radians, Z-Y-X convention as in Thalmic's hello-myo sample:
    roll about x, pitch about y, yaw about z. Ranges: roll, yaw in [-pi, pi], pitch in [-pi/2, pi/2]."""
    w, x, y, z = q
    roll = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    s = 2.0 * (w * y - z * x)
    pitch = math.asin(max(-1.0, min(1.0, s)))
    yaw = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return (roll, pitch, yaw)


def from_euler(roll: float, pitch: float, yaw: float) -> Quat:
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return (
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    )


def yaw_only(q: Quat) -> Quat:
    """The rotation about z contained in q (used to re-centre heading only)."""
    _, _, yaw = to_euler(q)
    return from_euler(0.0, 0.0, yaw)


def rotate_vector(q: Quat, v: tuple[float, float, float]) -> tuple[float, float, float]:
    """Rotate vector v by quaternion q (q v q*)."""
    w, x, y, z = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    # v' = v + w t + cross(q.xyz, t)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def to_degrees(e: Euler) -> Euler:
    return (math.degrees(e[0]), math.degrees(e[1]), math.degrees(e[2]))


def to_unit_range(e: Euler) -> Euler:
    """Map angles in [-pi, pi] to [0, 1] (MyoMapper's 'scaled' orientation)."""
    two_pi = 2.0 * math.pi
    return tuple(((a + math.pi) / two_pi) % 1.0 for a in e)  # type: ignore[return-value]


class OrientationReference:
    """Holds a 'zero' orientation and applies it to incoming quaternions.

    mode "yaw": only the heading is re-centred (roll/pitch stay gravity-referenced; this is
    what drifts on the Myo and what MyoMapper's calibrate does). mode "full": the whole
    orientation at zero time becomes the identity.
    """

    def __init__(self, mode: str = "yaw") -> None:
        self.mode = mode
        self.reference: Quat | None = None
        self._inv: Quat = IDENTITY

    def set_zero(self, q: Quat) -> None:
        q = normalize(q)
        ref = yaw_only(q) if self.mode == "yaw" else q
        self.reference = ref
        self._inv = conjugate(ref)

    def set_reference(self, ref: Quat | None) -> None:
        if ref is None:
            self.clear()
            return
        self.reference = normalize(ref)
        self._inv = conjugate(self.reference)

    def clear(self) -> None:
        self.reference = None
        self._inv = IDENTITY

    def apply(self, q: Quat) -> Quat:
        if self.reference is None:
            return q
        return multiply(self._inv, q)
