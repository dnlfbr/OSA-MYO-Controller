"""Qt entry point: start the bridge thread, show the monitor window, run the event loop."""

from __future__ import annotations

import logging
import signal
import sys

from myo_bridge.config import AppConfig

log = logging.getLogger(__name__)


def run_gui(config: AppConfig, autoconnect: bool = True) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from myo_bridge.gui import theme
    from myo_bridge.gui.bridge_thread import BridgeThread
    from myo_bridge.gui.monitor import MonitorWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("OSA MYO Controller")
    theme.apply(app)

    bt = BridgeThread(config)
    bt.start()
    win = MonitorWindow(config, bt)
    win.show()
    if autoconnect:
        bt.call(bt.bridge.connect_all())

    # let Ctrl-C in the terminal close the window cleanly
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keep = QTimer(); keep.start(200); keep.timeout.connect(lambda: None)
    app.aboutToQuit.connect(win.close)
    return app.exec()
