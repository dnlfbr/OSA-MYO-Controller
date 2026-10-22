"""Entry point of the packaged OSA MYO Controller.app: GUI with the saved config, auto-connect."""

from __future__ import annotations

import logging
import os
import sys


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("bleak").setLevel(logging.WARNING)
    # Command-line arguments still work when launched from Terminal: "OSA MYO Controller.app/Contents/MacOS/osa-myo-controller" run --mock
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-psn"):
        from myo_bridge.cli import app

        app(prog_name="osa-myo")
        return 0
    from myo_bridge.config import load_config
    from myo_bridge.gui.app import run_gui

    cfg = load_config(os.environ.get("OSA_MYO_CONFIG") or os.environ.get("MYO_BRIDGE_CONFIG"))
    return run_gui(cfg, autoconnect=True)


if __name__ == "__main__":
    sys.exit(main())
