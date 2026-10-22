// The relay itself, as a module: myo-osc-relay.mjs (command line) and the test kit's app
// (kit/launcher.mjs) both run it. See myo-osc-relay.mjs for what it does and why.

import { createHash } from "node:crypto";
import dgram from "node:dgram";
import http from "node:http";

const MAX_FRAME = 64 * 1024; // OSC packets from the page are small; refuse anything absurd
const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

/** Starts the relay; resolves once the WebSocket listens, rejects if its port is taken. A taken
 * control port is only reported: OSC out still works. */
export function startRelay({
  wsPort = 8765, oscHost = "127.0.0.1", oscPort = 7400, controlPort = 7401, controlHost = "0.0.0.0",
  allowOrigin = "", log = console.log, error = console.error,
} = {}) {
  const WS_PORT = wsPort, OSC_HOST = oscHost, OSC_PORT = oscPort;
  const CONTROL_PORT = controlPort; // 0 = no control input
  const CONTROL_HOST = controlHost;
  const ALLOW_ORIGIN = allowOrigin; // "" = any page may connect (it can only send to OSC_HOST)
  const udp = dgram.createSocket("udp4");
  const clients = new Set();
  const stats = { in: 0, out: 0, control: 0 };

  // ------------------------------------------------------------------ WebSocket (RFC 6455, minimal)
  function sendFrame(sock, opcode, payload) {
    const n = payload.length;
    const head = n < 126 ? Buffer.from([0x80 | opcode, n])
      : n < 65536 ? Buffer.from([0x80 | opcode, 126, n >> 8, n & 255])
      : (() => { const b = Buffer.alloc(10); b[0] = 0x80 | opcode; b[1] = 127; b.writeBigUInt64BE(BigInt(n), 2); return b; })();
    sock.write(Buffer.concat([head, payload]));
  }

  function attach(sock) {
    let buf = Buffer.alloc(0);
    let fragments = [];
    let fragOpcode = 0;
    clients.add(sock);
    log(`page connected (${clients.size} open)`);

    sock.on("data", (chunk) => {
      buf = Buffer.concat([buf, chunk]);
      for (;;) {
        if (buf.length < 2) return;
        const fin = (buf[0] & 0x80) !== 0;
        const opcode = buf[0] & 0x0f;
        const masked = (buf[1] & 0x80) !== 0;
        let len = buf[1] & 0x7f;
        let o = 2;
        if (len === 126) { if (buf.length < 4) return; len = buf.readUInt16BE(2); o = 4; }
        else if (len === 127) { if (buf.length < 10) return; len = Number(buf.readBigUInt64BE(2)); o = 10; }
        if (len > MAX_FRAME) { sock.destroy(); return; }
        const maskLen = masked ? 4 : 0;
        if (buf.length < o + maskLen + len) return;
        const mask = masked ? buf.subarray(o, o + 4) : null;
        const payload = Buffer.from(buf.subarray(o + maskLen, o + maskLen + len));
        if (mask) for (let i = 0; i < payload.length; i++) payload[i] ^= mask[i & 3];
        buf = buf.subarray(o + maskLen + len);

        if (opcode === 0x8) { sendFrame(sock, 0x8, Buffer.alloc(0)); sock.end(); return; } // close
        if (opcode === 0x9) { sendFrame(sock, 0xa, payload); continue; } // ping -> pong
        if (opcode === 0xa) continue; // pong
        if (opcode === 0x1 || opcode === 0x2 || opcode === 0x0) {
          if (opcode !== 0x0) fragOpcode = opcode;
          fragments.push(payload);
          if (!fin) continue;
          const packet = Buffer.concat(fragments);
          fragments = [];
          if (fragOpcode !== 0x2) continue; // text frames: not OSC, ignored
          stats.in++;
          udp.send(packet, OSC_PORT, OSC_HOST, (err) => { if (!err) stats.out++; });
        }
      }
    });
    const drop = () => { if (clients.delete(sock)) log(`page disconnected (${clients.size} open)`); };
    sock.on("close", drop);
    sock.on("error", drop);
  }

  const server = http.createServer((req, res) => {
    res.writeHead(200, { "content-type": "text/plain" });
    res.end(`myo-osc-relay: OSC out ${OSC_HOST}:${OSC_PORT}, control in :${CONTROL_PORT || "off"}\n` +
      `packets in ${stats.in}, datagrams out ${stats.out}, control ${stats.control}\n`);
  });

  server.on("upgrade", (req, sock) => {
    const key = req.headers["sec-websocket-key"];
    const origin = req.headers.origin ?? "";
    if (!key || (req.headers.upgrade ?? "").toLowerCase() !== "websocket") { sock.destroy(); return; }
    if (ALLOW_ORIGIN && origin !== ALLOW_ORIGIN) {
      sock.end("HTTP/1.1 403 Forbidden\r\n\r\n");
      log(`refused page from ${origin || "(no origin)"}`);
      return;
    }
    const accept = createHash("sha1").update(key + WS_GUID).digest("base64");
    sock.write("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
      `Sec-WebSocket-Accept: ${accept}\r\n\r\n`);
    sock.setNoDelay(true);
    attach(sock);
  });

  // ------------------------------------------------------------------ control in: UDP -> pages
  // bound only once the WebSocket listens, so a failed start leaves the port free for a retry
  let control = null;
  const bindControl = () => {
    if (!CONTROL_PORT) return;
    const sock = dgram.createSocket("udp4");
    control = sock;
    sock.on("message", (msg) => {
      stats.control++;
      for (const s of clients) sendFrame(s, 0x2, msg);
    });
    sock.on("error", (e) => {
      error(`control port ${CONTROL_PORT}: ${e.message} (is the Python bridge running? use --control-port 0)`);
      sock.close();
      if (control === sock) control = null;
    });
    sock.bind(CONTROL_PORT, CONTROL_HOST);
  };

  return new Promise((resolve, reject) => {
    server.once("error", (e) => {
      udp.close();
      reject(new Error(`WebSocket port ${WS_PORT}: ${e.message}`));
    });
    server.listen(WS_PORT, "127.0.0.1", () => {
      bindControl();
      log(`myo-osc-relay  ws://127.0.0.1:${WS_PORT}  ->  OSC ${OSC_HOST}:${OSC_PORT}` +
        (CONTROL_PORT ? `   control in :${CONTROL_PORT}` : ""));
      resolve({
        stats,
        pages: () => clients.size,
        close() {
          for (const s of clients) s.destroy();
          server.close();
          control?.close();
          udp.close();
        },
      });
    });
  });
}
