// Same vectors as tests/test_quaternion.py.
import { describe, expect, it } from "vitest";
import * as Q from "../src/processing/quaternion";

const close = (a: number[], b: number[], abs = 1e-9) => a.forEach((v, i) => expect(Math.abs(v - b[i])).toBeLessThan(abs));
const norm2 = (q: number[]) => q.reduce((s, c) => s + c * c, 0);

describe("quaternion", () => {
  it.each([[[0, 0, 0]], [[0.3, -0.2, 1.0]], [[-1.2, 0.9, -2.5]], [[0.1, 1.4, 3.0]]])("euler round trip %j", (rpy) => {
    const q = Q.fromEuler(rpy[0], rpy[1], rpy[2]);
    expect(Math.abs(norm2(q) - 1)).toBeLessThan(1e-9);
    close(Q.toEuler(q), rpy);
  });

  it("identity and axes", () => {
    close(Q.toEuler(Q.IDENTITY), [0, 0, 0]);
    const q = Q.fromEuler(0, 0, Math.PI / 2); // 90 deg yaw
    expect(Q.toEuler(q)[2]).toBeCloseTo(Math.PI / 2, 9);
    close(Q.rotateVector(q, [1, 0, 0]), [0, 1, 0]);
  });

  it("multiply, conjugate, inverse", () => {
    const q = Q.fromEuler(0.4, -0.3, 2.0);
    close(Q.multiply(Q.conjugate(q), q), Q.IDENTITY);
  });

  it("normalizes raw Myo values", () => {
    const q = Q.normalize([16384 / 16384, 100 / 16384, -200 / 16384, 50 / 16384]);
    expect(Math.abs(norm2(q) - 1)).toBeLessThan(1e-12);
    expect(Q.normalize([0, 0, 0, 0])).toEqual(Q.IDENTITY);
  });

  it("degrees and unit range", () => {
    const e: Q.Euler = [Math.PI, -Math.PI / 2, 0];
    close(Q.toDegrees(e), [180, -90, 0]);
    close(Q.toUnitRange(e), [0, 0.25, 0.5]); // +pi wraps to 0.0
  });

  it("yaw reference re-centres heading only", () => {
    const ref = new Q.OrientationReference("yaw");
    const q = Q.fromEuler(0.2, 0.1, 1.3);
    ref.setZero(q);
    close(Q.toEuler(ref.apply(q)), [0.2, 0.1, 0]);
    // a later heading change shows up relative to the zero
    const q2 = Q.fromEuler(0.2, 0.1, 1.3 + 0.5);
    expect(Q.toEuler(ref.apply(q2))[2]).toBeCloseTo(0.5, 9);
    ref.clear();
    expect(ref.apply(q2)).toEqual(q2);
  });

  it("full reference", () => {
    const ref = new Q.OrientationReference("full");
    const q = Q.fromEuler(0.2, 0.1, 1.3);
    ref.setZero(q);
    close(Q.toEuler(ref.apply(q)), [0, 0, 0]);
  });
});
