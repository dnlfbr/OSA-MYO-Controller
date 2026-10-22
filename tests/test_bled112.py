"""BLED112 transport against a simulated dongle.

``FakeDongle`` stands in for the serial port: it decodes BGAPI commands, answers them like the
dongle firmware does and puts mock armbands (myo.mock.MockTransport) behind a GATT table, so
MyoDevice runs end to end through bled112_transport and the reader thread.
"""

import asyncio
import struct
import threading
import time

import pytest

from myo_bridge.config import AppConfig, DeviceEntry
from myo_bridge.engine import Bridge, make_backend
from myo_bridge.myo import protocol as P
from myo_bridge.myo.device import DeviceConfig, DeviceState, MyoDevice
from myo_bridge.myo.mock import MockTransport
from myo_bridge.transport import bgapi as B
from myo_bridge.transport import bled112_transport as bled
from myo_bridge.transport.base import TransportError

MYO1, MYO2, PHONE = "D2:B5:D9:BE:CC:01", "D2:B5:D9:BE:CC:02", "11:22:33:44:55:66"
NOTIFY, INDICATE = "notify", "indicate"

MYO_GATT = [
    ("1800", [(P.UUIDS.DEVICE_NAME, "read")]),
    ("180a", [(P.UUIDS.MANUFACTURER, "read")]),
    (P.UUIDS.CONTROL_SERVICE, [(P.UUIDS.INFO, "read"), (P.UUIDS.FIRMWARE, "read"), (P.UUIDS.COMMAND, "write")]),
    (P.UUIDS.IMU_SERVICE, [(P.UUIDS.IMU_DATA, NOTIFY), (P.UUIDS.MOTION_EVENT, INDICATE)]),
    (P.UUIDS.CLASSIFIER_SERVICE, [(P.UUIDS.CLASSIFIER_EVENT, INDICATE)]),
    (P.UUIDS.FV_SERVICE, [(P.UUIDS.FV_DATA, NOTIFY)]),
    (P.UUIDS.EMG_SERVICE, [(u, NOTIFY) for u in P.EMG_UUIDS]),
    (P.UUIDS.BATTERY_SERVICE, [(P.UUIDS.BATTERY_LEVEL, NOTIFY)]),
]
OTHER_GATT = [("1800", [(P.UUIDS.DEVICE_NAME, "read")])]
OK = struct.pack("<H", 0)


def _uuid_bytes(u: str) -> bytes:
    u = u.lower()
    if len(u) == 4:
        return bytes.fromhex(u)[::-1]
    if u.startswith("0000") and u.endswith("-0000-1000-8000-00805f9b34fb"):
        return bytes.fromhex(u[4:8])[::-1]  # standard UUIDs travel as 16-bit
    return bytes.fromhex(u.replace("-", ""))[::-1]


def _gatt_table(gatt):
    """-> [(handle, uuid bytes)], {value handle: (uuid, kind)}, {ccc handle: value handle}"""
    attrs, values, cccs = [], {}, {}

    def add(u: str) -> int:
        h = len(attrs) + 1
        attrs.append((h, _uuid_bytes(u)))
        return h
    for svc, chars in gatt:
        add("2800")
        for u, kind in chars:
            add("2803")
            vh = add(u)
            values[vh] = (u, kind)
            if kind in (NOTIFY, INDICATE):
                cccs[add("2902")] = vh
    return attrs, values, cccs


def _addr_bytes(addr: str) -> bytes:
    return bytes(reversed(bytes.fromhex(addr.replace(":", ""))))


class FakeDongle:
    """Serial-port stand-in that speaks BGAPI, with mock armbands behind it."""

    def __init__(self) -> None:
        self.bands = {MYO1: MockTransport(seed=1), MYO2: MockTransport(seed=2)}
        self.names = {MYO1: "Myo One", MYO2: "Myo Two", PHONE: "Phone"}
        self.myo_gatt, self.other_gatt = _gatt_table(MYO_GATT), _gatt_table(OTHER_GATT)
        self.indicate_type = B.VALUE_INDICATE_RSP_REQ
        self.trailing_read_completion = False
        self.read_errors: dict[str, int] = {}
        self.links: dict[int, str] = {}  # connection handle -> address
        self.pending: str | None = None  # address of a connect_direct in progress
        self.cccs: dict[tuple[int, str], bytes] = {}
        self.commands: list[tuple[int, int]] = []
        self.unexpected: list[tuple[int, int]] = []
        self.confirms = 0
        self.opened = 0
        self.unplugged = False
        self._cv = threading.Condition()
        self._out = bytearray()
        self._parser = B.Parser()
        self._tasks: set[asyncio.Task] = set()

    # ---- what open_serial() returns
    def open(self):
        if self.unplugged:
            raise OSError("[Errno 2] could not open port")
        self.opened += 1
        with self._cv:
            self._out.clear()
        self._parser = B.Parser()
        return self

    def write(self, data: bytes) -> int:
        if self.unplugged:
            raise OSError("[Errno 6] Device not configured")
        for pkt in self._parser.feed(data):
            self._command(pkt)
        return len(data)

    def read(self, n: int) -> bytes:
        with self._cv:
            if not self._out and not self.unplugged:
                self._cv.wait(0.05)
            if self.unplugged:
                raise OSError("device reports readiness to read but returned no data")
            chunk = bytes(self._out[:n])
            del self._out[:n]
            return chunk

    def close(self) -> None:
        pass

    # ---- test controls
    def unplug(self) -> None:
        self.unplugged = True
        for conn in list(self.links):
            self._drop(conn, 0x0208)
        self.pending = None
        with self._cv:
            self._cv.notify_all()

    def replug(self) -> None:
        self.unplugged = False

    # ---- BGAPI
    def _emit(self, event: bool, key: tuple[int, int], payload: bytes) -> None:
        if self.unplugged:
            return
        frame = bytearray(B.build(*key, payload))
        if event:
            frame[0] |= 0x80
        with self._cv:
            self._out += frame
            self._cv.notify_all()

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _command(self, pkt: B.Packet) -> None:
        key, p = pkt.key, pkt.payload
        self.commands.append(key)

        def rsp(payload: bytes) -> None:
            self._emit(False, key, payload)
        if key == B.CMD_GAP_END_PROCEDURE:
            self.pending = None
            rsp(OK)
        elif key in (B.CMD_GAP_SET_MODE, B.CMD_GAP_SET_SCAN_PARAMETERS):
            rsp(OK)
        elif key == B.CMD_GAP_DISCOVER:
            if self.pending:
                rsp(struct.pack("<H", 0x0181))
                return
            rsp(OK)
            for addr in self.names:
                if addr not in self.links.values():  # a connected band stops advertising
                    self._advertise(addr)
        elif key == B.CMD_GAP_CONNECT_DIRECT:
            addr = ":".join(f"{b:02X}" for b in reversed(p[0:6]))
            free = sorted(set(range(3)) - set(self.links))
            if self.pending or not free:
                rsp(struct.pack("<HB", 0x0181, 0))
                return
            self.pending = addr
            rsp(OK + bytes([free[0]]))
            if addr in self.names and addr not in self.links.values():
                self._spawn(self._connect(free[0], addr, p[6]))
        elif key == B.CMD_CONNECTION_DISCONNECT:
            conn = p[0]
            if conn in self.links:
                rsp(bytes([conn]) + OK)
                self._drop(conn, 0x0216)
            else:
                rsp(bytes([conn]) + struct.pack("<H", 0x0186))
        elif key == B.CMD_CONNECTION_GET_RSSI:
            rsp(bytes([p[0], (-58) & 0xFF]))
        elif key == B.CMD_ATTCLIENT_INDICATE_CONFIRM:
            self.confirms += 1
            rsp(OK)
        elif key in (B.CMD_ATTCLIENT_FIND_INFORMATION, B.CMD_ATTCLIENT_READ_BY_HANDLE,
                     B.CMD_ATTCLIENT_ATTRIBUTE_WRITE, B.CMD_ATTCLIENT_WRITE_COMMAND):
            conn = p[0]
            if conn not in self.links:
                rsp(bytes([conn]) + struct.pack("<H", 0x0186))
                return
            rsp(bytes([conn]) + OK)
            self._spawn(self._att(key, conn, self.links[conn], p))
        else:
            self.unexpected.append(key)
            rsp(struct.pack("<H", 0x0184))

    def _advertise(self, addr: str) -> None:
        name = self.names[addr].encode()
        adv = b"\x02\x01\x06"
        if addr in self.bands:
            adv += bytes([17, 0x06]) + _uuid_bytes(P.UUIDS.CONTROL_SERVICE)
        addr_type = 1 if addr == PHONE else 0
        for ptype, data in ((0, adv), (4, bytes([len(name) + 1, 0x09]) + name)):
            self._emit(True, B.EVT_GAP_SCAN_RESPONSE, struct.pack(
                "<bB6sBBB", -60 if addr != MYO2 else -70, ptype, _addr_bytes(addr), addr_type, 0xFF,
                len(data)) + data)

    async def _connect(self, conn: int, addr: str, addr_type: int) -> None:
        await asyncio.sleep(0.02)
        if self.pending != addr:
            return  # cancelled with gap_end_procedure
        band = self.bands.get(addr)
        if band is not None:
            await band.connect(addr, on_disconnect=lambda: self._drop(conn, 0x0208))
        self.pending = None
        self.links[conn] = addr
        self._emit(True, B.EVT_CONNECTION_STATUS, struct.pack(
            "<BB6sBHHHB", conn, 0x05, _addr_bytes(addr), addr_type, 6, 64, 0, 0xFF))

    def _drop(self, conn: int, reason: int) -> None:
        addr = self.links.pop(conn, None)
        if addr is None:
            return
        band = self.bands.get(addr)
        if band is not None and band.is_connected:
            self._spawn(band.disconnect())
        for k in [k for k in self.cccs if k[0] == conn]:
            del self.cccs[k]
        self._emit(True, B.EVT_CONNECTION_DISCONNECTED, bytes([conn]) + struct.pack("<H", reason))

    def _forwarder(self, conn: int, addr: str, handle: int, kind: str):
        typ = B.VALUE_NOTIFY if kind == NOTIFY else self.indicate_type

        def cb(data: bytes) -> None:
            if self.links.get(conn) == addr:
                self._emit(True, B.EVT_ATTCLIENT_ATTRIBUTE_VALUE,
                           struct.pack("<BHBB", conn, handle, typ, len(data)) + data)
        return cb

    async def _att(self, key, conn: int, addr: str, p: bytes) -> None:
        attrs, values, cccs = self.myo_gatt if addr in self.bands else self.other_gatt
        band = self.bands.get(addr)

        def completed(result: int, handle: int) -> None:
            if self.links.get(conn) == addr:
                self._emit(True, B.EVT_ATTCLIENT_PROCEDURE_COMPLETED, struct.pack("<BHH", conn, result, handle))
        await asyncio.sleep(0.002)
        if key == B.CMD_ATTCLIENT_FIND_INFORMATION:
            for h, ub in attrs:
                self._emit(True, B.EVT_ATTCLIENT_FIND_INFORMATION_FOUND, struct.pack("<BHB", conn, h, len(ub)) + ub)
            completed(0, attrs[-1][0])
            return
        handle = struct.unpack_from("<H", p, 1)[0]
        if key == B.CMD_ATTCLIENT_READ_BY_HANDLE:
            uuid = values.get(handle, ("",))[0]
            if band is None or not uuid or uuid in self.read_errors:
                completed(self.read_errors.get(uuid, 0x0401), handle)
                return
            data = await band.read(uuid)
            self._emit(True, B.EVT_ATTCLIENT_ATTRIBUTE_VALUE,
                       struct.pack("<BHBB", conn, handle, B.VALUE_READ, len(data)) + data)
            if self.trailing_read_completion:
                completed(0, handle)
            return
        data = bytes(p[4:4 + p[3]])
        if handle in cccs and band is not None:
            uuid, kind = values[cccs[handle]]
            self.cccs[(conn, uuid)] = data
            if data == b"\x00\x00":
                await band.unsubscribe(uuid)
            else:
                await band.subscribe(uuid, self._forwarder(conn, addr, cccs[handle], kind))
        elif handle in values and band is not None:
            await band.write(values[handle][0], data)
        else:
            completed(0x0403, handle)
            return
        if key == B.CMD_ATTCLIENT_ATTRIBUTE_WRITE:
            completed(0, handle)


@pytest.fixture
def fake(monkeypatch):
    f = FakeDongle()
    monkeypatch.setattr(bled, "open_serial", lambda port: f.open())
    yield f
    bled.close_all()
    assert f.unexpected == []


def _cfg(**kw):
    base = dict(keepalive_s=0, battery_poll_s=0, rssi_poll_s=0, command_spacing_s=0,
                reconnect_backoff=(0.05, 0.05))
    base.update(kw)
    return DeviceConfig(**base)


async def _until(cond, timeout: float = 3.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


async def test_scan_lists_myos_strongest_first(fake):
    sc = bled.Bled112Scanner("FAKE")
    res = await sc.scan(timeout=0.2)
    assert [(r.address, r.name, r.is_myo) for r in res] == [(MYO1, "Myo One", True), (MYO2, "Myo Two", True)]
    every = await sc.scan(timeout=0.2, myo_only=False)
    assert {r.address for r in every} == {MYO1, MYO2, PHONE}
    d = bled.get_dongle("FAKE")
    assert d.address_types[PHONE] == 1 and d.address_types[MYO1] == 0
    t0 = time.monotonic()
    assert (await sc.find("myo two", timeout=5)).address == MYO2
    assert time.monotonic() - t0 < 1.0  # returns as soon as the band is heard
    assert await sc.find("AA:BB:CC:DD:EE:FF", timeout=0.2) is None
    # opening the port dropped any link a previous run left on the dongle
    assert fake.commands[:5] == [B.CMD_GAP_END_PROCEDURE, B.CMD_GAP_SET_MODE] + [B.CMD_CONNECTION_DISCONNECT] * 3


async def test_myo_device_streams_through_the_dongle(fake):
    tr = bled.Bled112Transport("FAKE")
    dev = MyoDevice(tr, device_id=1, config=_cfg(), selector=MYO1)
    emg, imu = [], []
    dev.on_emg.connect(lambda d, s, t: emg.append(s))
    dev.on_imu.connect(lambda d, p, t: imu.append(p))
    await dev.connect()
    assert dev.state is DeviceState.STREAMING and dev.address == MYO1
    assert dev.firmware.short == "1.5.1970.2" and dev.info.serial == "d2-b5-d9-be-cc-01"
    assert dev.battery == 87 and dev.name == "Mock Myo"
    assert fake.cccs[(0, P.UUIDS.EMG0)] == B.NOTIFY and fake.cccs[(0, P.UUIDS.CLASSIFIER_EVENT)] == B.INDICATE
    await asyncio.sleep(1.3)
    assert len(emg) >= 150 and all(len(s) == 8 for s in emg) and len(imu) >= 40
    assert dev.synced and dev.arm is P.Arm.RIGHT and not dev.locked
    assert P.cmd_unlock(P.UnlockType.HOLD) in fake.bands[MYO1].commands  # unlocked after sync
    assert fake.confirms >= 2 and tr.confirmed == fake.confirms  # every indication confirmed
    assert await tr.get_rssi() == -58

    await dev.resync()
    assert not dev.synced
    await _until(lambda: dev.synced)

    await dev.disconnect()
    assert dev.state is DeviceState.DISCONNECTED and fake.links == {}
    assert fake.bands[MYO1].commands[-1] == P.cmd_set_sleep_mode(P.SleepMode.NORMAL)


async def test_two_bands_share_one_dongle(fake):
    a = MyoDevice(bled.Bled112Transport("FAKE"), device_id=1, config=_cfg(), selector=MYO1)
    b = MyoDevice(bled.Bled112Transport("FAKE"), device_id=2, config=_cfg(), selector=MYO2)
    ea, eb = [], []
    a.on_emg.connect(lambda d, s, t: ea.append(s))
    b.on_emg.connect(lambda d, s, t: eb.append(s))
    await asyncio.gather(a.connect(), b.connect())  # the GAP lock queues the two connections
    assert sorted(fake.links.values()) == [MYO1, MYO2]
    assert {a.info.serial, b.info.serial} == {"d2-b5-d9-be-cc-01", "d2-b5-d9-be-cc-02"}
    await asyncio.sleep(0.6)
    assert len(ea) > 60 and len(eb) > 60
    await a.disconnect()
    assert list(fake.links.values()) == [MYO2] and b.state is DeviceState.STREAMING
    n = len(eb)
    await asyncio.sleep(0.2)
    assert len(eb) > n
    await b.disconnect()


async def test_link_loss_reconnects_through_the_dongle(fake):
    dev = MyoDevice(bled.Bled112Transport("FAKE"), config=_cfg(), selector=MYO1)
    await dev.connect()
    fake.bands[MYO1].simulate_link_loss()
    await _until(lambda: dev.state is DeviceState.RECONNECTING)
    await _until(lambda: dev.state is DeviceState.STREAMING)
    assert list(fake.links.values()) == [MYO1]
    await dev.disconnect()


async def test_unplugged_dongle_drops_the_link_and_recovers(fake):
    dev = MyoDevice(bled.Bled112Transport("FAKE"), config=_cfg(), selector=MYO1)
    await dev.connect()
    fake.unplug()
    await _until(lambda: dev.state is DeviceState.RECONNECTING)
    assert not bled.get_dongle("FAKE").is_open
    await asyncio.sleep(0.3)  # reconnect attempts fail while the port is gone
    assert dev.state is not DeviceState.STREAMING
    fake.replug()
    await _until(lambda: dev.state is DeviceState.STREAMING, 5.0)
    assert fake.opened == 2
    await dev.disconnect()


async def test_power_off_through_the_dongle(fake):
    dev = MyoDevice(bled.Bled112Transport("FAKE"), config=_cfg(), selector=MYO1)
    await dev.connect()
    t0 = time.monotonic()
    await dev.power_off()
    assert time.monotonic() - t0 < 1.0  # the link loss ends the pending write at once
    assert dev.state is DeviceState.DISCONNECTED and fake.links == {}
    assert fake.bands[MYO1].commands[-1] == P.cmd_deep_sleep()
    await asyncio.sleep(0.2)
    assert dev.state is DeviceState.DISCONNECTED  # no reconnect after a power off


async def test_errors_are_reported_and_leave_no_link_behind(fake):
    tr = bled.Bled112Transport("FAKE")
    with pytest.raises(TransportError, match="not a Bluetooth MAC address"):
        await tr.connect("6D2A1B3C-0000-4000-8000-123456789ABC")  # a CoreBluetooth identifier
    with pytest.raises(TransportError, match="not a Myo"):
        await tr.connect(PHONE)
    assert fake.links == {} and not tr.is_connected
    with pytest.raises(TransportError, match="no connection"):
        await tr.connect("AA:BB:CC:DD:EE:FF", timeout=0.3)
    assert fake.pending is None  # the attempt was cancelled

    fake.read_errors[P.UUIDS.FIRMWARE] = 0x0405
    await tr.connect(MYO2)
    t0 = time.monotonic()
    with pytest.raises(TransportError, match="insufficient authentication"):
        await tr.read(P.UUIDS.FIRMWARE)
    assert time.monotonic() - t0 < 1.0
    assert await tr.read(P.UUIDS.BATTERY_LEVEL) == bytes([87])
    await tr.disconnect()
    assert fake.links == {}


async def test_trailing_read_completion_and_auto_confirmed_indications(fake):
    fake.trailing_read_completion = True  # some firmware ends a read with a completion too
    fake.indicate_type = B.VALUE_INDICATE  # the stack confirmed already: nothing to send
    dev = MyoDevice(bled.Bled112Transport("FAKE"), config=_cfg(), selector=MYO1)
    await dev.connect()
    assert dev.firmware.short == "1.5.1970.2" and dev.battery == 87
    await _until(lambda: dev.synced)
    assert fake.confirms == 0
    await dev.disconnect()


async def test_bridge_connects_slots_through_the_dongle(fake):
    # slot 1 still has the address the built-in Bluetooth showed, plus the band's serial
    cfg = AppConfig(transport="bled112", dongle_port="FAKE", scan_timeout_s=0.3, devices=[
        DeviceEntry(selector="6D2A1B3C-0000-4000-8000-123456789ABC", serial="d2-b5-d9-be-cc-02"),
        DeviceEntry()])
    cfg.osc.enabled = False
    bridge = Bridge(cfg, *make_backend("bled112", cfg))
    assert await bridge.connect_all() == 2
    s1, s2 = bridge.slots
    assert s1.device.address == MYO2 and s2.device.address == MYO1
    assert s2.entry.serial == "d2-b5-d9-be-cc-01"
    assert any("another Bluetooth adapter" in e.text for e in bridge.log)
    # back to simulated bands: links dropped, the dongle's port released
    await bridge.set_transport("mock")
    assert fake.links == {} and bled._dongles == {}
    assert all(s.device.state is DeviceState.DISCONNECTED for s in bridge.slots)
    assert await bridge.connect_all() == 2
    assert s1.device.address == "MOCK-0002"  # found again by serial
    await bridge.disconnect_all()


async def test_busy_port_says_who_may_hold_it(monkeypatch):
    def busy(port):
        raise OSError(16, "Resource busy")
    monkeypatch.setattr(bled, "open_serial", busy)
    with pytest.raises(TransportError, match="another program"):
        await bled.Dongle("/dev/cu.usbmodem1").open()


def test_find_port_prefers_the_bled112(monkeypatch):
    from serial.tools import list_ports

    class Port:
        def __init__(self, device, vid, pid, description, manufacturer):
            self.device, self.vid, self.pid = device, vid, pid
            self.description, self.manufacturer = description, manufacturer
    monkeypatch.setattr(list_ports, "comports", lambda: [
        Port("/dev/cu.Bluetooth-Incoming-Port", None, None, "n/a", None),
        Port("/dev/cu.usbmodem11", 0x2458, 0x0001, "Low Energy Dongle", "Bluegiga"),
    ])
    assert bled.find_port() == "/dev/cu.usbmodem11"
    assert bled.list_serial_ports()[0] == ("/dev/cu.usbmodem11", "Low Energy Dongle", True)
