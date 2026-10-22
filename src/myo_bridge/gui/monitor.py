"""Main window: Armband Manager sidebar + MyoDiagnostics-style monitor for the selected slot,
plus extra windows (NEW WINDOW) to watch more armbands at once.

All device I/O happens on the BridgeThread's asyncio loop; this window only reads the slots'
deques/attributes on a QTimer, feeds its own view and the extra windows, and schedules
coroutines for button presses."""

from __future__ import annotations

import logging
import time
from collections import deque

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from myo_bridge import credits
from myo_bridge.config import LABEL_MAX, AppConfig, clean_label, save_config
from myo_bridge.engine import ADAPTERS, NO_ORIGIN, ORIGIN_FRESH_S, LogEntry, Slot
from myo_bridge.gui import theme
from myo_bridge.gui.about import AboutDialog
from myo_bridge.gui.band_view import BandView, BandWindow, drain
from myo_bridge.gui.bridge_thread import BridgeThread
from myo_bridge.gui.widgets.device_list import DeviceList
from myo_bridge.gui.widgets.emg_grid import EmgGrid
from myo_bridge.gui.widgets.event_feed import EventFeed
from myo_bridge.gui.widgets.imu_strips import ImuStrips
from myo_bridge.gui.widgets.orientation3d import Orientation3D
from myo_bridge.gui.widgets.overrides import Overrides
from myo_bridge.gui.widgets.pose_feed import PoseFeed
from myo_bridge.gui.widgets.status_panel import BatteryPanel, HeaderStrip, SignalPanel
from myo_bridge.myo import protocol as P
from myo_bridge.myo.device import DeviceState

log = logging.getLogger(__name__)


def _column(*items, width: int | None = None) -> QWidget:
    """A vertical stack of panels; an item is a widget or (widget, stretch)."""
    w = QWidget()
    v = QVBoxLayout(w); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(theme.GAP)
    for it in items:
        wid, stretch = it if isinstance(it, tuple) else (it, 0)
        v.addWidget(wid, stretch)
    if width:
        w.setFixedWidth(width)
    return w


class _Wordmark(QLabel):
    """The toolbar wordmark; a click opens the About window."""

    clicked = Signal()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


def _spacer(w: int) -> QWidget:
    sp = QWidget(); sp.setFixedWidth(w)
    return sp


class MonitorWindow(QMainWindow):
    def __init__(self, config: AppConfig, bt: BridgeThread) -> None:
        super().__init__()
        self.config = config
        self.bt = bt
        self.bridge = bt.bridge
        self.setWindowTitle("OSA MYO Controller")
        self._fit_to_screen(1480, 900)
        self._slot: Slot | None = self.bridge.slots[0] if self.bridge.slots else None
        self._scanning = False
        self._log_pending: deque[LogEntry] = deque(maxlen=2000)
        self.bridge.on_log_listeners.append(self._log_pending.append)  # called on the asyncio thread
        self.extra: list[BandWindow] = []  # NEW WINDOW: more armbands at once

        self._build_toolbar()
        self._build_body()
        self._connect_signals()

        fps = max(10, min(120, config.gui.fps))
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(int(1000 / fps))
        self._slow = QTimer(self)
        self._slow.timeout.connect(self._tick_slow)
        self._slow.start(250)
        self._frame_times: list[float] = []
        if config.notice:  # the config file had problems: say so instead of failing silently
            self.events.push(LogEntry(time.monotonic(), 0, "warning", config.notice))
            self.statusBar().showMessage("config problems: see the event log", 10000)
        if self._slot is not None:
            self._show_slot(self._slot)
        self._tick_slow()

    def _fit_to_screen(self, w: int, h: int) -> None:
        """Open at w x h, shrunk to the screen's free area (menu bar and Dock excluded)."""
        scr = self.screen() or QGuiApplication.primaryScreen()
        if scr is not None:
            av = scr.availableGeometry()
            w, h = min(w, av.width()), min(h, av.height() - 28)  # 28: title bar
        self.resize(w, h)

    # ------------------------------------------------------------------ build
    def _build_toolbar(self) -> None:
        tb = QToolBar("osc"); tb.setMovable(False)
        self.addToolBar(tb)
        word = _Wordmark('<span style="font-weight:600">OSA</span> <span style="font-weight:300">MYO Controller</span>')
        word.setObjectName("wordmark"); word.setTextFormat(Qt.RichText)
        word.setCursor(Qt.PointingHandCursor); word.setToolTip("About OSA MYO Controller: authors and credits")
        word.clicked.connect(self.about)
        tb.addWidget(word)
        if QGuiApplication.platformName() == "cocoa":  # the macOS menu bar, outside the window
            menu = self.menuBar().addMenu("Help")
            a = QAction("About OSA MYO Controller", self); a.setMenuRole(QAction.AboutRole)  # → app menu
            a.triggered.connect(self.about); menu.addAction(a)
            a = QAction(f"Oscilla Creations ({credits.CONTACT})", self); a.setMenuRole(QAction.NoRole)
            a.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(credits.CONTACT_URL)))
            menu.addAction(a)
        tb.addWidget(_spacer(theme.S3))
        tb.addWidget(theme.label("OSC OUT", "caption"))
        tb.addWidget(_spacer(theme.S_HALF))
        self.ed_host = QLineEdit(self.config.osc.host); self.ed_host.setFixedWidth(124)
        self.ed_host.setToolTip("OSC target host")
        self.ed_port = QLineEdit(str(self.config.osc.port)); self.ed_port.setFixedWidth(64)
        self.ed_port.setToolTip("OSC target port")
        tb.addWidget(self.ed_host); tb.addWidget(self.ed_port)
        b = QPushButton("APPLY"); b.clicked.connect(self._apply_osc); tb.addWidget(b)
        tb.addWidget(_spacer(theme.S1))
        self.ck_osc = QCheckBox("SEND"); self.ck_osc.setChecked(self.config.osc.enabled)
        self.ck_osc.toggled.connect(self._toggle_osc); tb.addWidget(self.ck_osc)
        tb.addWidget(_spacer(theme.S2))
        self.lbl_info = theme.label(self._info_text(), "label")
        self.lbl_info.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.lbl_info.setMinimumWidth(1); self.lbl_info.setToolTip(self.lbl_info.text())
        tb.addWidget(self.lbl_info)
        b = QPushButton("NEW WINDOW"); b.clicked.connect(lambda: self.open_window())
        b.setToolTip("Open a window for another armband, to watch several at once\n"
                     "(right-click an armband in the list to choose which)")
        tb.addWidget(b)
        b = QPushButton("SETTINGS"); b.clicked.connect(self._settings); tb.addWidget(b)
        b = QPushButton("SAVE CONFIG"); b.setObjectName("accent"); b.clicked.connect(self._save_config); tb.addWidget(b)
        # live counters sit in a permanent widget so transient messages stay readable
        self.lbl_stats = theme.label("", "label")
        self.statusBar().addPermanentWidget(self.lbl_stats)
        self.statusBar().showMessage("ready", 3000)
        self.statusBar().setSizeGripEnabled(False)

    def _build_body(self) -> None:
        bg = theme.Ambient()
        self.setCentralWidget(bg)
        outer = QHBoxLayout(bg); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self.devices = DeviceList([s.id for s in self.bridge.slots])
        outer.addWidget(self.devices)

        center = QWidget()
        g = theme.GAP
        lay = QVBoxLayout(center); lay.setContentsMargins(g, g, g, g); lay.setSpacing(g)
        self.header = HeaderStrip()
        lay.addWidget(self.header)

        # three columns, no bottom row: everything fits a laptop screen without scrolling
        cols = QHBoxLayout(); cols.setSpacing(g)
        self.battery = BatteryPanel()
        self.signal = SignalPanel()
        self.devices.add_footer(self.battery)
        self.devices.add_footer(self.signal)
        self.overrides = Overrides()
        self.orient = Orientation3D()
        self.orient.set_view(self.config.gui.orient_view)
        cols.addWidget(_column(self.overrides, (self.orient, 1), width=392))

        self.imu = ImuStrips(self.config.gui.imu_window_s)
        self.imu.setMinimumWidth(300)
        self.pose = PoseFeed()
        cols.addWidget(_column((self.imu, 1), self.pose), 5)

        self.emg = EmgGrid()
        gc = self.config.gui
        self.emg.apply_settings(gc.emg_window_s, gc.emg_scale, gc.emg_autoscale)
        self.events = EventFeed()
        cols.addWidget(_column((self.emg, 3), (self.events, 1)), 6)
        lay.addLayout(cols, 1)
        outer.addWidget(center, 1)
        self.view = BandView(self.emg, self.orient, self.pose, self.imu)
        theme.polish(self)

    def _connect_signals(self) -> None:
        d, o = self.devices, self.overrides
        d.slot_selected.connect(self._select_slot)
        d.scan_clicked.connect(self._scan)
        d.connect_all_clicked.connect(lambda: self.bt.call(self.bridge.connect_all()))
        d.disconnect_all_clicked.connect(lambda: self.bt.call(self._disconnect_all()))
        d.connect_scan_result.connect(self._connect_result)
        d.rename_requested.connect(self._rename)
        d.window_requested.connect(self.open_window)
        self.pose.tap_origin_toggled.connect(lambda on: self.set_tap_origin(self._slot, on))
        o.connect_clicked.connect(lambda: self._with_slot(lambda s: self.bridge.connect_slot(s)))
        o.disconnect_clicked.connect(lambda: self._with_slot(lambda s: s.device.disconnect()))
        o.unlock.connect(lambda: self._with_dev(lambda dv: dv.unlock(P.UnlockType.HOLD)))
        o.lock.connect(lambda: self._with_dev(lambda dv: dv.lock()))
        o.vibrate.connect(lambda k: self._with_dev(lambda dv: dv.vibrate(k)))
        o.set_origin.connect(lambda: self.set_origin(self._slot))
        o.clear_origin.connect(lambda: self._with_slot(lambda s: self.bridge.clear_zero(s.id)))
        o.mode_changed.connect(self._set_mode)
        o.sleep_changed.connect(self._set_sleep)
        o.resync.connect(self._resync)
        o.power_off.connect(self._power_off)

    # ------------------------------------------------------------------ helpers
    def _with_slot(self, fn) -> None:
        if self._slot is not None:
            self.bt.call(fn(self._slot))

    def _with_dev(self, fn) -> None:
        if self._slot is not None and self._slot.device.state in (DeviceState.CONNECTED, DeviceState.STREAMING):
            self.bt.call(fn(self._slot.device))
        else:
            self.statusBar().showMessage("device not connected", 2000)

    async def _disconnect_all(self) -> None:
        for s in self.bridge.slots:
            await s.device.disconnect()

    def _select_slot(self, sid: int) -> None:
        slot = self.bridge.slot(sid)
        if slot is None or slot is self._slot:
            return
        self._show_slot(slot)

    def _show_slot(self, slot: Slot) -> None:
        self._slot = slot
        self.view.set_slot(slot)
        self.signal.history.clear()
        e = slot.entry
        self.overrides.set_modes(e.emg_mode, e.imu_mode, e.classifier_mode)
        self.overrides.btn_sleep.blockSignals(True)
        self.overrides.btn_sleep.setChecked(e.never_sleep)
        self.overrides.btn_sleep.blockSignals(False)
        self._tick_slow()

    # ------------------------------------------------------------------ armband actions
    def about(self) -> AboutDialog:
        """Authors, contact and credits."""
        dlg = AboutDialog(self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.open()
        return dlg

    def set_origin(self, slot: Slot | None) -> None:
        """SET ORIGIN for ``slot`` (main window or an extra one)."""
        if slot is None:
            return
        if not slot.processor.imu_live(time.monotonic(), ORIGIN_FRESH_S):
            self.statusBar().showMessage(f"{slot.display_name}: {NO_ORIGIN}", 4000)
            return
        self.bt.call(self.bridge.zero(slot.id))

    def set_tap_origin(self, slot: Slot | None, on: bool) -> None:
        """The double-tap pose of ``slot`` sets its origin (on/off)."""
        if slot is None:
            return
        slot.entry.double_tap_origin = on
        msg = f"{slot.display_name}: double tap sets the origin" if on else \
            f"{slot.display_name}: double tap no longer sets the origin"
        if on and slot.device.config.classifier_mode is P.ClassifierMode.DISABLED:
            msg += " (switch POSE on)"
        self.statusBar().showMessage(msg + " · SAVE CONFIG keeps it", 6000)

    def _rename(self, sid: int) -> None:
        slot = self.bridge.slot(sid)
        if slot is None:
            return
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Rename armband")
        dlg.setInputMode(QInputDialog.TextInput)
        dlg.setLabelText(f"Name of MYO {sid}, shown in the monitor (empty = Bluetooth name).\n"
                         "macOS can't rename the band itself. SAVE CONFIG keeps it.")
        dlg.setTextValue(slot.entry.label)
        ed = dlg.findChild(QLineEdit)
        if ed is not None:
            ed.setMaxLength(LABEL_MAX)
            ed.setPlaceholderText(slot.device.name or f"Myo {sid}")
        theme.polish(dlg)
        if dlg.exec() != QDialog.Accepted:
            return
        slot.entry.label = clean_label(dlg.textValue())
        self.statusBar().showMessage(f"MYO {sid} is now “{slot.display_name}” · SAVE CONFIG keeps it", 6000)
        self._tick_slow()

    def open_window(self, sid: int | None = None) -> BandWindow | None:
        """An extra window for armband ``sid`` (default: the first one not on screen yet)."""
        if sid is None:
            shown = {w.slot.id for w in self.extra if w.slot is not None}
            if self._slot is not None:
                shown.add(self._slot.id)
            free = [s.id for s in self.bridge.slots if s.id not in shown]
            sid = free[0] if free else (self._slot.id if self._slot is not None else None)
        slot = self.bridge.slot(sid) if sid is not None else None
        if slot is None:
            return None
        for w in self.extra:  # already open: bring it forward
            if w.slot is slot:
                w.raise_(); w.activateWindow()
                return w
        w = BandWindow(self, slot)
        w.closed.connect(self._window_closed)
        self.extra.append(w)
        w.show()
        return w

    def _window_closed(self, w: BandWindow) -> None:
        if w in self.extra:
            self.extra.remove(w)

    def _views(self) -> list[BandView]:
        return [self.view] + [w.view for w in self.extra]

    def _scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self.devices.set_scanning(True)
        fut = self.bt.call(self.bridge.scanner.scan(timeout=self.config.scan_timeout_s, myo_only=False))

        def done(f) -> None:
            self._scan_results = None
            try:
                res = f.result()
                res.sort(key=lambda r: (not r.is_myo, -(r.rssi or -999)))
                self._scan_results = res
            except Exception as e:  # noqa: BLE001
                self._scan_error = str(e)
        fut.add_done_callback(done)
        self._scan_results = None
        self._scan_error = None
        self._scan_fut = fut

    def _poll_scan(self) -> None:
        if self._scanning and self._scan_fut.done():
            self._scanning = False
            self.devices.set_scanning(False)
            if self._scan_error:
                self.statusBar().showMessage(f"scan failed: {self._scan_error}", 5000)
            elif self._scan_results is not None:
                self.devices.set_scan_results(self._scan_results)
                n = sum(1 for r in self._scan_results if r.is_myo)
                self.statusBar().showMessage(f"scan: {n} Myo, {len(self._scan_results)} devices", 5000)

    def _connect_result(self, sid: int, address: str) -> None:
        slot = self.bridge.slot(sid)
        if slot is None:
            return
        name = None
        for r in (self._scan_results or []):
            if r.address == address:
                name = r.name
        self.bt.call(self.bridge.connect_address(slot, address, name))

    def _resync(self) -> None:
        if self._slot is None:
            return
        if self._slot.device.state not in (DeviceState.CONNECTED, DeviceState.STREAMING):
            self.statusBar().showMessage("device not connected", 2000)
            return
        self.overrides.set_modes(self._slot.entry.emg_mode, self._slot.entry.imu_mode, 1)
        self._slot.entry.classifier_mode = 1
        self.bt.call(self.bridge.resync(self._slot.id))
        self.statusBar().showMessage("classifier reset: wave out and hold to sync", 6000)

    def _power_off(self) -> None:
        slot = self._slot
        if slot is None or slot.device.state is DeviceState.DISCONNECTED:
            return
        name = slot.display_name
        box = QMessageBox(QMessageBox.Warning, "Power off",
                          f"Switch {name} off?\n\nThe band goes into deep sleep and wakes up only "
                          "when it is plugged into USB power.", QMessageBox.Cancel, self)
        ok = box.addButton("POWER OFF", QMessageBox.AcceptRole)
        ok.setObjectName("danger")
        box.setDefaultButton(QMessageBox.Cancel)
        theme.polish(box)
        box.exec()
        if box.clickedButton() is not ok:
            return
        self.bt.call(self.bridge.power_off(slot.id))
        self.statusBar().showMessage(f"{name}: powering off", 4000)

    def _set_mode(self, emg: int, imu: int, cls: int) -> None:
        if self._slot is None:
            return
        e = self._slot.entry
        smooth_now = emg == P.EmgMode.SMOOTH and e.emg_mode != P.EmgMode.SMOOTH
        e.emg_mode, e.imu_mode, e.classifier_mode = emg, imu, cls
        dev = self._slot.device
        dev.config.emg_mode, dev.config.imu_mode, dev.config.classifier_mode = (
            P.EmgMode(emg), P.ImuMode(imu), P.ClassifierMode(cls))
        self._slot.rms_latest = (0.0,) * 8
        if dev.state in (DeviceState.CONNECTED, DeviceState.STREAMING):
            self.bt.call(dev.set_mode(emg, imu, cls))
        if smooth_now and (hint := self.bridge.emg_hint(self._slot)):
            self.bridge.note(self._slot.id, "warning", hint)

    def _set_sleep(self, never: bool) -> None:
        if self._slot is None:
            return
        self._slot.entry.never_sleep = never
        dev = self._slot.device
        dev.config.never_sleep = never
        if dev.state in (DeviceState.CONNECTED, DeviceState.STREAMING):
            self.bt.call(dev.set_sleep_mode(P.SleepMode.NEVER_SLEEP if never else P.SleepMode.NORMAL))

    def _apply_osc(self) -> None:
        host = self.ed_host.text().strip() or "127.0.0.1"
        try:
            port = int(self.ed_port.text())
        except ValueError:
            self.statusBar().showMessage("invalid port", 3000)
            return
        self.config.osc.host, self.config.osc.port = host, port
        self.bt.call_soon(self.bridge.osc.set_target, host, port)
        self.statusBar().showMessage(f"OSC → {host}:{port}", 3000)

    def _toggle_osc(self, on: bool) -> None:
        self.config.osc.enabled = on
        self.bridge.osc.enabled = on

    def _settings(self) -> None:
        from myo_bridge.gui.settings import SettingsDialog

        adapter = (self.config.transport, self.config.dongle_port)
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self.bt.call_soon(self.bridge.apply_settings)
        if (self.config.transport, self.config.dongle_port) != adapter:
            self._switch_adapter()
        for s in self.bridge.slots:
            s.device.config.never_sleep = s.entry.never_sleep
        self.ed_host.setText(self.config.osc.host); self.ed_port.setText(str(self.config.osc.port))
        self.ck_osc.blockSignals(True); self.ck_osc.setChecked(self.config.osc.enabled); self.ck_osc.blockSignals(False)
        self.lbl_info.setText(self._info_text()); self.lbl_info.setToolTip(self.lbl_info.text())
        if dlg.save_requested:
            self._save_config()
        else:
            self.statusBar().showMessage("settings applied (not saved)", 3000)

    def _switch_adapter(self) -> None:
        """Disconnect everything and rebuild the slots' transports for the chosen adapter."""
        c = self.config
        self.bt.call(self.bridge.set_transport(c.transport, c.dongle_port))
        self._scan_results = None
        self.devices.set_scan_results([])
        self.statusBar().showMessage(f"adapter: {ADAPTERS.get(c.transport, c.transport)}: "
                                     "connect the armbands again", 8000)

    def _info_text(self) -> str:
        c = self.config
        return (f"{ADAPTERS.get(c.transport, c.transport)}  ·  preset {c.osc.preset}  ·  mode {c.osc.mode}  ·  "
                f"control in :{c.osc_in.port if c.osc_in.enabled else 'off'}")

    def _save_config(self) -> None:
        g = self.config.gui
        g.emg_window_s = self.emg.window_s
        g.emg_scale = self.emg.scales["emg"]
        g.emg_autoscale = self.emg.autoscale
        g.orient_view = self.orient.view
        try:
            path = save_config(self.config)
        except OSError as e:
            self.statusBar().showMessage(f"could not save the config: {e}", 8000)
            return
        self.statusBar().showMessage(f"saved {path}", 4000)

    # ------------------------------------------------------------------ timers
    def _tick(self) -> None:
        now = time.monotonic()
        # every slot is drained, shown or not, so a window opened later starts with fresh data
        batches = {s.id: drain(s) for s in self.bridge.slots}
        for v in self._views():
            if v.slot is not None:
                v.feed(batches.get(v.slot.id), now)
            v.refresh()
        self._frame_times.append(now)
        if len(self._frame_times) > 120:
            del self._frame_times[:60]

    def _tick_slow(self) -> None:
        self._poll_scan()
        views = self._views()
        while self._log_pending:
            try:
                e = self._log_pending.popleft()
            except IndexError:
                break
            self.events.push(e)
            for v in views:
                v.log(e)
        self.events.refresh()
        self.devices.update_from(self.bridge.slots)
        now = time.monotonic()
        for w in list(self.extra):
            w.slow(now)
        slot = self._slot
        if slot is None:
            return
        dev = slot.device
        self.header.update_from(dev, slot.entry.label.strip() or None)
        self.battery.update_from(dev)
        self.signal.update_from(dev, slot.processor.emg_latency_ms, self.bridge.osc.sent_messages)
        self.view.slow(now)
        self.overrides.set_connected(dev.state is not DeviceState.DISCONNECTED,
                                     dev.state in (DeviceState.CONNECTED, DeviceState.STREAMING))
        ft = self._frame_times
        fps = (len(ft) - 1) / (ft[-1] - ft[0]) if len(ft) > 10 and ft[-1] > ft[0] else 0.0
        osc = self.bridge.osc
        self.lbl_stats.setText(
            f"GUI {fps:.0f} FPS    ·    OSC {osc.target[0]}:{osc.target[1]}   MSGS {osc.sent_messages}   "
            f"DATAGRAMS {osc.sent_datagrams}   ERRORS {osc.send_errors}    ·    CONTROL IN "
            f"{self.bt.server.received if self.bt.server else '-'}")

    # ------------------------------------------------------------------ close
    def closeEvent(self, ev) -> None:  # noqa: N802
        for w in list(self.extra):
            w.close()
        self.timer.stop(); self._slow.stop()
        self.statusBar().showMessage("disconnecting… (restoring sleep mode)")
        self.bt.stop()
        super().closeEvent(ev)
