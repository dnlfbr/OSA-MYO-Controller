"""Inbound OSC control server (python-osc, asyncio UDP)."""

from __future__ import annotations

import asyncio
import logging

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer

from myo_bridge.myo import protocol as P
from myo_bridge.transport.base import TransportError

log = logging.getLogger(__name__)


class OscControlServer:
    """Listens for /myo/<id|all>/<command> and applies it to the bridge's devices."""

    def __init__(self, bridge, host: str = "0.0.0.0", port: int = 7401) -> None:
        self.bridge = bridge
        self.host, self.port = host, port
        self._transport = None
        self._server: AsyncIOOSCUDPServer | None = None
        self.received = 0
        d = Dispatcher()
        d.map("/myo/*/vibrate", self._h("vibrate"))
        d.map("/myo/*/lock", self._h("lock"))
        d.map("/myo/*/unlock", self._h("unlock"))
        d.map("/myo/*/zero", self._h("zero"))
        d.map("/myo/*/zero/clear", self._h("zero_clear"))
        d.map("/myo/*/mode", self._h("mode"))
        d.map("/myo/*/sleep", self._h("sleep"))
        d.map("/myo/*/led", self._h("led"))
        d.map("/myo/*/action", self._h("action"))
        d.map("/myo/*/resync", self._h("resync"))
        d.map("/myo/*/poweroff", self._h("poweroff"))
        # MyoMapper-style calibrate
        d.map("/myo*/Yaw/calibrate", self._h("zero"))
        d.set_default_handler(self._unknown)
        self.dispatcher = d

    @staticmethod
    def _device_id(address: str) -> int | None:
        parts = address.strip("/").split("/")
        tok = parts[1] if len(parts) > 1 and parts[0] == "myo" else parts[0][3:]
        if tok == "all" or tok == "":
            return None
        try:
            return int(tok)
        except ValueError:
            return None

    def _h(self, name: str):
        def handler(address: str, *args):
            self.received += 1
            did = self._device_id(address)
            asyncio.create_task(self._apply(name, did, args))
        return handler

    def _unknown(self, address: str, *args) -> None:
        log.info("OSC control: unknown address %s %s", address, args)

    async def _apply(self, name: str, did: int | None, args: tuple) -> None:
        b = self.bridge
        try:
            if name == "zero":
                await b.zero(did, "OSC")
                return
            if name == "zero_clear":
                await b.clear_zero(did)
                return
            if name == "resync":
                await b.resync(did)
                return
            if name == "poweroff":  # needs the argument 1, so a stray message can't switch bands off
                if args and int(args[0]) == 1:
                    await b.power_off(did)
                else:
                    log.info("OSC control: poweroff ignored (send it with the argument 1)")
                return
            for slot in b.targets(did):
                dev = slot.device
                if not dev.transport.is_connected:
                    continue
                if name == "vibrate":
                    kind = int(args[0]) if args else 1
                    if kind in (1, 2, 3):
                        await dev.vibrate(P.VibrationType(kind))
                    elif kind > 3:  # treat as duration ms at full strength
                        await dev.vibrate2([(min(65535, kind), 255)])
                elif name == "lock":
                    await dev.lock()
                elif name == "unlock":
                    kind = int(args[0]) if args else 2
                    await dev.unlock(P.UnlockType(kind if kind in (0, 1, 2) else 2))
                elif name == "mode" and len(args) >= 3:
                    await dev.set_mode(int(args[0]), int(args[1]), int(args[2]))
                elif name == "sleep":
                    await dev.set_sleep_mode(P.SleepMode(1 if args and int(args[0]) else 0))
                elif name == "led" and len(args) >= 3:
                    rgb = tuple(int(v) for v in args[:3])
                    bar = tuple(int(v) for v in args[3:6]) if len(args) >= 6 else rgb
                    await dev.set_led(rgb, bar)  # type: ignore[arg-type]
                elif name == "action":
                    await dev.user_action()
        except (TransportError, ValueError) as e:
            log.warning("OSC control %s failed: %s", name, e)

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._server = AsyncIOOSCUDPServer((self.host, self.port), self.dispatcher, loop)
        self._transport, _ = await self._server.create_serve_endpoint()
        log.info("OSC control server listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None
