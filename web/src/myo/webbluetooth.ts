/** Web Bluetooth transport (Chrome, Edge, Opera; desktop and Android).
 *
 * The browser counterpart of transport/bleak_transport.py. Two browser rules shape it:
 * - the band is chosen in Chrome's device chooser, which only opens from a click
 *   (WebBluetoothTransport.request), and only the services named there are reachable later;
 * - Chrome runs one GATT operation at a time per device and rejects the next one with
 *   "GATT operation already in progress", so every read/write/subscribe goes through a queue.
 * Reconnecting to an already chosen band needs no click: device.gatt.connect() again. */

import { ALL_SERVICES, SERVICE_OF, UUIDS } from "./protocol";
import { TransportError, type DisconnectCallback, type NotifyCallback, type Transport } from "./transport";

export const webBluetoothAvailable = (): boolean =>
  typeof navigator !== "undefined" && "bluetooth" in navigator && window.isSecureContext;

/** Why Web Bluetooth can't be used here, or "" when it can. */
export function webBluetoothProblem(): string {
  if (typeof window === "undefined") return "no browser";
  if (!window.isSecureContext) return "the page must be served over HTTPS or from localhost";
  if (!("bluetooth" in navigator))
    return "this browser has no Web Bluetooth: use Chrome or Edge on macOS, Windows, Linux or Android";
  return "";
}

export class WebBluetoothTransport implements Transport {
  readonly backendName = "webbluetooth";
  private server: BluetoothRemoteGATTServer | null = null;
  private chars = new Map<string, BluetoothRemoteGATTCharacteristic>();
  private queue: Promise<unknown> = Promise.resolve();
  private onDisconnect: DisconnectCallback | undefined;
  private closing = false;

  constructor(readonly device: BluetoothDevice) {
    device.addEventListener("gattserverdisconnected", () => this.handleDisconnect());
  }

  /** Open Chrome's chooser, filtered to Myo armbands. Must run inside a click handler. */
  static async request(): Promise<WebBluetoothTransport> {
    const problem = webBluetoothProblem();
    if (problem) throw new TransportError(problem);
    try {
      const device = await navigator.bluetooth.requestDevice({
        // a Myo advertises its control service; the name filter catches bands that don't
        filters: [{ services: [UUIDS.CONTROL_SERVICE] }, { namePrefix: "Myo" }],
        optionalServices: ALL_SERVICES,
      });
      return new WebBluetoothTransport(device);
    } catch (e) {
      const err = e as DOMException;
      if (err?.name === "NotFoundError") throw new TransportError("no armband chosen");
      throw new TransportError(err?.message ?? String(e));
    }
  }

  get isConnected(): boolean {
    return !!this.server?.connected;
  }

  get address(): string {
    return this.device.id;
  }

  async connect(onDisconnect?: DisconnectCallback, timeoutS = 20): Promise<void> {
    this.onDisconnect = onDisconnect;
    this.closing = false;
    this.chars.clear();
    const gatt = this.device.gatt;
    if (!gatt) throw new TransportError("this device has no GATT server");
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new TransportError(`connect timed out after ${timeoutS} s`)), timeoutS * 1000);
      });
      this.server = await Promise.race([gatt.connect(), timeout]);
    } catch (e) {
      if (gatt.connected) gatt.disconnect();
      throw e instanceof TransportError ? e : new TransportError(`connect failed: ${(e as Error).message}`);
    } finally {
      clearTimeout(timer);
    }
  }

  async disconnect(): Promise<void> {
    this.closing = true;
    this.chars.clear();
    if (this.device.gatt?.connected) this.device.gatt.disconnect();
    this.server = null;
  }

  private handleDisconnect(): void {
    this.chars.clear();
    this.server = null;
    if (!this.closing) this.onDisconnect?.();
  }

  /** Serialise GATT operations: Chrome allows one in flight per device. */
  private op<T>(fn: () => Promise<T>): Promise<T> {
    const run = async () => {
      try {
        return await fn();
      } catch (e) {
        if (e instanceof TransportError) throw e;
        throw new TransportError((e as Error)?.message ?? String(e));
      }
    };
    const p = this.queue.then(run, run);
    this.queue = p.catch(() => undefined);
    return p;
  }

  private async char(uuid: string): Promise<BluetoothRemoteGATTCharacteristic> {
    const cached = this.chars.get(uuid);
    if (cached) return cached;
    if (!this.server?.connected) throw new TransportError("not connected");
    const serviceUuid = SERVICE_OF[uuid];
    if (!serviceUuid) throw new TransportError(`unknown characteristic ${uuid}`);
    const service = await this.server.getPrimaryService(serviceUuid);
    const c = await service.getCharacteristic(uuid);
    this.chars.set(uuid, c);
    return c;
  }

  read(uuid: string): Promise<DataView> {
    return this.op(async () => (await this.char(uuid)).readValue());
  }

  write(uuid: string, data: Uint8Array, response = true): Promise<void> {
    return this.op(async () => {
      const c = await this.char(uuid);
      const buf = Uint8Array.from(data); // a copy on its own ArrayBuffer (BufferSource)
      if (response) await c.writeValueWithResponse(buf);
      else await c.writeValueWithoutResponse(buf);
    });
  }

  subscribe(uuid: string, callback: NotifyCallback): Promise<void> {
    return this.op(async () => {
      const c = await this.char(uuid);
      c.addEventListener("characteristicvaluechanged", (ev) => {
        const value = (ev.target as BluetoothRemoteGATTCharacteristic).value;
        if (value) callback(value);
      });
      await c.startNotifications(); // also handles indications (classifier, motion)
    });
  }

  async getName(): Promise<string | null> {
    return this.device.name ?? null;
  }

  async getRssi(): Promise<number | null> {
    return null; // Web Bluetooth exposes no RSSI for a connected device
  }
}
