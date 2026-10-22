"""Settings dialog: Bluetooth adapter, OSC output/input, streams, processing, device slots, GUI.
Edits the AppConfig in place; the caller applies it to the running bridge and optionally saves it."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from myo_bridge.config import LABEL_MAX, AppConfig, clean_label
from myo_bridge.gui import theme
from myo_bridge.osc.namespace import PRESETS

ADAPTER_CHOICES = (
    ("bleak", "Built-in Bluetooth (macOS)"),
    ("bled112", "BLED112 USB dongle"),
    ("mock", "Simulated armbands (no hardware)"),
)
AUTO_PORT = "auto-detect"

STREAM_HELP = {
    "emg_raw": "8 int8 per sample, 200 Hz (bundled)", "emg_norm": "raw/128, floats",
    "emg_rms": "RMS of norm over window", "emg_mav": "mean of RMS channels (1 float)",
    "fv": "/emg/smooth: the band's 50 Hz EMG envelope (EMG mode smooth)", "quat": "w x y z, zero applied",
    "quat_raw": "w x y z as received", "euler": "roll pitch yaw rad", "euler_deg": "degrees",
    "euler_norm": "0..1", "accel": "g", "gyro": "deg/s", "pose": "string + /pose/id int",
    "arm": "arm + xdir strings", "sync": "0/1", "lock": "0/1", "battery": "%", "rssi": "dBm",
    "status": "state string", "tap": "direction count (after the tap filter)", "firmware": "once on connect",
}


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("OSA MYO Controller settings")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        tabs.addTab(self._connection_tab(), "CONNECTION")
        tabs.addTab(self._osc_tab(), "OSC")
        tabs.addTab(self._streams_tab(), "STREAMS")
        tabs.addTab(self._processing_tab(), "PROCESSING")
        tabs.addTab(self._devices_tab(), "DEVICES")
        self.buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Apply).setText("APPLY")
        self.buttons.button(QDialogButtonBox.Save).setText("APPLY + SAVE")
        self.buttons.button(QDialogButtonBox.Cancel).setText("CANCEL")
        self.buttons.clicked.connect(self._clicked)
        lay.addWidget(self.buttons)
        lay.setContentsMargins(theme.S2, theme.S2, theme.S2, theme.S2)
        lay.setSpacing(theme.S2)
        self.buttons.button(QDialogButtonBox.Save).setObjectName("accent")
        for form in self.findChildren(QFormLayout):
            form.setHorizontalSpacing(theme.S2)
            form.setVerticalSpacing(theme.S1)
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for i in range(form.rowCount()):  # row names as mono captions, like the monitor's
                item = form.itemAt(i, QFormLayout.LabelRole)
                if item is not None and isinstance(item.widget(), QLabel):
                    item.widget().setObjectName("caption")
            if form.parentWidget() is not None and not isinstance(form.parentWidget(), QGroupBox):
                form.setContentsMargins(theme.S3, theme.S3, theme.S3, theme.S2)
        theme.polish(self)
        self.save_requested = False

    # ------------------------------------------------------------------ tabs
    def _connection_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        self.cb_adapter = QComboBox()
        for kind, text in ADAPTER_CHOICES:
            self.cb_adapter.addItem(text, kind)
        self.cb_adapter.setCurrentIndex(max(0, self.cb_adapter.findData(self.cfg.transport)))
        f.addRow("Bluetooth adapter", self.cb_adapter)
        row = QHBoxLayout(); row.setSpacing(theme.S1)
        self.cb_port = QComboBox(); self.cb_port.setEditable(True); self.cb_port.setMinimumWidth(300)
        self.cb_port.setToolTip("Serial port of the BLED112 (macOS: /dev/cu.usbmodem…). "
                                "auto-detect picks the first dongle found.")
        self.btn_ports = QPushButton("REFRESH"); self.btn_ports.clicked.connect(self._refresh_ports)
        row.addWidget(self.cb_port, 1); row.addWidget(self.btn_ports)
        f.addRow("dongle port", row)
        self.lbl_dongle = QLabel(""); self.lbl_dongle.setObjectName("hint"); self.lbl_dongle.setWordWrap(True)
        f.addRow("", self.lbl_dongle)
        self.sp_scan = QDoubleSpinBox(); self.sp_scan.setRange(1, 60); self.sp_scan.setValue(self.cfg.scan_timeout_s)
        f.addRow("scan timeout s", self.sp_scan)
        hint = QLabel("Changing the adapter disconnects every armband: connect them again afterwards.\n"
                      "Built-in Bluetooth: macOS asks for permission the first time.\n"
                      "BLED112 dongle: a separate radio, independent of macOS Bluetooth; plug it in "
                      "before choosing it. Slots bound by serial find their band with either adapter.")
        hint.setObjectName("hint"); hint.setWordWrap(True); f.addRow("", hint)
        self._dongle_status = ""
        self._refresh_ports()
        self.cb_adapter.currentIndexChanged.connect(self._adapter_changed)
        return w

    def _refresh_ports(self) -> None:
        from myo_bridge.transport.base import TransportError
        from myo_bridge.transport.bled112_transport import list_serial_ports

        want = self.port_value() if self.cb_port.count() else self.cfg.dongle_port
        try:
            ports, err = list_serial_ports(), ""
        except TransportError as e:
            ports, err = [], str(e)
        self.cb_port.clear()
        self.cb_port.addItem(AUTO_PORT, "")
        for dev, desc, likely in ports:
            self.cb_port.addItem(f"{dev}   {desc}{'  · BLED112' if likely else ''}".rstrip(), dev)
        i = self.cb_port.findData(want)
        if i < 0:  # a port that is not plugged in right now: keep it
            self.cb_port.addItem(want, want)
            i = self.cb_port.count() - 1
        self.cb_port.setCurrentIndex(i)
        found = next((dev for dev, _d, likely in ports if likely), None)
        self._dongle_status = err or (f"BLED112 detected on {found}" if found
                                      else "no BLED112 detected: plug it in and press REFRESH")
        self._adapter_changed()

    def port_value(self) -> str:
        """The chosen dongle port; "" = auto-detect."""
        text = self.cb_port.currentText().strip()
        i = self.cb_port.findText(text)
        if i >= 0:
            return self.cb_port.itemData(i) or ""
        return "" if text.lower() in ("", AUTO_PORT) else text

    def _adapter_changed(self, *_args) -> None:
        dongle = self.cb_adapter.currentData() == "bled112"
        self.cb_port.setEnabled(dongle)
        self.btn_ports.setEnabled(dongle)
        self.lbl_dongle.setText(self._dongle_status if dongle else "")
        self.lbl_dongle.setVisible(dongle)

    def _osc_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        o = self.cfg.osc
        self.ed_host = QLineEdit(o.host); f.addRow("target host", self.ed_host)
        self.sp_port = QSpinBox(); self.sp_port.setRange(1, 65535); self.sp_port.setValue(o.port)
        f.addRow("target port", self.sp_port)
        self.ck_enabled = QCheckBox("send OSC"); self.ck_enabled.setChecked(o.enabled); f.addRow("", self.ck_enabled)
        self.cb_preset = QComboBox()
        for p in PRESETS:
            self.cb_preset.addItem(p)
        self.cb_preset.setCurrentText(o.preset); f.addRow("namespace preset", self.cb_preset)
        self.cb_mode = QComboBox(); self.cb_mode.addItems(["vector", "axis"]); self.cb_mode.setCurrentText(o.mode)
        f.addRow("message mode", self.cb_mode)
        hint = QLabel("vector: one message per data type (/emg/raw i×8).\naxis: one message per channel / axis (/emg/raw/0 … /accel/x)")
        hint.setObjectName("hint"); hint.setWordWrap(True); f.addRow("", hint)
        self.sp_bundle = QSpinBox(); self.sp_bundle.setRange(1, 40); self.sp_bundle.setValue(o.emg_bundle_samples)
        f.addRow("EMG samples per bundle (1 = no bundling)", self.sp_bundle)
        self.sp_imu = QDoubleSpinBox(); self.sp_imu.setRange(0, 50); self.sp_imu.setValue(o.imu_rate_hz)
        f.addRow("IMU stream rate Hz (0 = every packet)", self.sp_imu)
        self.sp_rms = QDoubleSpinBox(); self.sp_rms.setRange(0, 200); self.sp_rms.setValue(o.rms_rate_hz)
        f.addRow("RMS/MAV stream rate Hz", self.sp_rms)
        g = QGroupBox("CONTROL INPUT (restart to apply)"); gf = QFormLayout(g)
        i = self.cfg.osc_in
        self.ck_in = QCheckBox("listen"); self.ck_in.setChecked(i.enabled); gf.addRow("", self.ck_in)
        self.ed_in_host = QLineEdit(i.host); gf.addRow("bind host", self.ed_in_host)
        self.sp_in_port = QSpinBox(); self.sp_in_port.setRange(1, 65535); self.sp_in_port.setValue(i.port)
        gf.addRow("port", self.sp_in_port)
        f.addRow(g)
        return w

    def _streams_tab(self) -> QWidget:
        w = QWidget(); g = QGridLayout(w)
        self.stream_boxes: dict[str, QCheckBox] = {}
        for i, (name, on) in enumerate(self.cfg.osc.streams.items()):
            cb = QCheckBox(name); cb.setChecked(on)
            g.addWidget(cb, i % 11, (i // 11) * 2)
            lab = QLabel(STREAM_HELP.get(name, "")); lab.setObjectName("hint"); lab.setWordWrap(True)
            g.addWidget(lab, i % 11, (i // 11) * 2 + 1)
            self.stream_boxes[name] = cb
        return w

    def _processing_tab(self) -> QWidget:
        w = QWidget(); f = QFormLayout(w)
        p = self.cfg.processing
        self.sp_rms_win = QDoubleSpinBox(); self.sp_rms_win.setRange(5, 1000); self.sp_rms_win.setValue(p.rms_window_ms)
        f.addRow("RMS window ms", self.sp_rms_win)
        self.cb_zero = QComboBox(); self.cb_zero.addItems(["yaw", "full"]); self.cb_zero.setCurrentText(p.zero_mode)
        f.addRow("SET ORIGIN mode", self.cb_zero)
        zh = QLabel("yaw: re-centre heading only (roll/pitch stay gravity-referenced)\n"
                    "full: the saved pose becomes the identity quaternion"); zh.setObjectName("hint"); zh.setWordWrap(True)
        f.addRow("", zh)
        self.sp_tap_th = QDoubleSpinBox(); self.sp_tap_th.setRange(0, 16); self.sp_tap_th.setDecimals(2)
        self.sp_tap_th.setSingleStep(0.05); self.sp_tap_th.setSpecialValueText("off")
        self.sp_tap_th.setValue(p.tap_threshold_g)
        f.addRow("tap threshold g", self.sp_tap_th)
        self.sp_tap_cd = QSpinBox(); self.sp_tap_cd.setRange(0, 5000); self.sp_tap_cd.setSingleStep(50)
        self.sp_tap_cd.setSpecialValueText("off"); self.sp_tap_cd.setValue(round(p.tap_cooldown_ms))
        f.addRow("tap cooldown ms", self.sp_tap_cd)
        th = QLabel("Taps come from the band's own detector (IMU mode evt or all), which can't be tuned.\n"
                    "Threshold: drop taps whose knock is weaker (largest change of acceleration around "
                    "the tap, from the IMU data: needs IMU mode all). Cooldown: drop taps that follow the "
                    "last one too closely. The event log shows each tap's strength_g, to pick a value.")
        th.setObjectName("hint"); th.setWordWrap(True); f.addRow("", th)
        self.sp_fps = QSpinBox(); self.sp_fps.setRange(10, 120); self.sp_fps.setValue(self.cfg.gui.fps)
        f.addRow("GUI refresh fps (restart to apply)", self.sp_fps)
        return w

    def _devices_tab(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w)
        v.setContentsMargins(theme.S3, theme.S3, theme.S3, theme.S2)
        dh = QLabel("Name: shown in the monitor (macOS can't rename the band itself).\n"
                    "Selector: Myo name, or the address shown by SCAN (empty = first free band).\n"
                    "Serial is recorded on connect; keep it to lock the slot to that band, clear to unbind.\n"
                    "2× tap: the double-tap pose sets the origin (like SET ORIGIN) and the band vibrates.")
        dh.setObjectName("hint"); dh.setWordWrap(True); v.addWidget(dh)
        g = QGridLayout(); g.setHorizontalSpacing(theme.S1); g.setVerticalSpacing(theme.S1)
        for col, cap in enumerate(("", "NAME", "SELECTOR", "SERIAL", "NEVER SLEEP", "2× TAP = ORIGIN")):
            g.addWidget(theme.label(cap, "caption"), 0, col)
        self.dev_rows: list[tuple[QLineEdit, QLineEdit, QLineEdit, QCheckBox, QCheckBox]] = []
        for i, e in enumerate(self.cfg.devices, 1):
            g.addWidget(theme.label(f"MYO {i}", "label"), i, 0)
            name = QLineEdit(e.label); name.setPlaceholderText(f"Myo {i}"); name.setMaxLength(LABEL_MAX)
            name.setMinimumWidth(120)
            sel = QLineEdit(e.selector); sel.setMinimumWidth(180); sel.setToolTip(e.selector)
            ser = QLineEdit(e.serial); ser.setMinimumWidth(130)
            ns = QCheckBox(); ns.setChecked(e.never_sleep); ns.setToolTip("never sleep while connected")
            dt = QCheckBox(); dt.setChecked(e.double_tap_origin)
            dt.setToolTip("the double-tap pose sets the orientation origin (needs POSE on and IMU data)")
            for col, wid in enumerate((name, sel, ser, ns, dt), 1):
                g.addWidget(wid, i, col)
            self.dev_rows.append((name, sel, ser, ns, dt))
        g.setColumnStretch(2, 1)
        v.addLayout(g)
        v.addSpacing(theme.S1)
        self.sp_slots = QSpinBox(); self.sp_slots.setRange(1, 4); self.sp_slots.setValue(len(self.cfg.devices))
        f2 = QFormLayout(); f2.addRow("number of slots (restart to apply)", self.sp_slots)
        v.addLayout(f2)
        v.addStretch(1)
        return w

    # ------------------------------------------------------------------ apply
    def _clicked(self, btn) -> None:
        role = self.buttons.buttonRole(btn)
        if role == QDialogButtonBox.RejectRole:
            self.reject(); return
        self.save_requested = role == QDialogButtonBox.AcceptRole
        self.write_back()
        self.accept()

    def write_back(self) -> None:
        c = self.cfg
        c.transport = self.cb_adapter.currentData()
        c.dongle_port = self.port_value()
        o = c.osc
        o.host = self.ed_host.text().strip() or "127.0.0.1"
        o.port = self.sp_port.value()
        o.enabled = self.ck_enabled.isChecked()
        o.preset = self.cb_preset.currentText()
        o.mode = self.cb_mode.currentText()
        o.emg_bundle_samples = self.sp_bundle.value()
        o.imu_rate_hz = self.sp_imu.value()
        o.rms_rate_hz = self.sp_rms.value()
        for name, cb in self.stream_boxes.items():
            o.streams[name] = cb.isChecked()
        c.osc_in.enabled = self.ck_in.isChecked()
        c.osc_in.host = self.ed_in_host.text().strip() or "0.0.0.0"
        c.osc_in.port = self.sp_in_port.value()
        c.processing.rms_window_ms = self.sp_rms_win.value()
        c.processing.zero_mode = self.cb_zero.currentText()
        c.processing.tap_threshold_g = round(self.sp_tap_th.value(), 2)
        c.processing.tap_cooldown_ms = float(self.sp_tap_cd.value())
        c.scan_timeout_s = self.sp_scan.value()
        c.gui.fps = self.sp_fps.value()
        for e, (name, sel, ser, ns, dt) in zip(c.devices, self.dev_rows):
            e.label = clean_label(name.text())
            e.selector = sel.text().strip()
            e.serial = ser.text().strip().lower()
            e.never_sleep = ns.isChecked()
            e.double_tap_origin = dt.isChecked()
        from myo_bridge.config import DeviceEntry
        n = self.sp_slots.value()
        while len(c.devices) < n:
            c.devices.append(DeviceEntry())
        del c.devices[n:]
