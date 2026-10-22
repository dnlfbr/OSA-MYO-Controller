#!/usr/bin/env python3
"""Minimal OSC receiver for testing OSA MYO Controller: prints each address with its latest
values and the measured message rate. Usage: python examples/osc_receiver.py [port]"""

import sys
import time
from collections import defaultdict

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

port = int(sys.argv[1]) if len(sys.argv) > 1 else 7400
counts: dict[str, int] = defaultdict(int)
latest: dict[str, tuple] = {}
t0 = time.monotonic()
last_print = t0


def handler(address, *args):
    global last_print
    counts[address] += 1
    latest[address] = args
    now = time.monotonic()
    if now - last_print >= 1.0:
        last_print = now
        dt = now - t0
        print("\033[2J\033[H" + f"listening on :{port}   {dt:.0f}s")
        for a in sorted(latest):
            vals = " ".join(f"{v:+.3f}" if isinstance(v, float) else str(v) for v in latest[a][:8])
            print(f"{a:34} {counts[a] / dt:7.1f} msg/s  {vals}")


d = Dispatcher()
d.set_default_handler(handler)
print(f"listening on :{port} ... (Ctrl-C to stop)")
BlockingOSCUDPServer(("0.0.0.0", port), d).serve_forever()
