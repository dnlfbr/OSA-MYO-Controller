import asyncio
import socket
import time

import pytest
from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_message import OscMessage

from myo_bridge.config import AppConfig, DeviceEntry
from myo_bridge.engine import Bridge, make_backend
from myo_bridge.myo import protocol as P
from myo_bridge.myo.device import DeviceState
from myo_bridge.osc.server import OscControlServer


def _listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(0.5)
    return s


def _drain(s):
    msgs = []
    try:
        while True:
            d, _ = s.recvfrom(65535)
            if OscBundle.dgram_is_bundle(d):
                msgs += [(m.address, m.params) for m in OscBundle(d)]
            else:
                m = OscMessage(d)
                msgs.append((m.address, m.params))
    except socket.timeout:
        pass
    return msgs


async def test_bridge_streams_two_mock_devices_and_control():
    rx = _listener()
    cfg = AppConfig(transport="mock", devices=[DeviceEntry(), DeviceEntry()])
    cfg.osc.port = rx.getsockname()[1]
    cfg.osc_in.port = 0
    factory, scanner = make_backend("mock", cfg)
    bridge = Bridge(cfg, factory, scanner)
    for s in bridge.slots:
        s.device.config.vibrate_on_connect = False
    assert await bridge.connect_all() == 2
    assert {s.device.address for s in bridge.slots} == {"MOCK-0001", "MOCK-0002"}
    assert all(s.device.state is DeviceState.STREAMING for s in bridge.slots)

    server = OscControlServer(bridge, "127.0.0.1", 0)
    await server.start()
    ctrl_port = server._transport.get_extra_info("sockname")[1]
    await asyncio.sleep(1.5)

    msgs = _drain(rx)
    addrs = {a for a, _ in msgs}
    for did in (1, 2):
        assert f"/myo/{did}/emg/raw" in addrs
        assert f"/myo/{did}/quat" in addrs and f"/myo/{did}/euler" in addrs
        assert f"/myo/{did}/status" in addrs and f"/myo/{did}/battery" in addrs
        assert (f"/myo/{did}/sync", [1]) in msgs
        assert (f"/myo/{did}/arm", ["right"]) in msgs
        assert (f"/myo/{did}/firmware", ["1.5.1970.2"]) in msgs
    # both bands get their own 50 Hz IMU budget (shared limiter used to starve band 2)
    for did in (1, 2):
        n_quat = sum(1 for a, _ in msgs if a == f"/myo/{did}/quat")
        assert n_quat >= 40, (did, n_quat)
    emg1 = [p for a, p in msgs if a == "/myo/1/emg/raw"]
    assert 250 <= len(emg1) <= 450  # ~200 sps over ~1.5-2 s incl. connect
    assert all(len(p) == 8 and all(isinstance(v, int) for v in p) for p in emg1)
    rms = [p for a, p in msgs if a == "/myo/1/emg/rms"]
    assert rms and all(0.0 <= v <= 1.0 for v in rms[-1])

    # inbound control: vibrate device 2, zero all, lock all
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    from pythonosc.osc_message_builder import OscMessageBuilder
    for addr, args in (("/myo/2/vibrate", [3]), ("/myo/all/zero", []), ("/myo/1/lock", []),
                       ("/myo/1/mode", [2, 1, 1])):
        b = OscMessageBuilder(addr)
        for a in args:
            b.add_arg(a)
        tx.sendto(b.build().dgram, ("127.0.0.1", ctrl_port))
    await asyncio.sleep(0.4)
    assert bridge.slots[1].device.transport.vibrations[-1] == 3
    assert bridge.slots[0].processor.reference.reference is not None
    assert bridge.slots[0].device.locked is True
    assert bridge.slots[0].device.transport.emg_mode == 2
    assert server.received == 4
    assert any(e.kind == "zero" and e.data.get("by") == "OSC" for e in bridge.log)

    await server.stop()
    await bridge.disconnect_all()
    assert all(s.device.state is DeviceState.DISCONNECTED for s in bridge.slots)
    assert all(s.device.transport.sleep_mode == 0 for s in bridge.slots)


async def test_slot_selection_by_serial_and_first_free():
    """Slot 1 wants the band with serial ...-02 (the weaker one); slot 2 takes the first free."""
    from myo_bridge.config import AppConfig, DeviceEntry
    from myo_bridge.engine import Bridge
    from myo_bridge.myo.mock import MockScanner, MockTransport

    cfg = AppConfig(transport="mock", devices=[DeviceEntry(serial="d2-b5-d9-be-cc-02"), DeviceEntry()])
    cfg.osc.enabled = False
    cfg.scan_timeout_s = 0.1
    b = Bridge(cfg, lambda: MockTransport(), MockScanner(2))
    assert await b.connect_all() == 2
    s1, s2 = b.slots
    assert s1.device.address == "MOCK-0002" and s1.entry.serial == "d2-b5-d9-be-cc-02"
    assert s2.device.address == "MOCK-0001" and s2.entry.serial == "d2-b5-d9-be-cc-01"
    # wrong-serial attempts are released without changing their sleep mode
    await b.disconnect_all()

    cfg2 = AppConfig(transport="mock", devices=[DeviceEntry(selector="ff-ff-ff-ff-ff-ff")])
    cfg2.osc.enabled = False
    cfg2.scan_timeout_s = 0.1
    b2 = Bridge(cfg2, lambda: MockTransport(), MockScanner(2))
    assert await b2.connect_all() == 0
    assert any("no Myo with serial" in e.text for e in b2.log)


def test_apply_settings_live():
    from myo_bridge.config import AppConfig
    from myo_bridge.engine import Bridge
    from myo_bridge.myo.mock import MockScanner, MockTransport

    cfg = AppConfig(transport="mock")
    b = Bridge(cfg, lambda: MockTransport(), MockScanner(1))
    cfg.osc.preset, cfg.osc.mode = "myomapper", "axis"
    cfg.osc.port = 9999
    cfg.osc.streams["emg_raw"] = False
    cfg.osc.imu_rate_hz = 10
    cfg.processing.rms_window_ms = 100
    cfg.processing.zero_mode = "full"
    b.apply_settings()
    assert b.osc.namespace.preset == "myomapper" and b.osc.namespace.mode == "axis"
    assert b.osc.target == ("127.0.0.1", 9999)
    assert not b.osc.wants("emg_raw")
    assert abs(b.osc._imu_limit(1).min_dt - 0.1) < 1e-9
    assert b.slots[0].processor.rms.window == 20
    assert b.slots[0].processor.reference.mode == "full"


async def test_osc_resync_and_poweroff_commands():
    from pythonosc.osc_message_builder import OscMessageBuilder

    from myo_bridge.myo import protocol as P

    cfg = AppConfig(transport="mock", devices=[DeviceEntry()])
    cfg.osc.enabled = False
    cfg.scan_timeout_s = 0.1
    bridge = Bridge(cfg, *make_backend("mock", cfg))
    assert await bridge.connect_all() == 1
    dev = bridge.slots[0].device
    server = OscControlServer(bridge, "127.0.0.1", 0)
    await server.start()
    port = server._transport.get_extra_info("sockname")[1]
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(addr, *args):
        b = OscMessageBuilder(addr)
        for a in args:
            b.add_arg(a)
        tx.sendto(b.build().dgram, ("127.0.0.1", port))

    await asyncio.sleep(1.0)
    assert dev.synced
    send("/myo/1/resync")
    await asyncio.sleep(0.15)
    assert not dev.synced
    send("/myo/all/poweroff")  # without the argument 1: ignored
    await asyncio.sleep(1.2)
    assert dev.synced and dev.state is DeviceState.STREAMING
    send("/myo/1/poweroff", 1)
    await asyncio.sleep(0.3)
    assert dev.state is DeviceState.DISCONNECTED
    assert dev.transport.commands[-1] == P.cmd_deep_sleep()
    await server.stop()
    await bridge.disconnect_all()


async def test_set_transport_rebuilds_the_slots():
    cfg = AppConfig(transport="mock", devices=[DeviceEntry(), DeviceEntry()])
    cfg.osc.enabled = False
    cfg.scan_timeout_s = 0.1
    bridge = Bridge(cfg, *make_backend("mock", cfg))
    assert await bridge.connect_all() == 2
    old = [s.device.transport for s in bridge.slots]
    await bridge.set_transport("mock")
    assert all(s.device.state is DeviceState.DISCONNECTED for s in bridge.slots)
    assert all(s.device.transport is not t for s, t in zip(bridge.slots, old))
    assert any("adapter: simulated armbands" in e.text for e in bridge.log)
    assert await bridge.connect_all() == 2
    await bridge.disconnect_all()
    with pytest.raises(ValueError):
        await bridge.set_transport("bluetooth")


def test_selector_fits_the_adapter():
    import sys

    from myo_bridge.engine import selector_fits

    cb = "6D2A1B3C-0000-4000-8000-123456789ABC"
    assert not selector_fits(cb, "bled112") and selector_fits("D2:B5:D9:BE:CC:01", "bled112")
    assert selector_fits("Myo-left", "bled112") and selector_fits(cb, "bleak")
    assert selector_fits("D2:B5:D9:BE:CC:01", "bleak") is (sys.platform != "darwin")


def _bridge(**entry) -> Bridge:
    cfg = AppConfig(transport="mock", devices=[DeviceEntry(**entry)])
    cfg.osc.enabled = False
    return Bridge(cfg, *make_backend("mock", cfg))


def _imu_packet(accel_g=(0.0, 0.0, 1.0), quat=(1.0, 0.0, 0.0, 0.0)) -> P.ImuPacket:
    return P.ImuPacket(quat=tuple(round(q * P.ORIENTATION_SCALE) for q in quat),
                       accel=tuple(round(a * P.ACCELEROMETER_SCALE) for a in accel_g), gyro=(0, 0, 0))


def _feed_imu(dev, t0: float, t1: float, knock_at: float, knock_g: float) -> None:
    """50 Hz IMU packets from t0 to t1, at rest but for one knock (a jump of knock_g) at knock_at."""
    for i in range(round((t1 - t0) / 0.02) + 1):
        t = t0 + i * 0.02
        dev.on_imu(dev, _imu_packet((knock_g, 0.0, 1.0) if abs(t - knock_at) < 0.01 else (0.0, 0.0, 1.0)), t)


async def test_tap_threshold_and_cooldown():
    b = _bridge()
    b.config.processing.tap_threshold_g = 0.5
    b.apply_settings()
    slot = b.slots[0]
    dev = slot.device
    sent = []
    b.osc.tap = lambda did, direction, count: sent.append((did, direction, count))

    def taps():
        return [e.data for e in b.log if e.kind == "tap"]

    tap = P.MotionEvent(P.MotionEventType.TAP, 1, 1)
    _feed_imu(dev, 10.0, 10.4, knock_at=10.2, knock_g=0.2)  # a light knock
    dev.on_motion(dev, tap, 10.2)
    _feed_imu(dev, 10.42, 11.4, knock_at=11.2, knock_g=1.2)  # a firm one
    dev.on_motion(dev, tap, 11.2)
    assert not sent and not taps()  # judged once the IMU samples after the knock are in
    await asyncio.sleep(0.15)
    assert sent == [(1, 1, 1)]
    weak, firm = taps()
    assert weak["ignored"] == "weaker than 0.50 g" and weak["strength_g"] == pytest.approx(0.2, abs=0.01)
    assert "ignored" not in firm and firm["strength_g"] == pytest.approx(1.2, abs=0.01)

    # no IMU data (IMU mode evt): the strength is unknown, so the tap is kept and the log says why
    dev.on_motion(dev, tap, 20.0)
    assert len(sent) == 2
    assert taps()[-1]["strength_g"] == "n/a" and taps()[-1]["threshold"].startswith("not applied")

    # cooldown: a tap 100 ms after a kept one is dropped
    slot.processor.set_tap_filter(0.0, 300)
    dev.on_motion(dev, tap, 30.0)
    dev.on_motion(dev, tap, 30.1)
    assert len(sent) == 3 and taps()[-1]["ignored"] == "within 300 ms of the last tap"


async def test_double_tap_pose_sets_the_origin():
    b = _bridge(double_tap_origin=True)
    slot = b.slots[0]
    dev = slot.device
    buzz = []

    async def vibrate(kind):
        buzz.append(kind)

    dev.vibrate = vibrate
    double_tap = P.ClassifierEvent(P.ClassifierEventType.POSE, pose=P.Pose.DOUBLE_TAP)
    dev.on_classifier(dev, double_tap, 1.0)  # no IMU data yet: nothing to set, the log says so
    assert slot.processor.reference.reference is None
    assert any(e.kind == "warning" and "double tap" in e.text for e in b.log)

    dev.on_imu(dev, _imu_packet(quat=(0.7071, 0.0, 0.0, 0.7071)), 2.5)  # turned 90° (yaw)
    dev.on_classifier(dev, double_tap, 2.5)
    dev.on_classifier(dev, double_tap, 2.9)  # reported again: one origin per gesture
    await asyncio.sleep(0.05)
    zeros = [e for e in b.log if e.kind == "zero"]
    assert len(zeros) == 1 and zeros[0].data["by"] == "double tap"
    assert slot.processor.reference.reference is not None and len(slot.entry.zero_quat) == 4
    assert buzz == [P.VibrationType.SHORT]  # felt on the arm

    dev.on_classifier(dev, double_tap, 6.0)  # IMU stopped since (mode evt): a stale frame is no origin
    assert len([e for e in b.log if e.kind == "zero"]) == 1 and buzz == [P.VibrationType.SHORT]
    slot.entry.double_tap_origin = False  # off: the pose is only a pose
    dev.on_imu(dev, _imu_packet(), 9.0)
    dev.on_classifier(dev, double_tap, 9.0)
    assert len([e for e in b.log if e.kind == "zero"]) == 1

    # SET ORIGIN from the monitor or OSC: the same rule, the last frame must be recent
    dev.on_imu(dev, _imu_packet(), time.monotonic() - 5.0)  # stream stopped 5 s ago
    await b.zero(1, "OSC")
    assert len([e for e in b.log if e.kind == "zero"]) == 1
    assert any(e.kind == "warning" and e.text.startswith("OSC: no IMU data") for e in b.log)
    dev.on_imu(dev, _imu_packet(), time.monotonic())
    await b.zero(1, "OSC")
    assert [e.data.get("by") for e in b.log if e.kind == "zero"] == ["double tap", "OSC"]


async def test_smooth_emg_feeds_the_monitor_and_warns_when_not_sent():
    b = _bridge(emg_mode=1)
    slot = b.slots[0]
    dev = slot.device
    dev.on_fv(dev, P.FvPacket(values=(512,) * 8, mask=0), 1.0)
    assert slot.fv_queue[-1] == (1.0, (512,) * 8)
    assert slot.rms_latest == pytest.approx((0.5,) * 8)  # pod activity bars
    assert b.emg_hint(slot) == ""  # OSC off altogether: nothing to say
    rx = _listener()
    b.osc.set_target("127.0.0.1", rx.getsockname()[1])
    b.osc.enabled = True
    assert b.emg_hint(slot) == ""  # the 'fv' stream is on by default
    b.osc.streams["fv"] = False  # as in a config saved before
    assert "fv" in b.emg_hint(slot)
    dev.on_state(dev, DeviceState.STREAMING)
    assert any(e.kind == "warning" and "/emg/smooth" in e.text for e in b.log)
    dev.config.emg_mode = P.EmgMode.RAW
    assert b.emg_hint(slot) == ""
    rx.close()
