"""The aidot integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from aidot.client import AidotClient

from .const import (
    DATA_LOGIN_RESPONSE,
    PLATFORMS,
)

if TYPE_CHECKING:
    from aidot.client import AidotClient

_LOGGER = logging.getLogger(__name__)

type AidotConfigEntry = ConfigEntry[AidotClient]


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
            if hasattr(entry.runtime_data, "stop_discover"):
                entry.runtime_data.stop_discover()
        except Exception as err:
            _LOGGER.debug("Error during client cleanup: %s", err)

    return unload_ok
