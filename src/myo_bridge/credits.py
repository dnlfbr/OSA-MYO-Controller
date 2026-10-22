"""Authors and credits: shown by the About window (click the wordmark, or the app menu) and by
`osa-myo credits`. The open-source projects below are the ones listed in the README's
*References and licences*; keep the two in step."""

from __future__ import annotations

from dataclasses import dataclass

from myo_bridge import __version__

AUTHORS = ("Daniele Fabris", "Simone Arganini")
YEAR = 2026
CONTACT = "www.oscillacreations.com"
CONTACT_URL = "https://www.oscillacreations.com"
COPYRIGHT = f"© {YEAR} {', '.join(AUTHORS)}"
TAGLINE = "Open-source project, MIT licence"


@dataclass(frozen=True)
class Credit:
    name: str  # owner/project
    url: str
    licence: str
    what: str  # what this project owes it


# open implementations of the Myo protocol this bridge was written from (no code copied from GPL ones)
SOURCES = (
    Credit("thalmiclabs/myo-bluetooth", "https://github.com/thalmiclabs/myo-bluetooth", "Apache-2.0",
           "myohw.h: UUIDs, commands, data layouts, scale factors"),
    Credit("PerlinWarp/pyomyo", "https://github.com/PerlinWarp/pyomyo", "MIT",
           "BLED112 dongle commands, EMG modes, never-sleep and restore"),
    Credit("Crimson-Crow/pymyo", "https://github.com/Crimson-Crow/pymyo", "MIT",
           "bleak reference: mode payload, IMU / EMG / classifier formats, smooth EMG"),
    Credit("jshahbazi/FreeMyo.py", "https://github.com/jshahbazi/FreeMyo.py", "MIT",
           "macOS specifics and troubleshooting"),
    Credit("iomz/dl-myo", "https://github.com/iomz/dl-myo", "GPL-3.0",
           "protocol knowledge only (GATT table, motion events); no code reused"),
    Credit("francesco-di-maggio/pyomyosc", "https://github.com/francesco-di-maggio/pyomyosc", "MIT",
           "OSC namespace and control messages"),
    Credit("balandinodidonato/MyoMapper", "https://github.com/balandinodidonato/MyoMapper", "MIT-style",
           "the myomapper OSC preset"),
    Credit("balandinodidonato/MyoToolkit", "https://github.com/balandinodidonato/MyoToolkit", "n/a",
           "pointers to the Myo OSC tools"),
    Credit("samyk/myo-osc", "https://github.com/samyk/myo-osc", "unstated",
           "historical OSC layout"),
    Credit("francocruces/MioConnect", "https://github.com/francocruces/MioConnect", "MIT",
           "several bands at once: clean-up, retries, command spacing"),
    Credit("cortinico/myonnaise", "https://github.com/cortinico/myonnaise", "MIT",
           "confirmation of the commands, keep-alive"),
)

# libraries inside the app
LIBRARIES = (
    Credit("bleak", "https://github.com/hbldh/bleak", "MIT", "Bluetooth LE"),
    Credit("PyObjC", "https://github.com/ronaldoussoren/pyobjc", "MIT", "CoreBluetooth bridge"),
    Credit("pyserial", "https://github.com/pyserial/pyserial", "BSD-3-Clause", "BLED112 dongle"),
    Credit("python-osc", "https://github.com/attwad/python-osc", "Unlicense", "OSC"),
    Credit("NumPy", "https://numpy.org", "BSD-3-Clause", "signal processing"),
    Credit("Qt for Python (PySide6)", "https://www.qt.io/qt-for-python", "LGPL-3.0", "user interface"),
    Credit("pyqtgraph", "https://www.pyqtgraph.org", "MIT", "plots"),
    Credit("Typer", "https://typer.tiangolo.com", "MIT", "command line"),
    Credit("tomli-w", "https://github.com/hukkin/tomli-w", "MIT", "configuration file"),
    Credit("PyInstaller", "https://pyinstaller.org", "GPL-2.0 + exception", "app bundle"),
)

FONTS = (
    Credit("Sora, Archivo, IBM Plex Mono, Newsreader", "https://openfontlicense.org", "SIL OFL 1.1",
           "type, bundled in the app"),
)

DISCLAIMER = ("Myo is a trademark of Thalmic Labs / North. Not affiliated with or endorsed by them; "
              "no Thalmic SDK code or assets are included.")


def credits_text() -> str:
    """Plain-text credits (`osa-myo credits`)."""
    lines = [f"OSA MYO Controller {__version__}", TAGLINE, COPYRIGHT, f"Contact: {CONTACT}", ""]
    for title, items in (("Built on the work of", SOURCES), ("Libraries", LIBRARIES), ("Fonts", FONTS)):
        lines.append(f"{title}:")
        lines += [f"  {c.name} ({c.licence}) - {c.what}  {c.url}" for c in items]
        lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)
