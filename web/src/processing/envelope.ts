/** Per-channel RMS envelope with an O(1) running-sum ring buffer (port of processing/envelope.py). */

export class RmsEnvelope {
  window = 1;
  private buf: Float64Array[] = [];
  private sum: Float64Array;
  private idx = 0;
  private count = 0;

  constructor(readonly channels = 8, windowSamples = 10) {
    this.sum = new Float64Array(channels);
    this.setWindow(windowSamples);
  }

  setWindow(windowSamples: number): void {
    const n = Math.max(1, Math.trunc(windowSamples));
    this.window = n;
    this.buf = Array.from({ length: this.channels }, () => new Float64Array(n));
    this.sum = new Float64Array(this.channels);
    this.idx = 0;
    this.count = 0;
  }

  /** sample: 8 normalised values (-1..1). */
  push(sample: ArrayLike<number>): void {
    const i = this.idx;
    for (let ch = 0; ch < this.channels; ch++) {
      const sq = sample[ch] * sample[ch];
      this.sum[ch] += sq - this.buf[ch][i];
      this.buf[ch][i] = sq;
    }
    this.idx = (i + 1) % this.window;
    if (this.count < this.window) this.count++;
  }

  get values(): number[] {
    const n = this.count || 1;
    return Array.from(this.sum, (s) => Math.sqrt(Math.max(0, s / n)));
  }

  get mean(): number {
    const v = this.values;
    return v.reduce((a, b) => a + b, 0) / v.length;
  }

  reset(): void {
    this.setWindow(this.window);
  }
}
