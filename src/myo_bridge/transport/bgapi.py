"""BGAPI framing for the Silicon Labs / Bluegiga BLED112 dongle (pure functions, no I/O).

Packet layout (BGAPI 1.x, BLE112/BLED112 firmware):

    byte 0: bit7 = message type (0 command/response, 1 event), bits 0-2 = payload length high
    byte 1: payload length low
    byte 2: class id
    byte 3: command / event id
    bytes 4..: payload (little-endian structs)

The command ids and payload layouts below are the subset a Myo needs (GAP discovery and direct
connection, ATT client read/write/find-information, connection disconnect). They match the
public BGAPI reference and the framing used by pyomyo (MIT) and MioConnect's bglib (MIT);
nothing here is copied from either, only the protocol.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# ---- classes
CLS_SYSTEM = 0
CLS_CONNECTION = 3
CLS_ATTCLIENT = 4
CLS_GAP = 6

# ---- commands (class, id)
CMD_SYSTEM_RESET = (CLS_SYSTEM, 0)
CMD_SYSTEM_HELLO = (CLS_SYSTEM, 1)
CMD_CONNECTION_DISCONNECT = (CLS_CONNECTION, 0)
CMD_CONNECTION_GET_RSSI = (CLS_CONNECTION, 1)
CMD_ATTCLIENT_FIND_INFORMATION = (CLS_ATTCLIENT, 3)
CMD_ATTCLIENT_READ_BY_HANDLE = (CLS_ATTCLIENT, 4)
CMD_ATTCLIENT_ATTRIBUTE_WRITE = (CLS_ATTCLIENT, 5)
CMD_ATTCLIENT_WRITE_COMMAND = (CLS_ATTCLIENT, 6)
CMD_ATTCLIENT_INDICATE_CONFIRM = (CLS_ATTCLIENT, 7)
CMD_GAP_SET_MODE = (CLS_GAP, 1)
CMD_GAP_DISCOVER = (CLS_GAP, 2)
CMD_GAP_CONNECT_DIRECT = (CLS_GAP, 3)
CMD_GAP_END_PROCEDURE = (CLS_GAP, 4)
CMD_GAP_SET_SCAN_PARAMETERS = (CLS_GAP, 7)

# ---- events (class, id)
EVT_SYSTEM_BOOT = (CLS_SYSTEM, 0)
EVT_CONNECTION_STATUS = (CLS_CONNECTION, 0)
EVT_CONNECTION_DISCONNECTED = (CLS_CONNECTION, 4)
EVT_ATTCLIENT_PROCEDURE_COMPLETED = (CLS_ATTCLIENT, 1)
EVT_ATTCLIENT_FIND_INFORMATION_FOUND = (CLS_ATTCLIENT, 4)
EVT_ATTCLIENT_ATTRIBUTE_VALUE = (CLS_ATTCLIENT, 5)
EVT_GAP_SCAN_RESPONSE = (CLS_GAP, 0)

CCC_UUID = "2902"
NOTIFY = b"\x01\x00"
INDICATE = b"\x02\x00"

# attclient_attribute_value.type
VALUE_READ, VALUE_NOTIFY, VALUE_INDICATE, VALUE_READ_BY_TYPE, VALUE_READ_BLOB, VALUE_INDICATE_RSP_REQ = range(6)

# a few BGAPI / Bluetooth / ATT error codes, for readable messages
ERRORS = {
    0x0180: "invalid parameter", 0x0181: "device in wrong state", 0x0182: "out of memory",
    0x0183: "feature not implemented", 0x0184: "command not recognized", 0x0185: "timeout",
    0x0186: "not connected", 0x0187: "flow", 0x018A: "command too long",
    0x0208: "connection timeout", 0x0213: "remote user terminated connection",
    0x0216: "connection terminated by local host", 0x023E: "connection failed to be established",
    0x0401: "invalid handle", 0x0402: "read not permitted", 0x0403: "write not permitted",
    0x0405: "insufficient authentication", 0x0406: "request not supported", 0x040A: "attribute not found",
}


def error_name(code: int) -> str:
    return f"0x{code:04x} ({ERRORS[code]})" if code in ERRORS else f"0x{code:04x}"


@dataclass(slots=True)
class Packet:
    is_event: bool
    cls: int
    id: int
    payload: bytes

    @property
    def key(self) -> tuple[int, int]:
        return (self.cls, self.id)


def build(cls: int, cmd: int, payload: bytes = b"") -> bytes:
    n = len(payload)
    return bytes([(n >> 8) & 0x07, n & 0xFF, cls, cmd]) + payload


MAX_PAYLOAD = 128  # BLE112 messages are short; anything longer means we are out of step
MAX_CLASS = 8


class Parser:
    """Incremental BGAPI de-framer; resynchronises on garbage (a byte that can't start a BLE
    packet, or an implausible length/class, e.g. when reading starts mid-packet) by skipping it."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[Packet]:
        self._buf += data
        out: list[Packet] = []
        while len(self._buf) >= 4:
            b0 = self._buf[0]
            if b0 & 0x78:  # technology bits must be 0 for BLE
                del self._buf[0]
                continue
            n = ((b0 & 0x07) << 8) | self._buf[1]
            if n > MAX_PAYLOAD or self._buf[2] > MAX_CLASS:
                del self._buf[0]
                continue
            if len(self._buf) < 4 + n:
                break
            out.append(Packet(bool(b0 & 0x80), self._buf[2], self._buf[3], bytes(self._buf[4:4 + n])))
            del self._buf[:4 + n]
        return out


# ---- payload builders
def gap_discover(mode: int = 1) -> bytes:
    return build(*CMD_GAP_DISCOVER, bytes([mode]))  # 1 = generic


def gap_set_scan_parameters(interval: int = 0x4B, window: int = 0x4B, active: bool = True) -> bytes:
    return build(*CMD_GAP_SET_SCAN_PARAMETERS, struct.pack("<HHB", interval, window, int(active)))


def gap_end_procedure() -> bytes:
    return build(*CMD_GAP_END_PROCEDURE)


def gap_set_mode(discover: int = 0, connect: int = 0) -> bytes:
    return build(*CMD_GAP_SET_MODE, bytes([discover, connect]))


def gap_connect_direct(addr: bytes, addr_type: int, interval_min: int = 6, interval_max: int = 6,
                       timeout: int = 64, latency: int = 0) -> bytes:
    """Connection interval units of 1.25 ms (6 = 7.5 ms, what the Myo asks for); timeout 10 ms."""
    return build(*CMD_GAP_CONNECT_DIRECT, addr + struct.pack("<BHHHH", addr_type, interval_min,
                                                              interval_max, timeout, latency))


def connection_disconnect(conn: int) -> bytes:
    return build(*CMD_CONNECTION_DISCONNECT, bytes([conn]))


def connection_get_rssi(conn: int) -> bytes:
    return build(*CMD_CONNECTION_GET_RSSI, bytes([conn]))


def attclient_find_information(conn: int, start: int = 0x0001, end: int = 0xFFFF) -> bytes:
    return build(*CMD_ATTCLIENT_FIND_INFORMATION, struct.pack("<BHH", conn, start, end))


def attclient_read_by_handle(conn: int, handle: int) -> bytes:
    return build(*CMD_ATTCLIENT_READ_BY_HANDLE, struct.pack("<BH", conn, handle))


def attclient_attribute_write(conn: int, handle: int, data: bytes) -> bytes:
    return build(*CMD_ATTCLIENT_ATTRIBUTE_WRITE, struct.pack("<BHB", conn, handle, len(data)) + data)


def attclient_write_command(conn: int, handle: int, data: bytes) -> bytes:
    return build(*CMD_ATTCLIENT_WRITE_COMMAND, struct.pack("<BHB", conn, handle, len(data)) + data)


def attclient_indicate_confirm(conn: int) -> bytes:
    return build(*CMD_ATTCLIENT_INDICATE_CONFIRM, bytes([conn]))


# ---- payload parsers
@dataclass(slots=True)
class ScanResponse:
    rssi: int
    packet_type: int
    sender: bytes  # 6 bytes, little-endian as on the wire
    address_type: int
    bond: int
    data: bytes

    @property
    def address(self) -> str:
        return ":".join(f"{b:02X}" for b in reversed(self.sender))

    def ad_records(self) -> list[tuple[int, bytes]]:
        out, i, d = [], 0, self.data
        while i + 1 < len(d):
            n = d[i]
            if n == 0:
                break
            out.append((d[i + 1], bytes(d[i + 2:i + 1 + n])))
            i += 1 + n
        return out

    @property
    def name(self) -> str | None:
        for t, v in self.ad_records():
            if t in (0x08, 0x09):
                return v.decode("utf-8", "replace")
        return None

    @property
    def service_uuids(self) -> list[str]:
        out = []
        for t, v in self.ad_records():
            if t in (0x06, 0x07) and len(v) >= 16:
                for i in range(0, len(v) - 15, 16):
                    out.append(uuid_from_le(v[i:i + 16]))
            elif t in (0x02, 0x03):
                for i in range(0, len(v) - 1, 2):
                    out.append(f"{v[i + 1]:02x}{v[i]:02x}")
        return out


def parse_scan_response(p: bytes) -> ScanResponse:
    rssi, ptype = struct.unpack_from("<bB", p, 0)
    sender = bytes(p[2:8])
    addr_type, bond, n = struct.unpack_from("<BBB", p, 8)
    return ScanResponse(rssi, ptype, sender, addr_type, bond, bytes(p[11:11 + n]))


def address_to_bytes(addr: str) -> bytes:
    parts = addr.replace("-", ":").split(":")
    if len(parts) != 6:
        raise ValueError(f"not a MAC address: {addr}")
    return bytes(int(x, 16) for x in reversed(parts))


def uuid_from_le(b: bytes) -> str:
    """16-byte little-endian UUID (as in find_information / advertisements) -> canonical string."""
    h = bytes(reversed(b)).hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def parse_find_information_found(p: bytes) -> tuple[int, int, str]:
    """-> (connection, handle, uuid string: 4 hex chars for 16-bit, canonical for 128-bit)."""
    conn, handle, n = struct.unpack_from("<BHB", p, 0)
    u = bytes(p[4:4 + n])
    if n == 2:
        return conn, handle, f"{u[1]:02x}{u[0]:02x}"
    if n == 16:
        return conn, handle, uuid_from_le(u)
    return conn, handle, u.hex()


def parse_attribute_value(p: bytes) -> tuple[int, int, int, bytes]:
    """-> (connection, handle, type, value)"""
    conn, handle, typ, n = struct.unpack_from("<BHBB", p, 0)
    return conn, handle, typ, bytes(p[5:5 + n])


def parse_connection_status(p: bytes) -> tuple[int, int, str]:
    """-> (connection, flags, address)"""
    conn, flags = p[0], p[1]
    addr = ":".join(f"{b:02X}" for b in reversed(p[2:8]))
    return conn, flags, addr


def parse_procedure_completed(p: bytes) -> tuple[int, int, int]:
    """-> (connection, result, chrhandle)"""
    return struct.unpack_from("<BHH", p, 0)


class HandleMap:
    """Build uuid -> value handle and value handle -> CCC handle from find_information events."""

    def __init__(self) -> None:
        self.by_uuid: dict[str, int] = {}
        self.ccc: dict[int, int] = {}
        self._last_value_handle: int | None = None

    def add(self, handle: int, uuid: str) -> None:
        u = uuid.lower()
        if u in ("2800", "2801", "2803"):  # service / include / characteristic declarations
            return
        if u == CCC_UUID:
            if self._last_value_handle is not None:
                self.ccc[self._last_value_handle] = handle
            return
        if u in ("2901", "2904"):  # user description / presentation format descriptors
            return
        self.by_uuid.setdefault(u, handle)
        self._last_value_handle = handle
