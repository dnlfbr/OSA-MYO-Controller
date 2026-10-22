from myo_bridge.myo.protocol import UUIDS
from myo_bridge.transport import bgapi as B


def test_frame_roundtrip_and_resync():
    f = B.gap_connect_direct(B.address_to_bytes("D2:B5:D9:BE:CC:8F"), 0)
    assert f[:4] == bytes([0, 15, 6, 3])
    pkts = B.Parser().feed(b"\xff" + f + b"\x80\x03\x03\x04\x01\x08\x00")
    assert len(pkts) == 2
    assert not pkts[0].is_event and pkts[0].key == B.CMD_GAP_CONNECT_DIRECT
    assert pkts[1].is_event and pkts[1].key == B.EVT_CONNECTION_DISCONNECTED and pkts[1].payload == b"\x01\x08\x00"
    # split delivery
    p = B.Parser()
    assert p.feed(f[:5]) == []
    assert len(p.feed(f[5:])) == 1


def test_address_roundtrip():
    b = B.address_to_bytes("d2:b5:d9:be:cc:8f")
    assert b == bytes([0x8F, 0xCC, 0xBE, 0xD9, 0xB5, 0xD2])
    sr = B.ScanResponse(-60, 0, b, 0, 0, b"")
    assert sr.address == "D2:B5:D9:BE:CC:8F"


def test_scan_response_name_and_service_uuid():
    name = b"\x09\x09Myo-left"[1:]  # type 0x09 + "Myo-left"
    rec_name = bytes([len(name)]) + name
    svc = bytes.fromhex("4248124a7f2c4847b9de04a9010006d5")  # control service UUID little-endian
    rec_svc = bytes([1 + 16, 0x06]) + svc
    data = rec_name + rec_svc
    payload = bytes([256 - 60, 0]) + B.address_to_bytes("D2:B5:D9:BE:CC:8F") + bytes([0, 0xFF, len(data)]) + data
    sr = B.parse_scan_response(payload)
    assert sr.rssi == -60 and sr.name == "Myo-left"
    assert sr.service_uuids == [UUIDS.CONTROL_SERVICE.lower()]


def test_handle_map_assigns_ccc_to_previous_value_handle():
    hm = B.HandleMap()
    conn_payload = lambda h, u: bytes([1]) + h.to_bytes(2, "little") + bytes([len(u)]) + u  # noqa: E731
    rows = [
        (0x0001, bytes.fromhex("0028")),  # primary service decl (2800)
        (0x0002, bytes.fromhex("0328")),  # characteristic decl (2803)
        (0x0003, bytes.fromhex("4248124a7f2c4847b9de04a9020406d5")),  # IMU data 0402
        (0x0004, bytes.fromhex("0229")),  # CCC
        (0x0005, bytes.fromhex("0328")),
        (0x0006, bytes.fromhex("192a")),  # battery level 2A19
        (0x0007, bytes.fromhex("0229")),
    ]
    for h, u in rows:
        c, handle, uuid = B.parse_find_information_found(conn_payload(h, u))
        hm.add(handle, uuid)
    assert hm.by_uuid[UUIDS.IMU_DATA.lower()] == 3
    assert hm.ccc[3] == 4
    assert hm.by_uuid["2a19"] == 6 and hm.ccc[6] == 7


def test_attribute_value_and_write_frames():
    conn, handle, typ, value = B.parse_attribute_value(bytes([1, 0x0F, 0x00, 1, 3, 9, 8, 7]))
    assert (conn, handle, typ, value) == (1, 15, 1, b"\x09\x08\x07")
    f = B.attclient_attribute_write(1, 0x19, bytes([1, 3, 3, 3, 1]))
    assert f == bytes([0, 9, 4, 5, 1, 0x19, 0, 5, 1, 3, 3, 3, 1])
