"""GUI smoke tests, run offscreen. Skipped if PySide6 is not installed."""

import os
from itertools import pairwise

import numpy as np
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from myo_bridge.gui.widgets.emg_grid import EmgRing  # noqa: E402
from myo_bridge.gui.widgets.imu_strips import Ring  # noqa: E402
from myo_bridge.gui.widgets.orientation3d import VIEWS, model_quat, project  # noqa: E402
from myo_bridge.processing import quaternion as Q  # noqa: E402


def test_emg_ring_wraps_in_order():
    r = EmgRing(seconds=0.05)  # 10 rows
    assert r.n == 10
    r.push_many([[i] * 8 for i in range(25)])
    last = r.last(4)
    assert last[:, 0].tolist() == [21, 22, 23, 24]
    assert len(r.last(100)) == 10
    assert r.last(10)[:, 3].tolist() == list(range(15, 25))


def test_imu_ring_short():
    r = Ring(3, seconds=1.0, rate=10)
    assert len(r.last(5)) == 0
    r.push((1, 2, 3))
    assert r.last(5).tolist() == [[1, 2, 3]]


def test_projection_views_and_rotation():
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])  # origin, hand (+x), logo pod (+z)
    for view in VIEWS:
        p0 = project(pts, Q.IDENTITY, view)
        assert p0.shape == (3, 2) and np.isfinite(p0).all()
        assert not np.allclose(p0, project(pts, Q.from_euler(0.0, 0.0, np.pi / 2), view))
        assert np.allclose(p0, project(pts, Q.from_euler(0.0, 0.0, 2 * np.pi), view), atol=1e-6)
    side = project(pts, Q.IDENTITY, "side")
    assert side[1, 0] > side[0, 0]  # seen from the right, the hand points to the right
    assert project(pts, Q.from_euler(0.0, -0.6, 0.0), "side")[1, 1] > side[1, 1]  # arm raised
    top = project(pts, Q.IDENTITY, "top")
    assert top[1, 1] > top[0, 1]  # from above, the hand points up the screen
    turned = project(pts, Q.from_euler(0.0, 0.0, 0.5), "top")  # yaw left (counter-clockwise)
    assert turned[1, 0] < top[1, 0]
    behind = project(pts, Q.IDENTITY, "behind")
    assert behind[2, 1] > behind[0, 1]  # the logo pod faces up


def test_band_worn_toward_elbow_keeps_the_hand_forward():
    assert np.allclose(Q.rotate_vector(model_quat(Q.IDENTITY, True), (1.0, 0.0, 0.0)), (1.0, 0.0, 0.0), atol=1e-9)
    q = Q.normalize(Q.from_euler(0.4, -0.5, 1.1))
    hand = Q.rotate_vector(model_quat(q, True), (1.0, 0.0, 0.0))
    band_minus_x = Q.rotate_vector(q, (-1.0, 0.0, 0.0))  # the band's -x is the hand side
    assert np.allclose(hand, (-band_minus_x[0], -band_minus_x[1], band_minus_x[2]), atol=1e-9)
    assert model_quat(q, False) == q


def test_emg_auto_ranges_follow_the_amplitude():
    from myo_bridge.gui.widgets.emg_grid import AUTO_MIN, EmgGrid

    rng = np.random.default_rng(0)
    quiet = rng.normal(0, 1.0, (400, 8))  # a resting band: a couple of counts
    loud = rng.normal(0, 30.0, (400, 8))
    cur = np.full(8, 64.0)
    nxt = EmgGrid.auto_ranges(quiet, cur)
    assert np.all(nxt < cur) and np.all(nxt > 55)  # shrinks gradually
    for _ in range(200):
        cur = EmgGrid.auto_ranges(quiet, cur)
    assert np.all(cur < 6) and np.all(cur >= AUTO_MIN)  # small signals fill the plot
    assert np.all(EmgGrid.auto_ranges(loud, cur) > 60)  # a contraction is never clipped


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from myo_bridge.gui import theme

    theme.apply(app)
    return app


def test_monitor_window_with_mock(qapp):
    from PySide6.QtCore import QEventLoop, QTimer

    from myo_bridge.config import AppConfig, DeviceEntry
    from myo_bridge.gui.bridge_thread import BridgeThread
    from myo_bridge.gui.monitor import MonitorWindow
    from myo_bridge.myo.device import DeviceState

    cfg = AppConfig(transport="mock", devices=[DeviceEntry(), DeviceEntry()])
    cfg.osc.port = 7470
    cfg.osc_in.enabled = False
    bt = BridgeThread(cfg)
    bt.start()
    win = MonitorWindow(cfg, bt)
    win.show()
    bt.call(bt.bridge.connect_all())
    loop = QEventLoop()
    QTimer.singleShot(2500, loop.quit)
    loop.exec()
    try:
        s1 = bt.bridge.slots[0]
        assert s1.device.state is DeviceState.STREAMING
        assert win.emg.ring.total > 100
        assert win.imu.quat.ring.total > 20
        assert win.events.text.document().blockCount() > 3
        assert "STREAMING" in win.header.status.text()
        win.overrides.vibrate.emit(3)
        win.overrides.set_origin.emit()
        win.devices._select(2)
        QTimer.singleShot(600, loop.quit)
        loop.exec()
        assert 3 in s1.device.transport.vibrations
        assert s1.processor.reference.reference is not None
        scene = win.orient.canvas.scene()
        assert scene and all(a[0] >= b[0] for a, b in pairwise(scene))  # far to near
        assert win.orient.canvas.arm == "right"  # the mock syncs on the right arm
        assert "MYO 2" in win.header.badge.text()
        assert "simulated armbands" in win.lbl_info.text()
        win._switch_adapter()  # same adapter again: everything is disconnected and rebuilt
        QTimer.singleShot(500, loop.quit)
        loop.exec()
        assert all(s.device.state is DeviceState.DISCONNECTED for s in bt.bridge.slots)
        assert win.devices.list.count() == 0
    finally:
        win.close()


def test_emg_grid_restores_the_saved_view_and_autoscales(qapp):
    from myo_bridge.gui.widgets.emg_grid import EmgGrid

    g = EmgGrid()
    g.apply_settings(1.7, 10.0, False)  # snapped to the nearest options
    assert g.window_s == 2.0 and g.scale == 8.0 and not g.autoscale
    assert g.plots[0].getViewBox().viewRange()[1] == pytest.approx([-8, 8])
    g.apply_settings(2.0, 64.0, True)
    assert g.autoscale and not g.cb_scale.isEnabled()
    g.push(np.random.default_rng(1).normal(0, 1.0, (400, 8)))
    for _ in range(100):
        g.refresh()
    lo, hi = g.plots[3].getViewBox().viewRange()[1]
    assert hi < 8 and lo == pytest.approx(-hi)
    assert g.tags[3].textItem.toPlainText().startswith("POD 3  ±")
    g.ck_auto.setChecked(False)
    assert g.plots[3].getViewBox().viewRange()[1] == pytest.approx([-64, 64])
    assert g.tags[3].textItem.toPlainText() == "POD 3"


def test_settings_connection_tab_writes_the_adapter(qapp):
    from myo_bridge.config import AppConfig
    from myo_bridge.gui.settings import SettingsDialog

    cfg = AppConfig()
    dlg = SettingsDialog(cfg)
    assert dlg.cb_adapter.currentData() == "bleak" and not dlg.cb_port.isEnabled()
    dlg.cb_adapter.setCurrentIndex(dlg.cb_adapter.findData("bled112"))
    assert dlg.cb_port.isEnabled() and dlg.lbl_dongle.text()
    dlg.write_back()
    assert cfg.transport == "bled112" and cfg.dongle_port == ""  # auto-detect
    dlg.cb_port.setEditText("/dev/cu.usbmodem99")
    dlg.write_back()
    assert cfg.dongle_port == "/dev/cu.usbmodem99"
    again = SettingsDialog(cfg)  # a saved port that is not plugged in stays selected
    assert again.cb_adapter.currentData() == "bled112" and again.port_value() == "/dev/cu.usbmodem99"
    again._refresh_ports()
    assert again.port_value() == "/dev/cu.usbmodem99"


def test_emg_grid_shows_smooth_emg(qapp):
    from myo_bridge.gui.widgets.emg_grid import EmgGrid

    g = EmgGrid()
    g.set_source("fv")
    assert g.scale == 1024 and g.plots[0].getViewBox().viewRange()[1] == pytest.approx([0, 1024])
    assert [g.cb_scale.itemText(i) for i in range(3)] == ["16", "32", "64"]  # 0..n, no ±
    g.push_fv(np.full((40, 8), 300.0))
    g.refresh()
    assert g.ring.total == 40
    g.set_source("emg")  # back to the samples, with their own scale
    assert g.scale == 64 and g.ring.total == 0
    assert g.plots[0].getViewBox().viewRange()[1] == pytest.approx([-64, 64])


def test_empty_views_say_why(qapp):
    from myo_bridge.gui.band_view import notices
    from myo_bridge.gui.theme import Panel
    from myo_bridge.myo import protocol as P

    p = Panel("Test")
    p.resize(300, 200)
    p.show()
    p.set_notice("why it is empty")
    assert p.notice() == "why it is empty"
    p.set_notice("")
    assert p.notice() == ""

    E, I = P.EmgMode, P.ImuMode
    assert notices(E.FILTERED, I.ALL, True, False, True, False) == ("", "")
    emg, imu = notices(E.SMOOTH, I.EVENTS, True, True, True, True)
    assert "smooth" in emg and "tap events" in imu
    assert notices(E.SMOOTH, I.ALL, False, True, True, True) == ("", "")  # data may still come
    assert "off" in notices(E.NONE, I.NONE, False, True, True, True)[0]
    assert notices(E.RAW, I.DATA, True, True, True, True) == ("No EMG data from the band.",
                                                               "No IMU data from the band.")


def test_extra_window_rename_and_double_tap_toggle(qapp):
    from PySide6.QtCore import QEventLoop, QTimer

    from myo_bridge.config import AppConfig, DeviceEntry
    from myo_bridge.gui.bridge_thread import BridgeThread
    from myo_bridge.gui.monitor import MonitorWindow

    cfg = AppConfig(transport="mock", devices=[DeviceEntry(), DeviceEntry(emg_mode=1)])
    cfg.osc.port = 7470
    cfg.osc_in.enabled = False
    bt = BridgeThread(cfg)
    bt.start()
    win = MonitorWindow(cfg, bt)
    win.show()
    header_w = win.header.minimumSizeHint().width()
    bt.call(bt.bridge.connect_all())
    loop = QEventLoop()
    try:
        extra = win.open_window()  # the first band not on screen: MYO 2
        assert extra is not None and extra.slot.id == 2 and win.open_window(2) is extra
        QTimer.singleShot(2500, loop.quit)
        loop.exec()
        assert extra.emg.source == "fv" and extra.emg.ring.total > 20  # smooth EMG, 50 Hz
        assert win.emg.source == "emg" and win.emg.ring.total > 100  # both bands at once
        assert win.header.minimumSizeHint().width() == header_w  # the header doesn't grow with data
        s2 = bt.bridge.slots[1]
        s2.entry.label = "Braccio sinistro"
        win._tick_slow()
        assert extra.windowTitle().startswith("Braccio sinistro")
        assert extra.cb_slot.currentText() == "MYO 2 · Braccio sinistro"
        assert win.devices.rows[2].name.text() == "Braccio sinistro"
        extra.pose.btn_tap_origin.click()
        assert s2.entry.double_tap_origin and not bt.bridge.slots[0].entry.double_tap_origin
        extra.close()
        qapp.processEvents()
        assert win.extra == []
    finally:
        win.close()


def test_settings_names_double_tap_and_tap_filter(qapp):
    from myo_bridge.config import AppConfig, DeviceEntry
    from myo_bridge.gui.settings import SettingsDialog

    cfg = AppConfig(devices=[DeviceEntry(label="Destro"), DeviceEntry()])
    dlg = SettingsDialog(cfg)
    assert dlg.dev_rows[0][0].text() == "Destro"
    name, _sel, _ser, _ns, dt = dlg.dev_rows[1]
    name.setText("  Sinistro ")
    dt.setChecked(True)
    dlg.sp_tap_th.setValue(0.65)
    dlg.sp_tap_cd.setValue(250)
    dlg.write_back()
    assert [d.label for d in cfg.devices] == ["Destro", "Sinistro"]
    assert cfg.devices[1].double_tap_origin and not cfg.devices[0].double_tap_origin
    assert cfg.processing.tap_threshold_g == 0.65 and cfg.processing.tap_cooldown_ms == 250.0


def test_about_window_credits(qapp):
    from pathlib import Path

    from typer.testing import CliRunner

    from myo_bridge import credits
    from myo_bridge.cli import app
    from myo_bridge.gui.about import AboutDialog

    dlg = AboutDialog()
    assert dlg.authors.text() == "Daniele Fabris · Simone Arganini"
    assert "www.oscillacreations.com" in dlg.contact.text()
    text = dlg.text.toPlainText()
    for c in credits.SOURCES + credits.LIBRARIES:
        assert c.name in text
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    assert all(f"[{c.name}]" in readme for c in credits.SOURCES)  # same list as the README
    dlg.close()

    out = CliRunner().invoke(app, ["credits"]).output
    assert "© 2026 Daniele Fabris, Simone Arganini" in out and "www.oscillacreations.com" in out
    assert "PerlinWarp/pyomyo" in out
