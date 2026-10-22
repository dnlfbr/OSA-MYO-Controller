"""One armband's live panels: the main window's monitor and the extra windows (NEW WINDOW) that
show more armbands at the same time.

The main window drains every slot's queues once per frame into a `Batch` and hands it to each
`BandView` showing that slot, so several windows can watch the same or different bands."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from myo_bridge.engine import LogEntry, Slot
from myo_bridge.gui import theme
from myo_bridge.gui.theme import Panel, label
from myo_bridge.gui.widgets.emg_grid import EmgGrid
from myo_bridge.gui.widgets.orientation3d import Orientation3D
from myo_bridge.gui.widgets.pose_feed import PoseFeed
from myo_bridge.myo import protocol as P
from myo_bridge.myo.device import DeviceState

NO_DATA_S = 2.0  # streaming this long without data in the chosen mode: say so on the panel
_ZERO8 = (0.0,) * 8


@dataclass
class Batch:
    """What one GUI frame drained from a slot's queues."""

    emg: list = field(default_factory=list)  # filtered / raw samples (int8 x 8)
    fv: list = field(default_factory=list)  # smooth EMG (uint16 x 8)
    imu: list = field(default_factory=list)  # ImuFrame


def _pop_all(q, out: list, index: int | None = None) -> None:
    while q:
        try:
            x = q.popleft()
        except IndexError:  # emptied by another reader in between
            break
        out.append(x if index is None else x[index])


def drain(slot: Slot) -> Batch:
    b = Batch()
    _pop_all(slot.emg_queue, b.emg, 1)
    _pop_all(slot.fv_queue, b.fv, 1)
    _pop_all(slot.imu_queue, b.imu)
    return b


def notices(emg_mode: P.EmgMode, imu_mode: P.ImuMode, waited: bool,
            emg_quiet: bool, fv_quiet: bool, imu_quiet: bool) -> tuple[str, str]:
    """(EMG notice, IMU notice) for a streaming band: why a view stays empty ('' = it shouldn't)."""
    emg = imu = ""
    if emg_mode is P.EmgMode.NONE:
        emg = "EMG is off. Set smooth, filt. or raw in Controls → MODES."
    elif emg_mode is P.EmgMode.SMOOTH:
        if waited and fv_quiet:
            emg = ("EMG smooth: no data from the band yet. If none arrives, its firmware doesn't "
                   "send this undocumented mode: use filt. or raw.")
    elif waited and emg_quiet:
        emg = "No EMG data from the band."
    if imu_mode is P.ImuMode.NONE:
        imu = "IMU is off. Set data or all in Controls → MODES."
    elif imu_mode is P.ImuMode.EVENTS:
        imu = ("IMU evt: the band sends only tap events (listed in Events), no motion data. "
               "Set all for motion data and taps.")
    elif waited and imu_quiet:
        imu = "No IMU data from the band."
    return emg, imu


class BandView:
    """Feeds one slot into a set of panels and explains the ones that stay empty."""

    def __init__(self, emg: EmgGrid, orient: Orientation3D, pose: PoseFeed, imu=None) -> None:
        self.emg, self.orient, self.pose, self.imu = emg, orient, pose, imu
        self.slot: Slot | None = None
        self._last = {"emg": 0.0, "fv": 0.0, "imu": 0.0}  # when data last arrived
        self._key: tuple | None = None
        self._key_t = 0.0

    def set_slot(self, slot: Slot) -> None:
        self.slot = slot
        self.emg.clear()
        if self.imu is not None:
            self.imu.clear()
        self.orient.reset_arm()
        self.pose.set_pose(slot.device.pose.label)
        self.pose.set_tap_origin(slot.entry.double_tap_origin)
        self._last = dict.fromkeys(self._last, 0.0)
        self._key = None

    def feed(self, b: Batch | None, now: float) -> None:
        slot = self.slot
        if slot is None:
            return
        if b is not None:
            if b.emg:
                self.emg.push(b.emg)
                self._last["emg"] = now
            if b.fv:
                self.emg.push_fv(b.fv)
                self._last["fv"] = now
            if b.imu:
                if self.imu is not None:
                    for fr in b.imu:
                        self.imu.push(fr)
                self.orient.set_frame(b.imu[-1])
                self._last["imu"] = now
        mode = slot.device.config.emg_mode
        self.pose.set_activity(_ZERO8 if mode is P.EmgMode.NONE else slot.rms_latest, mode is P.EmgMode.SMOOTH)

    def refresh(self) -> None:
        self.emg.refresh()
        if self.imu is not None:
            self.imu.refresh()
        self.orient.refresh()
        self.pose.refresh()

    def log(self, e: LogEntry) -> None:
        if self.slot is not None and e.device_id == self.slot.id and "pose" in e.data:
            self.pose.set_pose(e.data["pose"])

    def slow(self, now: float) -> None:
        slot = self.slot
        if slot is None:
            return
        dev = slot.device
        self.pose.set_synced(dev.synced)
        if dev.state is DeviceState.DISCONNECTED:
            self.pose.set_pose("rest")
            self.orient.reset_arm()
        elif dev.synced:
            self.orient.set_arm(dev.arm.label, dev.x_direction.label)
        self.orient.set_has_origin(slot.processor.reference.reference is not None)
        self.pose.set_tap_origin(slot.entry.double_tap_origin)  # may be changed elsewhere
        emg_mode, imu_mode = dev.config.emg_mode, dev.config.imu_mode
        self.emg.set_source("fv" if emg_mode is P.EmgMode.SMOOTH else "emg")
        streaming = dev.state is DeviceState.STREAMING
        key = (slot.id, streaming, emg_mode, imu_mode)
        if key != self._key:
            self._key, self._key_t = key, now
        emg_note = imu_note = ""
        if streaming:
            quiet = {k: now - t > NO_DATA_S for k, t in self._last.items()}
            emg_note, imu_note = notices(emg_mode, imu_mode, now - self._key_t > NO_DATA_S,
                                         quiet["emg"], quiet["fv"], quiet["imu"])
        self.emg.set_notice(emg_note)
        if self.imu is not None:
            self.imu.set_notice(imu_note)
        self.orient.set_notice(imu_note)


class BandWindow(QMainWindow):
    """An extra window for one armband: a status line, orientation and gesture side by side, EMG
    below. Narrow enough for two side by side on a 1440 px screen. Fed by the main window, which
    owns the bridge; closed with it."""

    closed = Signal(object)

    def __init__(self, monitor, slot: Slot) -> None:
        super().__init__(None)
        self.monitor = monitor
        self.setAttribute(Qt.WA_DeleteOnClose)
        bg = theme.Ambient()
        self.setCentralWidget(bg)
        g = theme.GAP
        lay = QVBoxLayout(bg); lay.setContentsMargins(g, g, g, g); lay.setSpacing(g)

        bar = Panel(None, stripe=True, pad=theme.S1 + 4)
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(theme.S2)
        self.cb_slot = QComboBox()
        self.cb_slot.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.cb_slot.setToolTip("Armband shown in this window")
        for s in monitor.bridge.slots:
            self.cb_slot.addItem(self._slot_text(s), s.id)
        row.addWidget(self.cb_slot)
        self.status = label("DISCONNECTED", "value_ink")
        row.addWidget(self.status)
        self.info = label("", "value_sm")
        self.info.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.info.setMinimumWidth(1)  # gives way when the window is narrow (full text in the tooltip)
        row.addWidget(self.info, 1)
        self.btn_origin = QPushButton("SET ORIGIN"); self.btn_origin.setObjectName("accent")
        self.btn_origin.setToolTip("Current orientation of this armband becomes the origin")
        row.addWidget(self.btn_origin)
        bar.body.addLayout(row)
        lay.addWidget(bar)

        top = QHBoxLayout(); top.setSpacing(g)
        self.orient = Orientation3D()
        self.orient.set_view(monitor.orient.view)
        self.orient.lbl_view.hide()  # the menu says it
        self.pose = PoseFeed()
        top.addWidget(self.orient, 1)
        top.addWidget(self.pose, 1)
        lay.addLayout(top, 1)
        self.emg = EmgGrid()
        e = monitor.emg
        self.emg.apply_settings(e.window_s, e.scales["emg"], e.autoscale)
        lay.addWidget(self.emg, 1)
        self.view = BandView(self.emg, self.orient, self.pose)

        self.cb_slot.currentIndexChanged.connect(lambda _i: self.show_slot(self.cb_slot.currentData()))
        self.btn_origin.clicked.connect(lambda: monitor.set_origin(self.view.slot))
        self.pose.tap_origin_toggled.connect(lambda on: monitor.set_tap_origin(self.view.slot, on))
        theme.polish(self)
        self.resize(820, 820)
        self.show_slot(slot.id)

    @staticmethod
    def _slot_text(s: Slot) -> str:
        return f"MYO {s.id} · {s.display_name}"

    @property
    def slot(self) -> Slot | None:
        return self.view.slot

    def show_slot(self, sid: int) -> None:
        slot = self.monitor.bridge.slot(sid)
        if slot is None:
            return
        i = self.cb_slot.findData(sid)
        if i >= 0 and self.cb_slot.currentIndex() != i:
            self.cb_slot.blockSignals(True); self.cb_slot.setCurrentIndex(i); self.cb_slot.blockSignals(False)
        if slot is not self.view.slot:
            self.view.set_slot(slot)
        self.slow(time.monotonic())

    def slow(self, now: float) -> None:
        slot = self.view.slot
        if slot is None:
            return
        for i in range(self.cb_slot.count()):  # names can change (Rename, SETTINGS)
            s = self.monitor.bridge.slot(self.cb_slot.itemData(i))
            if s is not None and self.cb_slot.itemText(i) != self._slot_text(s):
                self.cb_slot.setItemText(i, self._slot_text(s))
        self.setWindowTitle(f"{slot.display_name} · OSA MYO Controller")
        dev = slot.device
        st = dev.state
        self.status.setText(st.value.upper())
        self.status.setStyleSheet(f"color: {theme.INK if st is DeviceState.STREAMING else theme.INK_3};")
        parts = []
        if st is not DeviceState.DISCONNECTED:
            parts.append(f"{dev.arm.label} arm" if dev.synced else "not synced")  # x → in the orientation hint
            if dev.battery is not None:
                parts.append(f"{dev.battery}%")
            if dev.rssi is not None:
                parts.append(f"{dev.rssi} dBm")
            s = dev.stats
            smooth = dev.config.emg_mode is P.EmgMode.SMOOTH
            parts.append(f"EMG {s.fv_rate_hz if smooth else s.emg_rate_hz:.0f} Hz")
            parts.append(f"IMU {s.imu_rate_hz:.0f} Hz")
        text = " · ".join(parts)
        shown = self.info.fontMetrics().elidedText(text, Qt.ElideRight, max(0, self.info.width()))
        if self.info.text() != shown:
            self.info.setText(shown)
        self.info.setToolTip(text if shown != text else "")
        self.btn_origin.setEnabled(st is DeviceState.STREAMING)
        self.view.slow(now)

    def closeEvent(self, ev) -> None:  # noqa: N802
        self.closed.emit(self)
        super().closeEvent(ev)
