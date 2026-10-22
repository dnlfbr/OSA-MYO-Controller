"""OSC address namespace presets.

Stream keys (used in config ``osc.streams`` toggles) -> address templates with ``{id}``.
``axis`` mode appends one suffix per element (see ``AXIS_SUFFIXES``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# element names used by "axis" mode and by the README table
AXIS_SUFFIXES: dict[str, tuple[str, ...]] = {
    "emg_raw": tuple(str(i) for i in range(8)),
    "emg_norm": tuple(str(i) for i in range(8)),
    "emg_rms": tuple(str(i) for i in range(8)),
    "fv": tuple(str(i) for i in range(8)),
    "quat": ("w", "x", "y", "z"),
    "quat_raw": ("w", "x", "y", "z"),
    "euler": ("roll", "pitch", "yaw"),
    "euler_deg": ("roll", "pitch", "yaw"),
    "euler_norm": ("roll", "pitch", "yaw"),
    "accel": ("x", "y", "z"),
    "gyro": ("x", "y", "z"),
}

DEFAULT: dict[str, str] = {
    "emg_raw": "/myo/{id}/emg/raw",
    "emg_norm": "/myo/{id}/emg/norm",
    "emg_rms": "/myo/{id}/emg/rms",
    "emg_mav": "/myo/{id}/emg/mav",
    "fv": "/myo/{id}/emg/smooth",
    "quat": "/myo/{id}/quat",
    "quat_raw": "/myo/{id}/quat/raw",
    "euler": "/myo/{id}/euler",
    "euler_deg": "/myo/{id}/euler/deg",
    "euler_norm": "/myo/{id}/euler/norm",
    "accel": "/myo/{id}/accel",
    "gyro": "/myo/{id}/gyro",
    "pose": "/myo/{id}/pose",
    "pose_id": "/myo/{id}/pose/id",
    "arm": "/myo/{id}/arm",
    "xdir": "/myo/{id}/xdir",
    "sync": "/myo/{id}/sync",
    "lock": "/myo/{id}/lock",
    "battery": "/myo/{id}/battery",
    "rssi": "/myo/{id}/rssi",
    "status": "/myo/{id}/status",
    "tap": "/myo/{id}/tap",
    "firmware": "/myo/{id}/firmware",
}

# MyoMapper (balandinodidonato) compatible subset. Note: no slash between "myo" and the id.
MYOMAPPER: dict[str, str] = {
    "emg_raw": "/myo{id}/emg/raw",
    "emg_norm": "/myo{id}/emg/scaled",
    "emg_rms": "/myo{id}/emg/scaled/abs/mavg",
    "emg_mav": "/myo{id}/emg/scaled/abs/mav/mavg",
    "quat": "/myo{id}/orientation/quaternion",
    "euler": "/myo{id}/orientation/raw",
    "euler_norm": "/myo{id}/orientation/scaled",
    "accel": "/myo{id}/acceleration/raw",
    "gyro": "/myo{id}/gyro/raw",
    "pose": "/myo{id}/pose",  # MyoMapper sends (int id, string) in ONE message; handled in sender
    "battery": "/myo{id}/battery",
    "rssi": "/myo{id}/rssi",
    "status": "/myo{id}/status",
    "sync": "/myo{id}/sync",
    "lock": "/myo{id}/lock",
    "arm": "/myo{id}/arm",
    "xdir": "/myo{id}/xdir",
    "firmware": "/myo{id}/firmware",
    "tap": "/myo{id}/tap",
    "fv": "/myo{id}/emg/smooth",  # not in MyoMapper: the band's own 50 Hz envelope (EMG mode smooth)
}

PRESETS: dict[str, dict[str, str]] = {"default": DEFAULT, "myomapper": MYOMAPPER}

# inbound control (default preset); {id} may be a number or "all"
CONTROL: dict[str, str] = {
    "vibrate": "/myo/{id}/vibrate",
    "lock": "/myo/{id}/lock",
    "unlock": "/myo/{id}/unlock",
    "zero": "/myo/{id}/zero",
    "mode": "/myo/{id}/mode",
    "sleep": "/myo/{id}/sleep",
    "led": "/myo/{id}/led",
    "user_action": "/myo/{id}/action",
    "resync": "/myo/{id}/resync",
    "poweroff": "/myo/{id}/poweroff",  # argument 1 required
}


@dataclass
class Namespace:
    preset: str = "default"
    mode: str = "vector"  # vector | axis
    _table: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.preset not in PRESETS:
            raise ValueError(f"unknown OSC preset {self.preset!r}; choose from {list(PRESETS)}")
        if self.mode not in ("vector", "axis"):
            raise ValueError("mode must be 'vector' or 'axis'")
        self._table = PRESETS[self.preset]

    def has(self, stream: str) -> bool:
        return stream in self._table

    def address(self, stream: str, device_id: int) -> str:
        return self._table[stream].format(id=device_id)

    def axis_addresses(self, stream: str, device_id: int) -> tuple[str, ...]:
        base = self.address(stream, device_id)
        return tuple(f"{base}/{s}" for s in AXIS_SUFFIXES.get(stream, ()))

    def streams(self) -> tuple[str, ...]:
        return tuple(self._table)

    @property
    def is_myomapper(self) -> bool:
        return self.preset == "myomapper"
