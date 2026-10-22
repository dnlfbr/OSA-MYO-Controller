// The test kit's app: serves the built page on http://127.0.0.1:5180 (Web Bluetooth needs
// localhost or HTTPS), runs the OSC relay in the same process, opens Chrome, and quits by itself a
// few seconds after the last page is closed. Also serves the OSC monitor page (monitor.html),
// which listens on the OSC port only while it is open.
//
// Compiled with Deno into OSA-MYO-Controller-Web.app / .exe (kit/main.mjs, scripts/make-kit.mjs);
// kit/serve.mjs runs the same thing from web/dist under Node. Node APIs only.
//
//   OSA-MYO-Controller-Web [--port 5180] [--no-relay] [--no-open] [--stay]
//                [--osc-host 127.0.0.1] [--osc-port 7400] [--ws-port 8765] [--control-port 7401]

import { spawn } from "node:child_process";
import dgram from "node:dgram";
import http from "node:http";
import path from "node:path";

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
  ".woff2": "font/woff2", ".png": "image/png", ".svg": "image/svg+xml", ".json": "application/json",
  ".txt": "text/plain; charset=utf-8", ".ico": "image/x-icon",
};
const FIRST_PAGE_S = 180; // no page within this time after start: quit
const LAST_PAGE_S = 8; // after the last page closes (a reload reconnects well within this)
const APP_ID = "osa-myo-web-kit";

function parseArgs(argv) {
  const o = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) continue;
    const next = argv[i + 1];
    if (next !== undefined && !next.startsWith("--")) { o[a.slice(2)] = next; i++; }
    else o[a.slice(2)] = true;
  }
  return o;
}

/** A message the user sees even with no terminal: a dialog on macOS and Windows. */
function alertUser(title, text) {
  console.error(`${title}: ${text}`);
  const q = (s) => s.replace(/["\\]/g, "'");
  try {
    if (process.platform === "darwin") {
      spawn("osascript", ["-e", `display alert "${q(title)}" message "${q(text)}"`], { stdio: "ignore", detached: true }).unref();
    } else if (process.platform === "win32") {
      const ps = `Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show("${q(text)}", "${q(title)}")`;
      spawn("powershell", ["-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], { stdio: "ignore", detached: true, windowsHide: true }).unref();
    }
  } catch {
    // nothing else we can do
  }
}

function openBrowser(url, log) {
  const tries = process.platform === "darwin"
    ? [["open", ["-a", "Google Chrome", url]], ["open", ["-a", "Microsoft Edge", url]], ["open", [url]]]
    : process.platform === "win32"
      ? [["cmd", ["/c", "start", "", "chrome", url]], ["cmd", ["/c", "start", "", "msedge", url]], ["cmd", ["/c", "start", "", url]]]
      : [["google-chrome", [url]], ["chromium", [url]], ["xdg-open", [url]]];
  const next = (i) => {
    if (i >= tries.length) {
      alertUser("OSA MYO Controller web", `Open ${url} in Chrome or Edge.`);
      return;
    }
    const [cmd, args] = tries[i];
    let c;
    try {
      c = spawn(cmd, args, { stdio: "ignore", windowsHide: true });
    } catch {
      next(i + 1);
      return;
    }
    c.on("error", () => next(i + 1));
    c.on("exit", (code) => (code ? next(i + 1) : log(`browser: ${cmd} ${args.slice(0, -1).join(" ")}`)));
  };
  next(0);
}

// ------------------------------------------------------------------ OSC monitor (UDP in -> page)
function str(buf, o) {
  let e = o;
  while (e < buf.length && buf[e] !== 0) e++;
  return [buf.toString("latin1", o, e), (e + 4) & ~3];
}

function decode(buf, out) {
  if (buf.toString("latin1", 0, 8) === "#bundle\0") {
    let o = 16;
    while (o + 4 <= buf.length) {
      const n = buf.readInt32BE(o);
      decode(buf.subarray(o + 4, o + 4 + n), out);
      o += 4 + n;
    }
    return;
  }
  let [addr, o] = str(buf, 0);
  let tags = ",";
  if (o < buf.length) [tags, o] = str(buf, o);
  const args = [];
  for (const t of tags.slice(1)) {
    if (t === "i") { args.push(buf.readInt32BE(o)); o += 4; }
    else if (t === "f") { args.push(Number(buf.readFloatBE(o).toFixed(3))); o += 4; }
    else if (t === "s") { let s; [s, o] = str(buf, o); args.push(s); }
    else args.push(t);
  }
  out.push([addr, args]);
}

class OscMonitor {
  clients = new Set();
  seen = new Map(); // address -> { n, rate, last }
  state = "off"; // off | listening | busy
  error = "";
  sock = null;
  timer = undefined;
  t0 = Date.now();

  constructor(port, log) {
    this.port = port;
    this.log = log;
  }

  add(res) {
    this.clients.add(res);
    if (!this.sock) this.listen();
    this.push();
  }

  remove(res) {
    this.clients.delete(res);
    if (!this.clients.size) this.stop();
  }

  listen() {
    this.seen.clear();
    this.t0 = Date.now();
    const sock = dgram.createSocket("udp4");
    this.sock = sock;
    sock.on("message", (buf) => {
      const msgs = [];
      try { decode(buf, msgs); } catch { return; }
      for (const [addr, args] of msgs) {
        const e = this.seen.get(addr) ?? { n: 0, rate: 0, last: [] };
        e.n++;
        e.last = args;
        this.seen.set(addr, e);
      }
    });
    sock.on("error", (e) => {
      this.state = "busy";
      this.error = e.message;
      this.log(`monitor: UDP ${this.port}: ${e.message}`);
      sock.close();
      if (this.sock === sock) this.sock = null;
      this.push();
    });
    sock.bind(this.port, () => {
      this.state = "listening";
      this.log(`monitor: listening on UDP ${this.port}`);
      this.push();
    });
    this.timer = setInterval(() => this.tick(), 1000);
  }

  stop() {
    clearInterval(this.timer);
    this.sock?.close();
    this.sock = null;
    if (this.state === "listening") this.log(`monitor: stopped, UDP ${this.port} free`);
    this.state = "off";
  }

  tick() {
    const dt = Math.max(0.001, (Date.now() - this.t0) / 1000);
    this.t0 = Date.now();
    for (const e of this.seen.values()) {
      e.rate = e.n / dt;
      e.n = 0;
    }
    this.push();
  }

  push() {
    const data = JSON.stringify({
      port: this.port, state: this.state, error: this.error,
      rows: [...this.seen].sort(([a], [b]) => (a < b ? -1 : 1)).map(([addr, e]) => [addr, Number(e.rate.toFixed(1)), e.last]),
    });
    for (const res of this.clients) res.write(`data: ${data}\n\n`);
  }
}

// ------------------------------------------------------------------ the app
/** files(pathname) -> Uint8Array | null: the built page (embedded in the binary, or on disk). */
export async function run({ files, startRelay, argv = process.argv.slice(2), build = "dev" }) {
  const args = parseArgs(argv);
  const PORT = Number(args.port ?? 5180);
  const relayOpts = {
    wsPort: Number(args["ws-port"] ?? 8765),
    oscHost: String(args["osc-host"] ?? "127.0.0.1"),
    oscPort: Number(args["osc-port"] ?? 7400),
    controlPort: Number(args["control-port"] ?? 7401),
    controlHost: String(args["control-host"] ?? "0.0.0.0"),
  };
  const url = `http://127.0.0.1:${PORT}/`;

  const lines = [];
  const log = (s) => {
    const d = new Date();
    const line = `${d.toTimeString().slice(0, 8)}.${String(d.getMilliseconds()).padStart(3, "0")}  ${s}`;
    lines.push(line);
    if (lines.length > 2000) lines.splice(0, lines.length - 2000);
    console.log(line);
  };
  log(`OSA MYO Controller web kit, build ${build}, ${process.platform} ${process.arch}`);

  const monitor = new OscMonitor(relayOpts.oscPort, log);
  const alive = new Set();
  let relay = null;
  let relayError = "";
  let quitTimer;

  const quit = (why) => {
    log(`quit: ${why}`);
    relay?.close();
    monitor.stop();
    process.exit(0);
  };
  const presence = () => alive.size + monitor.clients.size;
  const armQuit = (s, why) => {
    if (args.stay) return;
    clearTimeout(quitTimer);
    quitTimer = setTimeout(() => presence() || quit(why), s * 1000);
  };

  const sse = (req, res, onOpen, onClose) => {
    res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
    res.write("retry: 1000\n\n");
    const ping = setInterval(() => res.write(": ping\n\n"), 15000);
    onOpen(res);
    req.on("close", () => {
      clearInterval(ping);
      onClose(res);
    });
  };

  const server = http.createServer((req, res) => {
    const p = decodeURIComponent(new URL(req.url ?? "/", "http://x").pathname);
    if (p === "/__kit") {
      res.writeHead(200, { "content-type": "application/json", "cache-control": "no-cache" });
      res.end(JSON.stringify({
        app: APP_ID, build, relay: relay ? "running" : relayError || "off",
        relayUrl: relay ? `ws://127.0.0.1:${relayOpts.wsPort}` : "",
        osc: `${relayOpts.oscHost}:${relayOpts.oscPort}`, control: relayOpts.controlPort,
      }));
      return;
    }
    if (p === "/__alive") {
      sse(req, res, (r) => {
        alive.add(r);
        clearTimeout(quitTimer);
        log(`page open (${alive.size})`);
      }, (r) => {
        alive.delete(r);
        log(`page closed (${alive.size})`);
        if (!presence()) armQuit(LAST_PAGE_S, "last page closed");
      });
      return;
    }
    if (p === "/__monitor") {
      sse(req, res, (r) => {
        clearTimeout(quitTimer);
        monitor.add(r);
      }, (r) => {
        monitor.remove(r);
        if (!presence()) armQuit(LAST_PAGE_S, "last page closed");
      });
      return;
    }
    if (p === "/__log") {
      res.writeHead(200, { "content-type": "text/plain; charset=utf-8", "cache-control": "no-cache" });
      res.end(lines.join("\n") + "\n");
      return;
    }
    let file = p.endsWith("/") ? `${p}index.html` : p;
    if (file === "/monitor") file = "/monitor.html";
    const body = files(file.replace(/^\/+/, ""));
    if (!body) {
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("not found");
      return;
    }
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] ?? "application/octet-stream", "cache-control": "no-cache" });
    res.end(body);
  });

  // already running (a second double-click): just open another page
  const other = await new Promise((resolve) => {
    const req = http.get(`${url}__kit`, { timeout: 1500 }, (res) => {
      let s = "";
      res.on("data", (d) => (s += d));
      res.on("end", () => {
        try { resolve(JSON.parse(s).app === APP_ID); } catch { resolve(false); }
      });
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => { req.destroy(); resolve(false); });
  });
  if (other) {
    log("already running: opening the page");
    if (!args["no-open"]) openBrowser(url, log);
    setTimeout(() => process.exit(0), 3000);
    return;
  }

  await new Promise((resolve) => {
    server.once("error", (e) => {
      const msg = e.code === "EADDRINUSE"
        ? `Port ${PORT} is used by another program. Close it and start again.`
        : e.message;
      alertUser("OSA MYO Controller web", msg);
      setTimeout(() => process.exit(1), 2000);
    });
    server.listen(PORT, "127.0.0.1", resolve);
  });
  log(`page: ${url}`);

  // the page learns the relay's address from /__kit, so a taken WebSocket port just moves on
  if (!args["no-relay"]) {
    for (let ws = relayOpts.wsPort; ws < relayOpts.wsPort + 10 && !relay; ws++) {
      try {
        relay = await startRelay({ ...relayOpts, wsPort: ws, log, error: log });
        relayOpts.wsPort = ws;
      } catch (e) {
        relayError = e.message;
        log(`relay: ${e.message}`);
      }
    }
  } else log("relay: off (--no-relay)");

  if (!args["no-open"]) openBrowser(url, log);
  armQuit(FIRST_PAGE_S, `no page opened within ${FIRST_PAGE_S} s`);

  process.on("SIGINT", () => quit("SIGINT"));
  try {
    process.on("SIGTERM", () => quit("SIGTERM"));
  } catch {
    // Windows under Deno: only SIGINT / SIGBREAK
  }
}
