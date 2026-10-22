"""IMUGraphs: three scrolling strips (gyroscope, accelerometer, orientation quaternion)."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from myo_bridge.gui import theme
from myo_bridge.gui.theme import Panel, label
from myo_bridge.myo import protocol as P

MAX_SECONDS = 20.0


class Ring:
    def __init__(self, cols: int, seconds: float = MAX_SECONDS, rate: int = P.IMU_SAMPLE_RATE_HZ) -> None:
        self.n = int(seconds * rate)
        self.buf = np.zeros((self.n, cols), dtype=np.float32)
        self.i = 0
        self.total = 0

    def push(self, row) -> None:
        self.buf[self.i] = row
        self.i = (self.i + 1) % self.n
        self.total += 1

    def last(self, count: int) -> np.ndarray:
        count = min(count, self.n, self.total)
        if count == 0:
            return self.buf[:0]
        start = (self.i - count) % self.n
        if start + count <= self.n:
            return self.buf[start:start + count]
        return np.concatenate((self.buf[start:], self.buf[:count - (self.n - start)]))


class Strip(QWidget):
    def __init__(self, title: str, unit: str, labels: tuple[str, ...], y_range: tuple[float, float],
                 parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S_HALF)
        head = QHBoxLayout()
        head.setSpacing(theme.S1)
        head.addWidget(label(title, "caption"))
        head.addWidget(label(unit, "label"))
        head.addStretch(1)
        for i, lb in enumerate(labels):
            sw = QLabel()
            sw.setFixedSize(10, 2)
            sw.setStyleSheet(f"background: {theme.AXIS_COLORS[i]}; border-radius: 1px;")
            head.addWidget(sw, 0, Qt.AlignVCenter)
            lab = label(lb, "label")
            lab.setStyleSheet(f"color: {theme.AXIS_COLORS[i]};")
            head.addWidget(lab)
            head.addSpacing(theme.S_HALF)
        lay.addLayout(head)
        self.widget = pg.PlotWidget()
        self.plot = self.widget.getPlotItem()
        theme.style_plot(self.plot, y_range)
        self.plot.getAxis("left").setWidth(36)
        self.plot.layout.setContentsMargins(0, 0, 0, 0)
        self.plot.addItem(pg.InfiniteLine(0, angle=0, pen=pg.mkPen(theme.LINE_2)))
        self.curves = []
        for i in range(len(labels)):
            c = pg.PlotCurveItem(pen=pg.mkPen(theme.AXIS_COLORS[i], width=1.2), skipFiniteCheck=True)
            self.plot.addItem(c)
            self.curves.append(c)
        lay.addWidget(self.widget, 1)
        self.ring = Ring(len(labels))
        self.y_range = y_range

    def refresh(self, t: np.ndarray) -> None:
        data = self.ring.last(len(t))
        if len(data) == 0:
            return
        tt = t[-len(data):]
        for i, c in enumerate(self.curves):
            c.setData(tt, data[:, i])


class ImuStrips(Panel):
    def __init__(self, window_s: float = 5.0, parent=None) -> None:
        super().__init__("IMU", parent, spacing=theme.S2)
        self.window_s = window_s
        self._t = np.linspace(-window_s, 0, int(window_s * P.IMU_SAMPLE_RATE_HZ))
        self.add_head(label(f"{window_s:g} s", "label"))
        self.gyro = Strip("GYRO", "deg/s", ("x", "y", "z"), (-500, 500))
        self.accel = Strip("ACCEL", "g", ("x", "y", "z"), (-5, 5))
        self.quat = Strip("QUAT", "unit", ("x", "y", "z", "w"), (-1, 1))
        for s in (self.gyro, self.accel, self.quat):
            s.widget.setMinimumHeight(52)
            self.body.addWidget(s, 1)
            s.plot.setXRange(-window_s, 0, padding=0)

    def set_window(self, seconds: float) -> None:
        self.window_s = seconds
        self._t = np.linspace(-seconds, 0, int(seconds * P.IMU_SAMPLE_RATE_HZ))
        for s in (self.gyro, self.accel, self.quat):
            s.plot.setXRange(-seconds, 0, padding=0)

    def push(self, frame) -> None:
        """frame: processing.pipeline.ImuFrame (quat is w,x,y,z; strips show x,y,z,w like MyoDiagnostics)."""
        self.gyro.ring.push(frame.gyro)
        self.accel.ring.push(frame.accel)
        w, x, y, z = frame.quat
        self.quat.ring.push((x, y, z, w))

    def clear(self) -> None:
        for s in (self.gyro, self.accel, self.quat):
            s.ring = Ring(len(s.curves))
            for c in s.curves:
                c.setData([], [])

    def refresh(self) -> None:
        for s in (self.gyro, self.accel, self.quat):
            s.refresh(self._t)
