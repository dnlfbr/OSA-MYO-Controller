"""EMGGraphs: 8 scrolling plots (pod0..pod7) fed from numpy ring buffers.

Two sources, following the band's EMG mode: ``emg`` (filtered / raw, 200 Hz signed int8; fixed
scales go down to ±2, raw EMG at rest is a few counts) and ``fv`` (smooth: the band's own 50 Hz
envelope, unsigned, nominally 0..1024). AUTO scales every pod on its own, from a high percentile
of |x| over the visible window (single spikes don't flatten the trace), growing at once and
shrinking slowly; each pod's tag shows its current range."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QPushButton,
)

from myo_bridge.gui import theme
from myo_bridge.gui.theme import Panel
from myo_bridge.myo import protocol as P

MAX_SECONDS = 10.0
AUTO_PERCENTILE = 99.5
AUTO_RELEASE = 0.04  # fraction of the gap closed per refresh when the range shrinks


@dataclass(frozen=True)
class Source:
    rate: float  # samples/s
    scales: tuple[int, ...]
    default: int
    auto_min: float  # smallest AUTO range
    signed: bool
    tip: str

    def span(self, v: float) -> tuple[float, float]:
        return (-v, v) if self.signed else (0.0, v)

    def text(self, v: float) -> str:
        """Range as shown in a pod's tag."""
        return f"±{v:.0f}" if self.signed else f"0–{v:.0f}"

    def item(self, v: float) -> str:
        """Range as listed in the scale menu (kept short: the combo is narrow)."""
        return f"±{v:.0f}" if self.signed else f"{v:.0f}"


SOURCES = {
    "emg": Source(P.EMG_SAMPLE_RATE_HZ, (2, 4, 8, 16, 32, 64, 128), 64, 2.0, True,
                  "Y scale (raw int8 units)"),
    "fv": Source(P.FV_SAMPLE_RATE_HZ, (16, 32, 64, 128, 256, 512, 1024, 2048), 1024, 16.0, False,
                 "Y scale: 0 to the chosen value (smooth EMG units, nominally 0–1024)"),
}
SCALES = SOURCES["emg"].scales
AUTO_MIN = SOURCES["emg"].auto_min  # smallest AUTO range (counts)


class EmgRing:
    """Fixed-size ring of (samples x 8) values with a monotonically increasing write index."""

    def __init__(self, seconds: float = MAX_SECONDS, rate: float = P.EMG_SAMPLE_RATE_HZ) -> None:
        self.n = int(seconds * rate)
        self.buf = np.zeros((self.n, 8), dtype=np.float32)
        self.i = 0
        self.total = 0

    def push_many(self, rows) -> None:
        for r in rows:
            self.buf[self.i] = r
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


class EmgGrid(Panel):
    def __init__(self, parent=None) -> None:
        super().__init__("EMG", parent)
        self.rings = {k: EmgRing(MAX_SECONDS, s.rate) for k, s in SOURCES.items()}
        self.source = "emg"
        self.scales = {k: float(s.default) for k, s in SOURCES.items()}  # per source
        self.paused = False
        self.window_s = 2.0
        self.autoscale = False
        self._ranges = np.full(8, self.scale)  # current per-pod y range (AUTO)
        self._t = self._time_axis()

        self.cb_window = QComboBox()
        for s in ("0.5", "1", "2", "5", "10"):
            self.cb_window.addItem(f"{s} s", float(s))
        self.cb_window.setCurrentIndex(2)
        self.cb_window.setToolTip("Time window")
        self.cb_window.currentIndexChanged.connect(self._on_window)
        self.add_head(self.cb_window)
        self.head.addSpacing(theme.S1)
        self.cb_scale = QComboBox()
        self._fill_scales()
        self.cb_scale.currentIndexChanged.connect(self._on_scale)
        self.add_head(self.cb_scale)
        self.ck_auto = QCheckBox("AUTO")
        self.ck_auto.setToolTip("Scale each pod to its own signal (tags show the range)")
        self.ck_auto.toggled.connect(self._on_auto)
        self.add_head(self.ck_auto)
        self.head.addSpacing(theme.S1)
        self.btn_pause = QPushButton("PAUSE")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setFixedWidth(72)
        self.btn_pause.toggled.connect(self._on_pause)
        self.add_head(self.btn_pause)

        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.S2)
        grid.setVerticalSpacing(theme.S1)
        self.plots: list[pg.PlotItem] = []
        self.curves: list[pg.PlotCurveItem] = []
        self.tags: list[pg.TextItem] = []
        self.zeros: list[pg.InfiniteLine] = []
        for ch in range(8):
            w = pg.PlotWidget()
            p = w.getPlotItem()
            theme.style_plot(p, (-self.scale, self.scale))
            p.setXRange(-self.window_s, 0, padding=0)
            p.getAxis("left").setWidth(32)
            p.layout.setContentsMargins(0, 0, 0, 0)
            zero = pg.InfiniteLine(0, angle=0, pen=pg.mkPen(theme.LINE_2))
            p.addItem(zero)
            c = pg.PlotCurveItem(pen=pg.mkPen(theme.POD_COLOR, width=1), skipFiniteCheck=True)
            p.addItem(c)
            tag = pg.TextItem(f"POD {ch}", color=theme.INK_3, anchor=(0, 0),
                              fill=theme.rgba(theme.PANEL, 0.85))  # readable over a full-scale trace
            tag.setFont(theme.font("caption"))
            tag.setZValue(10)
            tag.setParentItem(p.getViewBox())
            tag.setPos(6, 2)
            w.setMinimumHeight(64)
            grid.addWidget(w, ch // 2, ch % 2)
            self.plots.append(p)
            self.curves.append(c)
            self.tags.append(tag)
            self.zeros.append(zero)
        self.body.addLayout(grid, 1)

    # ------------------------------------------------------------------ source
    @property
    def ring(self) -> EmgRing:
        """The ring of the source on screen."""
        return self.rings[self.source]

    @property
    def scale(self) -> float:
        return self.scales[self.source]

    def _time_axis(self) -> np.ndarray:
        return np.linspace(-self.window_s, 0, int(self.window_s * SOURCES[self.source].rate))

    def _fill_scales(self) -> None:
        src, cb = SOURCES[self.source], self.cb_scale
        cb.blockSignals(True)
        cb.clear()
        for s in src.scales:
            cb.addItem(src.item(s), float(s))
        cb.setCurrentIndex(min(range(cb.count()), key=lambda k: abs(cb.itemData(k) - self.scale)))
        cb.setToolTip(src.tip)
        cb.blockSignals(False)

    def set_source(self, source: str) -> None:
        """Show ``emg`` (filtered / raw samples) or ``fv`` (smooth EMG, the band's envelope)."""
        if source == self.source or source not in SOURCES:
            return
        self.source = source
        self._fill_scales()
        self._t = self._time_axis()
        self._ranges[:] = self.scale
        for z in self.zeros:
            z.setVisible(SOURCES[source].signed)
        for c in self.curves:
            c.setData([], [])
        self._apply_ranges()

    def _apply_ranges(self) -> None:
        src = SOURCES[self.source]
        for ch, p in enumerate(self.plots):
            r = self._ranges[ch] if self.autoscale else self.scale
            p.setYRange(*src.span(r), padding=0)
            self.tags[ch].setText(f"POD {ch}  {src.text(r)}" if self.autoscale else f"POD {ch}")

    # ------------------------------------------------------------------ controls
    def apply_settings(self, window_s: float, scale: float, autoscale: bool) -> None:
        """Restore the saved view (GuiConfig; the scale is the filtered / raw one); unknown values
        snap to the nearest option."""
        i = min(range(self.cb_window.count()), key=lambda k: abs(self.cb_window.itemData(k) - window_s))
        self.cb_window.setCurrentIndex(i)
        self.scales["emg"] = float(min(SOURCES["emg"].scales, key=lambda s: abs(s - scale)))
        self._fill_scales()
        self.ck_auto.setChecked(autoscale)
        self._on_auto(autoscale)

    def _on_window(self, _i) -> None:
        self.window_s = float(self.cb_window.currentData())
        self._t = self._time_axis()
        for p in self.plots:
            p.setXRange(-self.window_s, 0, padding=0)

    def _on_scale(self, _i) -> None:
        self.scales[self.source] = float(self.cb_scale.currentData())
        if not self.autoscale:
            self._apply_ranges()

    def _on_auto(self, on: bool) -> None:
        self.autoscale = on
        self.cb_scale.setEnabled(not on)
        self._ranges[:] = self.scale
        self._apply_ranges()

    def _on_pause(self, on: bool) -> None:
        self.paused = on
        self.btn_pause.setText("RESUME" if on else "PAUSE")

    # ------------------------------------------------------------------ data
    def push(self, rows) -> None:
        """Filtered / raw EMG samples (int8 x 8)."""
        self.rings["emg"].push_many(rows)

    def push_fv(self, rows) -> None:
        """Smooth EMG values (uint16 x 8)."""
        self.rings["fv"].push_many(rows)

    def clear(self) -> None:
        self.rings = {k: EmgRing(MAX_SECONDS, s.rate) for k, s in SOURCES.items()}
        for c in self.curves:
            c.setData([], [])

    @staticmethod
    def auto_ranges(data: np.ndarray, current: np.ndarray, floor: float = AUTO_MIN) -> np.ndarray:
        """Next per-pod ranges: attack at once to the robust peak, release slowly."""
        peak = np.percentile(np.abs(data), AUTO_PERCENTILE, axis=0) * 1.25
        target = np.maximum(floor, peak)
        return np.where(target > current, target, current + (target - current) * AUTO_RELEASE)

    def refresh(self) -> None:
        if self.paused:
            return
        n = len(self._t)
        data = self.ring.last(n)
        if len(data) == 0:
            return
        t = self._t[-len(data):]
        if self.autoscale:
            src = SOURCES[self.source]
            new = self.auto_ranges(data, self._ranges, src.auto_min)
            for ch, p in enumerate(self.plots):
                if abs(new[ch] - self._ranges[ch]) > 0.01 * self._ranges[ch]:
                    p.setYRange(*src.span(new[ch]), padding=0)
                    self.tags[ch].setText(f"POD {ch}  {src.text(new[ch])}")
                    self._ranges[ch] = new[ch]
        for ch in range(8):
            self.curves[ch].setData(t, data[:, ch])
