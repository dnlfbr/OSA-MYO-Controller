"""GestureFeed: drawn pose pictograms, current pose, EMG activity per pod (no emoji)."""

from __future__ import annotations

import math
import time

import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QSizePolicy, QWidget

from myo_bridge.gui import theme
from myo_bridge.gui.theme import Panel, label

POSES = ("rest", "fist", "wave_in", "wave_out", "fingers_spread", "double_tap")
NAMES = {"fist": "FIST", "wave_in": "WAVE IN", "wave_out": "WAVE OUT",
         "fingers_spread": "SPREAD", "double_tap": "2× TAP"}


def draw_glyph(p: QPainter, pose: str, c: QPointF, s: float, color: QColor) -> None:
    """Minimal line pictograms, 1.5 px strokes with round caps."""
    pen = QPen(color, 1.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if pose == "fist":
        r = QRectF(c.x() - s * 0.55, c.y() - s * 0.45, s * 1.1, s * 0.9)
        p.drawRoundedRect(r, s * 0.25, s * 0.25)
        for i in range(1, 4):  # knuckle lines
            x = r.left() + r.width() * i / 4
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.top() + s * 0.3))
    elif pose == "fingers_spread":
        p.drawEllipse(QPointF(c.x(), c.y() + s * 0.3), s * 0.3, s * 0.3)
        for k in range(5):
            a = math.radians(-160 + k * 35)
            p0 = QPointF(c.x() + math.cos(a) * s * 0.45, c.y() + s * 0.3 + math.sin(a) * s * 0.45)
            p1 = QPointF(c.x() + math.cos(a) * s * 0.85, c.y() + s * 0.3 + math.sin(a) * s * 0.85)
            p.drawLine(p0, p1)
    elif pose in ("wave_in", "wave_out"):
        d = -1 if pose == "wave_in" else 1
        path = QPainterPath()
        path.moveTo(c.x() - d * s * 0.6, c.y() + s * 0.35)
        path.quadTo(c.x() - d * s * 0.1, c.y() - s * 0.45, c.x() + d * s * 0.55, c.y() - s * 0.05)
        p.drawPath(path)
        tip = QPointF(c.x() + d * s * 0.55, c.y() - s * 0.05)
        p.drawLine(tip, QPointF(tip.x() - d * s * 0.32, tip.y() - s * 0.22))
        p.drawLine(tip, QPointF(tip.x() - d * s * 0.18, tip.y() + s * 0.3))
    elif pose == "double_tap":
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(c.x() - s * 0.3, c.y()), s * 0.14, s * 0.14)
        p.drawEllipse(QPointF(c.x() + s * 0.3, c.y()), s * 0.14, s * 0.14)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(color, 1.0))
        p.drawEllipse(QPointF(c.x() - s * 0.3, c.y()), s * 0.32, s * 0.32)
        p.drawEllipse(QPointF(c.x() + s * 0.3, c.y()), s * 0.32, s * 0.32)


class PoseTile(QWidget):
    def __init__(self, pose: str, parent=None) -> None:
        super().__init__(parent)
        self.pose = pose
        self.active = False
        self.setMinimumSize(56, 52)
        f = theme.font("tick")
        f.setCapitalization(f.Capitalization.AllUppercase)
        f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 0.8)
        self.setFont(f)

    def set_active(self, on: bool) -> None:
        if on != self.active:
            self.active = on
            self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3.5, 3.5, -3.5, -3.5)
        if self.active:
            for i, a in enumerate((0.10, 0.06, 0.03)):  # glow, not shadow
                p.setPen(QPen(theme.rgba(theme.CYAN, a), 2))
                p.drawRoundedRect(r.adjusted(-i - 1, -i - 1, i + 1, i + 1), theme.R_CTRL + i, theme.R_CTRL + i)
        p.setPen(QPen(QColor(theme.CYAN if self.active else theme.LINE), 1))
        p.setBrush(theme.rgba("#FFFFFF", 0.06) if self.active else QColor(theme.CARD))
        p.drawRoundedRect(r, theme.R_CTRL, theme.R_CTRL)
        ink = QColor(theme.CYAN if self.active else theme.INK_3)
        draw_glyph(p, self.pose, QPointF(r.center().x(), r.top() + r.height() * 0.40), min(r.height() * 0.42, 22), ink)
        p.setPen(QColor(theme.INK if self.active else theme.INK_3))
        f = self.font()
        p.setFont(f)
        if p.fontMetrics().horizontalAdvance(NAMES[self.pose]) > r.width() - 4:
            f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 0)  # narrow tile: drop the tracking
        p.setFont(f)
        p.drawText(QRectF(r.left(), r.bottom() - 18, r.width(), 14), Qt.AlignCenter, NAMES[self.pose])
        p.end()


class PoseFeed(Panel):
    tap_origin_toggled = Signal(bool)  # the double-tap pose sets the origin (per slot)

    def __init__(self, parent=None) -> None:
        super().__init__("Gesture", parent)
        self.hint = self.add_head(label("perform the sync gesture: wave out and hold", "hint"))
        self.hint.setMinimumWidth(0)
        self.hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.btn_tap_origin = QPushButton("2× TAP → ORIGIN")
        self.btn_tap_origin.setCheckable(True)
        self.btn_tap_origin.setToolTip(
            "On: the double-tap pose sets the orientation origin, like SET ORIGIN, and the band\n"
            "vibrates once. Re-align the yaw from the stage, without the computer.\n"
            "Needs POSE on, a synced band and IMU data. Saved per armband with SAVE CONFIG.")
        self.btn_tap_origin.toggled.connect(self.tap_origin_toggled)
        self.add_head(self.btn_tap_origin)

        row = QHBoxLayout(); row.setSpacing(theme.S1)
        self.tiles: dict[str, PoseTile] = {}
        for name in POSES[1:]:
            t = PoseTile(name)
            row.addWidget(t, 1)
            self.tiles[name] = t
        self.body.addLayout(row)

        g = QGridLayout(); g.setHorizontalSpacing(theme.S3); g.setVerticalSpacing(theme.S_HALF)
        g.addWidget(label("CURRENT POSE", "caption"), 0, 0)
        self.current = label("rest", "big")
        self.current.setMinimumWidth(120)
        g.addWidget(self.current, 1, 0, Qt.AlignTop)
        self.cap_activity = label("POD ACTIVITY · RMS", "caption")
        g.addWidget(self.cap_activity, 0, 1)

        self.widget = pg.PlotWidget()
        p = self.widget.getPlotItem()
        p.hideAxis("left"); p.setMenuEnabled(False); p.hideButtons()
        p.setMouseEnabled(x=False, y=False)
        p.setYRange(0, 1, padding=0); p.setXRange(-0.6, 7.6, padding=0)
        p.getViewBox().setBorder(None)
        p.layout.setContentsMargins(0, 0, 0, 0)
        ax = p.getAxis("bottom")
        ax.setTicks([[(i, str(i)) for i in range(8)]])
        ax.setPen(pg.mkPen(theme.LINE_2)); ax.setTextPen(pg.mkPen(theme.LABEL))
        ax.setStyle(tickFont=theme.font("tick"), tickLength=0)
        ax.setHeight(16)
        self.track = pg.BarGraphItem(x=list(range(8)), height=[1] * 8, width=0.62,
                                     brush=theme.rgba("#FFFFFF", 0.04), pen=None)
        self.bars = pg.BarGraphItem(x=list(range(8)), height=[0] * 8, width=0.62, brush=theme.POD_COLOR, pen=None)
        p.addItem(self.track); p.addItem(self.bars)
        self.widget.setFixedHeight(56)
        g.addWidget(self.widget, 1, 1)
        g.setColumnStretch(1, 1)
        self.body.addSpacing(theme.S_HALF)
        self.body.addLayout(g)
        self.body.addStretch(1)
        self._pose_t = 0.0
        self._pose = "rest"
        self._rms = (0.0,) * 8
        self._gain = 3.0

    def set_pose(self, label_: str) -> None:
        self._pose = label_
        self._pose_t = time.monotonic()

    def set_rms(self, rms) -> None:
        self._rms = rms

    def set_activity(self, values, smooth: bool = False) -> None:
        """Pod bars: RMS of the filtered / raw samples, or the band's smooth EMG (0..1)."""
        self._rms = values
        gain = 1.0 if smooth else 3.0  # rms of norm is small: x3 for visibility
        if gain != self._gain:
            self._gain = gain
            self.cap_activity.setText("POD ACTIVITY · SMOOTH" if smooth else "POD ACTIVITY · RMS")

    def set_tap_origin(self, on: bool) -> None:
        if self.btn_tap_origin.isChecked() != on:
            self.btn_tap_origin.blockSignals(True)
            self.btn_tap_origin.setChecked(on)
            self.btn_tap_origin.blockSignals(False)

    def set_synced(self, synced: bool) -> None:
        self.hint.setText("" if synced else "perform the sync gesture: wave out and hold")

    def refresh(self) -> None:
        self.current.setText(NAMES.get(self._pose, self._pose.replace("_", " ")))
        self.current.setStyleSheet(f"color: {theme.INK if self._pose in self.tiles else theme.GHOST};")
        for name, t in self.tiles.items():
            t.set_active(name == self._pose)
        self.bars.setOpts(height=[min(1.0, v * self._gain) for v in self._rms])
