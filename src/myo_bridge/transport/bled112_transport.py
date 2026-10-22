"""Transport over a Bluegiga BLED112 USB dongle (BGAPI over a virtual serial port).

Why: CoreBluetooth hides MAC addresses and sometimes keeps a stale pairing to a Myo; the dongle
gives you the real MAC, a second independent radio, and works on any OS. pyomyo, MioConnect and
Myo Connect's own SDK path all used this dongle.

One ``Dongle`` per serial port is shared by the scanner and every transport (the BLED112
handles several connections, each identified by a connection handle). A reader thread
de-frames packets and hands them to the asyncio loop; commands are serialised with a lock
because BGAPI answers each command with exactly one response. ATT procedures (read, write,
find information) are serialised per connection, because the stack runs one at a time, and
every waiter is registered before its command is sent so a fast event can't be missed.

Not hardware-verified in this repository: written from the BGAPI reference and the Myo
implementations listed in the README, and exercised against a simulated dongle in
tests/test_bled112.py. See docs/hardware-tests.md.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable

from myo_bridge.myo.protocol import UUIDS
from myo_bridge.transport import bgapi as B
from myo_bridge.transport.base import (
    DisconnectCallback,
    NotifyCallback,
    Scanner,
    ScanResult,
    Transport,
    TransportError,
)

log = logging.getLogger(__name__)

_dongles: dict[str, Dongle] = {}

BLED112_VID_PID = (0x2458, 0x0001)


def _pyserial_missing() -> TransportError:
    return TransportError("pyserial is not installed: pip install 'osa-myo-controller[dongle]'")


def list_serial_ports() -> list[tuple[str, str, bool]]:
    """Serial ports as (device, description, looks_like_bled112), likely dongles first."""
    try:
        from serial.tools import list_ports
    except ImportError as e:  # pragma: no cover
        raise _pyserial_missing() from e
    out = []
    for p in list_ports.comports():
        if os.name == "posix" and p.device.startswith("/dev/tty."):
            continue  # macOS lists tty.* and cu.*; cu.* is the one to open
        likely = (p.vid, p.pid) == BLED112_VID_PID or "BLED112" in (p.description or "") \
            or "Bluegiga" in (p.manufacturer or "") or "Low Energy Dongle" in (p.description or "")
        desc = p.description if p.description and p.description != "n/a" else (p.manufacturer or "")
        out.append((p.device, desc, likely))
    out.sort(key=lambda r: (not r[2], r[0]))
    return out


def find_port() -> str | None:
    """Return the first serial port that looks like a BLED112 (macOS: /dev/cu.usbmodem*)."""
    ports = list_serial_ports()
    for dev, _desc, likely in ports:
        if likely:
            return dev
    for dev, _desc, _likely in ports:
        if "usbmodem" in dev:  # macOS CDC naming
            return dev
    return None


def open_serial(port: str):
    """Open the dongle's serial port (replaced by a simulated dongle in the tests)."""
    try:
        import serial
    except ImportError as e:  # pragma: no cover
        raise _pyserial_missing() from e
    # exclusive: a second app (or a second copy of this one) can't steal the dongle mid-show
    return serial.Serial(port, 115200, timeout=0.05, exclusive=True if os.name == "posix" else None)


def get_dongle(port: str | None) -> Dongle:
    port = port or find_port()
    if not port:
        raise TransportError("no BLED112 dongle found: plug it in, or choose its port in Settings")
    d = _dongles.get(port)
    if d is None:
        d = _dongles[port] = Dongle(port)
    return d


def close_all() -> None:
    """Release every dongle's serial port (when switching back to the built-in Bluetooth)."""
    for d in list(_dongles.values()):
        d.close()
    _dongles.clear()


class Dongle:
    MAX_CONNECTIONS = 3  # stock BLED112 firmware

    def __init__(self, port: str) -> None:
        self.port = port
        self._ser = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._cmd_lock = asyncio.Lock()
        self._open_lock = asyncio.Lock()
        # one GAP procedure at a time: the dongle refuses to scan while connecting and vice versa
        self.gap_lock = asyncio.Lock()
        self._response: asyncio.Future | None = None
        self._response_key: tuple[int, int] | None = None
        self._event_handlers: dict[tuple[int, int], list[Callable[[B.Packet], None]]] = {}
        self._scan_listeners: list[Callable[[B.ScanResponse], None]] = []
        self.connections: dict[int, Bled112Transport] = {}
        self.address_types: dict[str, int] = {}  # from scans: 0 public, 1 random

    @property
    def is_open(self) -> bool:
        return self._ser is not None

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        assert self._loop is not None
        return self._loop

    # ------------------------------------------------------------------ serial
    async def open(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:  # first use, or the previous event loop is gone
            self.close()
            self.connections.clear()
            self._loop = loop
            self._cmd_lock = asyncio.Lock()
            self._open_lock = asyncio.Lock()
            self.gap_lock = asyncio.Lock()
        async with self._open_lock:
            if self._ser is not None:
                return
            try:
                ser = open_serial(self.port)
            except TransportError:
                raise
            except Exception as e:
                busy = any(w in str(e).lower() for w in ("busy", "lock"))  # EBUSY, or exclusive=True
                raise TransportError(f"cannot open {self.port}: {e}" + (
                    " (in use by another program: Myo Connect, or another copy of OSA MYO Controller?)"
                    if busy else "")) from e
            self._ser = ser
            self._thread = threading.Thread(target=self._reader, args=(ser,), name="bled112-reader",
                                            daemon=True)
            self._thread.start()
            try:
                # clean slate: stop any scan/advertising and drop links left by a previous run
                # (the dongle keeps connections alive as long as it is powered)
                await self.command(B.gap_end_procedure())
                await self.command(B.gap_set_mode(0, 0))
                for h in range(self.MAX_CONNECTIONS):
                    await self.command(B.connection_disconnect(h))
            except TransportError:
                self.close()
                raise TransportError(f"{self.port} does not answer like a BLED112 dongle") from None
            log.info("BLED112 open on %s", self.port)

    def close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception as e:  # noqa: BLE001
                log.debug("closing %s: %s", self.port, e)

    def _reader(self, ser) -> None:
        parser = B.Parser()  # per port opening: a stale thread can't garble a reopened stream
        while self._ser is ser:
            try:
                data = ser.read(256)
            except Exception as e:  # noqa: BLE001 - unplugged, or closed under our feet
                if self._ser is ser and self._loop and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._on_reader_failed, str(e))
                return
            if not data:
                continue
            for pkt in parser.feed(data):
                if self._loop and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._dispatch, pkt)

    def _on_reader_failed(self, err: str) -> None:
        log.error("BLED112 on %s stopped: %s", self.port, err)
        self.close()
        fut = self._response
        if fut is not None and not fut.done():
            fut.set_exception(TransportError(f"BLED112 on {self.port} stopped: {err}"))
        for t in list(self.connections.values()):
            t._link_lost()

    # ------------------------------------------------------------------ dispatch
    def _dispatch(self, pkt: B.Packet) -> None:
        if not pkt.is_event:
            fut = self._response
            if fut is not None and not fut.done() and pkt.key == self._response_key:
                fut.set_result(pkt)
            return
        if pkt.key == B.EVT_GAP_SCAN_RESPONSE:
            try:
                sr = B.parse_scan_response(pkt.payload)
            except Exception:  # noqa: BLE001 - malformed advertisement
                return
            self.address_types[sr.address] = sr.address_type
            for cb in list(self._scan_listeners):
                cb(sr)
            return
        for cb in list(self._event_handlers.get(pkt.key, ())):
            try:
                cb(pkt)
            except Exception:  # a bad packet must not stop the dispatcher
                log.exception("BLED112 event handler failed")

    def on_event(self, key: tuple[int, int], cb: Callable[[B.Packet], None]) -> None:
        self._event_handlers.setdefault(key, []).append(cb)

    def off_event(self, key: tuple[int, int], cb: Callable[[B.Packet], None]) -> None:
        try:
            self._event_handlers.get(key, []).remove(cb)
        except ValueError:
            pass

    def expect(self, key: tuple[int, int], match: Callable[[B.Packet], object]) -> tuple[asyncio.Future, Callable]:
        """Register a waiter now (before sending the command that triggers the event).
        ``match`` returns a falsy value to keep waiting, True to resolve with the packet, any
        other value to resolve with it, or raises to fail. Returns (future, unregister)."""
        fut = self.loop.create_future()

        def cb(p: B.Packet) -> None:
            if fut.done():
                return
            try:
                r = match(p)
            except Exception as e:  # noqa: BLE001 - handed to the waiter
                fut.set_exception(e)
                return
            if r is True:
                fut.set_result(p)
            elif r:
                fut.set_result(r)
        self.on_event(key, cb)
        return fut, lambda: self.off_event(key, cb)

    async def command(self, frame: bytes, timeout: float = 2.0) -> B.Packet:
        """Send one command and wait for its response (same class/id, type 0)."""
        if self._ser is None:
            raise TransportError("dongle not open")
        async with self._cmd_lock:
            if self._ser is None:
                raise TransportError("dongle not open")
            self._response = self.loop.create_future()
            self._response_key = (frame[2], frame[3])
            try:
                self._ser.write(frame)
                return await asyncio.wait_for(self._response, timeout)
            except TimeoutError as e:
                raise TransportError(f"BLED112 command {self._response_key} timed out") from e
            except Exception as e:  # serial write failed (unplugged)
                if isinstance(e, TransportError):
                    raise
                raise TransportError(f"BLED112 write failed: {e}") from e
            finally:
                self._response = None

    # ------------------------------------------------------------------ scanning
    async def scan(self, timeout: float, myo_only: bool,
                   until: Callable[[ScanResult], bool] | None = None) -> list[ScanResult]:
        """Scan for ``timeout`` seconds, or until ``until`` accepts a result. Strongest first."""
        await self.open()
        seen: dict[str, ScanResult] = {}
        hit = asyncio.Event()

        def on_sr(sr: B.ScanResponse) -> None:
            addr = sr.address
            r = seen.get(addr)
            name = sr.name
            uuids = sr.service_uuids
            is_myo = any(u.lower() == UUIDS.CONTROL_SERVICE.lower() for u in uuids) or \
                bool(name and "myo" in name.lower())
            if r is None:
                r = seen[addr] = ScanResult(addr, name, sr.rssi, is_myo,
                                            {"address_type": sr.address_type, "backend": "bled112"})
            else:
                r.rssi = sr.rssi
                r.is_myo = r.is_myo or is_myo
                if name and not r.name:
                    r.name = name
            if until is not None and (r.is_myo or not myo_only) and until(r):
                hit.set()

        async with self.gap_lock:
            self._scan_listeners.append(on_sr)
            try:
                await self.command(B.gap_set_scan_parameters(active=True))
                # observation: every advertiser, whatever its discoverable flags (we filter ourselves)
                resp = await self.command(B.gap_discover(2))
                result = int.from_bytes(resp.payload[0:2], "little")
                if result:
                    raise TransportError(f"BLED112 scan failed: {B.error_name(result)}")
                try:
                    await asyncio.wait_for(hit.wait(), timeout)
                except TimeoutError:
                    pass
            finally:
                self._scan_listeners.remove(on_sr)
                if self.is_open:
                    try:
                        await self.command(B.gap_end_procedure())
                    except TransportError:
                        pass
        out = [r for r in seen.values() if r.is_myo or not myo_only]
        out.sort(key=lambda r: -(r.rssi if r.rssi is not None else -999))
        return out


class Bled112Scanner(Scanner):
    backend_name = "bled112"

    def __init__(self, port: str | None = None) -> None:
        self.port = port

    async def scan(self, timeout: float = 5.0, myo_only: bool = True) -> list[ScanResult]:
        return await get_dongle(self.port).scan(timeout, myo_only)

    async def find(self, selector: str | None, timeout: float = 10.0) -> ScanResult | None:
        """A Myo by MAC address or (case-insensitive) name, as soon as it is seen; with no
        selector, the strongest Myo heard in a short scan."""
        sel = (selector or "").strip().lower()

        def match(r: ScanResult) -> bool:
            return not sel or r.address.lower() == sel or (r.name or "").lower() == sel
        d = get_dongle(self.port)
        if sel:
            results = await d.scan(timeout, myo_only=True, until=match)
        else:
            results = await d.scan(min(timeout, 3.0), myo_only=True)
        return next((r for r in results if match(r)), None)


class Bled112Transport(Transport):
    backend_name = "bled112"

    def __init__(self, port: str | None = None) -> None:
        self.port = port
        self._dongle: Dongle | None = None
        self._conn: int | None = None
        self._address = ""
        self._handles = B.HandleMap()
        self._subs: dict[int, NotifyCallback] = {}  # value handle -> callback
        self._on_disconnect: DisconnectCallback | None = None
        self._connected = False
        self._att_lock = asyncio.Lock()
        self._lost: asyncio.Future | None = None  # resolved when the link goes away
        self._tasks: set[asyncio.Task] = set()
        self.confirmed = 0  # indications confirmed (diagnostics)

    # ------------------------------------------------------------------ Transport API
    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def address(self) -> str:
        return self._address

    async def connect(self, address: str, on_disconnect: DisconnectCallback | None = None,
                      timeout: float = 20.0) -> None:
        try:
            raw = B.address_to_bytes(address)
        except ValueError:
            raise TransportError(f"{address} is not a Bluetooth MAC address (macOS identifiers only work "
                                 "with the built-in Bluetooth): scan again with the dongle") from None
        if self._connected:
            await self.disconnect()
        d = self._dongle = get_dongle(self.port)
        await d.open()
        self._on_disconnect = on_disconnect
        addr = ":".join(f"{b:02X}" for b in reversed(raw))
        addr_type = d.address_types.get(addr, 0)  # from the scan; the Myo uses a public address

        def established(p: B.Packet):
            conn, flags, a = B.parse_connection_status(p.payload)
            return (conn,) if a == addr and (flags & 0x05) == 0x05 else False  # connected + completed

        async with d.gap_lock:
            fut, done = d.expect(B.EVT_CONNECTION_STATUS, established)
            try:
                resp = await d.command(B.gap_connect_direct(raw, addr_type))
                result = int.from_bytes(resp.payload[0:2], "little")
                if result:
                    raise TransportError(f"BLED112 could not start connecting: {B.error_name(result)}")
                try:
                    (conn,) = await asyncio.wait_for(fut, timeout)
                except TimeoutError:
                    try:  # cancel the pending connection attempt
                        await d.command(B.gap_end_procedure())
                    except TransportError:
                        pass
                    raise TransportError(f"no connection to {addr} within {timeout:g}s "
                                         "(out of range, switched off, or connected elsewhere?)") from None
            finally:
                done()
        self._conn = conn
        self._address = addr
        self._lost = d.loop.create_future()
        d.connections[conn] = self
        d.on_event(B.EVT_ATTCLIENT_ATTRIBUTE_VALUE, self._on_value)
        d.on_event(B.EVT_CONNECTION_DISCONNECTED, self._on_disconnected)
        self._connected = True
        try:
            await self._discover(timeout=10.0)
        except BaseException:
            await self.disconnect()  # never leave a half-open link on the dongle
            raise

    async def _discover(self, timeout: float) -> None:
        d, conn = self._require()
        self._handles = B.HandleMap()

        def on_found(p: B.Packet) -> None:
            c, handle, uuid = B.parse_find_information_found(p.payload)
            if c == conn:
                self._handles.add(handle, uuid)
        d.on_event(B.EVT_ATTCLIENT_FIND_INFORMATION_FOUND, on_found)
        try:
            await self._procedure(B.attclient_find_information(conn), timeout=timeout)
        finally:
            d.off_event(B.EVT_ATTCLIENT_FIND_INFORMATION_FOUND, on_found)
        log.info("BLED112: %d attributes, %d CCCs on %s", len(self._handles.by_uuid),
                 len(self._handles.ccc), self._address)
        if UUIDS.COMMAND.lower() not in self._handles.by_uuid:
            raise TransportError(f"{self._address} has no Myo control service (not a Myo?)")

    def _handle(self, uuid: str) -> int:
        u = uuid.lower()
        h = self._handles.by_uuid.get(u)
        if h is None and len(u) == 36 and u.startswith("0000") and u.endswith("-0000-1000-8000-00805f9b34fb"):
            h = self._handles.by_uuid.get(u[4:8])
        if h is None:
            raise TransportError(f"characteristic {uuid} not found on {self._address}")
        return h

    async def _procedure(self, frame: bytes, *, read_handle: int | None = None,
                         timeout: float = 3.0) -> bytes | None:
        """Run one ATT procedure on this connection and wait for it to finish.

        Writes and find-information end with attclient_procedure_completed. A read ends with the
        attribute value; the stack reports procedure_completed only when a read fails (a success
        completion, if some firmware sends one, is swallowed so the next write can't take it).
        A link loss ends the wait at once."""
        async with self._att_lock:
            d, conn = self._require()
            lost = self._lost
            assert lost is not None

            def completed(p: B.Packet):
                c, result, _h = B.parse_procedure_completed(p.payload)
                if c != conn:
                    return False
                if result:
                    raise TransportError(f"ATT procedure failed on {self._address}: {B.error_name(result)}")
                return read_handle is None

            fut_done, off_done = d.expect(B.EVT_ATTCLIENT_PROCEDURE_COMPLETED, completed)
            fut_val, off_val = None, None
            if read_handle is not None:
                def value(p: B.Packet):
                    c, h, typ, data = B.parse_attribute_value(p.payload)
                    ok = c == conn and h == read_handle and typ in (B.VALUE_READ, B.VALUE_READ_BY_TYPE,
                                                                    B.VALUE_READ_BLOB)
                    return (data,) if ok else False
                fut_val, off_val = d.expect(B.EVT_ATTCLIENT_ATTRIBUTE_VALUE, value)
            target = fut_val if fut_val is not None else fut_done
            try:
                resp = await d.command(frame)
                result = int.from_bytes(resp.payload[1:3], "little")
                if result:
                    raise TransportError(f"BLED112 refused ATT command: {B.error_name(result)}")
                finished, _ = await asyncio.wait({target, fut_done, lost}, timeout=timeout,
                                                 return_when=asyncio.FIRST_COMPLETED)
                if fut_done in finished:
                    fut_done.result()  # raises the ATT error (a read only resolves it on failure)
                if target in finished:
                    if fut_val is None:
                        return None
                    try:  # swallow a success completion that may trail the value
                        await asyncio.wait_for(asyncio.shield(fut_done), 0.05)
                    except (TimeoutError, TransportError):
                        pass
                    return fut_val.result()[0]
                if lost in finished:
                    raise TransportError(f"link to {self._address} lost")
                raise TimeoutError
            except TimeoutError:
                raise TransportError(f"ATT procedure timed out on {self._address}") from None
            finally:
                off_done()
                if off_val:
                    off_val()
                for f in (fut_done, fut_val):
                    if f is not None and f.done() and not f.cancelled():
                        f.exception()  # mark retrieved
                    elif f is not None:
                        f.cancel()

    async def disconnect(self) -> None:
        d, conn = self._dongle, self._conn
        self._connected = False
        if d is None or conn is None:
            return
        if d.is_open:
            fut, done = d.expect(B.EVT_CONNECTION_DISCONNECTED, lambda p: p.payload[0] == conn)
            try:
                resp = await d.command(B.connection_disconnect(conn))
                if int.from_bytes(resp.payload[1:3], "little") == 0:
                    await asyncio.wait_for(fut, 2.0)  # the dongle frees the handle on this event
            except (TimeoutError, TransportError):
                pass
            finally:
                done()
        self._cleanup()

    def _cleanup(self) -> None:
        d = self._dongle
        if d is not None:
            d.off_event(B.EVT_ATTCLIENT_ATTRIBUTE_VALUE, self._on_value)
            d.off_event(B.EVT_CONNECTION_DISCONNECTED, self._on_disconnected)
            if self._conn is not None and d.connections.get(self._conn) is self:
                d.connections.pop(self._conn, None)
        if self._lost is not None and not self._lost.done():
            self._lost.set_result(None)  # wakes any ATT procedure still waiting
        self._conn = None
        self._subs.clear()

    async def read(self, uuid: str) -> bytes:
        _d, conn = self._require()
        handle = self._handle(uuid)
        value = await self._procedure(B.attclient_read_by_handle(conn, handle), read_handle=handle)
        assert value is not None
        return value

    async def write(self, uuid: str, data: bytes, response: bool = True) -> None:
        d, conn = self._require()
        handle = self._handle(uuid)
        if response:
            await self._procedure(B.attclient_attribute_write(conn, handle, data))
        else:
            resp = await d.command(B.attclient_write_command(conn, handle, data))
            result = int.from_bytes(resp.payload[1:3], "little")
            if result:
                raise TransportError(f"BLED112 write command failed: {B.error_name(result)}")

    async def subscribe(self, uuid: str, callback: NotifyCallback) -> None:
        _d, conn = self._require()
        handle = self._handle(uuid)
        ccc = self._handles.ccc.get(handle)
        if ccc is None:
            raise TransportError(f"no client characteristic configuration for {uuid}")
        self._subs[handle] = callback
        # indicate-only characteristics (classifier 0x0103, motion 0x0502) need 0x0002
        indicate = uuid.lower() in (UUIDS.CLASSIFIER_EVENT.lower(), UUIDS.MOTION_EVENT.lower())
        await self._procedure(B.attclient_attribute_write(conn, ccc, B.INDICATE if indicate else B.NOTIFY))

    async def unsubscribe(self, uuid: str) -> None:
        _d, conn = self._require()
        handle = self._handle(uuid)
        self._subs.pop(handle, None)
        ccc = self._handles.ccc.get(handle)
        if ccc is not None:
            await self._procedure(B.attclient_attribute_write(conn, ccc, b"\x00\x00"))

    async def get_rssi(self) -> int | None:
        try:
            d, conn = self._require()
            resp = await d.command(B.connection_get_rssi(conn))
        except TransportError:
            return None
        return int.from_bytes(resp.payload[1:2], "little", signed=True)

    async def get_name(self) -> str | None:
        try:
            return (await self.read(UUIDS.DEVICE_NAME)).decode("utf-8", "replace")
        except TransportError:
            return None

    # ------------------------------------------------------------------ events
    def _require(self) -> tuple[Dongle, int]:
        if not self._connected or self._dongle is None or self._conn is None:
            raise TransportError("not connected")
        return self._dongle, self._conn

    def _on_value(self, p: B.Packet) -> None:
        c, handle, typ, value = B.parse_attribute_value(p.payload)
        if c != self._conn:
            return
        if typ == B.VALUE_INDICATE_RSP_REQ and self._dongle is not None:
            # the band waits for this confirmation before it sends the next indication
            task = self._dongle.loop.create_task(self._confirm(c))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        if typ not in (B.VALUE_NOTIFY, B.VALUE_INDICATE, B.VALUE_INDICATE_RSP_REQ):
            return
        cb = self._subs.get(handle)
        if cb is not None:
            cb(value)

    async def _confirm(self, conn: int) -> None:
        d = self._dongle
        if d is None or not d.is_open:
            return
        try:
            await d.command(B.attclient_indicate_confirm(conn))
            self.confirmed += 1
        except TransportError as e:
            log.warning("BLED112 indicate confirm failed: %s", e)

    def _on_disconnected(self, p: B.Packet) -> None:
        if p.payload[0] != self._conn:
            return
        reason = int.from_bytes(p.payload[1:3], "little")
        log.info("BLED112: connection %d to %s closed: %s", self._conn, self._address, B.error_name(reason))
        self._link_lost()

    def _link_lost(self) -> None:
        was = self._connected
        self._connected = False
        self._cleanup()
        if was and self._on_disconnect:
            self._on_disconnect()


__all__ = ["Bled112Scanner", "Bled112Transport", "Dongle", "close_all", "find_port", "list_serial_ports"]
