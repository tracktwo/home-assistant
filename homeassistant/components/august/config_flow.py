"""Config flow for August integration."""
from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from yalexs.authenticator import ValidationResult
from yalexs.const import BRANDS, DEFAULT_BRAND

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client

from .const import (
    CONF_ACCESS_TOKEN_CACHE_FILE,
    CONF_BRAND,
    CONF_LOGIN_METHOD,
    DEFAULT_LOGIN_METHOD,
    DOMAIN,
    LOGIN_METHODS,
    VERIFICATION_CODE_KEY,
)
from .exceptions import CannotConnect, InvalidAuth, RequireValidation
from .gateway import AugustGateway

_LOGGER = logging.getLogger(__name__)


async def async_validate_input(
    data: dict[str, Any], august_gateway: AugustGateway
) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.

    Request configuration steps from the user.
    """
    assert august_gateway.authenticator is not None
    authenticator = august_gateway.authenticator
    if (code := data.get(VERIFICATION_CODE_KEY)) is not None:
        result = await authenticator.async_validate_verification_code(code)
        _LOGGER.debug("Verification code validation: %s", result)
        if result != ValidationResult.VALIDATED:
            raise RequireValidation

    try:
        await august_gateway.async_authenticate()
    except RequireValidation:
        _LOGGER.debug(
            "Requesting new verification code for %s via %s",
            data.get(CONF_USERNAME),
            data.get(CONF_LOGIN_METHOD),
        )
        if code is None:
            await august_gateway.authenticator.async_send_verification_code()
        raise

    return {
        "title": data.get(CONF_USERNAME),
        "data": august_gateway.config_entry(),
    }


@dataclass
class ValidateResult:
    """Result from validation."""

    validation_required: bool
    info: dict[str, Any]
    errors: dict[str, str]
    description_placeholders: dict[str, str]


class AugustConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for August."""

    VERSION = 1

    def __init__(self):
        """Store an AugustGateway()."""
        self._august_gateway: AugustGateway | None = None
        self._aiohttp_session: aiohttp.ClientSession | None = None
        self._user_auth_details: dict[str, Any] = {}
        self._needs_reset = True
        self._mode = None
        super().__init__()

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        return await self.async_step_user_validate()

    async def async_step_user_validate(self, user_input=None):
        """Handle authentication."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}
        if user_input is not None:
            self._user_auth_details.update(user_input)
            validate_result = await self._async_auth_or_validate()
            description_placeholders = validate_result.description_placeholders
            if validate_result.validation_required:
                return await self.async_step_validation()
            if not (errors := validate_result.errors):
                return await self._async_update_or_create_entry(validate_result.info)

        return self.async_show_form(
            step_id="user_validate",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BRAND,
                        default=self._user_auth_details.get(CONF_BRAND, DEFAULT_BRAND),
                    ): vol.In(BRANDS),
                    vol.Required(
                        CONF_LOGIN_METHOD,
                        default=self._user_auth_details.get(
                            CONF_LOGIN_METHOD, DEFAULT_LOGIN_METHOD
                        ),
                    ): vol.In(LOGIN_METHODS),
                    vol.Required(
                        CONF_USERNAME,
                        default=self._user_auth_details.get(CONF_USERNAME),
                    ): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_validation(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle validation (2fa) step."""
        if user_input:
            if self._mode == "reauth":
                return await self.async_step_reauth_validate(user_input)
            return await self.async_step_user_validate(user_input)

        previously_failed = VERIFICATION_CODE_KEY in self._user_auth_details
        return self.async_show_form(
            step_id="validation",
            data_schema=vol.Schema(
                {vol.Required(VERIFICATION_CODE_KEY): vol.All(str, vol.Strip)}
            ),
            errors={"base": "invalid_verification_code"} if previously_failed else None,
            description_placeholders={
                CONF_BRAND: self._user_auth_details[CONF_BRAND],
                CONF_USERNAME: self._user_auth_details[CONF_USERNAME],
                CONF_LOGIN_METHOD: self._user_auth_details[CONF_LOGIN_METHOD],
            },
        )

    @callback
    def _async_get_gateway(self) -> AugustGateway:
        """Set up the gateway."""
        if self._august_gateway is not None:
            return self._august_gateway
        # Create an aiohttp session instead of using the default one since the
        # default one is likely to trigger august's WAF if another integration
        # is also using Cloudflare
        self._aiohttp_session = aiohttp_client.async_create_clientsession(self.hass)
        self._august_gateway = AugustGateway(self.hass, self._aiohttp_session)
        return self._august_gateway

    @callback
    def _async_shutdown_gateway(self) -> None:
        """Shutdown the gateway."""
        if self._aiohttp_session is not None:
            self._aiohttp_session.detach()
        self._august_gateway = None

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle configuration by re-auth."""
        self._user_auth_details = dict(entry_data)
        self._mode = "reauth"
        self._needs_reset = True
        return await self.async_step_reauth_validate()

    async def async_step_reauth_validate(self, user_input=None):
        """Handle reauth and validation."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}
        if user_input is not None:
            self._user_auth_details.update(user_input)
            validate_result = await self._async_auth_or_validate()
            description_placeholders = validate_result.description_placeholders
            if validate_result.validation_required:
                return await self.async_step_validation()
            if not (errors := validate_result.errors):
                return await self._async_update_or_create_entry(validate_result.info)

        return self.async_show_form(
            step_id="reauth_validate",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BRAND,
                        default=self._user_auth_details.get(CONF_BRAND, DEFAULT_BRAND),
                    ): vol.In(BRANDS),
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders=description_placeholders
            | {
                CONF_USERNAME: self._user_auth_details[CONF_USERNAME],
            },
        )

    async def _async_reset_access_token_cache_if_needed(
        self, gateway: AugustGateway, username: str, access_token_cache_file: str | None
    ) -> None:
        """Reset the access token cache if needed."""
        # We need to configure the access token cache file before we setup the gateway
        # since we need to reset it if the brand changes BEFORE we setup the gateway
        gateway.async_configure_access_token_cache_file(
            username, access_token_cache_file
        )
        if self._needs_reset:
            self._needs_reset = False
            await gateway.async_reset_authentication()

    async def _async_auth_or_validate(self) -> ValidateResult:
        """Authenticate or validate."""
        user_auth_details = self._user_auth_details
        gateway = self._async_get_gateway()
        assert gateway is not None
        await self._async_reset_access_token_cache_if_needed(
            gateway,
            user_auth_details[CONF_USERNAME],
            user_auth_details.get(CONF_ACCESS_TOKEN_CACHE_FILE),
        )
        await gateway.async_setup(user_auth_details)

        errors: dict[str, str] = {}
        info: dict[str, Any] = {}
        description_placeholders: dict[str, str] = {}
        validation_required = False

        try:
            info = await async_validate_input(user_auth_details, gateway)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except RequireValidation:
            validation_required = True
        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unhandled"
            description_placeholders = {"error": str(ex)}

        return ValidateResult(
            validation_required, info, errors, description_placeholders
        )

    async def _async_update_or_create_entry(self, info: dict[str, Any]) -> FlowResult:
        """Update existing entry or create a new one."""
        self._async_shutdown_gateway()

        existing_entry = await self.async_set_unique_id(
            self._user_auth_details[CONF_USERNAME]
        )
        if not existing_entry:
            return self.async_create_entry(title=info["title"], data=info["data"])

        self.hass.config_entries.async_update_entry(existing_entry, data=info["data"])
        await self.hass.config_entries.async_reload(existing_entry.entry_id)
        return self.async_abort(reason="reauth_successful")
