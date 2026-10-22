"""ManualOverrides: re-sync, lock/unlock, vibrate x3, SET ORIGIN, mode selectors, sleep toggle,
power off."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QPushButton

from myo_bridge.gui import theme
from myo_bridge.gui.theme import Panel, label
from myo_bridge.myo import protocol as P

# what each mode sends (tooltips of the MODES items)
MODE_HELP = {
    "emg": (
        (0, "EMG off", "EMG off: no muscle data"),
        (1, "EMG smooth", ("EMG smooth: the band's own envelope of each pod, 50 Hz (undocumented mode).\n"
                           "Light on the radio, no raw samples. OSC: /myo/<id>/emg/smooth")),
        (2, "EMG filt.", ("EMG filtered: 200 Hz samples per pod, filtered by the band (int8).\n"
                          "OSC: /emg/raw, /emg/rms, /emg/mav")),
        (3, "EMG raw", ("EMG raw: 200 Hz samples per pod, unfiltered (int8).\n"
                        "OSC: /emg/raw, /emg/rms, /emg/mav")),
    ),
    "imu": (
        (0, "IMU off", "IMU off: no motion data, no taps"),
        (1, "IMU data", "IMU data: orientation, acceleration and gyroscope, 50 Hz"),
        (2, "IMU evt", ("IMU events: only tap events (knocks on the band), no motion data,\n"
                        "so the IMU and orientation views stay still")),
        (3, "IMU all", "IMU all: motion data and tap events"),
        (4, "IMU raw", "IMU raw: undocumented mode, handled like data"),
    ),
    "pose": (
        (0, "POSE off", "Pose classifier off: no poses, no sync"),
        (1, "POSE on", "Pose classifier on: poses after the sync gesture (wave out and hold)"),
    ),
}


class Overrides(Panel):
    unlock = Signal()
    lock = Signal()
    vibrate = Signal(int)
    set_origin = Signal()
    clear_origin = Signal()
    mode_changed = Signal(int, int, int)
    sleep_changed = Signal(bool)  # True = never sleep
    connect_clicked = Signal()
    disconnect_clicked = Signal()
    resync = Signal()
    power_off = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Controls", parent)
        self.btn_connect = QPushButton("CONNECT"); self.btn_connect.setObjectName("accent")
        self.btn_connect.clicked.connect(self.connect_clicked)
        self.btn_disconnect = QPushButton("DISCONNECT")
        self.btn_disconnect.clicked.connect(self.disconnect_clicked)
        self.btn_power = QPushButton("POWER OFF"); self.btn_power.setObjectName("danger")
        self.btn_power.setToolTip("Switch the band off (deep sleep). It wakes up only when plugged into USB.")
        self.btn_power.clicked.connect(self.power_off)
        self.add_head(self.btn_connect); self.add_head(self.btn_disconnect)

        # 6-column grid: 3-button rows span 2 columns each, 2-button rows span 3
        g = QGridLayout(); g.setHorizontalSpacing(theme.S1); g.setVerticalSpacing(theme.S1)
        g.setColumnMinimumWidth(0, 64)

        def cap(row: int, text: str) -> None:
            lab = label(text, "caption")
            lab.setFixedHeight(theme.ROW - 4)
            g.addWidget(lab, row, 0)

        def buttons(row: int, items) -> list[QPushButton]:
            span = 6 // len(items)
            out = []
            for i, (text, slot, obj) in enumerate(items):
                b = QPushButton(text)
                if obj:
                    b.setObjectName(obj)
                b.clicked.connect(slot)
                g.addWidget(b, row, 1 + i * span, 1, span)
                out.append(b)
            return out

        cap(0, "POSES")
        self.btn_resync, _, _ = buttons(0, (("RE-SYNC", self.resync, "accent"), ("UNLOCK", self.unlock, None),
                                            ("LOCK", self.lock, None)))
        self.btn_resync.setToolTip("Reset the band's pose classifier, then make the sync gesture\n"
                                   "(wave out and hold) to sync again")
        cap(1, "VIBRATE")
        buttons(1, [(name, (lambda _=False, k=int(kind): self.vibrate.emit(k)), None)
                    for name, kind in (("SHORT", P.VibrationType.SHORT), ("MEDIUM", P.VibrationType.MEDIUM),
                                       ("LONG", P.VibrationType.LONG))])
        cap(2, "ORIGIN")
        buttons(2, (("SET ORIGIN", self.set_origin, "accent"), ("CLEAR", self.clear_origin, None)))

        sep = QFrame(); sep.setFixedHeight(1); sep.setStyleSheet(f"background: {theme.LINE};")
        g.addWidget(sep, 3, 0, 1, 7)

        # one row of three mode selectors; the stream name is part of each item. Each selector is
        # at least as wide as its longest item ("EMG smooth" needs more room than "POSE on")
        cap(4, "MODES")
        modes = QHBoxLayout(); modes.setSpacing(theme.S1)

        def combo(items, current: int) -> QComboBox:
            cb = QComboBox()
            cb.setSizeAdjustPolicy(QComboBox.AdjustToContentsOnFirstShow)  # minimum = longest item, can grow
            for i, (m, lab, tip) in enumerate(items):
                cb.addItem(lab, m)
                cb.setItemData(i, tip, Qt.ToolTipRole)
            cb.setCurrentIndex(current)
            cb.setStyleSheet("QComboBox { padding: 0 2px 0 6px; } QComboBox::drop-down { width: 14px; }")
            cb.currentIndexChanged.connect(lambda i, c=cb: c.setToolTip(c.itemData(i, Qt.ToolTipRole)))
            cb.setToolTip(cb.itemData(current, Qt.ToolTipRole))
            modes.addWidget(cb, 1)
            return cb

        self.cb_emg = combo(MODE_HELP["emg"], 3)
        self.cb_imu = combo(MODE_HELP["imu"], 3)
        self.cb_cls = combo(MODE_HELP["pose"], 1)
        g.addLayout(modes, 4, 1, 1, 6)
        for cb in (self.cb_emg, self.cb_imu, self.cb_cls):
            cb.currentIndexChanged.connect(self._emit_mode)
        cap(5, "POWER")
        self.btn_sleep = QPushButton("NEVER SLEEP"); self.btn_sleep.setCheckable(True); self.btn_sleep.setChecked(True)
        self.btn_sleep.toggled.connect(self._on_sleep)
        g.addWidget(self.btn_sleep, 5, 1, 1, 4)
        g.addWidget(self.btn_power, 5, 5, 1, 2)
        for c in range(1, 7):
            g.setColumnStretch(c, 1)
        self.body.addLayout(g)

    def _emit_mode(self, _i=0) -> None:
        self.mode_changed.emit(int(self.cb_emg.currentData()), int(self.cb_imu.currentData()),
                               int(self.cb_cls.currentData()))

    def _on_sleep(self, on: bool) -> None:
        self.btn_sleep.setText("NEVER SLEEP" if on else "NORMAL SLEEP")
        self.sleep_changed.emit(on)

    def set_modes(self, emg: int, imu: int, cls: int) -> None:
        for cb, v in ((self.cb_emg, emg), (self.cb_imu, imu), (self.cb_cls, cls)):
            cb.blockSignals(True)
            idx = cb.findData(v)
            if idx >= 0:
                cb.setCurrentIndex(idx)
                cb.setToolTip(cb.itemData(idx, Qt.ToolTipRole))
            cb.blockSignals(False)

    def set_connected(self, connected: bool, live: bool | None = None) -> None:
        """connected: not DISCONNECTED; live: link up (re-sync needs it). Defaults to connected."""
        live = connected if live is None else live
        self.btn_connect.setEnabled(not connected)
        self.btn_disconnect.setEnabled(connected)
        self.btn_power.setEnabled(connected)
        self.btn_resync.setEnabled(live)
