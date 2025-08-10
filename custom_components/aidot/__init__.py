"""The aidot integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from aidot.client import AidotClient

from .const import (
    ATTR_CONFIG_ENTRY_ID,
    DATA_LOGIN_RESPONSE,
    DOMAIN,
    PLATFORMS,
    SERVICE_REFRESH_DEVICES,
)

if TYPE_CHECKING:
    from aidot.client import AidotClient

_LOGGER = logging.getLogger(__name__)

type AidotConfigEntry = ConfigEntry[AidotClient]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the AiDot integration."""

    async def async_refresh_devices(call: ServiceCall) -> None:
        """Handle refresh devices service call."""
        config_entry_id = call.data[ATTR_CONFIG_ENTRY_ID]

        # Validate config entry exists and is loaded
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if not entry:
            raise ServiceValidationError(f"Config entry {config_entry_id} not found")

        if entry.state != ConfigEntryState.LOADED:
            raise ServiceValidationError(
                f"Config entry {config_entry_id} is not loaded"
            )

        if entry.domain != DOMAIN:
            raise ServiceValidationError(
                f"Config entry {config_entry_id} is not for {DOMAIN}"
            )

        try:
            client = entry.runtime_data

            # Stop and restart discovery to refresh device list
            _LOGGER.info(
                "Stopping device discovery for config entry %s", config_entry_id
            )
            client.stop_discover()

            _LOGGER.info(
                "Starting device discovery for config entry %s", config_entry_id
            )
            client.start_discover()

            # Reload platforms to pick up any new devices
            _LOGGER.info("Reloading platforms for config entry %s", config_entry_id)
            await hass.config_entries.async_reload(config_entry_id)

            _LOGGER.info(
                "Device discovery refresh completed for config entry %s",
                config_entry_id,
            )

        except Exception as err:
            _LOGGER.error(
                "Failed to refresh devices for config entry %s: %s",
                config_entry_id,
                err,
            )
            raise HomeAssistantError(f"Failed to refresh devices: {err}") from err

    # Register the service
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_DEVICES,
        async_refresh_devices,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
            }
        ),
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: AidotConfigEntry) -> bool:
    """Set up aidot from a config entry."""
    login_info = entry.data[DATA_LOGIN_RESPONSE]

    session = async_get_clientsession(hass)
    client = AidotClient(session, token=login_info)

    # Store the client in runtime_data
    entry.runtime_data = client

    # Start discovery
    client.start_discover()

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: AidotConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms first
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok and entry.runtime_data:
        # Clean up the client if it has cleanup methods
        try:
            # The AidotClient may have cleanup methods we should call
            entry.runtime_data.stop_discover()
        except Exception as err:
            _LOGGER.debug("Error during client cleanup: %s", err)

    return unload_ok


async def async_unload(hass: HomeAssistant) -> bool:
    """Unload the integration and clean up services."""
    # Remove services when the integration is completely unloaded
    hass.services.async_remove(DOMAIN, SERVICE_REFRESH_DEVICES)
    _LOGGER.debug("AiDot services removed")
    return True
