"""Config flow for Hello World integration."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp.client import ClientSession
import voluptuous as vol

from aidot.client import AidotClient
from aidot.const import (
    CONF_COUNTRY,
    CONF_PASSWORD,
    CONF_SELECTED_HOUSE,
    CONF_USERNAME,
    SUPPORTED_COUNTRY_NAMES,
)
from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DOMAIN = "aidot"


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    if len(data["host"]) < 3:
        raise InvalidHost
    return {"title": data["host"]}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle aidot config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._client: AidotClient | None = None
        self.login_response: dict[str, Any] = {}
        self.house_list: list[dict[str, Any]] = []

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            try:
                # get ContryCode
                username = user_input[CONF_USERNAME]
                password = user_input[CONF_PASSWORD]
                country_name = user_input[CONF_COUNTRY]

                self._client = client = AidotClient(
                    ClientSession(), country_name, username, password
                )
                self.login_response = await client.async_post_login()

                # get house list
                self.house_list = await client.async_get_houses()

                return await self.async_step_choose_house()

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidHost:
                errors["host"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "login_failed"

        if user_input is None:
            user_input = {}

        DATA_SCHEMA = vol.Schema(
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
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_choose_house(self, user_input=None):
        """Please select a room."""
        errors = {}
        if user_input is None:
            user_input = {}

        if (
            user_input.get(CONF_SELECTED_HOUSE) is not None
            and self._client is not None
        ):
            # get all house name
            for item in self.house_list:
                if item["name"] == user_input.get(CONF_SELECTED_HOUSE):
                    self.selected_house = item

            # get device_list
            self.device_list = await self._client.async_get_devices(
                self.selected_house["id"]
            )

            # get product_list
            product_ids = ",".join([item["productId"] for item in self.device_list])
            self.product_list = await self._client.async_get_products(
                product_ids
            )

            title = self.login_response["username"] + " " + self.selected_house["name"]
            return self.async_create_entry(
                title=title,
                data={
                    "login_response": self.login_response,
                    "selected_house": self.selected_house,
                    "device_list": self.device_list,
                    "product_list": self.product_list,
                },
            )

        # get default house
        default_house = {}
        for item in self.house_list:
            if item["isDefault"]:
                default_house = item

        # get all house name
        house_name_list = [item["name"] for item in self.house_list]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_HOUSE,
                    default=user_input.get(CONF_SELECTED_HOUSE, default_house["name"]),
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


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""
