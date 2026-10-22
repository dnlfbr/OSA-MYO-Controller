#!/usr/bin/env node
// myo-osc-relay: WebSocket <-> OSC/UDP for OSA MYO Controller web. Node 18+, no dependencies.
//
// Browsers can't send UDP. The web monitor sends every OSC packet as one binary WebSocket
// message; this relay sends it on, unchanged, as one UDP datagram to the OSC target
// (127.0.0.1:7400 by default, the same port as the Python bridge). Datagrams arriving on the
// control port (7401) are forwarded to every connected page, which applies /myo/<id>/vibrate,
// /zero, /lock ... like the Python bridge does.
//
// The target is fixed here on the command line, never chosen by the page, and the WebSocket
// listens on 127.0.0.1 only: a web page can't turn the relay into a UDP sender to arbitrary
// hosts. Run the Python bridge or this relay, not both: they would share the control port.
//
//   node relay/myo-osc-relay.mjs [--ws-port 8765] [--osc-host 127.0.0.1] [--osc-port 7400]
//                                [--control-port 7401] [--control-host 0.0.0.0] [--allow-origin URL]

import { startRelay } from "./relay.mjs";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => {
    if (a.startsWith("--")) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith("--") ? all[i + 1] : "1"]);
    return acc;
  }, []),
);
if (args.help || args.h) {
  console.log("usage: node relay/myo-osc-relay.mjs [--ws-port 8765] [--osc-host 127.0.0.1] [--osc-port 7400]\n" +
    "                                   [--control-port 7401|0] [--control-host 0.0.0.0] [--allow-origin URL]");
  process.exit(0);
}
startRelay({
  wsPort: Number(args["ws-port"] ?? 8765),
  oscHost: args["osc-host"] ?? "127.0.0.1",
  oscPort: Number(args["osc-port"] ?? 7400),
  controlPort: Number(args["control-port"] ?? 7401),
  controlHost: args["control-host"] ?? "0.0.0.0",
  allowOrigin: args["allow-origin"] ?? "",
}).catch((e) => {
  console.error(e.message);
  process.exit(1);
});
