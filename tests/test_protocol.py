import struct

import pytest

from myo_bridge.myo import protocol as P


def test_uuids_follow_base():
    assert P.UUIDS.CONTROL_SERVICE == "d5060001-a904-deb9-4748-2c7f4a124842"
    assert P.UUIDS.COMMAND == "d5060401-a904-deb9-4748-2c7f4a124842"
    assert P.UUIDS.EMG3 == "d5060405-a904-deb9-4748-2c7f4a124842"
    assert P.UUIDS.CLASSIFIER_EVENT == "d5060103-a904-deb9-4748-2c7f4a124842"
    assert P.UUIDS.BATTERY_LEVEL == "00002a19-0000-1000-8000-00805f9b34fb"


def test_command_bytes_match_myohw():
    assert P.cmd_set_mode(3, 3, 1) == bytes([0x01, 0x03, 0x03, 0x03, 0x01])
    assert P.cmd_set_mode(P.EmgMode.FILTERED, P.ImuMode.NONE, P.ClassifierMode.DISABLED) == \
        bytes([0x01, 3, 2, 0, 0])  # myonnaise emgFilteredOnly
    assert P.cmd_vibrate(P.VibrationType.LONG) == bytes([0x03, 0x01, 0x03])
    assert P.cmd_set_sleep_mode(P.SleepMode.NEVER_SLEEP) == bytes([0x09, 0x01, 0x01])
    assert P.cmd_unlock(P.UnlockType.HOLD) == bytes([0x0A, 0x01, 0x02])
    assert P.cmd_user_action() == bytes([0x0B, 0x01, 0x00])
    assert P.cmd_deep_sleep() == bytes([0x04, 0x00])
    assert P.cmd_set_led((255, 0, 0), (0, 0, 255)) == bytes([0x06, 6, 255, 0, 0, 0, 0, 255])


def test_vibrate2_is_18_byte_payload():
    b = P.cmd_vibrate2([(100, 255), (50, 128)])
    assert len(b) == 20 and b[0] == 0x07 and b[1] == 18
    assert struct.unpack_from("<HB", b, 2) == (100, 255)
    assert struct.unpack_from("<HB", b, 5) == (50, 128)
    assert b[8:] == bytes(12)
    with pytest.raises(ValueError):
        P.cmd_vibrate2([(1, 1)] * 7)


def test_parse_imu_scaling_and_order():
    # w=16384 (1.0), x=-8192 (-0.5), y=0, z=4096 (0.25); accel 2048 -> 1 g; gyro 160 -> 10 dps
    data = struct.pack("<10h", 16384, -8192, 0, 4096, 2048, 0, -2048, 160, -16, 0)
    pkt = P.parse_imu(data)
    assert pkt.quat == (16384, -8192, 0, 4096)
    assert pkt.quat_f == (1.0, -0.5, 0.0, 0.25)
    assert pkt.accel_g == (1.0, 0.0, -1.0)
    assert pkt.gyro_dps == (10.0, -1.0, 0.0)
    with pytest.raises(ValueError):
        P.parse_imu(data[:19])


def test_parse_emg_two_samples_int8():
    s1 = [-128, -1, 0, 1, 127, 10, -10, 5]
    s2 = [1, 2, 3, 4, 5, 6, 7, 8]
    data = struct.pack("<16b", *s1, *s2)
    a, b = P.parse_emg(data)
    assert list(a) == s1 and list(b) == s2
    with pytest.raises(ValueError):
        P.parse_emg(data[:15])


def test_parse_fv():
    data = struct.pack("<8Hb", *range(100, 900, 100), 3)
    pkt = P.parse_fv(data)
    assert pkt.values == tuple(range(100, 900, 100)) and pkt.mask == 3
    assert P.parse_fv(data[:16]).mask == 0


@pytest.mark.parametrize("raw", [bytes([0x01, 0x02, 0x01]), bytes([0x01, 0x02, 0x01, 0, 0, 0])])
def test_classifier_arm_synced_3_or_6_bytes(raw):
    ev = P.parse_classifier(raw)
    assert ev.type is P.ClassifierEventType.ARM_SYNCED
    assert ev.arm is P.Arm.LEFT and ev.x_direction is P.XDirection.TOWARD_WRIST
    assert ev.arm.label == "left" and ev.x_direction.label == "wrist"
    assert ev.label == "arm_synced"
    assert ev.warmup_state is P.WarmupState.UNKNOWN  # 3 bytes, or zero padding


def test_classifier_warmup():
    ev = P.parse_classifier(bytes([0x01, 0x01, 0x02, 0x01, 0x00, 0x40]))
    assert ev.arm is P.Arm.RIGHT and ev.x_direction is P.XDirection.TOWARD_ELBOW
    assert ev.warmup_state is P.WarmupState.COLD
    assert P.parse_classifier(bytes([0x01, 0x01, 0x01, 0x02, 0, 0])).warmup_state is P.WarmupState.WARM
    assert P.parse_classifier(bytes([0x01, 0x01, 0x01, 0x09, 0, 0])).warmup_state is P.WarmupState.UNKNOWN
    ev = P.parse_classifier(bytes([0x07, 0x01, 0, 0, 0, 0]))
    assert ev.label == "warmup_completed" and ev.warmup_result is P.WarmupResult.SUCCESS
    assert P.parse_classifier(bytes([0x07, 0x02])).warmup_result is P.WarmupResult.FAILED_TIMEOUT


def test_classifier_pose_is_uint16_le():
    ev = P.parse_classifier(bytes([0x03, 0x05, 0x00, 0, 0, 0]))
    assert ev.pose is P.Pose.DOUBLE_TAP and ev.pose.label == "double_tap"
    ev = P.parse_classifier(bytes([0x03, 0xFF, 0xFF]))
    assert ev.pose is P.Pose.UNKNOWN


def test_classifier_other_events():
    assert P.parse_classifier(bytes([0x02, 0, 0])).label == "arm_unsynced"
    assert P.parse_classifier(bytes([0x04, 0, 0])).label == "unlocked"
    assert P.parse_classifier(bytes([0x05, 0, 0])).label == "locked"
    ev = P.parse_classifier(bytes([0x06, 0x01, 0]))
    assert ev.label == "sync_failed" and ev.sync_result is P.SyncResult.FAILED_TOO_HARD
    assert P.parse_classifier(bytes([0x07, 0, 0])).label == "warmup_completed"
    assert P.parse_classifier(bytes([0x42, 0, 0])).label == "unknown_66"  # must not raise
    with pytest.raises(ValueError):
        P.parse_classifier(b"")


def test_parse_motion():
    ev = P.parse_motion(bytes([0x00, 0x02, 0x01]))
    assert ev.type is P.MotionEventType.TAP and ev.tap_direction == 2 and ev.tap_count == 1


def test_parse_firmware_version():
    fw = P.parse_firmware_version(struct.pack("<4H", 1, 5, 1970, 2))
    assert (fw.major, fw.minor, fw.patch) == (1, 5, 1970)
    assert fw.hardware_rev is P.HardwareRev.REV_D
    assert fw.short == "1.5.1970.2" and str(fw) == "1.5.1970 (rev_d)"


def test_parse_firmware_info():
    serial = bytes([0x8F, 0xCC, 0xBE, 0xD9, 0xB5, 0xD2])
    data = struct.pack("<6sH5B7x", serial, 0x0005, 1, 2, 1, 0, 2)
    assert len(data) == 20
    info = P.parse_firmware_info(data)
    assert info.serial == "d2-b5-d9-be-cc-8f"
    assert info.unlock_pose is P.Pose.DOUBLE_TAP
    assert info.classifier_type is P.ClassifierModelType.CUSTOM
    assert info.classifier_index == 2
    assert info.has_custom_classifier is True and info.stream_indicating is False
    assert info.sku is P.SKU.WHITE


def test_parse_battery():
    assert P.parse_battery(b"\x5b") == 91
    with pytest.raises(ValueError):
        P.parse_battery(b"")
