"""EventFeed: timestamped log of device events (JSON-ish, like MyoDiagnostics), colour-coded."""

from __future__ import annotations

import html
import json
import time

from PySide6.QtWidgets import QPushButton, QTextEdit

from myo_bridge.engine import LogEntry
from myo_bridge.gui import theme
from myo_bridge.gui.theme import Panel

MAX_LINES = 400
HANG = 2 * theme.S3  # px


class EventFeed(Panel):
    def __init__(self, parent=None) -> None:
        super().__init__("Events", parent)
        b = QPushButton("CLEAR"); b.clicked.connect(self.clear)
        self.add_head(b)
        self.text = QTextEdit(); self.text.setReadOnly(True)
        self.text.document().setMaximumBlockCount(MAX_LINES)
        self.text.setLineWrapMode(QTextEdit.WidgetWidth)  # long payloads wrap, no side scroll
        self.text.setFont(theme.font("data"))
        self.body.addWidget(self.text, 1)
        self._pending: list[str] = []

    def push(self, e: LogEntry) -> None:
        wall = e.t if e.t > 1e9 else time.time() - (time.monotonic() - e.t)  # entries carry monotonic time
        ts = time.strftime("%H:%M:%S", time.localtime(wall)) + f".{int((wall % 1) * 1000):03d}"
        body = json.dumps(e.data, separators=(", ", ": "), default=str) if e.data else (e.text or "")
        kind_color = (theme.BAD if e.kind in ("error", "warning")
                      else theme.LABEL if "ignored" in e.data else theme.CYAN)
        self._pending.append(  # hanging indent: a wrapped payload lines up under the kind
            f'<p style="margin:0 0 0 {HANG}px; text-indent:-{HANG}px">'
            f'<span style="color:{theme.LABEL}">{ts}</span>&nbsp;&nbsp;'
            f'<span style="color:{theme.COPPER}">myo{e.device_id}</span>&nbsp;&nbsp;'
            f'<span style="color:{kind_color}">{html.escape(f"{e.kind:<10}").replace(" ", "&nbsp;")}</span>&nbsp;'
            f'<span style="color:{theme.INK_2}">{html.escape(body)}</span></p>')

    def refresh(self) -> None:
        if not self._pending:
            return
        for line in self._pending:
            self.text.append(line)
        self._pending.clear()
        sb = self.text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def plain_text(self) -> str:
        return self.text.toPlainText()

    def clear(self) -> None:
        self.text.clear()
