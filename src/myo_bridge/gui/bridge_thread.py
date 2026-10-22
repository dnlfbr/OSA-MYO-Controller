"""Runs the asyncio Bridge (bleak + OSC) on a background thread. The GUI only talks to it
through ``call()`` (schedules a coroutine) and by reading the slots' deques/attributes."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Coroutine

from myo_bridge.config import AppConfig
from myo_bridge.engine import Bridge, make_backend
from myo_bridge.osc.server import OscControlServer

log = logging.getLogger(__name__)


class BridgeThread:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        factory, scanner = make_backend(config.transport, config)
        self.bridge = Bridge(config, factory, scanner)
        self.server: OscControlServer | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._run, name="osa-myo-loop", daemon=True)
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._thread.start()
        self._ready.wait(5.0)

    def _run(self) -> None:
        asyncio.run(self._main())

    async def _main(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        if self.config.osc_in.enabled:
            self.server = OscControlServer(self.bridge, self.config.osc_in.host, self.config.osc_in.port)
            try:
                await self.server.start()
            except OSError as e:
                log.warning("OSC control server not started: %s", e)
                self.server = None
        self.bridge.loop = self.loop
        self._ready.set()
        try:
            await self._stop.wait()
        finally:
            if self.server:
                await self.server.stop()
            await self.bridge.disconnect_all()

    def stop(self, timeout: float = 8.0) -> None:
        if self.loop and self._stop:
            self.loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout)

    # ------------------------------------------------------------------ calls
    def call(self, coro: Coroutine) -> concurrent.futures.Future:
        if not self.loop:
            raise RuntimeError("bridge loop not running")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def call_soon(self, fn, *args) -> None:
        if self.loop:
            self.loop.call_soon_threadsafe(fn, *args)
