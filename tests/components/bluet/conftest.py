"""Test fixtures for BlueT tests."""

from datetime import datetime
import struct
from unittest.mock import AsyncMock, patch

from Crypto.Cipher import AES
from bleak.backends.device import BLEDevice
from home_assistant_bluetooth import BluetoothServiceInfoBleak

from homeassistant.components.bluet.bluet import (
    BlueTCoordinator,
    BlueTDevice,
    BlueTStorage,
)
from homeassistant.components.bluet.const import (
    CONF_COUNT,
    CONF_EXPONENT,
    CONF_IDENTITY_KEY,
    CONF_LAST_SEEN,
    CONF_WINDOW_SIZE,
    DOMAIN,
    EDDYSTONE_SERVICE_UUID,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry
from tests.components.bluetooth import generate_advertisement_data

FAKE_IDENTITY_KEY_1 = "12345678901234567890123456789012"
FAKE_IDENTITY_KEY_2 = "11223344556677889900AABBCCDDEEFF"

FAKE_CONFIG_DATA_1 = {
    CONF_IDENTITY_KEY: FAKE_IDENTITY_KEY_1,
    CONF_NAME: "Test Device 1",
    CONF_WINDOW_SIZE: 3,
    CONF_EXPONENT: 15,
    CONF_COUNT: 1,
}

FAKE_CONFIG_DATA_2 = {
    CONF_IDENTITY_KEY: FAKE_IDENTITY_KEY_2,
    CONF_NAME: "Test Device 2",
    CONF_WINDOW_SIZE: 3,
    CONF_EXPONENT: 15,
    CONF_COUNT: 1,
}

FAKE_BLE_ADDRESS_1 = "00:11:22:33:44:55"
FAKE_BLE_ADDRESS_2 = "AA:BB:CC:DD:EE:FF"

FAKE_TIME_1 = datetime(2022, 12, 31, 11, 59, 30)
FAKE_TIME_2 = datetime(2023, 1, 1, 12, 1, 2)
FAKE_TIME_3 = datetime(2025, 10, 31, 6, 30, 0)
FAKE_TIME_4 = datetime(2024, 3, 29, 18, 4, 12)


# IDENTITY_KEY_1 at count 0
# Temporary key: B5 F0 5A 8D 6D FA 9C 34  49 64 F7 49 BB B9 A2 07
EID_PACKET_1 = b"\x30\00" + b"\xB1\xDC\x36\x0A\x2D\xD3\xDF\x22"

# IDENTITY_KEY_1 at count 0xFFFE8000
# Temporary key: 16 ED E1 27 35 DA 13 21  DE 6C 83 54 6F 98 6C 1A
EID_PACKET_2 = b"\x30\00" + b"\x6C\x37\x71\x3D\x94\xE9\x63\x69"

# IDENTITY_KEY_1 at count 0x00018000
# Temporary key: 5E 7B F0 65 AC F9 E7 8E  BE D5 6E BF 81 13 C9 84
EID_PACKET_3 = b"\x30\00" + b"\x04\xE0\x40\x3C\xC6\x1F\xB6\xC9"

# IDENTITY_KEY_1 at count 0x05540000
# Temporary key: C4 61 DB 4D 10 B7 31 B9  E9 CD FA A9 7C C8 8C 9E
#
# This packet represents an EID from a beacon at FAKE_TIME_3 that
# was initialized with count 0 at FAKE_TIME_1. This is 89404230 seconds,
# for a count of 89391104.
EID_PACKET_4 = b"\x30\00" + b"\x9D\x97\x7C\xAB\x2A\x35\x8A\xDA"


def _generate_etlm_packet(
    identity_key: str,
    count: int,
    temperature: float,
    battery: int,
    advcount: int,
    uptime: int,
):
    """Construct an ETLM packet with the given key and state."""

    # Convert the temperature to an 8.8 fixed point value: just multiply
    # by 2^8.
    fixed_temp = round(temperature * 256)
    # Build the unencrypted TLM payload
    tlm = struct.pack(">HHII", battery, fixed_temp, advcount, uptime)

    # Generate the nonce. 32 bits of 'count' (lowest K bits must be cleared)
    # concatenated with a 16-bit random salt.
    salt = 1248
    nonce = struct.pack(">IH", count, salt)

    # Encrypt the tlm payload with AES-EAX using the nonce and the identity
    # key. Note: PyCryptome does not support the 16-bit MAC Eddystone uses,
    # only 32-bits or larger. So we use a full-length MAC and truncate.
    cipher = AES.new(bytes.fromhex(identity_key), AES.MODE_EAX, nonce=nonce)
    ctext, tag = cipher.encrypt_and_digest(tlm)
    assert len(ctext) == 12

    # Return the ETLM packet:
    # 0x20 (TLM Frame)
    # 0x01 (Version: Encrypted)
    # [12 bytes of encrypted TLM]
    # [2 bytes of salt]
    # [upper 2 bytes of tag]
    etlm = b"\x20\x01" + ctext + struct.pack(">H", salt) + tag[0:2]

    assert len(etlm) == 18
    return etlm


# IDENTITY_KEY_1
# temp: 20.5 C
# battery: 2953 mV
# advertising count: 46
# uptime: 408 s
ETLM_PACKET_1 = _generate_etlm_packet(FAKE_IDENTITY_KEY_1, 0, 20.5, 2953, 46, 408)

FAKE_STORAGE_DATA_1 = {
    FAKE_IDENTITY_KEY_2: {
        CONF_IDENTITY_KEY: FAKE_IDENTITY_KEY_2,
        CONF_COUNT: 98304,
        CONF_LAST_SEEN: FAKE_TIME_2.isoformat(),
    }
}


def build_eddystone_service_info(
    packet: bytes, address: str = FAKE_BLE_ADDRESS_1
) -> BluetoothServiceInfoBleak:
    """Build a Bluetooth Service Info packet with an Eddystone EID payload."""

    return BluetoothServiceInfoBleak(
        name=None,
        address=address,
        rssi=-63,
        manufacturer_data={},
        service_uuids=[EDDYSTONE_SERVICE_UUID],
        service_data={EDDYSTONE_SERVICE_UUID: packet},
        source="local",
        device=BLEDevice(FAKE_BLE_ADDRESS_1, None),
        advertisement=generate_advertisement_data(),
        time=0,
        connectable=False,
    )


def mock_config_entry(hass: HomeAssistant, e=FAKE_CONFIG_DATA_1):
    """Return a mock config entry."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=e[CONF_IDENTITY_KEY],
        data=e,
    )
    entry.add_to_hass(hass)
    return entry


def mock_bluet_device() -> BlueTDevice:
    """Return a mocked BlueT device."""

    with patch("homeassistant.components.bluet.bluet.BlueTDevice") as mock:
        device = mock.return_value
        device.name = "test_bluet"
        device.identity_key = FAKE_IDENTITY_KEY_1
        device.count = 1024
        device.temperature = 20.5
        device.signal_strength = -44
        device.battery = 2980
        device.uptime = 500
        device.new_data_available = False
        device.last_seen = None

        return device


def mock_bluet_storage() -> BlueTStorage:
    """Return a mocked BlueTStorage instance."""

    with patch("homeassistant.components.bluet.bluet.BlueTStorage") as mock:
        storage = mock.return_value
        storage.async_update_item = AsyncMock(return_value=True)
        storage.async_create_item = AsyncMock(return_value=dict)
        storage.async_load = AsyncMock(return_value=True)
        storage._process_create_data = AsyncMock(return_value={})
        storage.data = FAKE_STORAGE_DATA_1
        return storage


def mock_coordinator(device: BlueTDevice, entry: ConfigEntry) -> BlueTCoordinator:
    """Return a mocked BlueTCoordinator instance."""

    with patch("homeassistant.components.bluet.bluet.BlueTCoordinator") as mock:
        coordinator = mock.return_value
        coordinator.device = device
        coordinator.entry = entry
        coordinator._async_update_data = AsyncMock(return_value=device)
        return coordinator


def patch_bluet_device(device: BlueTDevice = mock_bluet_device()):
    """Patch the BlueT device."""

    return patch("homeassistant.components.bluet.BlueTDevice", return_value=device)


def patch_bluet_storage(storage: BlueTStorage = mock_bluet_storage()):
    """Patch the BlueT storage object."""

    return patch("homeassistant.components.bluet.BlueTStorage", return_value=storage)


def patch_async_register_callback():
    """Patch async_register_callback to return True."""
    return patch("homeassistant.components.bluetooth.async_register_callback")


def patch_async_setup_entry():
    """Patch async_setup_entry to return True."""
    return patch("homeassistant.components.bluet.async_setup_entry")
