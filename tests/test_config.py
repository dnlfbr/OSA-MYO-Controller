from myo_bridge.config import (
    AppConfig,
    DeviceEntry,
    GuiConfig,
    OscConfig,
    ProcessingConfig,
    clean_label,
    load_config,
    save_config,
)
from myo_bridge.engine import Bridge, make_backend


def _edited() -> AppConfig:
    cfg = AppConfig(transport="bled112", dongle_port="/dev/cu.usbmodem1", devices=[DeviceEntry(), DeviceEntry()])
    cfg.osc.host, cfg.osc.port, cfg.osc.mode = "192.168.1.20", 9000, "axis"
    cfg.osc.streams["emg_norm"] = True
    cfg.osc_in.port = 9001
    cfg.processing.zero_mode = "full"
    cfg.devices[1].serial = "aa:bb"
    cfg.devices[1].zero_quat = [0.5, 0.5, 0.5, 0.5]
    cfg.gui.emg_scale, cfg.gui.emg_autoscale = 8.0, True
    cfg.processing.tap_threshold_g, cfg.processing.tap_cooldown_ms = 0.6, 250.0
    cfg.devices[0].label = 'Braccio "sinistro" – A\\B'  # quotes and a backslash survive TOML
    cfg.devices[1].double_tap_origin = True
    return cfg


def test_save_load_round_trip_rebuilds_nested_sections(tmp_path):
    # regression: nested tables came back as dicts and the next launch crashed on cfg.osc.host
    path = tmp_path / "config.toml"
    cfg = _edited()
    save_config(cfg, path)
    back = load_config(path)
    assert isinstance(back.osc, OscConfig) and isinstance(back.gui, GuiConfig)
    assert isinstance(back.processing, ProcessingConfig)
    assert all(isinstance(d, DeviceEntry) for d in back.devices)
    assert back == cfg
    assert back.notice == "" and back.path == path
    # a second save/load cycle is stable and the bridge can be built from it
    save_config(back)
    again = load_config(path)
    assert again == cfg
    again.transport = "mock"
    Bridge(again, *make_backend("mock", again))


def test_unreadable_file_falls_back_to_defaults_and_is_kept(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[osc\nhost = ")
    cfg = load_config(path)
    assert cfg == AppConfig()
    assert "could not be read" in cfg.notice
    assert not path.exists()
    assert len(list(tmp_path.glob("config.toml.broken-*"))) == 1
    assert cfg.path == path
    save_config(cfg)  # the next save recreates the file
    assert load_config(path) == AppConfig()


def test_invalid_values_are_reset_individually(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        'transport = "bluetooth"\n'
        "scan_timeout_s = 8\n"
        "future_option = 1\n"
        "[osc]\n"
        'host = "10.0.0.2"\n'
        'port = "7400"\n'
        'preset = "nope"\n'
        "[osc.streams]\n"
        "emg_norm = true\n"
        'quat = "yes"\n'
        "unknown_stream = true\n"
        "[gui]\n"
        "emg_scale = 0\n"
        "fps = 30\n"
        "[[devices]]\n"
        "emg_mode = 9\n"
        "zero_quat = [1, 0, 0]\n"
        'serial = "cc:dd"\n'
    )
    cfg = load_config(path)
    d = AppConfig()
    assert cfg.transport == "bleak" and cfg.scan_timeout_s == 8.0
    assert cfg.osc.host == "10.0.0.2" and cfg.osc.port == d.osc.port and cfg.osc.preset == "default"
    assert cfg.osc.streams["emg_norm"] is True and cfg.osc.streams["quat"] is True
    assert "unknown_stream" not in cfg.osc.streams
    assert set(cfg.osc.streams) == set(d.osc.streams)
    assert cfg.gui.emg_scale == d.gui.emg_scale and cfg.gui.fps == 30
    assert cfg.devices[0].emg_mode == 3 and cfg.devices[0].zero_quat == [] and cfg.devices[0].serial == "cc:dd"
    assert "invalid" in cfg.notice
    cfg.transport = "mock"
    Bridge(cfg, *make_backend("mock", cfg))


def test_missing_sections_use_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[osc]\nport = 7500\n[osc.streams]\nfv = true\n')
    cfg = load_config(path)
    assert cfg.osc.port == 7500 and cfg.osc.streams["fv"] is True and cfg.osc.streams["emg_raw"] is True
    assert cfg.gui == GuiConfig() and len(cfg.devices) == 1
    assert cfg.notice == ""


def test_band_names_and_tap_settings_are_checked(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[processing]\n"
        "tap_threshold_g = -1\n"
        "tap_cooldown_ms = 250\n"
        "[[devices]]\n"
        f'label = "{"x" * 40}"\n'
        "double_tap_origin = true\n"
        "[[devices]]\n"
        'label = "tab\\there"\n'
        "[[devices]]\n"
        'label = "Sinistro"\n'
    )
    cfg = load_config(path)
    assert cfg.processing.tap_threshold_g == 0.0 and cfg.processing.tap_cooldown_ms == 250.0
    assert [d.label for d in cfg.devices] == ["", "", "Sinistro"]  # too long, not printable, fine
    assert cfg.devices[0].double_tap_origin is True and cfg.devices[2].double_tap_origin is False
    assert "invalid" in cfg.notice


def test_band_names_are_cleaned_up():
    assert clean_label("  Destro\tbraccio\n ") == "Destro braccio"
    assert clean_label("Braccio  sinistro – A") == "Braccio sinistro – A"
    assert clean_label("x" * 40) == "x" * 32
    assert clean_label("\x07") == ""
