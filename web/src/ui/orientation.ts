/** Arm view: the armband on a forearm with a hand, in software 3D on a 2D canvas. A port of
 * gui/widgets/orientation3d.py: same model frame, cameras, flip and shading.
 *
 * Model frame: x toward the hand, z out of the logo pod. The quaternion world is Z up. When the
 * band's +x points to the elbow (sync x_direction) the model is turned 180° about z. */

import type { Quat } from "../myo/protocol";
import * as Q from "../processing/quaternion";
import { HiDpiCanvas, css, palette, toRgb, withAlpha, type RGB } from "./theme";

type V3 = [number, number, number];

export const VIEWS = ["behind", "side", "top", "mirror"] as const;
export type View = (typeof VIEWS)[number];
export const VIEW_HELP: Record<View, string> = {
  behind: "over the shoulder: the arm points into the screen",
  side: "from the right: raising the arm raises the model",
  top: "from above: the arm points up the screen",
  mirror: "facing you, like a mirror",
};

interface Camera { eye: V3; target: V3; up: V3; mirror: boolean; focal: number }
const cam = (eye: V3, target: V3, focal: number, up: V3 = [0, 0, 1], mirror = false): Camera =>
  ({ eye, target, up, mirror, focal });
export const CAMERAS: Record<View, Camera> = {
  behind: cam([-4.6, -2.3, 2.5], [0.5, 0, -0.3], 4.4),
  side: cam([0.35, -6.2, 1.1], [0.35, 0, -0.35], 4.6),
  top: cam([0.35, 0, 6.6], [0.35, 0, 0], 4.4, [1, 0, 0]),
  mirror: cam([5.6, -1.5, 2.1], [0.3, 0, -0.3], 4.4, [0, 0, 1], true),
};

const FLIP: Quat = [0, 0, 0, 1]; // 180° about z
const GROUND_Z = -1.3;

const sub = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: V3, b: V3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = (a: V3): V3 => {
  const n = Math.hypot(...a) || 1;
  return [a[0] / n, a[1] / n, a[2] / n];
};

function basis(c: Camera): [V3, V3, V3] {
  const f = unit(sub(c.target, c.eye));
  const r = unit(cross(f, c.up));
  return [r, cross(r, f), f];
}

export function rotMatrix(q: Quat): number[] {
  const [w, x, y, z] = Q.normalize(q);
  return [
    1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
    2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
    2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y),
  ];
}

const rot = (m: number[], v: V3): V3 => [
  m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
  m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
  m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
];

/** Quaternion that turns the model into the world, given the band's q. */
export const modelQuat = (q: Quat, towardElbow: boolean): Quat =>
  towardElbow ? Q.multiply(FLIP, Q.multiply(q, FLIP)) : q;

// ---------------------------------------------------------------- geometry (model frame)
type Tone = "skin" | "arm" | "pod" | "logo";
interface Part { verts: V3[]; faces: number[][]; tone: Tone; edge: boolean; shadow: boolean }

const BOX_FACES = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]];
function box(x0: number, x1: number, y0: number, y1: number, z0: number, z1: number): V3[] {
  const v: V3[] = [];
  for (const x of [x0, x1]) for (const y of [y0, y1]) for (const z of [z0, z1]) v.push([x, y, z]);
  return v;
}

function forearm(): Part {
  const around = 18, xs = Array.from({ length: 7 }, (_, i) => -1.05 + (i * 1.85) / 6);
  const verts: V3[] = [];
  for (const x of xs) {
    const k = (x - xs[0]) / (xs[xs.length - 1] - xs[0]);
    const ry = 0.36 + (0.27 - 0.36) * k, rz = 0.3 + (0.17 - 0.3) * k;
    for (let i = 0; i < around; i++) {
      const a = (2 * Math.PI * i) / around;
      verts.push([x, ry * Math.cos(a), rz * Math.sin(a)]);
    }
  }
  const faces: number[][] = [];
  for (let r = 0; r < xs.length - 1; r++)
    for (let i = 0; i < around; i++) {
      const j = (i + 1) % around;
      faces.push([r * around + i, r * around + j, (r + 1) * around + j, (r + 1) * around + i]);
    }
  faces.push(Array.from({ length: around }, (_, i) => i));
  faces.push(Array.from({ length: around }, (_, i) => (xs.length - 1) * around + i));
  return { verts, faces, tone: "arm", edge: false, shadow: true };
}

function band(): Part[] {
  const xc = -0.55, halfLen = 0.15, k = (xc + 1.05) / 1.85;
  const ry = 0.36 + (0.27 - 0.36) * k, rz = 0.3 + (0.17 - 0.3) * k;
  const parts: Part[] = [];
  for (let p = 0; p < 8; p++) {
    const a = Math.PI / 2 + (p * Math.PI) / 4;
    const r = (ry * rz) / Math.hypot(rz * Math.cos(a), ry * Math.sin(a));
    const n: V3 = [0, Math.cos(a), Math.sin(a)], t: V3 = [0, -Math.sin(a), Math.cos(a)];
    const hw = r * Math.sin(Math.PI / 8) * 0.8;
    const verts: V3[] = [];
    for (const dx of [-halfLen, halfLen])
      for (const dt of [-hw, hw])
        for (const dr of [r + 0.01, r + 0.085])
          verts.push([xc + dx + dt * t[0] + dr * n[0], dt * t[1] + dr * n[1], dt * t[2] + dr * n[2]]);
    parts.push({ verts, faces: BOX_FACES, tone: p === 0 ? "logo" : "pod", edge: true, shadow: false });
  }
  return parts;
}

/** Palm toward -z, fingers toward +x; thumb on +y for a right arm, -y for a left one. */
function hand(arm: string): Part[] {
  const part = (verts: V3[]): Part => ({ verts, faces: BOX_FACES, tone: "skin", edge: true, shadow: true });
  const parts = [part(box(0.82, 1.38, -0.25, 0.25, -0.085, 0.075))];
  const lengths = [0.3, 0.36, 0.34, 0.26];
  for (let i = 0; i < 4; i++) {
    const y0 = -0.24 + i * 0.125;
    const len = lengths[arm !== "left" ? i : 3 - i];
    parts.push(part(box(1.4, 1.4 + len, y0, y0 + 0.105, -0.06, 0.05)));
  }
  if (arm === "right" || arm === "left") {
    const s = arm === "right" ? 1 : -1, ang = (35 * Math.PI * s) / 180;
    const c = Math.cos(ang), sn = Math.sin(ang);
    parts.push(part(box(0, 0.34, -0.055, 0.055, -0.06, 0.04).map(([x, y, z]) =>
      [x * c - y * sn + 0.95, x * sn + y * c + s * 0.25, z - 0.03] as V3)));
  }
  return parts;
}

interface Face { idx: number[]; normal: V3; centre: V3; tone: Tone; edge: boolean }

const LIGHT = unit([-0.35, -0.45, 0.82]);

/** Convex hull (monotone chain) of 2-D points. */
function hull(pts: Array<[number, number]>): Array<[number, number]> {
  const p = [...pts].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (p.length < 3) return p;
  const cr = (o: number[], a: number[], b: number[]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: Array<[number, number]> = [], upper: Array<[number, number]> = [];
  for (const pt of p) {
    while (lower.length >= 2 && cr(lower[lower.length - 2], lower[lower.length - 1], pt) <= 0) lower.pop();
    lower.push(pt);
  }
  for (const pt of p.reverse()) {
    while (upper.length >= 2 && cr(upper[upper.length - 2], upper[upper.length - 1], pt) <= 0) upper.pop();
    upper.push(pt);
  }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}

export class ArmView {
  view: View = "behind";
  q: Quat = [...Q.IDENTITY];
  towardElbow = false;
  live = false; // false: drawn grey (no IMU data)
  private arm = "unknown";
  private verts: V3[] = [];
  private faces: Face[] = [];
  private shadowIdx: number[] = [];
  private readonly c: HiDpiCanvas;

  constructor(canvas: HTMLCanvasElement) {
    this.c = new HiDpiCanvas(canvas);
    this.compile();
  }

  setArm(arm: string): void {
    if (arm !== this.arm) {
      this.arm = arm;
      this.compile();
    }
  }

  private compile(): void {
    const parts = [forearm(), ...band(), ...hand(this.arm)];
    this.verts = [];
    this.faces = [];
    this.shadowIdx = [];
    let off = 0;
    for (const part of parts) {
      const centre = part.verts.reduce<V3>((a, v) => [a[0] + v[0], a[1] + v[1], a[2] + v[2]], [0, 0, 0])
        .map((v) => v / part.verts.length) as V3;
      for (const f of part.faces) {
        const pw = f.map((i) => part.verts[i]);
        let n: V3 = [0, 0, 0]; // Newell's method
        for (let i = 0; i < pw.length; i++) {
          const a = pw[i], b = pw[(i + 1) % pw.length];
          n = [n[0] + (a[1] - b[1]) * (a[2] + b[2]), n[1] + (a[2] - b[2]) * (a[0] + b[0]), n[2] + (a[0] - b[0]) * (a[1] + b[1])];
        }
        const fc = pw.reduce<V3>((a, v) => [a[0] + v[0], a[1] + v[1], a[2] + v[2]], [0, 0, 0]).map((v) => v / pw.length) as V3;
        if (dot(n, sub(fc, centre)) < 0) n = [-n[0], -n[1], -n[2]];
        this.faces.push({ idx: f.map((i) => i + off), normal: unit(n), centre: fc, tone: part.tone, edge: part.edge });
      }
      this.verts.push(...part.verts);
      if (part.shadow) for (let i = 0; i < part.verts.length; i++) this.shadowIdx.push(off + i);
      off += part.verts.length;
    }
  }

  draw(): void {
    const ctx = this.c.begin();
    const { w, h } = this.c;
    const pal = palette();
    const camera = CAMERAS[this.view];
    const [br, bu, bf] = basis(camera);
    const s = Math.min(w / 2.6, h / 2.15), cx = w / 2, cy = h / 2;
    const toCam = (p: V3): V3 => {
      const d = sub(p, camera.eye);
      return [dot(d, br), dot(d, bu), dot(d, bf)];
    };
    const px = (c: V3): [number, number] => {
      const depth = Math.max(c[2], 0.2);
      let x = (camera.focal * c[0]) / depth;
      if (camera.mirror) x = -x;
      return [cx + x * s, cy - ((camera.focal * c[1]) / depth) * s];
    };

    // ground grid
    ctx.lineWidth = 1;
    ctx.strokeStyle = pal.line2;
    ctx.beginPath();
    const seg = (a: V3, b: V3) => {
      const ca = toCam(a), cb = toCam(b);
      if (ca[2] > 0.2 && cb[2] > 0.2) {
        ctx.moveTo(...px(ca));
        ctx.lineTo(...px(cb));
      }
    };
    for (let y = -2; y <= 2.001; y += 0.5) seg([-2, y, GROUND_Z], [3, y, GROUND_Z]);
    for (let x = -2; x <= 3.001; x += 0.5) seg([x, -2, GROUND_Z], [x, 2, GROUND_Z]);
    ctx.stroke();

    const m = rotMatrix(modelQuat(this.q, this.towardElbow));
    const world = this.verts.map((v) => rot(m, v));

    // shadow: the arm dropped onto the ground (a darker tint of the ground, not black)
    const sh = this.shadowIdx.map((i) => toCam([world[i][0], world[i][1], GROUND_Z]));
    if (sh.every((c) => c[2] > 0.2)) {
      const poly = hull(sh.map(px));
      ctx.fillStyle = withAlpha(pal.line, 0.9);
      ctx.beginPath();
      poly.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.closePath();
      ctx.fill();
    }

    // arm, back to front
    const grey = toRgb(pal.label);
    const tones: Record<Tone, RGB> = this.live
      ? { skin: toRgb(pal.ink3), arm: toRgb(pal.ink3).map((v) => v * 0.8) as RGB, pod: toRgb(pal.line3), logo: toRgb(pal.copper) }
      : { skin: grey, arm: grey.map((v) => v * 0.85) as RGB, pod: toRgb(pal.line2), logo: grey };
    const edgeOf: Record<Tone, string> = {
      skin: withAlpha(pal.ink2, 0.5), arm: "", pod: pal.line3, logo: this.live ? pal.copper : pal.label,
    };
    const scr = world.map((v) => px(toCam(v)));
    const visible = this.faces
      .map((f) => {
        const n = rot(m, f.normal), c = rot(m, f.centre);
        return { f, n, c, depth: dot(sub(c, camera.eye), bf) };
      })
      .filter(({ n, c }) => dot(n, sub(c, camera.eye)) < 0)
      .sort((a, b) => b.depth - a.depth);
    for (const { f, n } of visible) {
      const shade = 0.42 + 0.58 * Math.max(0, dot(n, LIGHT));
      const fill = tones[f.tone].map((v) => Math.min(1, v * shade * 1.15)) as RGB;
      ctx.fillStyle = css(fill);
      ctx.beginPath();
      f.idx.forEach((i, k) => (k ? ctx.lineTo(...scr[i]) : ctx.moveTo(...scr[i])));
      ctx.closePath();
      ctx.fill();
      ctx.lineWidth = f.edge ? 0.8 : 0.6;
      ctx.strokeStyle = f.edge ? edgeOf[f.tone] : css(fill.map((v) => v / 1.15) as RGB);
      ctx.stroke();
    }
  }
}
