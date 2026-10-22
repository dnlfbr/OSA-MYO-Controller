"""bleak backend (CoreBluetooth on macOS, BlueZ on Linux, WinRT on Windows)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from myo_bridge.myo.protocol import UUIDS
from myo_bridge.transport.base import (
    DisconnectCallback,
    NotifyCallback,
    Scanner,
    ScanResult,
    Transport,
    TransportError,
)

log = logging.getLogger(__name__)


def _looks_like_myo(name: str | None, service_uuids: list[str] | None) -> bool:
    if service_uuids and UUIDS.CONTROL_SERVICE in [u.lower() for u in service_uuids]:
        return True
    return bool(name) and "myo" in name.lower()


class BleakScannerBackend(Scanner):
    backend_name = "bleak"

    async def scan(self, timeout: float = 5.0, myo_only: bool = True) -> list[ScanResult]:
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        results: list[ScanResult] = []
        for address, (dev, adv) in found.items():
            name = adv.local_name or dev.name
            is_myo = _looks_like_myo(name, adv.service_uuids)
            if myo_only and not is_myo:
                continue
            results.append(
                ScanResult(
                    address=address,
                    name=name,
                    rssi=adv.rssi,
                    is_myo=is_myo,
                    extra={"device": dev, "service_uuids": list(adv.service_uuids)},
                )
            )
        results.sort(key=lambda r: (not r.is_myo, -(r.rssi or -999)))
        return results

    async def find(self, selector: str | None, timeout: float = 10.0) -> ScanResult | None:
        """Find a Myo by address/UUID, by (case-insensitive) name, or the strongest one if None."""
        sel = (selector or "").strip().lower()

        def match(dev: BLEDevice, adv) -> bool:
            name = adv.local_name or dev.name
            if not _looks_like_myo(name, adv.service_uuids):
                return False
            if not sel:
                return True
            return dev.address.lower() == sel or (name or "").lower() == sel

        dev = await BleakScanner.find_device_by_filter(match, timeout=timeout)
        if dev is None:
            return None
        return ScanResult(address=dev.address, name=dev.name, rssi=None, is_myo=True,
                          extra={"device": dev})


class BleakTransport(Transport):
    backend_name = "bleak"

    def __init__(self) -> None:
        self._client: BleakClient | None = None
        self._address = ""
        self._on_disconnect: DisconnectCallback | None = None
        self._subs: dict[str, NotifyCallback] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    @property
    def address(self) -> str:
        return self._address

    def _disconnected(self, _client: BleakClient) -> None:
        log.info("bleak: disconnected from %s", self._address)
        cb = self._on_disconnect
        if cb:
            cb()

    async def connect(self, address: str | BLEDevice, on_disconnect: DisconnectCallback | None = None,
                      timeout: float = 20.0) -> None:
        self._loop = asyncio.get_running_loop()
        self._on_disconnect = on_disconnect
        target = address
        self._address = address.address if isinstance(address, BLEDevice) else address
        client = BleakClient(target, disconnected_callback=self._disconnected, timeout=timeout)
        try:
            await client.connect()
        except (BleakError, asyncio.TimeoutError, OSError) as e:
            raise TransportError(f"connect to {self._address} failed: {e}") from e
        self._client = client
        log.info("bleak: connected to %s (mtu=%s)", self._address, getattr(client, "mtu_size", "?"))

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        self._on_disconnect = None  # a disconnect we asked for is not a link loss
        self._subs.clear()
        if client is None:
            return
        try:
            await client.disconnect()
        except BleakError as e:  # already gone
            log.debug("bleak: disconnect error ignored: %s", e)

    def _require(self) -> BleakClient:
        if self._client is None or not self._client.is_connected:
            raise TransportError("not connected")
        return self._client

    async def read(self, uuid: str) -> bytes:
        try:
            return bytes(await self._require().read_gatt_char(uuid))
        except BleakError as e:
            raise TransportError(f"read {uuid} failed: {e}") from e

    async def write(self, uuid: str, data: bytes, response: bool = True) -> None:
        try:
            await self._require().write_gatt_char(uuid, data, response=response)
        except BleakError as e:
            raise TransportError(f"write {uuid} failed: {e}") from e

    async def subscribe(self, uuid: str, callback: NotifyCallback) -> None:
        self._subs[uuid] = callback

        def _cb(_char, data: bytearray) -> None:
            callback(bytes(data))

        try:
            await self._require().start_notify(uuid, _cb)
        except BleakError as e:
            raise TransportError(f"subscribe {uuid} failed: {e}") from e

    async def unsubscribe(self, uuid: str) -> None:
        self._subs.pop(uuid, None)
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(uuid)
            except BleakError as e:
                log.debug("stop_notify %s: %s", uuid, e)

    async def get_rssi(self) -> int | None:
        client = self._client
        if client is None or not client.is_connected:
            return None
        backend = getattr(client, "_backend", None)
        get_rssi: Callable | None = getattr(backend, "get_rssi", None)
        if get_rssi is None:
            return None
        try:
            return int(await get_rssi())
        except Exception as e:  # noqa: BLE001 - backend specific, best effort
            log.debug("get_rssi failed: %s", e)
            return None

    async def get_name(self) -> str | None:
        try:
            return (await self.read(UUIDS.DEVICE_NAME)).decode("utf-8", "replace")
        except TransportError:
            return None
