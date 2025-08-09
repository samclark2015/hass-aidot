"""Config flow for AiDot integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries, exceptions
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from aidot.client import AidotClient
from aidot.const import SUPPORTED_COUNTRY_NAMES

from .const import (
    CONF_COUNTRY,
    CONF_PASSWORD,
    CONF_SELECTED_HOUSE,
    CONF_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle AiDot config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._client: AidotClient | None = None
        self._login_response: dict[str, Any] = {}
        self._house_list: list[dict[str, Any]] = []
        self._selected_house: dict[str, Any] = {}
        self._device_list: list[dict[str, Any]] = []
        self._product_list: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                username = user_input[CONF_USERNAME]
                password = user_input[CONF_PASSWORD]
                country_name = user_input[CONF_COUNTRY]

                session = async_get_clientsession(self.hass)
                self._client = AidotClient(session, country_name, username, password)
                self._login_response = await self._client.async_post_login()

                # Get house list
                self._house_list = await self._client.async_get_houses()

                return await self.async_step_choose_house()

            except Exception:
                _LOGGER.exception("Unexpected exception during login")
                errors["base"] = "cannot_connect"

        # Default user input if none provided
        if user_input is None:
            user_input = {}

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_COUNTRY,
                    default=user_input.get(CONF_COUNTRY, "United States"),
                ): vol.In(SUPPORTED_COUNTRY_NAMES),
                vol.Required(
                    CONF_USERNAME, default=user_input.get(CONF_USERNAME, vol.UNDEFINED)
                ): str,
                vol.Required(
                    CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, vol.UNDEFINED)
                ): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_choose_house(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle house selection step."""
        errors: dict[str, str] = {}

        if user_input is not None and self._client is not None:
            selected_house_name = user_input.get(CONF_SELECTED_HOUSE)

            # Find the selected house
            for house in self._house_list:
                if house["name"] == selected_house_name:
                    self._selected_house = house
                    break

            try:
                # Get device list for the selected house
                self._device_list = await self._client.async_get_devices(
                    self._selected_house["id"]
                )

                # Get product list
                product_ids = ",".join(
                    device["productId"] for device in self._device_list
                )
                self._product_list = await self._client.async_get_products(product_ids)

                # Create unique ID from login response
                username = self._login_response["username"]
                house_id = self._selected_house["id"]
                unique_id = f"{username}_{house_id}"

                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # Create the entry
                title = f"{username} {self._selected_house['name']}"
                return self.async_create_entry(
                    title=title,
                    data={
                        "login_response": self._login_response,
                        "selected_house": self._selected_house,
                        "device_list": self._device_list,
                        "product_list": self._product_list,
                    },
                )

            except Exception:
                _LOGGER.exception("Error getting devices or products")
                errors["base"] = "cannot_connect"

        # Get default house if available
        default_house_name = None
        for house in self._house_list:
            if house.get("isDefault"):
                default_house_name = house["name"]
                break

        # Get all house names
        house_name_list = [house["name"] for house in self._house_list]

        if user_input is None:
            user_input = {}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_HOUSE,
                    default=user_input.get(
                        CONF_SELECTED_HOUSE,
                        default_house_name
                        or (house_name_list[0] if house_name_list else ""),
                    ),
                ): vol.In(house_name_list)
            }
        )

        return self.async_show_form(
            step_id="choose_house",
            data_schema=schema,
            errors=errors,
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid authentication."""
