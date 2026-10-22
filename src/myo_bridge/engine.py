"""Bridge engine: devices + processing + OSC, running on one asyncio loop.

Used by the headless CLI and (in a background thread) by the GUI.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field

from myo_bridge.config import AppConfig, DeviceEntry
from myo_bridge.myo import protocol as P
from myo_bridge.myo.device import DeviceConfig, DeviceState, MyoDevice
from myo_bridge.osc.namespace import Namespace
from myo_bridge.osc.sender import OscSender
from myo_bridge.processing import quaternion as Q
from myo_bridge.processing.pipeline import DeviceProcessor, ProcessingParams, fv_activity
from myo_bridge.transport.base import Scanner, ScanResult, Transport, TransportError

log = logging.getLogger(__name__)
_SERIAL_RE = re.compile(r"^[0-9a-f]{2}(-[0-9a-f]{2}){5}$")
_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
_CB_UUID_RE = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")

# a tap event is judged on the IMU samples from TAP_PRE_S before to TAP_POST_S after it (the
# sample holding the knock can reach us after the event)
TAP_PRE_S, TAP_POST_S = 0.12, 0.06
DOUBLE_TAP_ORIGIN_GAP_S = 1.0  # one origin per double tap, however the classifier repeats it
ORIGIN_FRESH_S = 1.0  # SET ORIGIN needs IMU data this recent: a stale frame is no origin
NO_ORIGIN = "no IMU data, origin not set (IMU mode data or all)"

ADAPTERS = {
    "bleak": "built-in Bluetooth",
    "bled112": "BLED112 USB dongle",
    "mock": "simulated armbands",
}


def selector_fits(selector: str, backend: str) -> bool:
    """False when ``selector`` is an address only another adapter can see: the dongle reports
    MAC addresses, macOS's built-in Bluetooth per-Mac UUIDs."""
    s = selector.strip().lower()
    if backend == "bled112":
        return not _CB_UUID_RE.match(s)
    if backend == "bleak" and sys.platform == "darwin":
        return not _MAC_RE.match(s)
    return True


@dataclass
class LogEntry:
    t: float
    device_id: int
    kind: str
    text: str
    data: dict = field(default_factory=dict)


class Slot:
    """One armband slot (id 1..N): device + processor + GUI ring buffers."""

    def __init__(self, device_id: int, entry: DeviceEntry, device: MyoDevice,
                 processor: DeviceProcessor) -> None:
        self.id = device_id
        self.entry = entry
        self.device = device
        self.processor = processor
        # GUI feeds: appended on the asyncio thread, drained by the GUI timer (deque is thread-safe
        # for append/popleft)
        self.emg_queue: deque[tuple] = deque(maxlen=4000)  # (t, raw8, norm8)
        self.fv_queue: deque[tuple] = deque(maxlen=1000)  # (t, values8): smooth EMG, mode 1
        self.imu_queue: deque = deque(maxlen=1000)  # ImuFrame
        self.rms_latest: tuple[float, ...] = (0.0,) * 8  # pod activity 0..1 (RMS, or smooth EMG)
        self.last_origin_tap = -1e9

    @property
    def display_name(self) -> str:
        """The name given in the monitor (Rename / SETTINGS → DEVICES), else the Bluetooth name."""
        return self.entry.label.strip() or self.device.name or f"Myo {self.id}"


class Bridge:
    def __init__(self, config: AppConfig, transport_factory, scanner: Scanner) -> None:
        self.config = config
        self._transport_factory = transport_factory
        self.scanner = scanner
        ns = Namespace(config.osc.preset, config.osc.mode)
        self.osc = OscSender(config.osc.host, config.osc.port, ns, config.osc.streams,
                             config.osc.emg_bundle_samples, config.osc.imu_rate_hz,
                             config.osc.rms_rate_hz, config.osc.enabled)
        self.slots: list[Slot] = []
        self.log: deque[LogEntry] = deque(maxlen=500)
        self.on_log_listeners: list = []
        self.loop: asyncio.AbstractEventLoop | None = None
        self._build_slots()

    # ------------------------------------------------------------------ setup
    def _build_slots(self) -> None:
        entries = self.config.devices or [DeviceEntry()]
        for i, entry in enumerate(entries, 1):
            dcfg = DeviceConfig(emg_mode=P.EmgMode(entry.emg_mode), imu_mode=P.ImuMode(entry.imu_mode),
                                classifier_mode=P.ClassifierMode(entry.classifier_mode),
                                never_sleep=entry.never_sleep)
            dev = MyoDevice(self._transport_factory(), device_id=i, config=dcfg,
                            selector=entry.selector or None)
            pc = self.config.processing
            proc = DeviceProcessor(ProcessingParams(rms_window_ms=pc.rms_window_ms, zero_mode=pc.zero_mode,
                                                    tap_threshold_g=pc.tap_threshold_g,
                                                    tap_cooldown_ms=pc.tap_cooldown_ms))
            if entry.zero_quat and len(entry.zero_quat) == 4:
                proc.reference.set_reference(tuple(entry.zero_quat))  # type: ignore[arg-type]
            slot = Slot(i, entry, dev, proc)
            self._wire(slot)
            self.slots.append(slot)

    def slot(self, device_id: int) -> Slot | None:
        for s in self.slots:
            if s.id == device_id:
                return s
        return None

    def _emit_log(self, entry: LogEntry) -> None:
        self.log.append(entry)
        for cb in self.on_log_listeners:
            try:
                cb(entry)
            except Exception:  # noqa: BLE001
                log.exception("log listener failed")

    def note(self, device_id: int, kind: str, text: str, data: dict | None = None) -> None:
        """Add a line to the event log (also from the GUI thread)."""
        self._emit_log(LogEntry(time.monotonic(), device_id, kind, text, data or {}))

    def emg_hint(self, slot: Slot) -> str:
        """What the user should know about where this band's EMG goes ('' = nothing)."""
        if slot.device.config.emg_mode is P.EmgMode.SMOOTH and self.osc.enabled and not self.osc.wants("fv"):
            return ("EMG smooth is shown in the monitor but not sent: switch on the 'fv' stream "
                    "(SETTINGS → STREAMS) for /emg/smooth")
        return ""

    @staticmethod
    def _later(delay: float, fn) -> None:
        """Run ``fn`` on the bridge loop after ``delay`` s (device callbacks run on that loop)."""
        try:
            asyncio.get_running_loop().call_later(delay, fn)
        except RuntimeError:  # no running loop (direct calls): now
            fn()

    def _spawn(self, slot: Slot, coro) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()
            return

        def done(t: asyncio.Task) -> None:
            if not t.cancelled() and t.exception() is not None:
                self.note(slot.id, "log", f"command failed: {t.exception()}")
        task.add_done_callback(done)

    def _wire(self, slot: Slot) -> None:
        dev, proc, osc, did = slot.device, slot.processor, self.osc, slot.id
        limiter_now = time.monotonic

        @dev.on_emg.connect
        def _emg(d, sample, t):
            norm = proc.push_emg(sample, t)
            slot.emg_queue.append((t, sample, norm))
            if osc.emg(did, sample, norm, t):
                proc.note_emg_sent(t)
            now = limiter_now()
            rms = proc.rms.values
            slot.rms_latest = rms
            osc.emg_rms(did, rms, sum(rms) / len(rms), now)

        @dev.on_fv.connect
        def _fv(d, pkt, t):  # EMG mode smooth: the band's own 50 Hz envelope instead of samples
            slot.fv_queue.append((t, pkt.values))
            slot.rms_latest = fv_activity(pkt.values)
            osc.fv(did, pkt.values)

        @dev.on_imu.connect
        def _imu(d, pkt, t):
            fr = proc.push_imu(pkt, t)
            slot.imu_queue.append(fr)
            osc.imu(did, fr.quat, fr.quat_raw, fr.euler, Q.to_degrees(fr.euler),
                    Q.to_unit_range(fr.euler), fr.accel, fr.gyro, t)

        @dev.on_classifier.connect
        def _cls(d, ev: P.ClassifierEvent, t):
            typ = ev.type
            data: dict = {}
            if typ is P.ClassifierEventType.POSE:
                osc.pose(did, ev.pose.label, int(ev.pose))
                data = {"pose": ev.pose.label}
            elif typ is P.ClassifierEventType.ARM_SYNCED:
                osc.string("arm", did, ev.arm.label)
                osc.string("xdir", did, ev.x_direction.label)
                osc.integer("sync", did, 1)
                data = {"arm": ev.arm.label, "x_direction": ev.x_direction.label}
                if ev.warmup_state is P.WarmupState.COLD:  # poses improve after a few minutes on the skin
                    data["warmup"] = "cold, poses get reliable once warm"
                elif ev.warmup_state is P.WarmupState.WARM:
                    data["warmup"] = "warm"
            elif typ is P.ClassifierEventType.WARMUP_COMPLETED:
                data = {"warmup_result": ev.warmup_result.name.lower()}
            elif typ is P.ClassifierEventType.ARM_UNSYNCED:
                osc.string("arm", did, "unknown")
                osc.string("xdir", did, "unknown")
                osc.integer("sync", did, 0)
                osc.pose(did, "rest", int(P.Pose.REST))
            elif typ is P.ClassifierEventType.UNLOCKED:
                osc.integer("lock", did, 0)
            elif typ is P.ClassifierEventType.LOCKED:
                osc.integer("lock", did, 1)
            elif typ is P.ClassifierEventType.SYNC_FAILED:
                osc.integer("sync", did, 0)
                data = {"sync_result": ev.sync_result.name.lower()}
            self._emit_log(LogEntry(t, did, ev.label, ev.label, data))
            if typ is P.ClassifierEventType.POSE and ev.pose is P.Pose.DOUBLE_TAP and slot.entry.double_tap_origin:
                self._double_tap_origin(slot, t)

        @dev.on_motion.connect
        def _motion(d, ev: P.MotionEvent, t):
            if ev.type is not P.MotionEventType.TAP:
                self._emit_log(LogEntry(t, did, "motion", f"motion event {ev.type}", {"type": int(ev.type)}))
                return
            self._tap(slot, ev, t)

        @dev.on_battery.connect
        def _batt(d, level):
            osc.integer("battery", did, level)
            self._emit_log(LogEntry(time.monotonic(), did, "battery_level", f"battery {level}%",
                                    {"battery_level": level}))

        @dev.on_rssi.connect
        def _rssi(d, rssi):
            osc.integer("rssi", did, rssi)

        @dev.on_state.connect
        def _state(d, state: DeviceState):
            osc.string("status", did, state.value)
            if state is DeviceState.STREAMING and d.firmware:
                osc.string("firmware", did, d.firmware.short)
            self._emit_log(LogEntry(time.monotonic(), did, "status", state.value, {"status": state.value}))
            if state is DeviceState.STREAMING and (hint := self.emg_hint(slot)):
                self.note(did, "warning", hint)

        @dev.on_log.connect
        def _log(d, msg):
            self._emit_log(LogEntry(time.monotonic(), did, "log", msg))

    def _tap(self, slot: Slot, ev: P.MotionEvent, t: float) -> None:
        """A tap from the band's firmware: through the tap filter (threshold, cooldown) to OSC.
        The strength comes from the IMU stream, so it is known only in IMU mode "all"."""
        proc, did = slot.processor, slot.id
        taps, measured = proc.taps, proc.imu_live(t)

        def report(kept: bool, why: str) -> None:
            s = proc.tap_strength(t - TAP_PRE_S, t + TAP_POST_S) if measured else None
            data: dict = {"direction": ev.tap_direction, "count": ev.tap_count,
                          "strength_g": round(s, 2) if s is not None else "n/a"}
            if not kept:
                data["ignored"] = why
            elif taps.threshold_g > 0 and not measured:
                data["threshold"] = "not applied: needs IMU data (IMU mode all)"
            self._emit_log(LogEntry(t, did, "tap", f"tap dir={ev.tap_direction} count={ev.tap_count}", data))

        def decide() -> None:
            s = proc.tap_strength(t - TAP_PRE_S, t + TAP_POST_S) if measured else None
            kept, why = taps.decide(t, s)
            if kept:
                self.osc.tap(did, ev.tap_direction, ev.tap_count)
            report(kept, why)

        if taps.threshold_g > 0 and measured:
            self._later(TAP_POST_S, decide)  # wait for the IMU samples just after the knock
            return
        kept, why = taps.decide(t, None)  # no threshold to check: send at once
        if kept:
            self.osc.tap(did, ev.tap_direction, ev.tap_count)
        if measured:
            self._later(TAP_POST_S, lambda: report(kept, why))  # log the strength, to pick a threshold
        else:
            report(kept, why)

    def _double_tap_origin(self, slot: Slot, t: float) -> None:
        """Double-tap pose = SET ORIGIN, so the performer can re-align the yaw away from the computer."""
        if t - slot.last_origin_tap < DOUBLE_TAP_ORIGIN_GAP_S:
            return
        slot.last_origin_tap = t
        if self._set_origin(slot, "double tap", t):
            self._spawn(slot, slot.device.vibrate(P.VibrationType.SHORT))  # felt on the arm
        else:
            self.note(slot.id, "warning", f"double tap: {NO_ORIGIN}")

    # ------------------------------------------------------------------ live settings
    def apply_settings(self) -> None:
        """Re-read self.config (after the GUI edited it) into the live sender/processors."""
        c = self.config
        self.osc.set_target(c.osc.host, c.osc.port)
        self.osc.enabled = c.osc.enabled
        if (self.osc.namespace.preset, self.osc.namespace.mode) != (c.osc.preset, c.osc.mode):
            self.osc.set_namespace(Namespace(c.osc.preset, c.osc.mode))
        self.osc.streams = dict(c.osc.streams)
        self.osc.emg_bundle_samples = max(1, int(c.osc.emg_bundle_samples))
        self.osc.set_rates(c.osc.imu_rate_hz, c.osc.rms_rate_hz)
        for s in self.slots:
            s.processor.set_rms_window_ms(c.processing.rms_window_ms)
            s.processor.reference.mode = c.processing.zero_mode
            s.processor.set_tap_filter(c.processing.tap_threshold_g, c.processing.tap_cooldown_ms)

    async def set_transport(self, kind: str, port: str = "") -> None:
        """Switch the Bluetooth adapter at runtime (built-in, BLED112 dongle, simulated): every
        band is disconnected, then each slot gets a transport of the new kind."""
        if kind not in ADAPTERS:
            raise ValueError(f"unknown transport {kind!r}")
        for s in self.slots:
            if s.device.state is not DeviceState.DISCONNECTED:
                await s.device.disconnect()
        self.config.transport, self.config.dongle_port = kind, port
        factory, scanner = make_backend(kind, self.config)
        self._transport_factory, self.scanner = factory, scanner
        for s in self.slots:
            s.device.transport = factory()
            s.device.selector = None  # addresses differ between adapters; the serial does not
            s.device.address = ""
        from myo_bridge.transport import bled112_transport
        bled112_transport.close_all()  # release the dongle's serial port (reopened on demand)
        where = f" on {port}" if kind == "bled112" and port else ""
        self._emit_log(LogEntry(time.monotonic(), 0, "log", f"adapter: {ADAPTERS[kind]}{where}"))

    # ------------------------------------------------------------------ device actions
    async def zero(self, device_id: int | None = None, source: str = "") -> None:
        for s in self.targets(device_id):
            if not self._set_origin(s, source) and (
                    device_id is not None or s.device.state is DeviceState.STREAMING):
                self.note(s.id, "warning", f"{source or 'SET ORIGIN'}: {NO_ORIGIN}")

    def _set_origin(self, s: Slot, source: str = "", now: float | None = None) -> bool:
        """Current orientation becomes the origin (SET ORIGIN). False without IMU data from the
        last second (IMU mode evt or off, stream stopped): a stale frame is no origin."""
        if not s.processor.imu_live(time.monotonic() if now is None else now, ORIGIN_FRESH_S):
            return False
        ref = s.processor.zero()
        if ref is None:
            return False
        s.entry.zero_quat = list(ref)
        data: dict = {"reference": list(ref)}
        if source:
            data["by"] = source
        self._emit_log(LogEntry(time.monotonic(), s.id, "zero", "orientation zero set", data))
        return True

    async def clear_zero(self, device_id: int | None = None) -> None:
        for s in self.slots:
            if device_id in (None, s.id):
                s.processor.clear_zero()
                s.entry.zero_quat = []

    def targets(self, device_id: int | None) -> list[Slot]:
        return [s for s in self.slots if device_id in (None, s.id)]

    async def resync(self, device_id: int | None = None) -> None:
        """Reset the classifier of the connected band(s): the performer syncs again."""
        for s in self.targets(device_id):
            if s.device.state in (DeviceState.CONNECTED, DeviceState.STREAMING):
                await s.device.resync()

    async def power_off(self, device_id: int | None = None) -> None:
        """Switch the band(s) off (deep sleep; they wake up only on USB power)."""
        for s in self.targets(device_id):
            if s.device.state is not DeviceState.DISCONNECTED:
                await s.device.power_off()

    # ------------------------------------------------------------------ connection
    async def connect_slot(self, slot: Slot, timeout: float | None = None) -> bool:
        """Resolve the slot's target and connect. Rules, in order:

        1. ``selector`` set: name or address/UUID as seen in a scan (a serial-looking selector
           ``xx-xx-xx-xx-xx-xx`` is treated like rule 2);
        2. ``serial`` set (recorded from the band's MyoInfo on a previous connect): try every
           free Myo in RSSI order and keep the one whose serial matches;
        3. otherwise the first free Myo found (strongest RSSI), skipping bands bound to
           other slots.
        The CoreBluetooth address is a per-Mac UUID, so the serial is the only identifier that
        survives a move to another computer.
        """
        dev = slot.device
        if dev.state not in (DeviceState.DISCONNECTED,):
            return True
        taken = {s.device.address for s in self.slots if s is not slot and s.device.address}
        taken_serials = {s.entry.serial for s in self.slots if s is not slot and s.entry.serial}
        sel = (slot.entry.selector or "").strip()
        want_serial = slot.entry.serial.lower() if slot.entry.serial else ""
        if sel and _SERIAL_RE.match(sel.lower()):
            want_serial, sel = sel.lower(), ""
        if sel and not selector_fits(sel, getattr(self.scanner, "backend_name", "")):
            self._emit_log(LogEntry(time.monotonic(), slot.id, "log",
                                    f"slot {slot.id}: '{sel}' is an address seen through another "
                                    "Bluetooth adapter, ignored"))
            sel = ""
        scan_t = timeout or self.config.scan_timeout_s

        if sel:
            found = await self.scanner.find(sel, timeout=scan_t)
            if found is not None and found.address not in taken:
                return await self._connect_found(slot, found, want_serial)
            if not want_serial:
                self._emit_log(LogEntry(time.monotonic(), slot.id, "log",
                                        f"slot {slot.id}: '{sel}' not found or already in use"))
                return False
            self._emit_log(LogEntry(time.monotonic(), slot.id, "log",
                                    f"slot {slot.id}: '{sel}' not found, looking for serial {want_serial}"))

        results = await self.scanner.scan(timeout=scan_t)
        results.sort(key=lambda r: -(r.rssi if r.rssi is not None else -999))
        candidates = [r for r in results if r.is_myo and r.address not in taken]
        if not candidates:
            self._emit_log(LogEntry(time.monotonic(), slot.id, "log", f"slot {slot.id}: no free Myo found"))
            return False
        if want_serial:
            for r in candidates:
                if await self._connect_found(slot, r, want_serial):
                    return True
            self._emit_log(LogEntry(time.monotonic(), slot.id, "log",
                                    f"slot {slot.id}: no Myo with serial {want_serial} among "
                                    f"{len(candidates)} found"))
            return False
        # first free: prefer bands whose serial is not claimed by another slot (unknown until
        # connected, so just skip ones another slot already streams from)
        for r in candidates:
            ok = await self._connect_found(slot, r, "")
            if ok and dev.info and dev.info.serial in taken_serials:
                self._emit_log(LogEntry(time.monotonic(), slot.id, "log",
                                        f"slot {slot.id}: {dev.info.serial} belongs to another slot, skipping"))
                await dev.disconnect(restore_sleep=False)
                continue
            if ok:
                return True
        return False

    async def _connect_found(self, slot: Slot, found: ScanResult, want_serial: str) -> bool:
        dev = slot.device
        dev.selector = found.address
        dev.name = found.name
        if found.rssi is not None:
            dev.rssi = found.rssi
        try:
            await dev.connect(found.address)
        except TransportError as e:
            self._emit_log(LogEntry(time.monotonic(), slot.id, "log", f"connect failed: {e}"))
            return False
        serial = dev.info.serial if dev.info else ""
        if want_serial and serial.lower() != want_serial:
            self._emit_log(LogEntry(time.monotonic(), slot.id, "log",
                                    f"slot {slot.id}: {found.display_name} is {serial}, want {want_serial}"))
            await dev.disconnect(restore_sleep=False)
            return False
        if serial:
            slot.entry.serial = serial
        return True

    async def connect_address(self, slot: Slot, address: str, name: str | None = None) -> bool:
        """Connect a slot to an explicit scan result (GUI: double-click in the NEARBY list)."""
        dev = slot.device
        if dev.state is not DeviceState.DISCONNECTED:
            await dev.disconnect()
        dev.selector = address
        slot.entry.selector = address
        if name:
            dev.name = name
        try:
            await dev.connect(address)
        except TransportError as e:
            self._emit_log(LogEntry(time.monotonic(), slot.id, "log", f"connect failed: {e}"))
            return False
        return True

    async def connect_all(self) -> int:
        ok = 0
        for s in self.slots:
            if await self.connect_slot(s):
                ok += 1
        return ok

    async def disconnect_all(self) -> None:
        for s in self.slots:
            try:
                await s.device.disconnect()
            except Exception:  # noqa: BLE001
                log.exception("disconnect failed")
        self.osc.close()

    async def run(self, stop: asyncio.Event) -> None:
        self.loop = asyncio.get_running_loop()
        await self.connect_all()
        try:
            await stop.wait()
        finally:
            await self.disconnect_all()


def make_backend(kind: str, config: AppConfig):
    """Return (transport_factory, scanner) for a transport kind."""
    if kind == "bleak":
        from myo_bridge.transport.bleak_transport import BleakScannerBackend, BleakTransport
        return BleakTransport, BleakScannerBackend()
    if kind == "mock":
        from myo_bridge.myo.mock import MockScanner, MockTransport
        return MockTransport, MockScanner(count=max(2, len(config.devices)))
    if kind == "bled112":
        from myo_bridge.transport.bled112_transport import Bled112Scanner, Bled112Transport
        port = config.dongle_port or None
        return (lambda: Bled112Transport(port)), Bled112Scanner(port)
    raise ValueError(f"unknown transport {kind!r}")
