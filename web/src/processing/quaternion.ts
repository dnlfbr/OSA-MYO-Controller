/** Quaternion helpers (port of processing/quaternion.py). Quaternions are [w, x, y, z], as the
 * Myo sends them. */

import type { Quat, Vec3 } from "../myo/protocol";

export type Euler = Vec3; // roll, pitch, yaw (radians)

export const IDENTITY: Quat = [1, 0, 0, 0];

export function normalize(q: Quat): Quat {
  const [w, x, y, z] = q;
  const n = Math.sqrt(w * w + x * x + y * y + z * z);
  return n === 0 ? [...IDENTITY] : [w / n, x / n, y / n, z / n];
}

export const conjugate = ([w, x, y, z]: Quat): Quat => [w, -x, -y, -z];

export function multiply(a: Quat, b: Quat): Quat {
  const [aw, ax, ay, az] = a;
  const [bw, bx, by, bz] = b;
  return [
    aw * bw - ax * bx - ay * by - az * bz,
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
  ];
}

/** [roll, pitch, yaw] in radians, Z-Y-X convention as in Thalmic's hello-myo sample: roll about
 * x, pitch about y, yaw about z. Ranges: roll, yaw in [-pi, pi], pitch in [-pi/2, pi/2]. */
export function toEuler([w, x, y, z]: Quat): Euler {
  const roll = Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y));
  const s = 2 * (w * y - z * x);
  const pitch = Math.asin(Math.max(-1, Math.min(1, s)));
  const yaw = Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
  return [roll, pitch, yaw];
}

export function fromEuler(roll: number, pitch: number, yaw: number): Quat {
  const cr = Math.cos(roll / 2), sr = Math.sin(roll / 2);
  const cp = Math.cos(pitch / 2), sp = Math.sin(pitch / 2);
  const cy = Math.cos(yaw / 2), sy = Math.sin(yaw / 2);
  return [
    cr * cp * cy + sr * sp * sy,
    sr * cp * cy - cr * sp * sy,
    cr * sp * cy + sr * cp * sy,
    cr * cp * sy - sr * sp * cy,
  ];
}

/** The rotation about z contained in q (used to re-centre heading only). */
export const yawOnly = (q: Quat): Quat => fromEuler(0, 0, toEuler(q)[2]);

/** Rotate vector v by quaternion q (q v q*). */
export function rotateVector([w, x, y, z]: Quat, [vx, vy, vz]: Vec3): Vec3 {
  const tx = 2 * (y * vz - z * vy);
  const ty = 2 * (z * vx - x * vz);
  const tz = 2 * (x * vy - y * vx);
  return [
    vx + w * tx + (y * tz - z * ty),
    vy + w * ty + (z * tx - x * tz),
    vz + w * tz + (x * ty - y * tx),
  ];
}

export const toDegrees = (e: Euler): Euler => e.map((a) => (a * 180) / Math.PI) as Euler;

/** Map angles in [-pi, pi] to [0, 1] (MyoMapper's 'scaled' orientation). */
export const toUnitRange = (e: Euler): Euler =>
  e.map((a) => ((((a + Math.PI) / (2 * Math.PI)) % 1) + 1) % 1) as Euler;

export type ZeroMode = "yaw" | "full";

/** Holds a 'zero' orientation and applies it to incoming quaternions.
 *
 * mode "yaw": only the heading is re-centred (roll/pitch stay gravity-referenced; this is what
 * drifts on the Myo and what MyoMapper's calibrate does). mode "full": the whole orientation at
 * zero time becomes the identity. */
export class OrientationReference {
  reference: Quat | null = null;
  private inv: Quat = [...IDENTITY];

  constructor(public mode: ZeroMode = "yaw") {}

  setZero(q: Quat): void {
    const n = normalize(q);
    const ref = this.mode === "yaw" ? yawOnly(n) : n;
    this.reference = ref;
    this.inv = conjugate(ref);
  }

  setReference(ref: Quat | null): void {
    if (ref === null) return this.clear();
    this.reference = normalize(ref);
    this.inv = conjugate(this.reference);
  }

  clear(): void {
    this.reference = null;
    this.inv = [...IDENTITY];
  }

  apply(q: Quat): Quat {
    return this.reference === null ? q : multiply(this.inv, q);
  }
}
