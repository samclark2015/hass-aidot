"""DataUpdateCoordinator for AiDot."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from aidot.client import AidotClient
from aidot.exceptions import AidotAuthFailed

from .const import DATA_SELECTED_HOUSE, DOMAIN

_LOGGER = logging.getLogger(__name__)

type AidotConfigEntry = ConfigEntry[AidotClient]


class AidotDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: AidotClient,
        entry: AidotConfigEntry,
    ) -> None:
        """Initialize."""
        self.client = client
        self.config_entry = entry
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=10),
            config_entry=entry,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        try:
            # Get selected house info
            selected_house = self.config_entry.data[DATA_SELECTED_HOUSE]
            house_id = selected_house["id"]

            # Fetch device list for the selected house
            device_list = await self.client.async_get_devices(house_id)

            # Get product list if there are devices
            product_list = []
            if device_list:
                product_ids = ",".join(
                    device["productId"]
                    for device in device_list
                    if "productId" in device
                )
                if product_ids:
                    product_list = await self.client.async_get_products(product_ids)

            # Match products with devices
            for product in product_list:
                for device in device_list:
                    if device.get("productId") == product.get("id"):
                        device["product"] = product

            return {
                "device_list": device_list,
                "product_list": product_list,
            }

        except AidotAuthFailed as err:
            raise ConfigEntryAuthFailed(
                "Authentication failed while fetching device data"
            ) from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via library."""
        try:
            # Get current device list
            device_list = await self.client.async_get_devices(self.house_id)

            # Get product list for all devices
            if device_list:
                product_ids = ",".join(device["productId"] for device in device_list)
                product_list = await self.client.async_get_products(product_ids)
            else:
                product_list = []

            # Check for new devices
            current_device_ids = {device["id"] for device in device_list}
            new_device_ids = current_device_ids - self._known_device_ids

            if new_device_ids:
                _LOGGER.info(
                    "Found %d new device(s): %s", len(new_device_ids), new_device_ids
                )
                self._known_device_ids.update(new_device_ids)

            # Check for removed devices
            removed_device_ids = self._known_device_ids - current_device_ids
            if removed_device_ids:
                _LOGGER.info(
                    "Removed %d device(s): %s",
                    len(removed_device_ids),
                    removed_device_ids,
                )
                self._known_device_ids -= removed_device_ids
                await self._async_remove_devices(removed_device_ids)

            return {
                "device_list": device_list,
                "product_list": product_list,
                "new_devices": list(new_device_ids),
                "removed_devices": list(removed_device_ids),
            }

        except Exception as err:
            raise UpdateFailed(f"Error communicating with AiDot API: {err}") from err

    def initialize_known_devices(self, device_list: list[dict[str, Any]]) -> None:
        """Initialize the set of known device IDs."""
        self._known_device_ids = {device["id"] for device in device_list}

    async def _async_remove_devices(self, device_ids: set[str]) -> None:
        """Remove devices that are no longer available."""
        device_registry = dr.async_get(self.hass)

        for device_id in device_ids:
            # Find device in registry
            device_entry = device_registry.async_get_device(
                identifiers={(DOMAIN, device_id)}
            )

            if device_entry:
                device_registry.async_update_device(
                    device_entry.id,
                    remove_config_entry_id=self.config_entry.entry_id,
                )
                _LOGGER.info("Removed device %s from registry", device_id)
