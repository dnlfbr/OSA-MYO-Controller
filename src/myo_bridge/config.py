"""Persistent configuration (TOML). Loaded from, in order: --config path, ./config.toml,
~/Library/Application Support/osa-myo-controller/config.toml. Missing keys fall back to defaults."""

from __future__ import annotations

import dataclasses
import logging
import math
import os
import sys
import time
import tomllib
import typing
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import tomli_w

log = logging.getLogger(__name__)

APP_NAME = "osa-myo-controller"
LEGACY_APP_NAME = "myo-bridge"  # the project's earlier name: its config is still read


def user_config_dir(name: str = APP_NAME) -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / name
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / name
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / name


@dataclass
class OscConfig:
    host: str = "127.0.0.1"
    port: int = 7400
    enabled: bool = True
    preset: str = "default"  # default | myomapper
    mode: str = "vector"  # vector (one message per data type) | axis (per channel/axis)
    emg_bundle_samples: int = 4  # samples per bundle; 1 = one message per sample
    imu_rate_hz: float = 50.0  # rate limiter for IMU-derived streams (<=50)
    rms_rate_hz: float = 50.0
    streams: dict[str, bool] = field(default_factory=lambda: {
        "emg_raw": True, "emg_norm": False, "emg_rms": True, "emg_mav": True,
        "quat": True, "quat_raw": False, "euler": True, "euler_deg": False, "euler_norm": False,
        "accel": True, "gyro": True, "pose": True, "arm": True, "sync": True, "lock": True,
        "battery": True, "rssi": True, "status": True, "tap": True, "firmware": True,
        "fv": True,
    })


@dataclass
class OscInConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 7401


@dataclass
class ProcessingConfig:
    rms_window_ms: float = 50.0
    zero_mode: str = "yaw"  # yaw: re-centre heading only | full: whole orientation
    euler_order: str = "zyx"
    gyro_norm_range: float = 1000.0  # for *_norm variants
    accel_norm_range: float = 2.0
    tap_threshold_g: float = 0.0  # drop taps weaker than this (needs IMU mode "all"); 0 = keep all
    tap_cooldown_ms: float = 0.0  # drop taps closer than this to the previous kept one; 0 = off


@dataclass
class DeviceEntry:
    """A device slot. ``selector`` = name, address/UUID or serial; empty = first Myo found."""

    label: str = ""  # name shown in the monitor; the band's Bluetooth name can't be changed from macOS
    selector: str = ""
    serial: str = ""  # serial of the band last bound to this slot; non-empty = slot is locked to it
    emg_mode: int = 3
    imu_mode: int = 3
    classifier_mode: int = 1
    never_sleep: bool = True
    double_tap_origin: bool = False  # the double-tap pose sets the orientation origin (SET ORIGIN)
    zero_quat: list[float] = field(default_factory=list)  # saved orientation reference (w x y z)


@dataclass
class GuiConfig:
    emg_window_s: float = 2.0
    emg_scale: float = 64.0
    emg_autoscale: bool = False
    imu_window_s: float = 5.0
    fps: int = 60
    orient_view: str = "behind"  # behind | side | top | mirror


@dataclass
class AppConfig:
    transport: str = "bleak"  # bleak | bled112 | mock
    dongle_port: str = ""  # serial port of the BLED112
    scan_timeout_s: float = 6.0
    devices: list[DeviceEntry] = field(default_factory=lambda: [DeviceEntry()])
    osc: OscConfig = field(default_factory=OscConfig)
    osc_in: OscInConfig = field(default_factory=OscInConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    gui: GuiConfig = field(default_factory=GuiConfig)
    path: Path | None = field(default=None, compare=False, repr=False)
    notice: str = field(default="", compare=False, repr=False)  # load problems, shown in the GUI


# runtime-only fields: never read from or written to the file
_RUNTIME_FIELDS = frozenset({"path", "notice"})

TRANSPORTS = ("bleak", "bled112", "mock")
LABEL_MAX = 32  # characters in a band's name


def clean_label(text: str) -> str:
    """A band name as typed or pasted: tabs, line breaks and other control characters become
    single spaces, at most LABEL_MAX characters."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())[:LABEL_MAX]


def _coerce(v: Any, default: Any, key: str, problems: list[str]) -> Any:
    """Return ``v`` converted to the type of ``default``; raise TypeError if it can't be."""
    if isinstance(default, bool):
        if isinstance(v, bool):
            return v
        raise TypeError(f"expected true/false, got {v!r}")
    if isinstance(default, int):
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        if isinstance(v, float) and v.is_integer():
            return int(v)
        raise TypeError(f"expected an integer, got {v!r}")
    if isinstance(default, float):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        raise TypeError(f"expected a number, got {v!r}")
    if isinstance(default, str):
        if isinstance(v, str):
            return v
        raise TypeError(f"expected a string, got {v!r}")
    if isinstance(default, dict):  # e.g. osc.streams: merge over the defaults, keep known keys only
        if not isinstance(v, dict):
            raise TypeError(f"expected a table, got {v!r}")
        out = dict(default)
        for k, x in v.items():
            if k not in default:
                problems.append(f"{key}.{k}: unknown key ignored")
                continue
            try:
                out[k] = _coerce(x, default[k], f"{key}.{k}", problems)
            except TypeError as e:
                problems.append(f"{key}.{k}: {e}")
        return out
    if isinstance(default, list):
        if isinstance(v, list):
            return list(v)
        raise TypeError(f"expected a list, got {v!r}")
    return v


def _from_dict(cls, data: Any, where: str = "", problems: list[str] | None = None):
    """Build ``cls`` from a parsed TOML table. Missing keys keep their defaults; unknown keys and
    values of the wrong type are skipped (and reported in ``problems``) instead of raising."""
    problems = [] if problems is None else problems
    obj = cls()
    if not isinstance(data, dict):
        problems.append(f"{where or cls.__name__}: expected a table, using defaults")
        return obj
    hints = typing.get_type_hints(cls)  # resolves the string annotations (PEP 563)
    names = {f.name for f in fields(cls)} - _RUNTIME_FIELDS
    for k in data.keys() - names:
        problems.append(f"{_join(where, k)}: unknown key ignored")
    for f in fields(cls):
        if f.name in _RUNTIME_FIELDS or f.name not in data:
            continue
        key = _join(where, f.name)
        tp, v = hints.get(f.name), data[f.name]
        try:
            if isinstance(tp, type) and is_dataclass(tp):
                v = _from_dict(tp, v, key, problems)
            elif typing.get_origin(tp) is list and is_dataclass(_first_arg(tp)):
                if not isinstance(v, list):
                    raise TypeError(f"expected a list of tables, got {v!r}")
                v = [_from_dict(_first_arg(tp), d, f"{key}[{i}]", problems) for i, d in enumerate(v)]
                if not v:
                    raise TypeError("empty list")
            else:
                v = _coerce(v, getattr(obj, f.name), key, problems)
        except TypeError as e:
            problems.append(f"{key}: {e}, using default")
            continue
        setattr(obj, f.name, v)
    return obj


def _join(where: str, name: str) -> str:
    return f"{where}.{name}" if where else name


def _first_arg(tp) -> Any:
    args = typing.get_args(tp)
    return args[0] if args else None


def _sanitize(cfg: AppConfig, problems: list[str]) -> None:
    """Reset out-of-range values to their defaults so a hand-edited file can't break startup."""

    def check(obj, name: str, ok, where: str) -> None:
        v = getattr(obj, name)
        try:
            good = bool(ok(v))
        except Exception:  # noqa: BLE001
            good = False
        if not good:
            d = getattr(type(obj)(), name)
            problems.append(f"{_join(where, name)} = {v!r} is not valid, using {d!r}")
            setattr(obj, name, d)

    def finite(v) -> bool:
        return math.isfinite(v)

    check(cfg, "transport", lambda v: v in TRANSPORTS, "")
    check(cfg, "scan_timeout_s", lambda v: finite(v) and 1 <= v <= 60, "")
    o = cfg.osc
    check(o, "port", lambda v: 1 <= v <= 65535, "osc")
    check(o, "preset", lambda v: v in ("default", "myomapper"), "osc")
    check(o, "mode", lambda v: v in ("vector", "axis"), "osc")
    check(o, "emg_bundle_samples", lambda v: 1 <= v <= 40, "osc")
    check(o, "imu_rate_hz", lambda v: finite(v) and 0 <= v <= 50, "osc")
    check(o, "rms_rate_hz", lambda v: finite(v) and 0 <= v <= 200, "osc")
    check(cfg.osc_in, "port", lambda v: 0 <= v <= 65535, "osc_in")
    p = cfg.processing
    check(p, "rms_window_ms", lambda v: finite(v) and 5 <= v <= 1000, "processing")
    check(p, "zero_mode", lambda v: v in ("yaw", "full"), "processing")
    check(p, "gyro_norm_range", lambda v: finite(v) and v > 0, "processing")
    check(p, "accel_norm_range", lambda v: finite(v) and v > 0, "processing")
    check(p, "tap_threshold_g", lambda v: finite(v) and 0 <= v <= 16, "processing")
    check(p, "tap_cooldown_ms", lambda v: finite(v) and 0 <= v <= 5000, "processing")
    for i, e in enumerate(cfg.devices):
        w = f"devices[{i}]"
        check(e, "emg_mode", lambda v: v in (0, 1, 2, 3), w)
        check(e, "imu_mode", lambda v: v in (0, 1, 2, 3, 4), w)
        check(e, "classifier_mode", lambda v: v in (0, 1), w)
        check(e, "label", lambda v: len(v) <= LABEL_MAX and v.isprintable(), w)
        check(e, "zero_quat", lambda v: len(v) == 0 or (
            len(v) == 4 and all(isinstance(x, (int, float)) and not isinstance(x, bool) and finite(x) for x in v)
            and any(x != 0 for x in v)), w)
        e.zero_quat = [float(x) for x in e.zero_quat]
    g = cfg.gui
    check(g, "emg_window_s", lambda v: finite(v) and 0.1 <= v <= 10, "gui")
    check(g, "emg_scale", lambda v: finite(v) and 0 < v <= 128, "gui")
    check(g, "imu_window_s", lambda v: finite(v) and 0.5 <= v <= 60, "gui")
    check(g, "fps", lambda v: 10 <= v <= 120, "gui")
    check(g, "orient_view", lambda v: v in ("behind", "side", "top", "mirror"), "gui")


def _to_dict(obj) -> Any:
    if is_dataclass(obj):
        out = {}
        for f in fields(obj):
            if f.name in _RUNTIME_FIELDS:
                continue
            out[f.name] = _to_dict(getattr(obj, f.name))
        return out
    if isinstance(obj, list):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    return obj


def default_config_path() -> Path:
    return user_config_dir() / "config.toml"


def find_config(explicit: str | Path | None = None) -> Path | None:
    candidates = ([Path(explicit)] if explicit else
                  [Path("config.toml"), default_config_path(), user_config_dir(LEGACY_APP_NAME) / "config.toml"])
    for c in candidates:
        if c.is_file():
            return c
    return None


def load_config(explicit: str | Path | None = None) -> AppConfig:
    """Load the config. Never raises because of the file's contents: a file that can't be parsed
    is renamed to ``config.toml.broken-<time>`` and the defaults are used; invalid values are
    reset to their defaults. Either way ``cfg.notice`` says what happened."""
    path = find_config(explicit)
    if path is None:
        cfg = AppConfig()
        cfg.path = Path(explicit) if explicit else default_config_path()
        return cfg
    problems: list[str] = []
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        cfg = _from_dict(AppConfig, data, "", problems)
        _sanitize(cfg, problems)
    except Exception as e:  # noqa: BLE001 - corrupt/unreadable file: keep a copy, start clean
        backup = _set_aside(path)
        log.error("config %s could not be read (%s); using defaults", path, e)
        cfg = AppConfig()
        cfg.notice = (f"{path.name} could not be read ({e}); defaults loaded"
                      + (f", the old file was kept as {backup.name}" if backup else ""))
    else:
        for msg in problems:
            log.warning("config %s: %s", path, msg)
        if problems:
            cfg.notice = (f"{len(problems)} setting(s) in {path.name} were invalid and reset to "
                          f"defaults: " + "; ".join(problems[:4]) + (" …" if len(problems) > 4 else ""))
        log.info("config loaded from %s", path)
    # a config under the earlier name is saved under the new one from now on
    cfg.path = default_config_path() if path == user_config_dir(LEGACY_APP_NAME) / "config.toml" else path
    return cfg


def _set_aside(path: Path) -> Path | None:
    backup = path.with_name(f"{path.name}.broken-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        path.rename(backup)
        return backup
    except OSError:
        log.exception("could not rename %s", path)
        return None


def save_config(cfg: AppConfig, path: str | Path | None = None) -> Path:
    """Write atomically (temp file + rename) so an interrupted save can't leave a truncated file."""
    target = Path(path) if path else (cfg.path or default_config_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    data = tomli_w.dumps(_to_dict(cfg)).encode("utf-8")
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)
    cfg.path = target
    return target


def config_to_toml(cfg: AppConfig) -> str:
    return tomli_w.dumps(_to_dict(cfg))


__all__ = [
    "LABEL_MAX", "TRANSPORTS", "AppConfig", "DeviceEntry", "GuiConfig", "OscConfig", "OscInConfig",
    "ProcessingConfig", "clean_label", "config_to_toml", "default_config_path", "load_config", "save_config",
    "dataclasses",
]
