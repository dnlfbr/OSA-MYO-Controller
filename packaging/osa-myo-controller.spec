# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: builds OSA MYO Controller.app (one-dir, arm64 native, no Rosetta).

Build:  uv pip install -e ".[gui,dongle,build]" && uv run pyinstaller packaging/osa-myo-controller.spec
Result: dist/OSA MYO Controller.app  (double-click; macOS asks for Bluetooth permission on first run)
"""
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH (set by PyInstaller) is the directory containing this spec file
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

hidden = (
    collect_submodules("myo_bridge")
    + collect_submodules("bleak")
    + collect_submodules("pythonosc")
    + ["pyqtgraph", "PySide6.QtOpenGL", "serial", "serial.serialposix", "serial.tools.list_ports",
       "serial.tools.list_ports_posix", "serial.tools.list_ports_osx"]
)

a = Analysis(
    [os.path.join(ROOT, "packaging", "app_main.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "config.example.toml"), "."),
        (os.path.join(ROOT, "src", "myo_bridge", "gui", "fonts"), os.path.join("myo_bridge", "gui", "fonts")),
        (os.path.join(ROOT, "src", "myo_bridge", "gui", "icon.png"), os.path.join("myo_bridge", "gui")),
    ],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "IPython", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="osa-myo-controller",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch="arm64",
    codesign_identity=os.environ.get("CODESIGN_IDENTITY"),
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="osa-myo-controller")

app = BUNDLE(
    coll,
    name="OSA MYO Controller.app",
    icon=os.path.join(ROOT, "packaging", "OSA-MYO-Controller.icns"),
    bundle_identifier="com.oscillacreations.osa-myo-controller",
    info_plist={
        "CFBundleName": "OSA MYO Controller",
        "CFBundleDisplayName": "OSA MYO Controller",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.music",
        "NSHumanReadableCopyright": "© 2026 Daniele Fabris, Simone Arganini · www.oscillacreations.com",
        # Without this key macOS kills any process that touches CoreBluetooth (SIGABRT, TCC).
        "NSBluetoothAlwaysUsageDescription":
            "OSA MYO Controller connects to your Myo armbands over Bluetooth to stream EMG and motion data.",
        "NSBluetoothPeripheralUsageDescription":
            "OSA MYO Controller connects to your Myo armbands over Bluetooth to stream EMG and motion data.",
        "LSUIElement": False,
    },
)
