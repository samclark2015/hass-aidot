"""The aidot integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

from aiohttp.client import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from aidot.client import AidotClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT]
DOMAIN = "aidot"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up aidot from a config entry."""
    aidot_data = hass.data.setdefault(DOMAIN, {})
    aidot_data["device_list"] = entry.data["device_list"]
    aidot_data["login_response"] = login_info = entry.data[
        "login_response"
    ]

    client = AidotClient(
        ClientSession(),
        token=login_info
    )

    aidot_data["client"] = client
    aidot_data["products"] = entry.data["product_list"]

    client.start_discover()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


    return True


async def cleanup_device_registry(hass: HomeAssistant) -> None:
    """Remove deleted device registry entry if there are no remaining entities."""
    device_registry = dr.async_get(hass)
    for dev_id, device_entry in list(device_registry.devices.items()):
        for item in device_entry.identifiers:
            _LOGGER.info(item)
            _LOGGER.info(dev_id)
            device_registry.async_remove_device(dev_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop("device_list", None)
        hass.data[DOMAIN].pop("login_response", None)
        hass.data[DOMAIN].pop("products", None)

    return unload_ok
