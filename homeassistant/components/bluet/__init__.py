"""The BlueT integration."""
from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import BluetoothCallbackMatcher
from homeassistant.components.bluetooth.models import BluetoothScanningMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant

from .beacon import BlueTDevice
from .bluet import BlueTCoordinator, BlueTStorage
from .const import (
    CONF_COUNT,
    CONF_EXPONENT,
    CONF_IDENTITY_KEY,
    CONF_LAST_SEEN,
    CONF_WINDOW_SIZE,
    DATA_STORAGE,
    DOMAIN,
    EDDYSTONE_SERVICE_UUID,
)

# pylint: disable=fixme

PLATFORMS: list[Platform] = [Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a BlueT beacon from a config entry."""

    identity_key = entry.unique_id
    assert identity_key is not None
    storage = BlueTStorage(hass)
    await storage.async_load()
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][DATA_STORAGE] = storage

    stored_data = storage.data.get(identity_key)
    if stored_data is None:
        _LOGGER.debug("No saved data found for %s", identity_key)
        # No saved data for this config entry. Create one now.
        stored_data = {
            CONF_IDENTITY_KEY: identity_key,
            CONF_COUNT: entry.data[CONF_COUNT],
        }
        _LOGGER.info("Creating new entry %s", stored_data)
        await storage.async_create_item(stored_data)

    _LOGGER.debug("Setting up %s with count %s", identity_key, stored_data[CONF_COUNT])
    last_seen_str = stored_data.get(CONF_LAST_SEEN)
    last_seen = datetime.fromisoformat(last_seen_str) if last_seen_str else None
    device: BlueTDevice = BlueTDevice(
        name=entry.data[CONF_NAME],
        identity_key=bytes.fromhex(identity_key),
        exponent=entry.data[CONF_EXPONENT],
        count=stored_data[CONF_COUNT],
        window_size=entry.data[CONF_WINDOW_SIZE],
        last_seen=last_seen,
    )
    coordinator: BlueTCoordinator = BlueTCoordinator(hass, entry, device)

    # Necessary?
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            coordinator.update_ble,
            BluetoothCallbackMatcher(
                service_data_uuid=EDDYSTONE_SERVICE_UUID, connectable=False
            ),
            BluetoothScanningMode.PASSIVE,
        )
    )  # only start after all platforms have had a chance to subscribe
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
