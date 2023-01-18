"""BlueT sensor module."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .bluet import BlueTCoordinator, BlueTDevice
from .const import CONF_IDENTITY_KEY, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class BlueTSensorEntityDescriptionMixin:
    """Description for a BlueT sensor."""

    state_fn: Callable[[BlueTDevice], Any]
    set_fn: Callable[[BlueTDevice, Any], Any]


@dataclass
class BlueTSensorEntityDescription(
    SensorEntityDescription, BlueTSensorEntityDescriptionMixin
):
    """Describes a sensor."""


DEVICE_ENTITY_DESCRIPTIONS: list[BlueTSensorEntityDescription] = [
    BlueTSensorEntityDescription(
        device_class=SensorDeviceClass.VOLTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        key="battery",
        name="Battery",
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        state_class=SensorStateClass.MEASUREMENT,
        state_fn=lambda device: device.battery,
        set_fn=lambda device, val: device.set_battery(val),
    ),
    BlueTSensorEntityDescription(
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_category=EntityCategory.DIAGNOSTIC,
        key="temperature",
        name="Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        state_fn=lambda device: device.temperature,
        set_fn=lambda device, val: device.set_temperature(val),
    ),
    BlueTSensorEntityDescription(
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        entity_category=EntityCategory.DIAGNOSTIC,
        key="strength",
        name="Signal Strength",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        state_fn=lambda device: device.signal_strength,
        set_fn=lambda device, val: device.set_signal_strength(val),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add a new sensor."""

    _LOGGER.info("Async_setup_entry: entry_id is %s", entry.entry_id)
    _LOGGER.info("Async_setup_entry: data is %s", entry.data)
    coordinator: BlueTCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        BlueTSensorEntity(
            coordinator,
            description,
        )
        for description in DEVICE_ENTITY_DESCRIPTIONS
    )


class BlueTSensorEntity(CoordinatorEntity[BlueTCoordinator], RestoreSensor):
    """A BlueT sensor."""

    entity_description: BlueTSensorEntityDescription
    _device: BlueTDevice
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BlueTCoordinator,
        entity_description: BlueTSensorEntityDescription,
    ) -> None:
        """Initialize a BlueT sensor."""
        _LOGGER.info("Added new sensor entity %s", coordinator.device)
        super().__init__(coordinator)
        self._device = coordinator.device
        identity_key = coordinator.entry.data[CONF_IDENTITY_KEY]
        self._attr_unique_id = f"{identity_key}-{entity_description.key}"
        self.entity_description = entity_description
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{identity_key}")},
            manufacturer="BlueT",
            name=self._device.name,
        )

    @property
    def native_value(self) -> int | float | None:
        """Return the native value."""
        return self.entity_description.state_fn(self._device)

    async def async_added_to_hass(self):
        """Entity was added to hass. Restore the state if there is any."""
        await super().async_added_to_hass()
        if val := await self.async_get_last_sensor_data():
            self.entity_description.set_fn(self._device, val)
