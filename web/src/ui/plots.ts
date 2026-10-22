/** Scrolling strip charts on canvas, fed from the bridge's ring buffers, drawn like the app's
 * pyqtgraph plots (theme.style_plot): a left axis with tick values, faint grid lines at the ticks,
 * the 0 line, no x values. */

import type { Ring } from "../bridge";
import { HiDpiCanvas, palette, withAlpha } from "./theme";

export interface StripOptions {
  rate: number; // samples/s of the ring
  windowS: number;
  min: number;
  max: number;
  channels: number[]; // which ring channels to draw
  colors: string[]; // one per drawn channel
  zero?: boolean; // draw the 0 line
  tag?: string; // top-left text, inside the plot
  lineWidth?: number;
  axisW?: number; // width of the left axis (px), 0 = none
}

/** Tick step: 1, 2 or 5 x 10^k, about one tick per `px` pixels. */
export function tickStep(span: number, height: number, px = 18): number {
  const raw = span / Math.max(1, Math.floor(height / px));
  const mag = 10 ** Math.floor(Math.log10(raw));
  for (const m of [1, 2, 5, 10]) if (m * mag >= raw) return m * mag;
  return 10 * mag;
}

const tickText = (v: number, step: number) =>
  step >= 1 ? String(Math.round(v)) : v.toFixed(Math.min(3, Math.ceil(-Math.log10(step))));

/** Draws the last windowS seconds of a ring, newest at the right. */
export class Strip {
  readonly c: HiDpiCanvas;

  constructor(canvas: HTMLCanvasElement) {
    this.c = new HiDpiCanvas(canvas);
  }

  /** Axis, grid and tag only (no data yet). */
  frame(o: Pick<StripOptions, "min" | "max" | "zero" | "tag" | "axisW">): void {
    this.draw(null, { rate: 1, windowS: 1, channels: [], colors: [], ...o }, false);
  }

  draw(ring: Ring | null, o: StripOptions, live: boolean): void {
    const ctx = this.c.begin();
    const { w, h } = this.c;
    const pal = palette();
    const ax = o.axisW ?? 0;
    const pw = Math.max(1, w - ax);
    const ph = Math.max(1, h - 4); // bottom axis: a line, no values
    const y = (v: number) => ph - ((v - o.min) / (o.max - o.min)) * ph;

    // ticks, grid and the left axis
    if (ax) {
      const step = tickStep(o.max - o.min, ph);
      ctx.font = `9px ${pal.mono}`;
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.lineWidth = 1;
      for (let v = Math.ceil(o.min / step) * step; v <= o.max + 1e-9; v += step) {
        const yy = Math.round(y(v)) + 0.5;
        if (yy < 5 || yy > ph - 5) continue; // no half-cut labels at the edges
        ctx.strokeStyle = withAlpha(pal.line2, 0.5);
        ctx.beginPath();
        ctx.moveTo(ax, yy);
        ctx.lineTo(w, yy);
        ctx.stroke();
        ctx.strokeStyle = pal.line2;
        ctx.beginPath();
        ctx.moveTo(ax, yy);
        ctx.lineTo(ax + 4, yy);
        ctx.stroke();
        ctx.fillStyle = pal.label;
        ctx.fillText(tickText(Math.abs(v) < step / 1e6 ? 0 : v, step), ax - 6, yy);
      }
      ctx.strokeStyle = pal.line2;
      ctx.beginPath();
      ctx.moveTo(ax + 0.5, 0);
      ctx.lineTo(ax + 0.5, ph);
      ctx.lineTo(w, ph + 0.5);
      ctx.stroke();
    }
    if (o.zero && o.min < 0 && o.max > 0) {
      ctx.strokeStyle = pal.line2;
      ctx.lineWidth = 1;
      ctx.beginPath();
      const yz = Math.round(y(0)) + 0.5;
      ctx.moveTo(ax, yz);
      ctx.lineTo(w, yz);
      ctx.stroke();
    }

    const n = ring ? Math.min(ring.count, Math.round(o.windowS * o.rate)) : 0;
    if (ring && n > 1) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(ax + 1, 0, pw - 1, ph);
      ctx.clip();
      const total = Math.round(o.windowS * o.rate);
      const dx = pw / Math.max(1, total - 1);
      const x0 = w - (n - 1) * dx;
      // more samples than pixels: draw a min/max column per pixel instead of every point
      const step = Math.max(1, Math.floor(n / pw));
      ctx.lineWidth = o.lineWidth ?? 1.2;
      ctx.lineJoin = "round";
      o.channels.forEach((ch, k) => {
        const d = ring.data[ch];
        ctx.strokeStyle = live ? o.colors[k] : pal.label; // no fresh signal: grey, not fake colour
        ctx.beginPath();
        const start = (ring.head - n + ring.size) % ring.size;
        for (let i = 0; i < n; i += step) {
          let lo = Infinity, hi = -Infinity;
          for (let j = 0; j < step && i + j < n; j++) {
            const v = d[(start + i + j) % ring.size];
            if (v < lo) lo = v;
            if (v > hi) hi = v;
          }
          const xx = x0 + i * dx;
          if (i === 0) ctx.moveTo(xx, y(lo));
          else ctx.lineTo(xx, y(lo));
          if (hi !== lo) ctx.lineTo(xx, y(hi));
        }
        ctx.stroke();
      });
      ctx.restore();
    }

    if (o.tag) {
      ctx.font = `10px ${pal.mono}`;
      ctx.letterSpacing = "2px";
      ctx.fillStyle = pal.ink3;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      // a veil under the tag keeps it readable over a full-scale trace
      ctx.fillStyle = withAlpha(pal.card, 0.85);
      ctx.fillRect(ax + 2, 0, ctx.measureText(o.tag).width + 8, 15);
      ctx.fillStyle = pal.ink3;
      ctx.fillText(o.tag, ax + 6, 3);
      ctx.letterSpacing = "0px";
    }
  }
}

/** AUTO range per pod: a high percentile of |x| over the window, grows at once, shrinks slowly
 * (widgets/emg_grid.py). */
export function autoRange(ring: Ring, ch: number, n: number, current: number, minRange: number, signed: boolean): number {
  n = Math.min(n, ring.count);
  if (n < 4) return current;
  const d = ring.data[ch];
  const vals = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const v = d[(ring.head - n + i + ring.size) % ring.size];
    vals[i] = signed ? Math.abs(v) : v;
  }
  vals.sort();
  const target = Math.max(minRange, vals[Math.min(n - 1, Math.floor(n * 0.995))] * 1.25);
  return target > current ? target : current + (target - current) * 0.04;
}

/** Eight bars 0..1 on a track, pod numbers below (the Gesture panel's POD ACTIVITY). */
export class Bars {
  readonly c: HiDpiCanvas;

  constructor(canvas: HTMLCanvasElement) {
    this.c = new HiDpiCanvas(canvas);
  }

  draw(values: number[], live: boolean): void {
    const ctx = this.c.begin();
    const { w, h } = this.c;
    const pal = palette();
    const n = values.length;
    const axisH = 16;
    const hh = h - axisH;
    const slot = w / (n + 0.2);
    const bw = slot * 0.62;
    ctx.font = `9px ${pal.mono}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let i = 0; i < n; i++) {
      const cx = slot * (i + 0.6);
      ctx.fillStyle = withAlpha(pal.ink, 0.04);
      ctx.fillRect(cx - bw / 2, 0, bw, hh);
      const v = Math.max(0, Math.min(1, values[i]));
      ctx.fillStyle = live ? pal.copper : pal.label; // no signal: grey
      ctx.fillRect(cx - bw / 2, hh * (1 - v), bw, hh * v);
      ctx.fillStyle = pal.label;
      ctx.fillText(String(i), cx, hh + 4);
    }
    ctx.strokeStyle = pal.line2;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, hh + 0.5);
    ctx.lineTo(w, hh + 0.5);
    ctx.stroke();
  }
}

/** The Link panel's history: one bar per second, 0..100, newest at the right. */
export class History {
  readonly c: HiDpiCanvas;

  constructor(canvas: HTMLCanvasElement, readonly slots = 60) {
    this.c = new HiDpiCanvas(canvas);
  }

  draw(values: number[]): void {
    const ctx = this.c.begin();
    const { w, h } = this.c;
    const pal = palette();
    const slot = w / this.slots;
    const bw = slot * 0.7;
    const off = this.slots - values.length;
    for (let i = 0; i < this.slots; i++) {
      const x = i * slot + (slot - bw) / 2;
      ctx.fillStyle = withAlpha(pal.ink, 0.04);
      ctx.fillRect(x, 0, bw, h);
      const v = i >= off ? values[i - off] : 0;
      if (v > 0) {
        ctx.fillStyle = pal.cyan;
        ctx.fillRect(x, h * (1 - v / 100), bw, (h * v) / 100);
      }
    }
  }
}
