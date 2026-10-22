"""Armband Manager-style sidebar: one row per slot plus the scan result list."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from myo_bridge.gui import theme
from myo_bridge.gui.theme import Panel, label
from myo_bridge.myo.device import DeviceState
from myo_bridge.transport.base import ScanResult

DOT = {
    DeviceState.STREAMING: theme.OK,
    DeviceState.CONNECTED: theme.CYAN,
    DeviceState.CONNECTING: theme.AMBER,
    DeviceState.RECONNECTING: theme.COPPER,
    DeviceState.DISCONNECTED: theme.GHOST,
}


class Dot(QWidget):
    """Status dot with a soft glow when live."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.color = theme.GHOST
        self.glow = False

    def set(self, color: str, glow: bool) -> None:
        if (color, glow) != (self.color, self.glow):
            self.color, self.glow = color, glow
            self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        c = QPointF(7, 7)
        if self.glow:
            p.setBrush(theme.rgba(self.color, 0.18)); p.drawEllipse(c, 7, 7)
        p.setBrush(QColor(self.color)); p.drawEllipse(c, 3.5, 3.5)
        p.end()


class SlotRow(Panel):
    clicked = Signal(int)
    rename_requested = Signal(int)
    window_requested = Signal(int)

    def __init__(self, slot_id: int) -> None:
        super().__init__(None, stripe=False, pad=12)
        self.slot_id = slot_id
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(); lay.setSpacing(theme.S1 + 4); lay.setContentsMargins(0, 0, 0, 0)
        self.dot = Dot()
        lay.addWidget(self.dot, 0, Qt.AlignTop)
        col = QVBoxLayout(); col.setSpacing(2)
        self.name = QLabel(f"Myo {slot_id}")
        f = theme.font("body"); f.setWeight(QFont.DemiBold); f.setPixelSize(theme.T_DATA + 1)
        self.name.setFont(f); self.name.setStyleSheet(f"color: {theme.INK};")
        self.sub = label("DISCONNECTED", "label")
        col.addWidget(self.name); col.addWidget(self.sub)
        lay.addLayout(col, 1)
        right = QVBoxLayout(); right.setSpacing(2)
        self.slot_tag = label(f"#{slot_id}", "label"); self.slot_tag.setAlignment(Qt.AlignRight)
        self.rssi = label("", "value_sm"); self.rssi.setAlignment(Qt.AlignRight)
        right.addWidget(self.slot_tag); right.addWidget(self.rssi)
        lay.addLayout(right)
        self.body.addLayout(lay)
        self.set_selected(False)
        self.setToolTip("Double-click to rename · right-click for more")

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self.slot_id)
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self.rename_requested.emit(self.slot_id)

    def contextMenuEvent(self, ev) -> None:  # noqa: N802
        m = QMenu(self)
        m.addAction("Rename…", lambda: self.rename_requested.emit(self.slot_id))
        m.addAction("Open in a new window", lambda: self.window_requested.emit(self.slot_id))
        m.exec(ev.globalPos())

    def update_from(self, dev, name: str | None = None) -> None:
        """``name``: the name given in the monitor (else the Bluetooth name)."""
        self.dot.set(DOT.get(dev.state, theme.GHOST), dev.state == DeviceState.STREAMING)
        self.name.setText(name or dev.name or f"Myo {self.slot_id}")
        sub = dev.state.value.upper()
        if dev.state == DeviceState.STREAMING:
            if dev.battery is not None:
                sub += f" · {dev.battery}%"
        self.sub.setText(sub)
        self.sub.setStyleSheet(f"color: {theme.INK_3};" if dev.state != DeviceState.DISCONNECTED else "")
        self.rssi.setText(f"{dev.rssi} dBm" if dev.rssi is not None else "")


class DeviceList(QWidget):
    slot_selected = Signal(int)
    rename_requested = Signal(int)
    window_requested = Signal(int)
    scan_clicked = Signal()
    connect_all_clicked = Signal()
    disconnect_all_clicked = Signal()
    connect_scan_result = Signal(int, str)  # slot id, address

    def __init__(self, slot_ids: list[int], parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(264)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("sidebar")
        self.setStyleSheet(f"QWidget#sidebar {{ background: {theme.VOID}; border-right: 1px solid {theme.LINE}; }}")
        lay = QVBoxLayout(self); lay.setContentsMargins(theme.S2, theme.S2, theme.S2, theme.S2); lay.setSpacing(theme.S1)
        head = QHBoxLayout()
        head.addWidget(label("Armbands", "title")); head.addStretch(1)
        head.addWidget(label(f"{len(slot_ids)} slots", "label"))
        lay.addLayout(head)
        self.rows: dict[int, SlotRow] = {}
        for sid in slot_ids:
            r = SlotRow(sid)
            r.clicked.connect(self._select)
            r.rename_requested.connect(self.rename_requested)
            r.window_requested.connect(self.window_requested)
            lay.addWidget(r)
            self.rows[sid] = r
        row = QHBoxLayout(); row.setSpacing(theme.S1)
        b = QPushButton("CONNECT ALL"); b.setObjectName("accent"); b.clicked.connect(self.connect_all_clicked); row.addWidget(b)
        b = QPushButton("DISCONNECT"); b.clicked.connect(self.disconnect_all_clicked); row.addWidget(b)
        lay.addSpacing(theme.S_HALF)
        lay.addLayout(row)

        lay.addSpacing(theme.S3)
        sep = QFrame(); sep.setFixedHeight(1); sep.setStyleSheet(f"background: {theme.LINE};")
        lay.addWidget(sep)
        lay.addSpacing(theme.S1)
        head = QHBoxLayout()
        head.addWidget(label("Nearby", "title")); head.addStretch(1)
        self.btn_scan = QPushButton("SCAN"); self.btn_scan.clicked.connect(self.scan_clicked)
        self.btn_scan.setFixedWidth(104)
        head.addWidget(self.btn_scan)
        lay.addLayout(head)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._on_double)
        lay.addWidget(self.list, 1)
        hint = label("Double-click a device to connect it to the selected slot.", "hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self._lay = lay
        self.selected = slot_ids[0] if slot_ids else 1
        self._select(self.selected)

    def add_footer(self, w: QWidget) -> None:
        """Dock a panel (battery, link) under the Nearby list."""
        self._lay.addSpacing(theme.S1)
        self._lay.addWidget(w)

    def _select(self, sid: int) -> None:
        self.selected = sid
        for k, r in self.rows.items():
            r.set_selected(k == sid)
        self.slot_selected.emit(sid)

    def set_scanning(self, on: bool) -> None:
        self.btn_scan.setEnabled(not on)
        self.btn_scan.setText("SCANNING…" if on else "SCAN")

    def set_scan_results(self, results: list[ScanResult]) -> None:
        self.list.clear()
        for r in results:
            it = QListWidgetItem(f"{r.display_name}\n{r.address}   {r.rssi} dBm")
            it.setData(Qt.UserRole, r.address)
            if not r.is_myo:
                it.setForeground(QColor(theme.LABEL))
            self.list.addItem(it)

    def _on_double(self, item: QListWidgetItem) -> None:
        self.connect_scan_result.emit(self.selected, item.data(Qt.UserRole))

    def update_from(self, slots) -> None:
        for s in slots:
            if s.id in self.rows:
                self.rows[s.id].update_from(s.device, s.display_name)
