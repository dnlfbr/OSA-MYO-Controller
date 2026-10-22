"""The monitor's look in Qt: colours, fonts, spacing, the panel and meter widgets.

Near-black surfaces, hairline borders, copper for the body,
amber for data values, cyan for active/space, a copper→amber→cyan spectrum stripe on panels,
glow instead of shadow. Fonts by role: Sora (wordmark), Archivo (titles/prose), IBM Plex Mono
(data, labels, buttons), Newsreader italic (captions/hints). Spacing on an 8 px grid.

Qt stylesheets have no letter-spacing or text-transform, so fonts are applied in Python by
`polish()` according to each widget's objectName."""

from __future__ import annotations

from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QLocale, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QSpinBox,
    QDoubleSpinBox,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"
ICON_PATH = HERE / "icon.png"

# ---------------------------------------------------------------- tokens (dark)
VOID = "#000000"
BG = "#0A0A0A"
PANEL = "#0E0E0E"
CARD = "#141414"
ELEV = "#1A1A1A"

LINE = "#1E1E1E"
LINE_2 = "#2A2A2A"
LINE_3 = "#4A4A4A"
GRID = "#161616"

INK = "#FFFFFF"
INK_2 = "#B8B0A8"
INK_3 = "#8A847C"
LABEL = "#555555"
GHOST = "#333333"
DISABLED = "#2A2A2A"

COPPER = "#D98E5A"
COPPER_DEEP = "#B5703F"
AMBER = "#C8A050"
CYAN = "#4FB8C4"
CYAN_DEEP = "#3A8E98"
VERMILION = "#C8502E"
OK = "#5ABF5A"
WARN = "#C8A050"
BAD = "#BF4A4A"
ALERT = "#E0533A"

SURFACE_ON = "rgba(255,255,255,0.08)"
TRACK = "rgba(255,255,255,0.07)"
SPECTRUM = (COPPER, AMBER, CYAN)

# spacing (8 px grid), radii
S_HALF, S1, S2, S3, S4 = 4, 8, 16, 24, 32
GAP = S2           # between panels
PAD = S2           # inside panels
ROW = 28           # control row height
R_CTRL, R_CARD, R_BAR = 6, 12, 3

# data colours
AXIS_COLORS = (COPPER, AMBER, CYAN, INK_2)  # x y z (w)
POD_COLOR = COPPER

# font families (registered from FONT_DIR, with system fallbacks)
SANS = "Archivo"
MONO = "IBM Plex Mono"
WORD = "Sora"
SERIF = "Newsreader"
MONO_CSS = f"'{MONO}', Menlo, monospace"
SANS_CSS = f"'{SANS}', 'Helvetica Neue', sans-serif"

# type scale in px (rem × 16, rounded)
T_CAPTION, T_SM, T_BODY, T_DATA, T_HEAD, T_DISPLAY = 10, 11, 12, 13, 15, 22

# legacy aliases (kept so older call sites keep working)
BG_PANEL, BG_PLOT, BORDER, TEXT, TEXT_DIM = PANEL, PANEL, LINE, INK_2, INK_3
ORANGE, YELLOW, GREEN, RED, WHITE, PURPLE, CYAN_DIM = COPPER, AMBER, OK, BAD, INK, LINE_3, CYAN_DEEP


def rgba(hex_color: str, alpha: float) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


# ---------------------------------------------------------------- fonts
def load_fonts() -> list[str]:
    fams: list[str] = []
    if FONT_DIR.is_dir():
        for f in sorted(FONT_DIR.glob("*.ttf")):
            i = QFontDatabase.addApplicationFont(str(f))
            if i >= 0:
                fams += QFontDatabase.applicationFontFamilies(i)
    return sorted(set(fams))


def font(role: str) -> QFont:
    """Fonts by role. Letter-spacing values are em fractions converted to px."""
    def mk(family, px, weight=QFont.Normal, spacing_em=0.0, upper=False, italic=False):
        f = QFont(family)
        f.setPixelSize(px)
        f.setWeight(weight)
        f.setItalic(italic)
        if spacing_em:
            f.setLetterSpacing(QFont.AbsoluteSpacing, round(px * spacing_em, 2))
        if upper:
            f.setCapitalization(QFont.AllUppercase)
        f.setHintingPreference(QFont.PreferNoHinting)
        return f

    return {
        "body": mk(SANS, T_BODY + 1),
        "title": mk(SANS, T_SM, QFont.DemiBold, 0.26, True),
        "caption": mk(MONO, T_CAPTION, QFont.Normal, 0.2, True),
        "label": mk(MONO, T_CAPTION, QFont.Normal, 0.2, True),
        "hint": mk(SERIF, T_BODY + 1, QFont.Normal, 0.0, False, True),
        "value": mk(MONO, T_DATA, QFont.Medium),
        "value_sm": mk(MONO, T_SM, QFont.Normal),
        "data": mk(MONO, T_SM),
        "display": mk(SANS, T_DISPLAY, QFont.Light, 0.08, True),
        "wordmark": mk(WORD, T_HEAD + 1, QFont.DemiBold, 0.02),
        "button": mk(MONO, T_CAPTION + 1, QFont.Medium, 0.12, True),
        "tick": mk(MONO, 9),
    }[role]


# objectName → (font role, colour)
LABEL_STYLES = {
    "title": ("title", INK_2),
    "caption": ("caption", INK_3),
    "label": ("label", LABEL),
    "hint": ("hint", INK_3),
    "value": ("value", AMBER),
    "value_ink": ("value", INK),
    "value_sm": ("value_sm", INK_2),
    "value_orange": ("value", AMBER),
    "mono": ("data", INK_2),
    "big": ("display", INK),
    "big_dim": ("display", GHOST),
    "wordmark": ("wordmark", INK),
}


def polish(root: QWidget) -> None:
    """Apply role fonts to every child widget (QSS cannot set letter-spacing/uppercase)."""
    widgets = [root] + root.findChildren(QWidget)
    for w in widgets:
        name = w.objectName()
        if isinstance(w, QLabel) and name in LABEL_STYLES:
            w.setFont(font(LABEL_STYLES[name][0]))
        elif isinstance(w, (QAbstractButton, QTabBar)):
            w.setFont(font("button"))
        elif isinstance(w, (QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox)):
            w.setFont(font("data"))
        elif isinstance(w, QPlainTextEdit):
            w.setFont(font("data"))


def label(text: str, kind: str = "caption") -> QLabel:
    lab = QLabel(text)
    lab.setObjectName(kind)
    if kind not in ("hint",):
        lab.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
    if kind in LABEL_STYLES:
        lab.setFont(font(LABEL_STYLES[kind][0]))
    return lab


# ---------------------------------------------------------------- panel component
class Panel(QFrame):
    """Card: panel surface, hairline border, 12 px radius, 2 px spectrum stripe on top.

    `head` holds the title (left) and any controls added with `add_head()` (right);
    `body` is the content layout. Pass `title=None` for a panel without header."""

    def __init__(self, title: str | None = None, parent=None, *, stripe: bool = True,
                 pad: int = PAD, spacing: int = S1) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._stripe = stripe
        self._selected = False
        self._notice: QLabel | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(pad, pad + (2 if stripe else 0), pad, pad)
        outer.setSpacing(spacing + 4 if title else spacing)
        self.head = QHBoxLayout()
        self.head.setContentsMargins(0, 0, 0, 0)
        self.head.setSpacing(S1)
        self.title = None
        if title is not None:
            self.title = label(title, "title")
            self.title.setFixedHeight(ROW - 4)
            self.head.addWidget(self.title)
            self.head.addStretch(1)
            outer.addLayout(self.head)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(spacing)
        outer.addLayout(self.body, 1)

    def add_head(self, w: QWidget) -> QWidget:
        self.head.addWidget(w)
        return w

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self.update()

    def set_notice(self, text: str) -> None:
        """A short message centred over the panel, e.g. why a plot is empty ('' hides it)."""
        n = self._notice
        if n is None:
            if not text:
                return
            n = self._notice = QLabel(self)
            n.setObjectName("notice")
            n.setAlignment(Qt.AlignCenter)
            n.setWordWrap(True)
            n.setFont(font("hint"))
            n.setAttribute(Qt.WA_TransparentForMouseEvents)
            c = QColor(ELEV)
            n.setStyleSheet(f"QLabel#notice {{ color: {INK_2}; background: rgba({c.red()},{c.green()},"
                            f"{c.blue()},0.94); border: 1px solid {LINE_2}; border-radius: {R_CTRL}px;"
                            f" padding: {S1}px {S2}px; }}")
        if text == n.text() and n.isVisible() == bool(text):
            return
        n.setText(text)
        n.setVisible(bool(text))
        if text:
            self._place_notice()
            n.raise_()

    def notice(self) -> str:
        return self._notice.text() if self._notice is not None and self._notice.isVisible() else ""

    def _place_notice(self) -> None:
        n = self._notice
        n.setFixedWidth(max(120, min(self.width() - 2 * S3, 360)))
        n.setFixedHeight(n.heightForWidth(n.width()))
        n.move((self.width() - n.width()) // 2, (self.height() - n.height()) // 2 + S1)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        if self._notice is not None and self._notice.isVisible():
            self._place_notice()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, R_CARD, R_CARD)
        p.fillPath(path, QColor(PANEL))
        if self._stripe:
            p.save()
            p.setClipPath(path)
            g = QLinearGradient(r.left(), 0, r.right(), 0)
            g.setColorAt(0.0, QColor(COPPER)); g.setColorAt(0.5, QColor(AMBER)); g.setColorAt(1.0, QColor(CYAN))
            p.fillRect(QRectF(r.left(), r.top(), r.width(), 2), g)
            p.restore()
        p.setPen(QPen(QColor(CYAN if self._selected else LINE), 1))
        p.drawPath(path)
        p.end()


class Meter(QWidget):
    """Meter: 6 px track, 3 px radius, spectrum (or solid) fill, value 0..1."""

    def __init__(self, parent=None, *, height: int = 6, solid: str | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self._v = 0.0
        self._solid = solid

    def set_value(self, v: float, solid: str | None = None) -> None:
        self._v = max(0.0, min(1.0, float(v)))
        self._solid = solid
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(rgba("#FFFFFF", 0.07))
        p.drawRoundedRect(r, R_BAR, R_BAR)
        if self._v > 0:
            fr = QRectF(r.left(), r.top(), max(r.height(), r.width() * self._v), r.height())
            if self._solid:
                p.setBrush(QColor(self._solid))
            else:
                g = QLinearGradient(r.left(), 0, r.right(), 0)
                g.setColorAt(0.0, QColor(COPPER)); g.setColorAt(0.5, QColor(AMBER)); g.setColorAt(1.0, QColor(CYAN))
                p.setBrush(g)
            p.drawRoundedRect(fr, R_BAR, R_BAR)
        p.end()


class Pill(QLabel):
    """Status pill (radius 999): off = ghost, on = cyan glow surface, warn = copper."""

    def __init__(self, text: str, parent=None, *, compact: bool = False) -> None:
        super().__init__(text, parent)
        self._pad = 0 if compact else 12
        self.setAlignment(Qt.AlignCenter)
        self.setFont(font("button"))
        self.setFixedHeight(ROW - 4)
        self.setMinimumWidth(24 if compact else 40)
        self.set_state(None)

    def set_state(self, on: bool | None, text: str | None = None) -> None:
        if text is not None:
            self.setText(text)
        if on is None:
            color, border, bg = GHOST, LINE_2, "transparent"
        elif on:
            color, border, bg = CYAN, CYAN_DEEP, "rgba(79,184,196,0.10)"
        else:
            color, border, bg = COPPER, COPPER_DEEP, "rgba(217,142,90,0.08)"
        self.setStyleSheet(f"color: {color}; background: {bg}; border: 1px solid {border};"
                           f" border-radius: {(ROW - 4) // 2}px; padding: 0 {self._pad}px;")


class Ambient(QWidget):
    """Window background: void with faint copper (top-right) and cyan (bottom-left) glows."""

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        r = QRectF(self.rect())
        p.fillRect(r, QColor(BG))
        for center, color in ((QPointF(r.right(), r.top()), COPPER), (QPointF(r.left(), r.bottom()), CYAN)):
            g = QRadialGradient(center, max(r.width(), r.height()) * 0.55)
            g.setColorAt(0.0, rgba(color, 0.07))
            g.setColorAt(1.0, rgba(color, 0.0))
            p.fillRect(r, g)
        p.end()


# ---------------------------------------------------------------- stylesheet
LABEL_QSS = "\n".join(f"QLabel#{name} {{ color: {color}; }}" for name, (_r, color) in LABEL_STYLES.items())
QSS = f"""
QWidget {{ color: {INK_2}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QLabel {{ background: transparent; }}

QPushButton {{ background: {CARD}; border: 1px solid {LINE_2}; color: {INK_2};
    padding: 0 12px; min-height: {ROW - 4}px; max-height: {ROW - 4}px;
    border-radius: {R_CTRL}px; }}
QPushButton:hover {{ background: {ELEV}; color: {INK}; border-color: {LINE_3}; }}
QPushButton:pressed {{ background: {SURFACE_ON}; }}
QPushButton:checked {{ background: {SURFACE_ON}; color: {CYAN}; border-color: {CYAN}; }}
QPushButton:disabled {{ background: transparent; color: {GHOST}; border-color: {LINE}; }}
QPushButton#accent {{ color: {COPPER}; border-color: {COPPER_DEEP}; }}
QPushButton#accent:hover {{ background: rgba(217,142,90,0.10); color: {INK}; border-color: {COPPER}; }}
QPushButton#accent:disabled {{ background: transparent; color: {GHOST}; border-color: {LINE}; }}
QPushButton#danger {{ color: {BAD}; border-color: rgba(191,74,74,0.45); }}
QPushButton#danger:hover {{ background: rgba(191,74,74,0.12); color: {INK}; border-color: {BAD}; }}
QPushButton#danger:disabled {{ background: transparent; color: {GHOST}; border-color: {LINE}; }}

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{ background: {CARD}; border: 1px solid {LINE_2};
    border-radius: {R_CTRL}px; padding: 0 8px; min-height: {ROW - 4}px; color: {INK};
    selection-background-color: {CYAN_DEEP}; }}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{ border-color: {LINE_3}; }}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{ border-color: {CYAN}; }}
QComboBox:disabled, QLineEdit:disabled {{ color: {GHOST}; border-color: {LINE}; background: transparent; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{ width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {INK_3}; margin-right: 6px; }}
QComboBox QAbstractItemView {{ background: {ELEV}; border: 1px solid {LINE_2}; color: {INK_2};
    selection-background-color: {SURFACE_ON}; selection-color: {INK}; outline: none; }}

QCheckBox {{ spacing: 8px; color: {INK_2}; background: transparent; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {LINE_3}; border-radius: 4px; background: {CARD}; }}
QCheckBox::indicator:hover {{ border-color: {CYAN}; }}
QCheckBox::indicator:checked {{ background: {CYAN}; border-color: {CYAN}; }}

QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ color: {INK_2}; padding: 8px; border: 1px solid {LINE}; border-radius: {R_CTRL}px;
    margin: 0 0 8px 0; background: {CARD}; font-family: {MONO_CSS}; font-size: {T_SM}px; }}
QListWidget::item:hover {{ border-color: {LINE_3}; }}
QListWidget::item:selected {{ border: 1px solid {CYAN}; background: {SURFACE_ON}; color: {INK}; }}

QPlainTextEdit, QTextEdit {{ background: {BG}; border: 1px solid {LINE}; border-radius: {R_CTRL}px;
    color: {INK_2}; padding: 4px; selection-background-color: {CYAN_DEEP}; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle {{ background: {LINE_2}; border-radius: 2px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {LINE_3}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0; background: none; }}

QSplitter::handle {{ background: {LINE}; width: 1px; }}
QToolBar {{ background: {VOID}; border: none; border-bottom: 1px solid {LINE}; spacing: {S1}px; padding: 10px {S2}px; }}
QToolBar QLabel {{ background: transparent; }}
QStatusBar {{ background: {VOID}; color: {LABEL}; border-top: 1px solid {LINE}; font-family: {MONO_CSS};
    font-size: {T_CAPTION}px; padding: 0 {S1}px; }}
QStatusBar::item {{ border: none; }}

QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: {R_CARD}px; background: {PANEL}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {INK_3}; padding: 8px 16px; border-bottom: 2px solid transparent;
    font-family: {MONO_CSS}; font-size: {T_SM}px; }}
QTabBar::tab:hover {{ color: {INK}; }}
QTabBar::tab:selected {{ color: {CYAN}; border-bottom: 2px solid {CYAN}; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: {R_CARD}px; margin-top: 14px; padding: {S2}px {S1}px {S1}px {S1}px; background: {PANEL}; }}
QGroupBox::title {{ color: {INK_3}; subcontrol-origin: margin; left: 12px; padding: 0 4px; font-size: {T_CAPTION}px; }}
QDialogButtonBox QPushButton {{ min-width: 72px; }}
{LABEL_QSS}
QToolTip {{ background: {ELEV}; color: {INK}; border: 1px solid {LINE_2}; border-radius: 4px; padding: 4px 8px;
    font-family: {MONO_CSS}; font-size: {T_SM}px; }}
"""


def apply(app: QApplication) -> None:
    load_fonts()
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(INK_2))
    pal.setColor(QPalette.Base, QColor(CARD))
    pal.setColor(QPalette.AlternateBase, QColor(PANEL))
    pal.setColor(QPalette.Text, QColor(INK))
    pal.setColor(QPalette.Button, QColor(CARD))
    pal.setColor(QPalette.ButtonText, QColor(INK_2))
    pal.setColor(QPalette.Highlight, QColor(CYAN_DEEP))
    pal.setColor(QPalette.HighlightedText, QColor(INK))
    pal.setColor(QPalette.PlaceholderText, QColor(LABEL))
    app.setPalette(pal)
    app.setFont(font("body"))
    QLocale.setDefault(QLocale.c())  # 6.00, not 6,00: numbers read as in config.toml and OSC
    app.setStyleSheet(QSS)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    pg.setConfigOptions(background=PANEL, foreground=LABEL, antialias=True, useOpenGL=False)


def style_plot(plot: pg.PlotItem, y_range: tuple[float, float] | None = None, show_x: bool = False) -> None:
    plot.showGrid(x=False, y=True, alpha=0.5)
    plot.setMenuEnabled(False)
    plot.hideButtons()
    plot.setMouseEnabled(x=False, y=False)
    for ax in ("left", "bottom"):
        a = plot.getAxis(ax)
        a.setPen(pg.mkPen(LINE_2))
        a.setTextPen(pg.mkPen(LABEL))
        a.setStyle(tickFont=font("tick"), tickLength=-4)
    plot.getAxis("bottom").setStyle(showValues=show_x)
    if not show_x:
        plot.getAxis("bottom").setHeight(4)
    if y_range:
        plot.setYRange(*y_range, padding=0)
    plot.getViewBox().setBorder(None)
