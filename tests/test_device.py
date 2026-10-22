import asyncio

import pytest

from myo_bridge.myo import protocol as P
from myo_bridge.myo.device import DeviceConfig, DeviceState, MyoDevice
from myo_bridge.myo.mock import MockTransport


def _cfg(**kw):
    base = dict(keepalive_s=0, battery_poll_s=0, rssi_poll_s=0, command_spacing_s=0,
                reconnect_backoff=(0.05, 0.05))
    base.update(kw)
    return DeviceConfig(**base)


async def test_connect_configure_stream_and_shutdown():
    tr = MockTransport(seed=1)
    dev = MyoDevice(tr, device_id=1, config=_cfg(), selector="MOCK-0001")
    states, emg, imu, cls = [], [], [], []
    dev.on_state.connect(lambda d, s: states.append(s))
    dev.on_emg.connect(lambda d, s, t: emg.append(s))
    dev.on_imu.connect(lambda d, p, t: imu.append(p))
    dev.on_classifier.connect(lambda d, e, t: cls.append(e))

    await dev.connect()
    assert dev.state is DeviceState.STREAMING
    assert dev.firmware.short == "1.5.1970.2"
    assert dev.info.serial == "d2-b5-d9-be-cc-01"
    assert dev.battery == 87
    # configure order: never_sleep, then set_mode, unlock (classifier on), then vibrate
    assert tr.commands[0] == P.cmd_set_sleep_mode(P.SleepMode.NEVER_SLEEP)
    assert tr.commands[1] == P.cmd_set_mode(3, 3, 1)
    assert tr.commands[2] == P.cmd_unlock(P.UnlockType.HOLD)
    assert tr.commands[3] == P.cmd_vibrate(P.VibrationType.SHORT)

    await asyncio.sleep(1.2)
    assert len(emg) >= 180 and all(len(s) == 8 for s in emg)
    assert len(imu) >= 45
    assert dev.synced and dev.arm is P.Arm.RIGHT and not dev.locked
    assert any(e.type is P.ClassifierEventType.ARM_SYNCED for e in cls)
    st = dev.stats
    assert st.emg_dropped == 0 and st.emg_per_char[0] > 10

    await dev.disconnect()
    assert dev.state is DeviceState.DISCONNECTED
    assert tr.commands[-2] == P.cmd_set_mode(0, 0, 0)
    assert tr.commands[-1] == P.cmd_set_sleep_mode(P.SleepMode.NORMAL)
    assert tr.sleep_mode is P.SleepMode.NORMAL
    assert states == [DeviceState.CONNECTING, DeviceState.CONNECTED, DeviceState.STREAMING,
                      DeviceState.DISCONNECTED]


async def test_reconnect_after_link_loss():
    tr = MockTransport(seed=2)
    dev = MyoDevice(tr, config=_cfg(), selector="MOCK-0001")
    states = []
    dev.on_state.connect(lambda d, s: states.append(s))
    await dev.connect()
    tr.simulate_link_loss()
    assert dev.state is DeviceState.RECONNECTING
    await asyncio.sleep(0.5)
    assert dev.state is DeviceState.STREAMING
    assert DeviceState.RECONNECTING in states
    await dev.disconnect()


async def test_no_reconnect_when_disabled():
    tr = MockTransport(seed=3)
    dev = MyoDevice(tr, config=_cfg(reconnect=False), selector="MOCK-0001")
    await dev.connect()
    tr.simulate_link_loss()
    await asyncio.sleep(0.2)
    assert dev.state is DeviceState.DISCONNECTED


async def test_commands_and_lock_state():
    tr = MockTransport(seed=4)
    dev = MyoDevice(tr, config=_cfg(), selector="MOCK-0001")
    await dev.connect()
    await dev.vibrate(P.VibrationType.LONG)
    assert tr.vibrations[-1] == 3
    await dev.lock()
    assert dev.locked
    await dev.unlock()
    assert not dev.locked
    await dev.set_mode(P.EmgMode.FILTERED, P.ImuMode.DATA, P.ClassifierMode.DISABLED)
    assert tr.emg_mode is P.EmgMode.FILTERED and dev.config.imu_mode is P.ImuMode.DATA
    await dev.disconnect()


async def test_drop_counter_sees_missing_notifications():
    tr = MockTransport(seed=5, drop_every=10)
    dev = MyoDevice(tr, config=_cfg(), selector="MOCK-0001")
    await dev.connect()
    await asyncio.sleep(2.3)
    assert dev.stats.emg_dropped >= 10
    await dev.disconnect()


async def test_connect_failure_raises_and_resets_state():
    from myo_bridge.transport.base import TransportError
    dev = MyoDevice(MockTransport(), config=_cfg(), selector="fail-0001")
    with pytest.raises(TransportError):
        await dev.connect()
    assert dev.state is DeviceState.DISCONNECTED


async def test_resync_unlocks_after_sync_and_power_off_stays_off():
    tr = MockTransport(seed=6)
    dev = MyoDevice(tr, config=_cfg(), selector="MOCK-0001")
    events = []
    dev.on_classifier.connect(lambda d, e, t: events.append(e.type))
    await dev.connect()
    unlock = P.cmd_unlock(P.UnlockType.HOLD)
    assert tr.commands.count(unlock) == 1  # on connect: a band still synced from before sends no ARM_SYNCED
    await asyncio.sleep(1.0)
    assert dev.synced and tr.commands.count(unlock) == 2  # and after each sync: poses need an unlocked band

    n = len(tr.commands)
    await dev.resync()
    assert not dev.synced and P.ClassifierEventType.ARM_UNSYNCED in events
    assert tr.commands[n:n + 2] == [P.cmd_set_mode(3, 3, 0), P.cmd_set_mode(3, 3, 1)]
    await asyncio.sleep(1.0)
    assert dev.synced  # the mock syncs again once the classifier is back on

    await dev.power_off()
    assert tr.commands[-1] == P.cmd_deep_sleep()
    assert dev.state is DeviceState.DISCONNECTED and not tr.is_connected and not dev.synced
    await asyncio.sleep(0.2)
    assert dev.state is DeviceState.DISCONNECTED  # no reconnect after a power off


async def test_unlock_on_sync_can_be_disabled():
    tr = MockTransport(seed=7)
    dev = MyoDevice(tr, config=_cfg(unlock_on_sync=False), selector="MOCK-0001")
    await dev.connect()
    await asyncio.sleep(1.0)
    assert dev.synced and P.cmd_unlock(P.UnlockType.HOLD) not in tr.commands
    await dev.disconnect()
