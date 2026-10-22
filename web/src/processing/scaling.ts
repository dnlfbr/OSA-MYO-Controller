/** Unit conversions (port of processing/scaling.py). Documented in the README "Scaling".
 *
 *   quaternion : int16 / 16384   -> unit quaternion
 *   accel      : int16 / 2048    -> g        (range +-16 g)
 *   gyro       : int16 / 16      -> deg/s    (range +-2000 deg/s)
 *   emg        : int8            -> raw -128..127 ; norm = raw / 128 -> -1..1
 */

import { EMG_SCALE, type Vec3 } from "../myo/protocol";

export const EMG_NORM = 1 / EMG_SCALE;

export const emgNorm = (sample: ArrayLike<number>): number[] => Array.from(sample, (v) => v * EMG_NORM);

export const clampUnit = (v: number) => (v < -1 ? -1 : v > 1 ? 1 : v);

/** Scale a 3-vector so that +-fullScale maps to +-1 (clamped). */
export const vecNorm = (v: Vec3, fullScale: number): Vec3 =>
  v.map((x) => clampUnit(x / fullScale)) as Vec3;
