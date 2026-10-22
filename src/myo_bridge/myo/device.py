"""MyoDevice: connection state machine, configuration, streaming and command API.

Transport-agnostic. Parses notifications with :mod:`myo_bridge.myo.protocol` and
fans typed events out to listeners (OSC sender, GUI queue, dump CLI).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from myo_bridge.myo import protocol as P
from myo_bridge.transport.base import Transport, TransportError

log = logging.getLogger(__name__)


class DeviceState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"  # link up, reading info
    STREAMING = "streaming"  # modes set, notifications flowing
    RECONNECTING = "reconnecting"


@dataclass(slots=True)
class DeviceConfig:
    emg_mode: P.EmgMode = P.EmgMode.RAW
    imu_mode: P.ImuMode = P.ImuMode.ALL
    classifier_mode: P.ClassifierMode = P.ClassifierMode.ENABLED
    never_sleep: bool = True
    keepalive_s: float = 10.0  # re-send never_sleep (myonnaise); 0 disables
    battery_poll_s: float = 30.0
    rssi_poll_s: float = 1.0
    reconnect: bool = True
    reconnect_backoff: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)
    command_spacing_s: float = 0.02  # MioConnect-style pause between writes
    vibrate_on_connect: bool = True
    unlock_on_sync: bool = True  # unlock(hold) after each sync so every pose is reported


@dataclass(slots=True)
class DeviceStats:
    t_connect: float = 0.0
    emg_notifications: int = 0
    emg_per_char: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    emg_samples: int = 0
    imu_packets: int = 0
    fv_packets: int = 0
    classifier_events: int = 0
    motion_events: int = 0
    last_emg_t: float = 0.0
    last_imu_t: float = 0.0
    emg_rate_hz: float = 0.0  # samples/s measured over the last second
    imu_rate_hz: float = 0.0
    fv_rate_hz: float = 0.0  # smooth EMG packets/s (EMG mode 1)
    emg_dropped: int = 0  # estimated per 1 s window: expected 200 sps minus received
    emg_expected_hz: float = 0.0  # 0 while EMG is off
    _win_t0: float = 0.0
    _win_emg: int = 0
    _win_imu: int = 0
    _win_fv: int = 0

    def tick_window(self, now: float) -> None:
        if self._win_t0 == 0.0:
            self._win_t0 = now
            return
        dt = now - self._win_t0
        if dt >= 1.0:
            self.emg_rate_hz = self._win_emg / dt
            self.imu_rate_hz = self._win_imu / dt
            self.fv_rate_hz = self._win_fv / dt
            if self.emg_expected_hz and self._win_emg:
                missing = self.emg_expected_hz * dt - self._win_emg
                if missing > 3:  # tolerate connection-interval jitter at the window edge
                    self.emg_dropped += int(missing)
            self._win_t0, self._win_emg, self._win_imu, self._win_fv = now, 0, 0, 0


class Event:
    """Minimal multicast callback list."""

    __slots__ = ("_cbs",)

    def __init__(self) -> None:
        self._cbs: list[Callable] = []

    def connect(self, cb: Callable) -> Callable:
        self._cbs.append(cb)
        return cb

    def disconnect(self, cb: Callable) -> None:
        if cb in self._cbs:
            self._cbs.remove(cb)

    def __call__(self, *args) -> None:
        for cb in self._cbs:
            try:
                cb(*args)
            except Exception:  # noqa: BLE001 - a listener must never kill the data path
                log.exception("listener %r failed", cb)


class MyoDevice:
    """One armband. ``device_id`` is the 1-based index used in OSC addresses."""

    def __init__(self, transport: Transport, device_id: int = 1,
                 config: DeviceConfig | None = None, selector: str | None = None) -> None:
        self.transport = transport
        self.id = device_id
        self.config = config or DeviceConfig()
        self.selector = selector  # name / address used to (re)connect
        self.state = DeviceState.DISCONNECTED
        self.stats = DeviceStats()

        # device facts
        self.address: str = ""
        self.name: str | None = None
        self.firmware: P.FirmwareVersion | None = None
        self.info: P.FirmwareInfo | None = None
        self.battery: int | None = None
        self.rssi: int | None = None
        self.arm: P.Arm = P.Arm.UNKNOWN
        self.x_direction: P.XDirection = P.XDirection.UNKNOWN
        self.synced: bool = False
        self.locked: bool = True
        self.pose: P.Pose = P.Pose.REST
        self.last_imu: P.ImuPacket | None = None
        self.last_emg: P.EmgSample | None = None

        # events (args: device, payload)
        self.on_state = Event()  # (device, DeviceState)
        self.on_emg = Event()  # (device, sample8, t_monotonic)
        self.on_emg_packet = Event()  # (device, (s1, s2), t)   - batch of 2 samples
        self.on_fv = Event()  # (device, FvPacket, t)
        self.on_imu = Event()  # (device, ImuPacket, t)
        self.on_classifier = Event()  # (device, ClassifierEvent, t)
        self.on_motion = Event()  # (device, MotionEvent, t)
        self.on_battery = Event()  # (device, int)
        self.on_rssi = Event()  # (device, int)
        self.on_log = Event()  # (device, str)

        self._cmd_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []
        self._user_disconnect = False
        self._reconnect_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ state helpers
    def _set_state(self, s: DeviceState) -> None:
        if s != self.state:
            self.state = s
            log.info("myo[%d] %s", self.id, s.value)
            self.on_state(self, s)

    def _log(self, msg: str) -> None:
        log.info("myo[%d] %s", self.id, msg)
        self.on_log(self, msg)

    @property
    def label(self) -> str:
        return self.name or self.address or f"myo{self.id}"

    # ------------------------------------------------------------------ lifecycle
    async def connect(self, address: str | None = None, timeout: float = 20.0) -> None:
        self._loop = asyncio.get_running_loop()
        self._user_disconnect = False
        target = address or self.selector
        if not target:
            raise TransportError("no address to connect to")
        self._set_state(DeviceState.CONNECTING)
        try:
            await self.transport.connect(target, on_disconnect=self._on_transport_disconnect,
                                         timeout=timeout)
        except TransportError:
            self._set_state(DeviceState.DISCONNECTED)
            raise
        self.address = self.transport.address
        self.stats = DeviceStats(t_connect=time.monotonic())
        self._set_state(DeviceState.CONNECTED)
        try:
            await self._configure()
        except TransportError:
            # don't keep a half-configured link: the next attempt would open a second one
            if self.transport.is_connected:
                try:
                    await self.transport.disconnect()
                except TransportError:
                    pass
                self._set_state(DeviceState.DISCONNECTED)
            raise
        self._set_state(DeviceState.STREAMING)
        self._start_background()

    async def _configure(self) -> None:
        t = self.transport
        cfg = self.config
        # identity
        try:
            self.firmware = P.parse_firmware_version(await t.read(P.UUIDS.FIRMWARE))
        except (TransportError, ValueError) as e:
            self._log(f"firmware read failed: {e}")
        try:
            self.info = P.parse_firmware_info(await t.read(P.UUIDS.INFO))
        except (TransportError, ValueError) as e:
            self._log(f"info read failed: {e}")
        self.name = await t.get_name() or self.name
        try:
            self.battery = P.parse_battery(await t.read(P.UUIDS.BATTERY_LEVEL))
            self.on_battery(self, self.battery)
        except (TransportError, ValueError) as e:
            self._log(f"battery read failed: {e}")
        self._log(f"connected: {self.label} fw={self.firmware} "
                  f"serial={self.info.serial if self.info else '?'} battery={self.battery}%")

        # subscriptions first, so no packet is lost once modes are set
        await t.subscribe(P.UUIDS.IMU_DATA, self._on_imu_bytes)
        for i, u in enumerate(P.EMG_UUIDS):
            await t.subscribe(u, self._emg_handler(i))
        try:
            await t.subscribe(P.UUIDS.FV_DATA, self._on_fv_bytes)
        except TransportError as e:
            self._log(f"FV subscribe skipped: {e}")
        await t.subscribe(P.UUIDS.CLASSIFIER_EVENT, self._on_classifier_bytes)
        try:
            await t.subscribe(P.UUIDS.MOTION_EVENT, self._on_motion_bytes)
        except TransportError as e:
            self._log(f"motion subscribe skipped: {e}")
        try:
            await t.subscribe(P.UUIDS.BATTERY_LEVEL, self._on_battery_bytes)
        except TransportError as e:
            self._log(f"battery notify skipped: {e}")

        # modes
        if cfg.never_sleep:
            await self.set_sleep_mode(P.SleepMode.NEVER_SLEEP)
        await self.set_mode(cfg.emg_mode, cfg.imu_mode, cfg.classifier_mode)
        if cfg.classifier_mode and cfg.unlock_on_sync:
            # a band still synced from before (a reconnect) sends no new ARM_SYNCED
            await self.unlock(P.UnlockType.HOLD)
        if cfg.vibrate_on_connect:
            await self.vibrate(P.VibrationType.SHORT)

    def _start_background(self) -> None:
        self._cancel_background()
        cfg = self.config
        if cfg.keepalive_s > 0 and cfg.never_sleep:
            self._tasks.append(asyncio.create_task(self._keepalive_loop(), name="myo-keepalive"))
        if cfg.battery_poll_s > 0:
            self._tasks.append(asyncio.create_task(self._battery_loop(), name="myo-battery"))
        if cfg.rssi_poll_s > 0:
            self._tasks.append(asyncio.create_task(self._rssi_loop(), name="myo-rssi"))

    def _cancel_background(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    async def _keepalive_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.keepalive_s)
            if self.state is DeviceState.STREAMING:
                try:
                    await self.set_sleep_mode(P.SleepMode.NEVER_SLEEP)
                except TransportError:
                    pass

    async def _battery_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.battery_poll_s)
            if self.state is DeviceState.STREAMING:
                try:
                    self._on_battery_bytes(await self.transport.read(P.UUIDS.BATTERY_LEVEL))
                except (TransportError, ValueError):
                    pass

    async def _rssi_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.rssi_poll_s)
            if self.state is DeviceState.STREAMING:
                rssi = await self.transport.get_rssi()
                if rssi is not None and rssi != self.rssi:
                    self.rssi = rssi
                    self.on_rssi(self, rssi)

    def _on_transport_disconnect(self) -> None:
        self._cancel_background()
        if self._user_disconnect or not self.config.reconnect:
            self._set_state(DeviceState.DISCONNECTED)
            return
        self._set_state(DeviceState.RECONNECTING)
        if self._reconnect_task and not self._reconnect_task.done():
            return  # the link dropped during a reconnect attempt: that loop keeps trying
        loop = self._loop or asyncio.get_event_loop()
        self._reconnect_task = loop.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        for attempt, delay in enumerate(self.config.reconnect_backoff, 1):
            await asyncio.sleep(delay)
            if self._user_disconnect:
                return
            self._log(f"reconnect attempt {attempt}")
            try:
                await self.connect()
                self._log("reconnected")
                return
            except TransportError as e:
                self._log(f"reconnect failed: {e}")
        # keep trying at the max backoff until the user gives up
        while not self._user_disconnect:
            await asyncio.sleep(self.config.reconnect_backoff[-1])
            try:
                await self.connect()
                self._log("reconnected")
                return
            except TransportError as e:
                self._log(f"reconnect failed: {e}")

    async def disconnect(self, restore_sleep: bool = True) -> None:
        """Graceful shutdown: let the armband sleep again, stop streams, drop the link."""
        self._user_disconnect = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        self._cancel_background()
        if self.transport.is_connected:
            try:
                if restore_sleep:
                    await self.set_mode(P.EmgMode.NONE, P.ImuMode.NONE, P.ClassifierMode.DISABLED)
                    await self.set_sleep_mode(P.SleepMode.NORMAL)
            except TransportError as e:
                self._log(f"shutdown commands failed: {e}")
            await self.transport.disconnect()
        self._set_state(DeviceState.DISCONNECTED)

    # ------------------------------------------------------------------ commands
    async def _command(self, data: bytes) -> None:
        async with self._cmd_lock:
            await self.transport.write(P.UUIDS.COMMAND, data, response=True)
            if self.config.command_spacing_s:
                await asyncio.sleep(self.config.command_spacing_s)

    async def set_mode(self, emg: P.EmgMode | int, imu: P.ImuMode | int,
                       classifier: P.ClassifierMode | int) -> None:
        self.config.emg_mode = P.EmgMode(int(emg))
        self.config.imu_mode = P.ImuMode(int(imu))
        self.config.classifier_mode = P.ClassifierMode(int(classifier))
        await self._command(P.cmd_set_mode(emg, imu, classifier))
        self.stats.emg_expected_hz = (
            float(P.EMG_SAMPLE_RATE_HZ)
            if self.config.emg_mode in (P.EmgMode.FILTERED, P.EmgMode.RAW) else 0.0)
        self._log(f"mode emg={self.config.emg_mode.name} imu={self.config.imu_mode.name} "
                  f"classifier={self.config.classifier_mode.name}")

    async def vibrate(self, kind: P.VibrationType | int = P.VibrationType.SHORT) -> None:
        await self._command(P.cmd_vibrate(kind))

    async def vibrate2(self, steps: list[tuple[int, int]]) -> None:
        await self._command(P.cmd_vibrate2(steps))

    async def set_sleep_mode(self, mode: P.SleepMode | int) -> None:
        await self._command(P.cmd_set_sleep_mode(mode))

    async def unlock(self, kind: P.UnlockType | int = P.UnlockType.HOLD) -> None:
        await self._command(P.cmd_unlock(kind))

    async def lock(self) -> None:
        await self._command(P.cmd_unlock(P.UnlockType.LOCK))

    async def user_action(self) -> None:
        await self._command(P.cmd_user_action())

    async def set_led(self, logo: tuple[int, int, int], bar: tuple[int, int, int]) -> None:
        await self._command(P.cmd_set_led(logo, bar))

    async def deep_sleep(self) -> None:
        """Only wakes up again on USB power. Never called automatically; see power_off()."""
        await self._command(P.cmd_deep_sleep())

    async def resync(self) -> None:
        """Reset the onboard classifier (classifier off, then on again): the band forgets the
        arm and waits for a new sync gesture. EMG and IMU keep streaming."""
        cfg = self.config
        await self._command(P.cmd_set_mode(cfg.emg_mode, cfg.imu_mode, P.ClassifierMode.DISABLED))
        was_synced = self.synced
        self._clear_sync()
        if was_synced:  # tell the listeners (OSC /sync 0, GUI) even if the firmware stays silent
            self.on_classifier(self, P.ClassifierEvent(P.ClassifierEventType.ARM_UNSYNCED), time.monotonic())
        await asyncio.sleep(0.3)
        cfg.classifier_mode = P.ClassifierMode.ENABLED
        await self._command(P.cmd_set_mode(cfg.emg_mode, cfg.imu_mode, P.ClassifierMode.ENABLED))
        self._log("classifier reset: make the sync gesture (wave out and hold)")
        await self.vibrate(P.VibrationType.SHORT)

    async def power_off(self) -> None:
        """Switch the band off (deep sleep). The link drops and the band stays off until it is
        plugged into USB power; no reconnect is attempted."""
        self._user_disconnect = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        self._cancel_background()
        if self.transport.is_connected:
            try:
                await self._command(P.cmd_deep_sleep())
            except TransportError as e:  # the band may drop the link before acknowledging
                self._log(f"deep sleep: {e}")
            if self.transport.is_connected:
                try:
                    await self.transport.disconnect()
                except TransportError:
                    pass
        self._clear_sync()
        self._set_state(DeviceState.DISCONNECTED)
        self._log("powered off: plug the band into USB to wake it up")

    def _clear_sync(self) -> None:
        self.synced, self.arm, self.x_direction = False, P.Arm.UNKNOWN, P.XDirection.UNKNOWN
        self.pose, self.locked = P.Pose.REST, True

    def _spawn(self, coro) -> None:
        """Run a command from a notification callback without blocking it."""
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            return
        def done(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception() is not None:
                self._log(f"command failed: {task.exception()}")

        loop.create_task(coro).add_done_callback(done)

    # ------------------------------------------------------------------ notification handlers
    def _emg_handler(self, char_index: int):
        stats = self.stats
        on_emg, on_packet = self.on_emg, self.on_emg_packet

        def handler(data: bytes) -> None:
            now = time.monotonic()
            st = self.stats if self.stats is not stats else stats
            try:
                s1, s2 = P.parse_emg(data)
            except ValueError:
                return
            st.emg_notifications += 1
            st.emg_per_char[char_index] += 1
            st.emg_samples += 2
            st._win_emg += 2
            st.last_emg_t = now
            st.tick_window(now)
            self.last_emg = s2
            on_packet(self, (s1, s2), now)
            if on_emg._cbs:
                on_emg(self, s1, now)
                on_emg(self, s2, now)

        return handler

    def _on_imu_bytes(self, data: bytes) -> None:
        now = time.monotonic()
        try:
            pkt = P.parse_imu(data)
        except ValueError:
            return
        st = self.stats
        st.imu_packets += 1
        st._win_imu += 1
        st.last_imu_t = now
        st.tick_window(now)
        self.last_imu = pkt
        self.on_imu(self, pkt, now)

    def _on_fv_bytes(self, data: bytes) -> None:
        now = time.monotonic()
        try:
            pkt = P.parse_fv(data)
        except ValueError:
            return
        st = self.stats
        st.fv_packets += 1
        st._win_fv += 1
        st.tick_window(now)
        self.on_fv(self, pkt, now)

    def _on_classifier_bytes(self, data: bytes) -> None:
        now = time.monotonic()
        try:
            ev = P.parse_classifier(data)
        except ValueError:
            return
        self.stats.classifier_events += 1
        t = ev.type
        if t is P.ClassifierEventType.ARM_SYNCED:
            self.synced, self.arm, self.x_direction = True, ev.arm, ev.x_direction
            if self.config.unlock_on_sync:
                self._spawn(self.unlock(P.UnlockType.HOLD))
        elif t is P.ClassifierEventType.ARM_UNSYNCED:
            self.synced, self.arm, self.x_direction = False, P.Arm.UNKNOWN, P.XDirection.UNKNOWN
            self.pose = P.Pose.REST
        elif t is P.ClassifierEventType.POSE:
            self.pose = ev.pose
        elif t is P.ClassifierEventType.UNLOCKED:
            self.locked = False
        elif t is P.ClassifierEventType.LOCKED:
            self.locked = True
        elif t is P.ClassifierEventType.SYNC_FAILED:
            self.synced = False
        self.on_classifier(self, ev, now)

    def _on_motion_bytes(self, data: bytes) -> None:
        now = time.monotonic()
        ev = P.parse_motion(data)
        self.stats.motion_events += 1
        self.on_motion(self, ev, now)

    def _on_battery_bytes(self, data: bytes) -> None:
        try:
            level = P.parse_battery(data)
        except ValueError:
            return
        if level != self.battery:
            self.battery = level
            self.on_battery(self, level)
