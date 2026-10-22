/** Canvas colours and fonts read from the CSS variables, so plots follow [data-theme]. Re-read on
 * the "ui-theme" event and when the colour scheme changes. */

export type RGB = [number, number, number];

export interface Palette {
  bg: string; card: string; line: string; line2: string; line3: string; grid: string; track: string;
  ink: string; ink2: string; ink3: string; label: string; ghost: string;
  copper: string; amber: string; cyan: string; ok: string; warn: string; bad: string;
  mono: string;
  axis: string[]; // x y z w: copper, amber, cyan, ink-2 (as theme.py AXIS_COLORS)
}

const read = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

let current: Palette | null = null;
const listeners = new Set<() => void>();

export function palette(): Palette {
  if (current) return current;
  const p: Palette = {
    bg: read("--ui-bg"), card: read("--ui-card"), line: read("--ui-line"), line2: read("--ui-line-2"),
    line3: read("--ui-line-3"), grid: read("--ui-grid"), track: read("--ui-track"),
    ink: read("--ui-ink"), ink2: read("--ui-ink-2"), ink3: read("--ui-ink-3"), label: read("--ui-label"),
    ghost: read("--ui-ghost"),
    copper: read("--ui-copper"), amber: read("--ui-amber"), cyan: read("--ui-cyan"),
    ok: read("--ui-ok"), warn: read("--ui-warn"), bad: read("--ui-bad"),
    mono: read("--ui-mono"),
    axis: [],
  };
  p.axis = [p.copper, p.amber, p.cyan, p.ink2];
  current = p;
  return p;
}

export function onPalette(fn: () => void): void {
  listeners.add(fn);
}

function invalidate(): void {
  current = null;
  for (const fn of listeners) fn();
}

if (typeof window !== "undefined") {
  window.addEventListener("ui-theme", invalidate);
  window.matchMedia?.("(prefers-color-scheme: light)").addEventListener?.("change", invalidate);
}

/** A token value ("#RRGGBB" or the rgb/rgba function form) -> [r, g, b] in 0..1. */
export function toRgb(color: string): RGB {
  const c = color.trim();
  if (c.startsWith("#")) {
    const h = c.length === 4 ? c.slice(1).split("").map((d) => d + d).join("") : c.slice(1, 7);
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255) as RGB;
  }
  const m = c.match(/[\d.]+/g);
  return m ? (m.slice(0, 3).map((v) => Number(v) / 255) as RGB) : [0.5, 0.5, 0.5];
}

export const css = ([r, g, b]: RGB, a = 1) =>
  `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`; // ui-lint: allow token colours re-composed for canvas

export const withAlpha = (color: string, a: number) => css(toRgb(color), a);

/** Canvas sized to its box at devicePixelRatio (capped at 2); returns a context scaled to CSS px. */
export class HiDpiCanvas {
  readonly ctx: CanvasRenderingContext2D;
  w = 0;
  h = 0;
  private dirty = true;

  constructor(readonly canvas: HTMLCanvasElement, onResize?: () => void) {
    this.ctx = canvas.getContext("2d")!;
    new ResizeObserver(() => {
      this.dirty = true;
      onResize?.();
    }).observe(canvas);
  }

  /** Call at the start of each draw. */
  begin(): CanvasRenderingContext2D {
    if (this.dirty) {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const r = this.canvas.getBoundingClientRect();
      this.w = Math.max(1, r.width);
      this.h = Math.max(1, r.height);
      this.canvas.width = Math.round(this.w * dpr);
      this.canvas.height = Math.round(this.h * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.dirty = false;
    }
    this.ctx.clearRect(0, 0, this.w, this.h);
    return this.ctx;
  }
}
