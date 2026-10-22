"""About window: version, authors, contact and the open-source work this project is built on.
Opened by clicking the wordmark in the toolbar or from the app menu (About OSA MYO Controller)."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout

from myo_bridge import __version__, credits
from myo_bridge.gui import theme
from myo_bridge.gui.theme import Panel, label


def _link(url: str, text: str) -> str:
    return f'<a href="{escape(url)}" style="color:{theme.CYAN}; text-decoration:none">{escape(text)}</a>'


def credits_html() -> str:
    """The scrolling part: sources, libraries, fonts, design, disclaimer."""
    def section(title: str, items) -> str:
        rows = "".join(
            f'<tr><td style="padding:3px 12px 3px 0">{_link(c.url, c.name)}</td>'
            f'<td style="padding:3px 12px 3px 0; color:{theme.INK_3}">{escape(c.licence)}</td>'
            f'<td style="padding:3px 0; color:{theme.INK_2}">{escape(c.what)}</td></tr>'
            for c in items)
        return (f'<p style="margin:14px 0 4px 0; color:{theme.INK_3}; font-family:{theme.MONO_CSS}; '
                f'font-size:10px; letter-spacing:2px">{escape(title.upper())}</p>'
                f'<table cellspacing="0" style="font-size:12px">{rows}</table>')

    return (f'<div style="color:{theme.INK_2}; font-family:{theme.SANS_CSS}">'
            + section("Built on the work of", credits.SOURCES)
            + section("Libraries", credits.LIBRARIES)
            + section("Fonts", credits.FONTS)
            + f'<p style="margin:14px 0 0 0; font-size:11px; color:{theme.INK_3}">{escape(credits.DISCLAIMER)}</p>'
            + "</div>")


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About OSA MYO Controller")
        self.setMinimumSize(640, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.S3, theme.S3, theme.S3, theme.S2)
        lay.setSpacing(theme.S2)

        top = QHBoxLayout(); top.setSpacing(theme.S2)
        icon = QLabel()
        pm = QPixmap(str(theme.ICON_PATH))
        if not pm.isNull():
            icon.setPixmap(pm.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        top.addWidget(icon, 0, Qt.AlignTop)
        who = QVBoxLayout(); who.setSpacing(theme.S_HALF)
        word = QLabel(f'myo<span style="color:{theme.COPPER}">·</span>bridge')
        word.setObjectName("wordmark"); word.setTextFormat(Qt.RichText)
        who.addWidget(word)
        who.addWidget(label(f"version {__version__} · {credits.TAGLINE}", "caption"))
        who.addSpacing(theme.S1)
        self.authors = label(" · ".join(credits.AUTHORS), "value_ink")
        who.addWidget(self.authors)
        who.addWidget(label(credits.COPYRIGHT, "value_sm"))
        self.contact = QLabel(_link(credits.CONTACT_URL, credits.CONTACT))
        self.contact.setObjectName("value_sm"); self.contact.setTextFormat(Qt.RichText)
        self.contact.setOpenExternalLinks(True)
        who.addWidget(self.contact)
        top.addLayout(who, 1)
        lay.addLayout(top)

        box = Panel(None, stripe=True, pad=theme.S2)
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        self.text.setFrameShape(QTextBrowser.NoFrame)
        self.text.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        self.text.setHtml(credits_html())
        box.body.addWidget(self.text)
        lay.addWidget(box, 1)

        row = QHBoxLayout(); row.addStretch(1)
        b = QPushButton("CLOSE"); b.setObjectName("accent"); b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)
        theme.polish(self)
