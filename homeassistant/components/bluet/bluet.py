"""BlueT implementation details."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from home_assistant_bluetooth import BluetoothServiceInfoBleak
from voluptuous_serialize import vol

from homeassistant.components.bluetooth.models import BluetoothChange
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.collection import StorageCollection
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .beacon import BlueTDevice
from .const import (
    CONF_COUNT,
    CONF_IDENTITY_KEY,
    CONF_LAST_SEEN,
    DATA_STORAGE,
    DOMAIN,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


class BlueTCoordinator(DataUpdateCoordinator[BlueTDevice]):
    """BlueT data update coordinator."""

    device: BlueTDevice
    entry: ConfigEntry
    last_saved: datetime | None

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, device: BlueTDevice
    ) -> None:
        """Initialize the BlueT Coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="BlueT",
            update_method=self._async_update_data,
            update_interval=timedelta(seconds=60),
        )
        self.device = device
        self.entry = entry
        self.last_saved = device.last_seen

    async def _async_update_data(self) -> BlueTDevice:
        """Update the device state."""

        # If the beacon has updated its last_seen field since the last time
        # we checked save the current device count + last seen to persistent
        # storage.
        if self.device.last_seen != self.last_saved:
            _LOGGER.debug("Saving updated data for %s", self.device.name)
            # Update the storage entry
            storage: BlueTStorage = self.hass.data[DOMAIN][DATA_STORAGE]
            new_data = {
                CONF_COUNT: int(self.device.count),
                CONF_LAST_SEEN: datetime.utcnow().isoformat(),
            }
            await storage.async_update_item(
                self.entry.data[CONF_IDENTITY_KEY], new_data
            )
            self.last_saved = self.device.last_seen
        return self.device

    def update_ble(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """BLE update callback."""
        self.device.process_packet(service_info)


# Creating a new storage entry for a device must have an identity key and the
# configured count. There is no last_seen field initially since the device
# has not yet been seen.
CREATE_FIELDS = {
    vol.Required(CONF_IDENTITY_KEY): str,
    vol.Required(CONF_COUNT): int,
}

# Updates should always provide a new count and last-seen time.
UPDATE_FIELDS = {
    vol.Required(CONF_COUNT): int,
    vol.Required(CONF_LAST_SEEN): str,
}


class BlueTStorage(StorageCollection):
    """Manage persistent storage for BlueT devices."""

    CREATE_SCHEMA = vol.Schema(CREATE_FIELDS)
    UPDATE_SCHEMA = vol.Schema(UPDATE_FIELDS)

    def __init__(self, hass: HomeAssistant) -> None:
        """Create a storage object."""
        super().__init__(Store(hass, STORAGE_VERSION, STORAGE_KEY), _LOGGER)

    async def _process_create_data(self, data: dict) -> dict:
        """Create a new entry."""
        return self.CREATE_SCHEMA(data)

    async def _update_data(self, data: dict, update_data: dict) -> dict:
        """Update an entry."""
        return {**data, **self.UPDATE_SCHEMA(update_data)}

    def _get_suggested_id(self, info: dict) -> str:
        return str(info[CONF_IDENTITY_KEY])
