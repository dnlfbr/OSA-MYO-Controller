/** Transport: the link to one armband (port of transport/base.py, browser flavour).
 *
 * Unlike the Python transports there is no scanner: in the browser the band is picked in
 * Chrome's own device chooser (requestDevice, needs a click), so a transport is created already
 * bound to one device and connect() takes no address. */

export class TransportError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TransportError";
  }
}

export type NotifyCallback = (data: DataView) => void;
export type DisconnectCallback = () => void;

export interface Transport {
  readonly backendName: string; // "webbluetooth" | "mock"
  readonly isConnected: boolean;
  readonly address: string; // a stable id for the band (Web Bluetooth: device.id)
  connect(onDisconnect?: DisconnectCallback, timeoutS?: number): Promise<void>;
  disconnect(): Promise<void>;
  read(uuid: string): Promise<DataView>;
  write(uuid: string, data: Uint8Array, response?: boolean): Promise<void>;
  subscribe(uuid: string, callback: NotifyCallback): Promise<void>;
  getName(): Promise<string | null>;
  /** Signal strength of the link; null where the backend can't measure it (Web Bluetooth). */
  getRssi(): Promise<number | null>;
}

/** Minimal multicast callback list; a listener must never kill the data path. */
export class Signal<A extends unknown[]> {
  private cbs: Array<(...args: A) => void> = [];

  connect(cb: (...args: A) => void): () => void {
    this.cbs.push(cb);
    return () => this.disconnect(cb);
  }

  disconnect(cb: (...args: A) => void): void {
    const i = this.cbs.indexOf(cb);
    if (i >= 0) this.cbs.splice(i, 1);
  }

  get size(): number {
    return this.cbs.length;
  }

  emit(...args: A): void {
    for (const cb of this.cbs) {
      try {
        cb(...args);
      } catch (e) {
        console.error("listener failed", e);
      }
    }
  }
}

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Seconds on a monotonic clock, like time.monotonic() in the Python code. */
export const monotonic = () => performance.now() / 1000;
