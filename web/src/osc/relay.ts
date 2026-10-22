/** Browser side of the OSC relay: a WebSocket to web/relay/myo-osc-relay.mjs.
 *
 * Browsers can't send UDP, so each OSC packet travels as one binary WebSocket message; the relay
 * sends it on as one UDP datagram (to 127.0.0.1:7400 by default) and forwards the datagrams it
 * receives on its control port (7401) back here. The relay picks the UDP target, not the page.
 * While the relay is down the client retries every 2 s, backing off to 10 s. */

import { decodePacket, type OscMessage } from "./osc";

export type RelayState = "off" | "connecting" | "open" | "closed";

export class RelayClient {
  state: RelayState = "off";
  sent = 0;
  dropped = 0; // packets not sent because the socket wasn't open
  received = 0;
  onState: (s: RelayState) => void = () => undefined;
  onControl: (m: OscMessage) => void = () => undefined;
  private ws: WebSocket | null = null;
  private retry: ReturnType<typeof setTimeout> | undefined;
  private wanted = false;
  private retryS = 2; // doubles up to 10 s while the relay is down

  constructor(public url = "ws://127.0.0.1:8765") {}

  private set(s: RelayState): void {
    if (s !== this.state) {
      this.state = s;
      this.onState(s);
    }
  }

  start(url = this.url): void {
    this.url = url;
    this.wanted = true;
    this.retryS = 2;
    this.open();
  }

  stop(): void {
    this.wanted = false;
    clearTimeout(this.retry);
    this.ws?.close();
    this.ws = null;
    this.set("off");
  }

  private open(): void {
    clearTimeout(this.retry);
    this.ws?.close();
    this.set("connecting");
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch {
      this.set("closed");
      return;
    }
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      this.retryS = 2;
      this.set("open");
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (!this.wanted) return;
      this.set("closed");
      this.retry = setTimeout(() => this.wanted && this.open(), this.retryS * 1000); // the relay may start later
      this.retryS = Math.min(10, this.retryS * 2);
    };
    ws.onmessage = (ev) => {
      if (!(ev.data instanceof ArrayBuffer)) return;
      this.received++;
      try {
        for (const m of decodePacket(new Uint8Array(ev.data))) this.onControl(m);
      } catch (e) {
        console.warn("relay: bad OSC packet", e);
      }
    };
    this.ws = ws;
  }

  /** A PacketSink for OscSender. */
  readonly send = (packet: Uint8Array): void => {
    const ws = this.ws;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(packet);
      this.sent++;
    } else {
      this.dropped++;
    }
  };
}
