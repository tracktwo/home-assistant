"""Test the BlueT config flow."""
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.components.bluet.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry


async def test_form(hass: HomeAssistant, enable_bluetooth) -> None:
    """Test we get the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] is None

    with patch(
        "homeassistant.components.bluet.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "name": "Test BlueT Device",
                "exponent": 15,
                "window_size": 3,
                "count": 1,
                "identity_key": "12345678901234567890123456789012",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Test BlueT Device"
    assert result2["data"] == {
        "name": "Test BlueT Device",
        "exponent": 15,
        "window_size": 3,
        "count": 1,
        "identity_key": "12345678901234567890123456789012",
    }
    assert len(mock_setup_entry.mock_calls) == 1


async def test_duplicate_key(hass: HomeAssistant, enable_bluetooth):
    """Test adding a device with a duplicate key fails."""

    MockConfigEntry(
        domain=DOMAIN, unique_id="12345678901234567890123456789012"
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )

    with patch(
        "homeassistant.components.bluet.async_setup_entry",
        return_value=True,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "name": "Test BlueT Device",
                "exponent": 15,
                "window_size": 3,
                "count": 1,
                "identity_key": "12345678901234567890123456789012",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.ABORT
    assert result2["reason"] == "already_configured"
