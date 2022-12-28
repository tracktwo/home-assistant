"""Test cases for the BlueT beacon."""

from datetime import datetime

from freezegun import freeze_time

from homeassistant.components.bluet.beacon import BlueTDevice

from .conftest import (
    EID_PACKET_1,
    EID_PACKET_2,
    EID_PACKET_3,
    EID_PACKET_4,
    ETLM_PACKET_1,
    FAKE_BLE_ADDRESS_2,
    FAKE_IDENTITY_KEY_1,
    FAKE_TIME_1,
    FAKE_TIME_3,
    FAKE_TIME_4,
    build_eddystone_service_info,
)


def test_eid_update_last_seen():
    """Test reception of a EID message updates the 'last_seen' field."""
    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 0, 3, None
    )
    assert device.last_seen is None
    with freeze_time(FAKE_TIME_1):
        device.process_packet(build_eddystone_service_info(EID_PACKET_1))
    assert device.last_seen == FAKE_TIME_1


def test_eid_update_bad_count():
    """Test reception of an EID message outside the window."""

    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 1000000, 3, None
    )
    assert device.last_seen is None
    with freeze_time(FAKE_TIME_1):
        device.process_packet(build_eddystone_service_info(EID_PACKET_1))

    # The message was an EID for count 0, but the device is at count 1000000.
    # This should be outside the window and fail to match.
    assert device.last_seen is None


def test_eid_update_first_window():
    """Test reception of an EID message with the first EID in the window."""

    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 0, 3, None
    )
    assert device.last_seen is None
    with freeze_time(FAKE_TIME_1):
        device.process_packet(build_eddystone_service_info(EID_PACKET_2))

    # The message was an EID for count 0xFFFE8000. This should be matched at
    # the start of the window.
    assert device.last_seen == FAKE_TIME_1

    # The window should now have centered on count 0xFFFE8000.
    assert device._eids[3].count == 0xFFFE8000


def test_eid_update_last_window():
    """Test reception of an EID message with the last EID in the window."""

    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 0, 3, None
    )
    assert device.last_seen is None
    with freeze_time(FAKE_TIME_1):
        device.process_packet(build_eddystone_service_info(EID_PACKET_3))

    # The message was an EID for count 0x00018000. This should be matched at
    # the end of the window.
    assert device.last_seen == FAKE_TIME_1

    # The window should now have centered on count 0x00018000.
    assert device._eids[3].count == 0x00018000


# Tests for bounds checking EIDs around a window. All tests use a window size
# of 3 and an exponent of 15. The broadcast EID message is for a count of 0.
#
# The device should have computed an EID cache with counters:
# [ 0xFFFE8000, 0xFFFF0000, 0xFFFF8000, 0, 0x00008000, 0x00010000, 0x00018000 ]


def test_eid_update_window_late_inside_bound():
    """Test reception of a late EID message just inside the window."""

    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 0xFFFE8000, 3, None
    )
    assert device.last_seen is None
    with freeze_time(FAKE_TIME_1):
        device.process_packet(build_eddystone_service_info(EID_PACKET_1))

    # The message was an EID just barely inside the -3 window from the current
    # state of 0. This should be recognized.
    assert device.last_seen == FAKE_TIME_1

    # This should have centered the window back at count 0
    assert device._eids[3].count == 0


def test_eid_update_window_late_outside_bound():
    """Test reception of a late EID message outside the window."""

    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 0xFFFE7FFF, 3, None
    )
    assert device.last_seen is None
    with freeze_time(FAKE_TIME_1):
        device.process_packet(build_eddystone_service_info(EID_PACKET_1))

    # The message was an EID just outside the -3 window from the current
    # state of 0. This should not have been understood.
    assert device.last_seen is None


def test_eid_update_window_early_inside_bound():
    """Test reception of a late EID message just inside the window."""

    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 0x00018FFF, 3, None
    )
    assert device.last_seen is None
    with freeze_time(FAKE_TIME_1):
        device.process_packet(build_eddystone_service_info(EID_PACKET_1))

    # The message was an EID just barely inside the +3 window from the current
    # state of 0. This should be recognized.
    assert device.last_seen == FAKE_TIME_1

    # This should have shifted the window back to centering on 0
    assert device._eids[3].count == 0


def test_eid_update_window_early_outside_bound():
    """Test reception of a late EID message outside the window."""

    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 0x00020000, 3, None
    )
    assert device.last_seen is None
    with freeze_time(FAKE_TIME_1):
        device.process_packet(build_eddystone_service_info(EID_PACKET_1))

    # The message was an EID just outside the +3 window from the current
    # state of 0. This should not have been understood.
    assert device.last_seen is None


def test_etlm_update():
    """Test reception of an ETLM packet updates the device state."""

    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 0, 3, None
    )
    assert device.last_seen is None
    assert device.new_data_available is False
    assert device.temperature == 0
    assert device.battery == 0
    assert device.uptime == 0
    assert device.signal_strength == 0

    with freeze_time(FAKE_TIME_1):
        device.process_packet(build_eddystone_service_info(EID_PACKET_1))
        device.process_packet(build_eddystone_service_info(ETLM_PACKET_1))

    assert device.new_data_available
    assert device.temperature == 20.5
    assert device.battery == 2953
    assert device.advertising_count == 46
    assert device.uptime == 408


def test_etlm_update_unknown_address():
    """Test reception of an ETLM packet from an unknown address."""

    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 0, 3, None
    )
    assert device.last_seen is None
    assert device.new_data_available is False
    assert device.temperature == 0
    assert device.battery == 0
    assert device.uptime == 0
    assert device.signal_strength == 0

    with freeze_time(FAKE_TIME_1):
        # Build an EID packet with address 1, then receive an ETLM from address 2
        device.process_packet(build_eddystone_service_info(EID_PACKET_1))
        device.process_packet(
            build_eddystone_service_info(ETLM_PACKET_1, FAKE_BLE_ADDRESS_2)
        )

    # None of the state should have been modified even though the packet is
    # valid.
    assert not device.new_data_available
    assert device.temperature == 0
    assert device.battery == 0
    assert device.advertising_count == 0
    assert device.uptime == 0


def test_beacon_lost_power():
    """Test recognition of a beacon that disappeared long ago."""

    device: BlueTDevice = BlueTDevice(
        "Test device",
        bytes.fromhex(FAKE_IDENTITY_KEY_1),
        15,
        0,
        3,
        datetime(2020, 6, 15, 3, 15, 45),
    )
    assert device.new_data_available is False
    assert device.temperature == 0
    assert device.battery == 0
    assert device.uptime == 0
    assert device.signal_strength == 0

    with freeze_time(FAKE_TIME_1):
        # Receive a packet from count 0, despite last_seen being long in the past
        device.process_packet(build_eddystone_service_info(EID_PACKET_1))

    # Last seen should now be updated
    assert device.last_seen == FAKE_TIME_1


def test_server_lost_power():
    """Test recognition of a beacon after the server comes back from a long poweroff."""

    # Create the device at FAKE_TIME_1 with count 0. This will be the "old"
    # data restored after power loss.
    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 0, 3, FAKE_TIME_1
    )
    assert device.new_data_available is False
    assert device.temperature == 0
    assert device.battery == 0
    assert device.uptime == 0
    assert device.signal_strength == 0

    # Send an EID at a time >> FAKE_TIME_1. The device should recognize its
    # cached EID list is very old and build a resync list, which will match.
    with freeze_time(FAKE_TIME_3):
        # Receive a packet corresponding to this time
        device.process_packet(build_eddystone_service_info(EID_PACKET_4))

    # Last seen should now be updated
    assert device.last_seen == FAKE_TIME_3
    # The _eids array should now be centered on this time.
    assert device._eids[3].count == 0x05540000


def test_resync_list_recompute():
    """Test recomputing a resync list that doesn't match."""

    # Create the device at FAKE_TIME_1 with count 0. This will be the "old"
    # data restored after power loss.
    device: BlueTDevice = BlueTDevice(
        "Test device", bytes.fromhex(FAKE_IDENTITY_KEY_1), 15, 0, 3, FAKE_TIME_1
    )
    assert device.new_data_available is False
    assert device.temperature == 0
    assert device.battery == 0
    assert device.uptime == 0
    assert device.signal_strength == 0

    # Send an EID at a time >> FAKE_TIME_1 << FAKE_TIME_3. The device should
    # recognize its cached EID list is very old and build a resync list, but
    # this one won't match.
    with freeze_time(FAKE_TIME_4):
        # Receive a packet corresponding to this time
        device.process_packet(build_eddystone_service_info(EID_PACKET_4))

    # Last seen should not be updated
    assert device.last_seen == FAKE_TIME_1
    # The _eids array should still be centered at the original count
    assert device._eids[3].count == 0
    # We should have computed a resync list
    assert len(device._resync_eids) > 0

    # Send an EID at a time >> FAKE_TIME_1 and >> FAKE_TIME_4. This should
    # prompt recomputation of the resync list and finally match.
    with freeze_time(FAKE_TIME_3):
        # Receive a packet corresponding to this time
        device.process_packet(build_eddystone_service_info(EID_PACKET_4))

    # Last seen should now be updated
    assert device.last_seen == FAKE_TIME_3
    # The _eids array should now be centered on this time.
    assert device._eids[3].count == 0x05540000
