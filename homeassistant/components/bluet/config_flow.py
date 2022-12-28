"""Config flow for the BlueT integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_COUNT,
    CONF_EXPONENT,
    CONF_IDENTITY_KEY,
    CONF_NAME,
    CONF_WINDOW_SIZE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# pylint: disable=fixme

# Schema for beacon configuration. Each beacon device requires an identity key,
# an exponent value, and a window size.
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        # The beacon name is an arbitrary string
        vol.Required(CONF_NAME): str,
        # The identity key is a 16-byte hexadecimal value
        vol.Required(CONF_IDENTITY_KEY): vol.All(
            str  # , vol.Length(32)
            # , vol.Match(r'[A-Fa-f0-9]+')
        ),
        # The exponent is an integer from 0-15
        vol.Required(CONF_EXPONENT, default=15): vol.All(
            int,
            selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=15, mode=selector.NumberSelectorMode.BOX
                )
            ),
        ),
        # The window size is an integer at least 1
        vol.Required(CONF_WINDOW_SIZE, default=3): vol.All(int, vol.Range(min=1)),
        vol.Required(CONF_COUNT): int,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BlueT."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure a BlueT beacon."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        # The identity key is the unique ID for each beacon
        await self.async_set_unique_id(user_input[CONF_IDENTITY_KEY])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
