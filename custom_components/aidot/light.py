"""Support for Aidot lights."""

import asyncio
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from aidot.const import CONF_CCT, CONF_DIMMING, CONF_ON_OFF, CONF_RGBW

from .const import (
    DOMAIN,
    COMMAND_MAX_RETRIES,
    COMMAND_RETRY_BASE_DELAY,
    COMMAND_RETRY_BACKOFF_FACTOR,
)
from .coordinator import AidotConfigEntry, AidotDeviceUpdateCoordinator
from .device_wrapper import DeviceClientWrapper

_LOGGER = logging.getLogger(__name__)

# Limit concurrent updates to prevent command conflicts
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AidotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Light."""
    coordinator = entry.runtime_data
    lists_added: set[str] = set()

    @callback
    def add_entities() -> None:
        """Add light entities."""
        nonlocal lists_added
        new_lists = {
            device_coordinator.device_client.device_id
            for device_coordinator in coordinator.device_coordinators.values()
        }

        if new_lists - lists_added:
            async_add_entities(
                AidotLight(coordinator.device_coordinators[device_id])
                for device_id in new_lists
            )
            lists_added |= new_lists
        elif lists_added - new_lists:
            removed_device_ids = lists_added - new_lists
            for device_id in removed_device_ids:
                entity_registry = er.async_get(hass)
                if entity := entity_registry.async_get_entity_id(
                    "light", DOMAIN, device_id
                ):
                    entity_registry.async_remove(entity)
            lists_added = lists_added - removed_device_ids

    coordinator.async_add_listener(add_entities)
    add_entities()


class AidotLight(CoordinatorEntity[AidotDeviceUpdateCoordinator], LightEntity):
    """Representation of a Aidot Wi-Fi Light."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self, coordinator: AidotDeviceUpdateCoordinator
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.device_client.info.dev_id
        if hasattr(coordinator.device_client.info, "cct_max"):
            self._attr_max_color_temp_kelvin = coordinator.device_client.info.cct_max
        if hasattr(coordinator.device_client.info, "cct_min"):
            self._attr_min_color_temp_kelvin = coordinator.device_client.info.cct_min

        model_id = coordinator.device_client.info.model_id
        manufacturer = model_id.split(".")[0]
        model = model_id[len(manufacturer) + 1 :]
        mac = format_mac(coordinator.device_client.info.mac)

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            connections={(CONNECTION_NETWORK_MAC, mac)},
            manufacturer=manufacturer,
            model=model,
            name=coordinator.device_client.info.name,
            hw_version=coordinator.device_client.info.hw_version,
        )
        if coordinator.device_client.info.enable_rgbw:
            self._attr_color_mode = ColorMode.RGBW
            self._attr_supported_color_modes = {ColorMode.RGBW, ColorMode.COLOR_TEMP}
        elif coordinator.device_client.info.enable_cct:
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
        else:
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._update_status()

    def _update_status(self) -> None:
        """Update entity state from coordinator data."""
        # Available only if device is connected and online
        self._attr_available = (
            self.coordinator.is_connected
            and self.coordinator.data is not None
            and self.coordinator.data.online
        )

        if self.coordinator.data:
            self._attr_is_on = self.coordinator.data.on
            self._attr_brightness = self.coordinator.data.dimming
            self._attr_color_temp_kelvin = self.coordinator.data.cct
            self._attr_rgbw_color = self.coordinator.data.rgbw

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update."""
        self._update_status()
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        attrs = {CONF_ON_OFF: 1}
        if ATTR_BRIGHTNESS in kwargs:
            attrs[CONF_DIMMING] = kwargs[ATTR_BRIGHTNESS]
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            self._attr_color_mode = ColorMode.COLOR_TEMP
            attrs[CONF_CCT] = kwargs[ATTR_COLOR_TEMP_KELVIN]
        if ATTR_RGBW_COLOR in kwargs:
            self._attr_color_mode = ColorMode.RGBW
            rgbw = kwargs[ATTR_RGBW_COLOR]
            final_rgbw = (rgbw[0] << 24) | (rgbw[1] << 16) | (rgbw[2] << 8) | rgbw[3]
            attrs[CONF_RGBW] = final_rgbw

        # Optimistically update the UI state
        self.coordinator.data.on = True
        self._attr_is_on = True
        self.async_write_ha_state()

        try:
            await self._send_command_with_retry(attrs)
        except ConnectionError as err:
            # Revert optimistic state on failure
            self.coordinator.data.on = False
            self._attr_is_on = False
            self.async_write_ha_state()
            _LOGGER.error(
                "Failed to turn on %s after retry: %s",
                self.entity_id,
                err,
            )
            raise HomeAssistantError(f"Failed to turn on light: {err}") from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        # Optimistically update the UI state
        self.coordinator.data.on = False
        self._attr_is_on = False
        self.async_write_ha_state()

        try:
            await self._send_command_with_retry({CONF_ON_OFF: 0})
        except ConnectionError as err:
            # Revert optimistic state on failure
            self.coordinator.data.on = True
            self._attr_is_on = True
            self.async_write_ha_state()
            _LOGGER.error(
                "Failed to turn off %s after retry: %s",
                self.entity_id,
                err,
            )
            raise HomeAssistantError(f"Failed to turn off light: {err}") from err

    async def _send_command_with_retry(self, attrs: dict[str, Any]) -> None:
        """Send command with automatic retry on connection failure."""
        max_retries = COMMAND_MAX_RETRIES
        retry_delay = COMMAND_RETRY_BASE_DELAY

        for attempt in range(max_retries + 1):
            try:
                await self.coordinator.device_client.send_dev_attr(attrs)
                return  # Success!
            except ConnectionError as err:
                if attempt < max_retries:
                    _LOGGER.warning(
                        "Command failed for %s (attempt %d/%d): %s. Triggering reconnect and retrying...",
                        self.entity_id,
                        attempt + 1,
                        max_retries + 1,
                        err,
                    )
                    # Trigger reconnection attempt with proper error handling
                    wrapper = DeviceClientWrapper(self.coordinator.device_client)
                    if wrapper.ip_address:
                        
                        async def reconnect_with_logging():
                            """Reconnect with error logging."""
                            try:
                                await self.coordinator.device_client.async_login()
                            except Exception as reconnect_err:
                                _LOGGER.error(
                                    "Reconnection attempt failed for %s: %s",
                                    self.entity_id,
                                    reconnect_err,
                                )
                        
                        self.hass.async_create_task(reconnect_with_logging())
                    # Wait before retry
                    await asyncio.sleep(retry_delay)
                    retry_delay *= COMMAND_RETRY_BACKOFF_FACTOR
                else:
                    # Final attempt failed
                    raise
