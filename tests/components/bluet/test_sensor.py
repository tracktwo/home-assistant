"""Test cases for the BlueT sensor platform."""

from freezegun import freeze_time

from homeassistant.components.bluet.bluet import BlueTCoordinator
from homeassistant.components.bluet.const import DOMAIN
from homeassistant.components.bluetooth.models import BluetoothChange
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .conftest import (
    EID_PACKET_1,
    ETLM_PACKET_1,
    FAKE_CONFIG_DATA_1,
    FAKE_CONFIG_DATA_2,
    FAKE_IDENTITY_KEY_2,
    FAKE_TIME_1,
    FAKE_TIME_2,
    build_eddystone_service_info,
    mock_bluet_device,
    mock_config_entry,
    mock_coordinator,
    patch_async_register_callback,
    patch_async_setup_entry,
    patch_bluet_storage,
)

from tests.components.bluet.conftest import FAKE_IDENTITY_KEY_1


async def test_battery_sensor(hass: HomeAssistant, enable_bluetooth):
    """Test a mocked battery sensor."""

    entry = mock_config_entry(hass)
    coordinator = mock_coordinator(mock_bluet_device(), entry)
    with patch_async_setup_entry():
        hass.data[DOMAIN] = {}
        hass.data[DOMAIN][entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    await hass.async_block_till_done()

    battery_sensor = hass.states.get("sensor.test_bluet_battery")
    assert battery_sensor
    assert battery_sensor.state == "2980"


async def test_temperature_sensor(hass: HomeAssistant, enable_bluetooth):
    """Test a mocked temperature sensor."""

    entry = mock_config_entry(hass)
    coordinator = mock_coordinator(mock_bluet_device(), entry)
    with patch_async_setup_entry():
        hass.data[DOMAIN] = {}
        hass.data[DOMAIN][entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    await hass.async_block_till_done()

    battery_sensor = hass.states.get("sensor.test_bluet_temperature")
    assert battery_sensor
    assert battery_sensor.state == "20.5"


async def test_signal_strength_sensor(hass: HomeAssistant, enable_bluetooth):
    """Test a mocked signal strength sensor."""

    entry = mock_config_entry(hass)
    coordinator = mock_coordinator(mock_bluet_device(), entry)
    with patch_async_setup_entry():
        hass.data[DOMAIN] = {}
        hass.data[DOMAIN][entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    await hass.async_block_till_done()

    battery_sensor = hass.states.get("sensor.test_bluet_signal_strength")
    assert battery_sensor
    assert battery_sensor.state == "-44"


async def test_new_device(hass: HomeAssistant, enable_bluetooth):
    """Test creation of a new device has default data."""

    entry = mock_config_entry(hass)
    with patch_async_register_callback(), patch_bluet_storage():
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    temperature_sensor = hass.states.get("sensor.test_device_1_temperature")
    assert temperature_sensor
    assert temperature_sensor.state == "0"
    device = hass.data[DOMAIN][entry.entry_id].device
    assert device.identity_key == bytes.fromhex(FAKE_IDENTITY_KEY_1)
    assert device.last_seen is None
    assert device.new_data_available is False


async def test_existing_device(hass: HomeAssistant, enable_bluetooth):
    """Test loading of existing data from storage."""

    entry = mock_config_entry(hass, FAKE_CONFIG_DATA_2)
    with patch_async_register_callback(), patch_bluet_storage():
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = hass.data[DOMAIN][entry.entry_id].device
    assert device.identity_key == bytes.fromhex(FAKE_IDENTITY_KEY_2)
    assert device.count == 98304
    assert device.last_seen == FAKE_TIME_2
    assert device.new_data_available is False


async def test_eid_message(hass: HomeAssistant, enable_bluetooth):
    """Test reception and decoding of an Eddystone EID message."""

    entry = mock_config_entry(hass, FAKE_CONFIG_DATA_1)
    with patch_async_register_callback(), patch_bluet_storage():
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator: BlueTCoordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator is not None
    # At startup this device should not have any last_seen value
    assert coordinator.device.last_seen is None
    with freeze_time(FAKE_TIME_1):
        coordinator.update_ble(
            build_eddystone_service_info(EID_PACKET_1), BluetoothChange.ADVERTISEMENT
        )

    # Update the data with an EID message for count 0
    await coordinator._async_update_data()
    # This device should now have a last_seen time updated from this packet
    # reception.
    assert coordinator.device.last_seen == FAKE_TIME_1


async def test_etlm_message(hass: HomeAssistant, enable_bluetooth):
    """Test reception and decoding of an Eddystone ETLM message."""

    entry = mock_config_entry(hass)
    with patch_async_register_callback(), patch_bluet_storage():
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator: BlueTCoordinator = hass.data[DOMAIN][entry.entry_id]

    # At startup this device should not have any last_seen value
    assert coordinator.device.last_seen is None

    with freeze_time(FAKE_TIME_1):
        coordinator.update_ble(
            build_eddystone_service_info(EID_PACKET_1), BluetoothChange.ADVERTISEMENT
        )
        coordinator.update_ble(
            build_eddystone_service_info(ETLM_PACKET_1), BluetoothChange.ADVERTISEMENT
        )

    # Ask the coordinator to poll for new data.
    await coordinator.async_request_refresh()
    await hass.async_block_till_done()

    temperature_entity_id = "sensor.test_device_1_temperature"
    battery_entity_id = "sensor.test_device_1_battery"
    signal_entity_id = "sensor.test_device_1_signal_strength"

    battery_sensor = hass.states.get(temperature_entity_id)
    assert battery_sensor
    assert battery_sensor.state == "20.5"
    temperature_sensor = hass.states.get(battery_entity_id)
    assert temperature_sensor
    assert temperature_sensor.state == "2953"
    signal_sensor = hass.states.get(signal_entity_id)
    assert signal_sensor
    assert signal_sensor.state == "-63"


async def test_eid_other_device(hass: HomeAssistant, enable_bluetooth):
    """Test reception and decoding of an Eddystone EID message for an unknown device."""

    entry = mock_config_entry(hass, FAKE_CONFIG_DATA_2)
    with patch_async_register_callback(), patch_bluet_storage():
        await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator: BlueTCoordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator is not None
    # Send an update for device 1. Device 2 should not be able to decode this
    with freeze_time(FAKE_TIME_1):
        coordinator.update_ble(
            build_eddystone_service_info(EID_PACKET_1), BluetoothChange.ADVERTISEMENT
        )

    # Update the data with an EID message for count 0
    await coordinator._async_update_data()

    # This device should not have recognized the packet and ignored it.
    assert coordinator.device.last_seen == FAKE_TIME_2
