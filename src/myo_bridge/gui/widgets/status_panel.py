"""Header strip + battery + link panels (MyoDiagnostics top row)."""

from __future__ import annotations

import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from myo_bridge.gui import theme
from myo_bridge.gui.theme import Meter, Panel, Pill, label
from myo_bridge.myo import protocol as P
from myo_bridge.myo.device import DeviceState, MyoDevice

# kept for older imports
Indicator = Pill


def field(caption: str, w: QWidget, spacing: int = theme.S_HALF) -> QVBoxLayout:
    """Caption above a value/control, top-aligned so fields line up across a row."""
    col = QVBoxLayout()
    col.setSpacing(spacing)
    col.setContentsMargins(0, 0, 0, 0)
    col.addWidget(label(caption, "caption"))
    col.addWidget(w)
    col.addStretch(1)
    return col


def fixed_for(lab: QLabel, *samples: str, extra: int = 4) -> QLabel:
    """Give ``lab`` the width of its widest expected text, so the layout doesn't move with data."""
    fm = lab.fontMetrics()
    lab.setFixedWidth(max(fm.horizontalAdvance(s) for s in samples) + extra)
    return lab


def set_fitted(lab: QLabel, text: str, tip: str = "") -> None:
    """Show ``text`` elided to the label's fixed width; the full text goes to the tooltip."""
    shown = lab.fontMetrics().elidedText(text, Qt.ElideMiddle, lab.maximumWidth())
    if lab.text() != shown:
        lab.setText(shown)
    lab.setToolTip(tip or (text if shown != text else ""))


def vline() -> QFrame:
    f = QFrame()
    f.setFixedWidth(1)
    f.setStyleSheet(f"background: {theme.LINE};")
    return f


class HeaderStrip(Panel):
    def __init__(self, parent=None) -> None:
        super().__init__(None, parent)
        row = QHBoxLayout()
        row.setSpacing(theme.S3)
        row.setContentsMargins(0, 0, 0, 0)
        self.body.addLayout(row)

        self.badge = QLabel("MYO 1")
        self.badge.setFont(theme.font("button"))
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedSize(64, 40)
        self.badge.setStyleSheet(f"color: {theme.COPPER}; background: rgba(217,142,90,0.10);"
                                 f" border: 1px solid {theme.COPPER_DEEP}; border-radius: {theme.R_CTRL}px;")
        row.addWidget(self.badge, 0, Qt.AlignVCenter)

        self.status = fixed_for(label("DISCONNECTED", "big_dim"),
                                *(s.value.upper() for s in DeviceState))
        row.addLayout(field("STATUS", self.status, 0))
        row.addWidget(vline())

        self.sync = Pill("UNSYNCED")
        self.sync.setMinimumWidth(self.sync.sizeHint().width())  # widest text: no jump on sync
        row.addLayout(field("SYNC", self.sync))
        self.lock = Pill("UNLOCKED")
        self.lock.setMinimumWidth(self.lock.sizeHint().width())
        self.lock.setText("LOCKED")
        row.addLayout(field("LOCK", self.lock))

        arm = QWidget()
        al = QHBoxLayout(arm); al.setContentsMargins(0, 0, 0, 0); al.setSpacing(theme.S_HALF)
        self.arm_l = Pill("L", compact=True); self.arm_r = Pill("R", compact=True)
        self.arm_l.setFixedWidth(32); self.arm_r.setFixedWidth(32)
        self.arm_text = fixed_for(label("—", "value_sm"), "not on arm", "x → elbow", "x → wrist")
        al.addWidget(self.arm_l); al.addWidget(self.arm_r); al.addSpacing(theme.S1); al.addWidget(self.arm_text)
        row.addLayout(field("ARM", arm))

        row.addStretch(1)
        row.addWidget(vline())
        # fixed widths: the strip keeps its size whatever the band reports (long names are
        # elided, full text in the tooltip); the address is in the DEVICE tooltip
        grid = QGridLayout(); grid.setHorizontalSpacing(theme.S2); grid.setVerticalSpacing(theme.S_HALF)
        self.name = label("—", "value_sm"); self.name.setFixedWidth(112)
        self.serial = fixed_for(label("—", "value_sm"), "00-00-00-00-00-00")
        self.fw = fixed_for(label("—", "value_sm"), "1.5.1970.2", "FIRMWARE")
        for i, (cap, w) in enumerate((("DEVICE", self.name), ("SERIAL", self.serial), ("FIRMWARE", self.fw))):
            grid.addWidget(label(cap, "caption"), 0, i)
            grid.addWidget(w, 1, i)
        row.addLayout(grid)

    def update_from(self, dev: MyoDevice, name: str | None = None) -> None:
        """``name``: the name given in the monitor, shown instead of the Bluetooth name."""
        self.badge.setText(f"MYO {dev.id}")
        st = dev.state
        self.status.setText(st.value.upper())
        live = st in (DeviceState.STREAMING, DeviceState.CONNECTED)
        color = {DeviceState.STREAMING: theme.INK, DeviceState.CONNECTED: theme.INK_2,
                 DeviceState.CONNECTING: theme.INK_3, DeviceState.RECONNECTING: theme.COPPER}.get(st, theme.GHOST)
        self.status.setStyleSheet(f"color: {color};")
        self.sync.set_state(dev.synced if live else None, "SYNCED" if dev.synced else "UNSYNCED")
        self.lock.set_state((not dev.locked) if st == DeviceState.STREAMING else None,
                            "LOCKED" if dev.locked else "UNLOCKED")
        arm = dev.arm.label if dev.arm is not None else "unknown"
        self.arm_l.set_state(True if arm == "left" else None)
        self.arm_r.set_state(True if arm == "right" else None)
        xd = dev.x_direction.label if dev.x_direction is not None else "—"
        self.arm_text.setText(f"x → {xd}" if arm != "unknown" else "not on arm")
        self.arm_text.setToolTip(f"{arm} arm, band +x toward the {xd}" if arm != "unknown" else "")
        tip = "\n".join(t for t in ((name or ""), f"Bluetooth name: {dev.name}" if dev.name else "",
                                     f"address: {dev.address}" if dev.address else "") if t)
        set_fitted(self.name, name or dev.name or "—", tip)
        set_fitted(self.serial, dev.info.serial if dev.info else "—")
        set_fitted(self.fw, dev.firmware.short if dev.firmware else "—")


class BatteryPanel(Panel):
    def __init__(self, parent=None) -> None:
        super().__init__("Battery", parent)
        self.pct = self.add_head(label("—", "value"))
        self.bar = Meter()
        self.body.addWidget(self.bar)
        self.checked = label("not read yet", "label")
        self.body.addWidget(self.checked)
        self._last_level = None

    def update_from(self, dev: MyoDevice) -> None:
        lvl = dev.battery
        if lvl is None:
            self.pct.setText("—"); self.bar.set_value(0); return
        if lvl != self._last_level:
            self._last_level = lvl
            self.checked.setText("last checked " + time.strftime("%H:%M:%S"))
        self.pct.setText(f"{lvl}%")
        self.bar.set_value(lvl / 100.0, None if lvl > 20 else theme.BAD)


class SignalPanel(Panel):
    """Bluetooth signal %, RSSI history bars, plus link stats (rates, drops, latency)."""

    def __init__(self, parent=None) -> None:
        super().__init__("Link", parent)
        self.pct = self.add_head(label("—", "value"))
        self.widget = pg.PlotWidget()
        p = self.widget.getPlotItem()
        p.hideAxis("left"); p.hideAxis("bottom"); p.setMenuEnabled(False); p.hideButtons()
        p.setMouseEnabled(x=False, y=False)
        p.setYRange(0, 100, padding=0); p.setXRange(-0.5, 59.5, padding=0)
        p.getViewBox().setBorder(None)
        p.layout.setContentsMargins(0, 0, 0, 0)
        self.track = pg.BarGraphItem(x=list(range(60)), height=[100] * 60, width=0.7,
                                     brush=theme.rgba("#FFFFFF", 0.04), pen=None)
        self.bars = pg.BarGraphItem(x=[], height=[], width=0.7, brush=theme.CYAN, pen=None)
        p.addItem(self.track); p.addItem(self.bars)
        self.widget.setFixedHeight(32)
        self.body.addWidget(self.widget)
        self.history: deque[float] = deque(maxlen=60)
        grid = QGridLayout(); grid.setHorizontalSpacing(theme.S2); grid.setVerticalSpacing(theme.S_HALF)
        self.k: dict[str, QLabel] = {}
        for i, (key, cap) in enumerate((("rssi", "RSSI"), ("emg", "EMG Hz"), ("imu", "IMU Hz"),
                                         ("drop", "DROP"), ("lat", "LAT ms"), ("osc", "OSC"))):
            r, c = divmod(i, 3)  # 3 x 2: fits the sidebar
            grid.addWidget(label(cap, "label"), 2 * r, c)
            v = label("—", "value_sm"); grid.addWidget(v, 2 * r + 1, c); self.k[key] = v
            grid.setColumnStretch(c, 1)
        self.body.addSpacing(theme.S_HALF)
        self.body.addLayout(grid)
        self._last_rssi = None

    @staticmethod
    def rssi_to_pct(rssi: int) -> int:
        return int(max(0, min(100, (rssi + 100) * 2)))  # -100 dBm → 0 %, -50 → 100 %

    def push_rssi(self, rssi: int) -> None:
        self.history.append(self.rssi_to_pct(rssi))

    def update_from(self, dev: MyoDevice, latency_ms: float, osc_msgs: int) -> None:
        if dev.rssi is not None and dev.rssi != self._last_rssi:
            self._last_rssi = dev.rssi
            self.push_rssi(dev.rssi)
        if self.history:
            h = list(self.history)
            off = 60 - len(h)
            self.bars.setOpts(x=[off + i for i in range(len(h))], height=h)
            self.pct.setText(f"{h[-1]}%")
        s = dev.stats
        self.k["rssi"].setText(f"{dev.rssi}" if dev.rssi is not None else "—")
        smooth = dev.config.emg_mode is P.EmgMode.SMOOTH  # 50 Hz envelope packets instead of samples
        self.k["emg"].setText(f"{s.fv_rate_hz if smooth else s.emg_rate_hz:.0f}")
        self.k["imu"].setText(f"{s.imu_rate_hz:.0f}")
        self.k["drop"].setText(str(s.emg_dropped))
        self.k["drop"].setStyleSheet(f"color: {theme.BAD};" if s.emg_dropped else "")
        self.k["lat"].setText(f"{latency_ms:.1f}" if latency_ms else "—")
        self.k["osc"].setText(_short(osc_msgs))


def _short(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1000:.0f}k"
    return str(n)
