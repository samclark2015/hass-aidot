"""Support for AiDot lights."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGBW_COLOR,
    LightEntity,
)
from homeassistant.components.light.const import ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from aidot.client import AidotClient
from aidot.device_client import DeviceStatusData

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

type AidotConfigEntry = ConfigEntry[AidotClient]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AidotConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AiDot light platform."""
    client = entry.runtime_data
    device_list = entry.data.get("device_list", [])
    products = entry.data.get("product_list", [])

    # Match products with devices
    for product in products:
        for device in device_list:
            if device["productId"] == product["id"]:
                device["product"] = product

    # Filter for light devices that have the required data
    light_devices = [
        device
        for device in device_list
        if (
            device["type"] == "light"
            and "aesKey" in device
            and device["aesKey"]
            and device["aesKey"][0] is not None
        )
    ]

    async_add_entities(
        [AidotLight(hass, entry, client, device) for device in light_devices]
    )


class AidotLight(LightEntity):
    """Representation of an AiDot Wi-Fi Light."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: AidotConfigEntry,
        client: AidotClient,
        device: dict[str, Any],
    ) -> None:
        """Initialize the light."""
        super().__init__()
        self.hass = hass
        self.entry = entry
        self._device = device
        self._attr_unique_id = device["id"]
        self._attr_name = device["name"]

        # Set up device info
        self._setup_device_info()

        # Set up color mode support
        self._setup_color_modes()

        # Initialize device status and client
        self.device_status: DeviceStatusData | None = None
        self.recv_task: asyncio.Task | None = None
        self.lan_client = client.get_device_client(device)

    def _setup_device_info(self) -> None:
        """Set up device information."""
        model_id = self._device["modelId"]
        manufacturer = model_id.split(".")[0] if "." in model_id else "AiDot"
        model = model_id[len(manufacturer) + 1 :] if "." in model_id else model_id
        mac = format_mac(self._device["mac"]) if self._device.get("mac") else ""

        identifiers = (
            {(DOMAIN, self._attr_unique_id)} if self._attr_unique_id else set()
        )
        connections = {(CONNECTION_NETWORK_MAC, mac)} if mac else set()

        self._attr_device_info = DeviceInfo(
            identifiers=identifiers,
            connections=connections,
            manufacturer=manufacturer,
            model=model,
            name=self._device["name"],
            hw_version=self._device.get("hardwareVersion"),
        )

    def _setup_color_modes(self) -> None:
        """Set up supported color modes based on device capabilities."""
        supported_color_modes = set()
        self._cct_min = 0
        self._cct_max = 0

        product: dict = self._device.get("product", {})
        service_modules = product.get("serviceModules", [])

        for service in service_modules:
            identity = service.get("identity", "")

            if identity == "control.light.rgbw":
                supported_color_modes.add(ColorMode.RGBW)
            elif identity == "control.light.cct":
                properties = service.get("properties", [])
                if properties:
                    self._cct_min = int(properties[0].get("minValue", 0))
                    self._cct_max = int(properties[0].get("maxValue", 0))
                supported_color_modes.add(ColorMode.COLOR_TEMP)

        # Set the appropriate color mode and supported modes
        if ColorMode.RGBW in supported_color_modes:
            self._attr_color_mode = ColorMode.RGBW
            self._attr_supported_color_modes = {ColorMode.RGBW, ColorMode.COLOR_TEMP}
        elif ColorMode.COLOR_TEMP in supported_color_modes:
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
        else:
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    async def async_added_to_hass(self) -> None:
        """Called when the entity is added to Home Assistant."""

        async def recv_task() -> None:
            """Task to read status from the device."""
            await self.lan_client.send_action({}, "getDevAttrReq")
            while True:
                try:
                    self.device_status = await self.lan_client.read_status()
                    _LOGGER.debug(
                        "Device %s status updated: %s",
                        self._device["name"],
                        self.device_status,
                    )
                    await self._update_state()
                except asyncio.CancelledError:
                    _LOGGER.debug(
                        "recv_task cancelled for device: %s", self._device["name"]
                    )
                    break
                except Exception:
                    _LOGGER.exception(
                        "Error reading status for device %s", self._device["name"]
                    )
                    await asyncio.sleep(5)

        async def discovery_task() -> None:
            """Task to wait for device discovery."""
            try:
                await self.lan_client.async_wait_discovered()
                _LOGGER.info("%s added to Home Assistant", self._device["name"])
                self.recv_task = self.entry.async_create_background_task(
                    self.hass,
                    recv_task(),
                    f"aidot_recv_{self._device['id']}",
                )
            except asyncio.CancelledError:
                pass

        self.entry.async_create_background_task(
            self.hass, discovery_task(), f"aidot_discovery_{self._device['id']}"
        )

    async def async_will_remove_from_hass(self) -> None:
        """Release task."""
        await self.lan_client.close()
        if self.recv_task is not None:
            self.recv_task.cancel()
            self.recv_task = None

    async def _update_state(self) -> None:
        """Update the state of the entity."""
        if self.hass is not None and self.entity_id is not None:
            await self.async_update_ha_state(True)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.lan_client.connect_and_login
            and self.device_status is not None
            and self.device_status.online
        )

    @property
    def is_on(self) -> bool:
        """Return True if the light is on."""
        return self.device_status is not None and self.device_status.on

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        if self.device_status is None:
            return None
        return self.device_status.dimming if self.device_status.dimming else None

    @property
    def min_color_temp_kelvin(self) -> int:
        """Return the warmest color_temp_kelvin that this light supports."""
        return self._cct_min

    @property
    def max_color_temp_kelvin(self) -> int:
        """Return the coldest color_temp_kelvin that this light supports."""
        return self._cct_max

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the CT color value in Kelvin."""
        return self.device_status.cct if self.device_status else None

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Return the rgbw color value [int, int, int, int]."""
        return self.device_status.rgbw if self.device_status else None

    @property
    def color_mode(self) -> ColorMode | str | None:
        """Return the color mode of the light."""
        # For now, default to RGBW - this could be made more dynamic
        return ColorMode.RGBW

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        if not self.lan_client.connect_and_login:
            raise HomeAssistantError(
                "The device is not logged in or may not be on the local area network"
            )

        brightness = kwargs.get(ATTR_BRIGHTNESS, 255)

        if ATTR_BRIGHTNESS in kwargs and brightness is not None:
            await self.lan_client.async_set_brightness(brightness)

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            cct = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
            if cct is not None:
                if cct < self._cct_min or cct > self._cct_max:
                    raise HomeAssistantError(
                        f"Color temperature {cct} is out of range ({self._cct_min}-{self._cct_max})"
                    )
                await self.lan_client.async_set_cct(cct)

        if ATTR_RGBW_COLOR in kwargs:
            rgbw = kwargs.get(ATTR_RGBW_COLOR)
            if rgbw is not None:
                if len(rgbw) != 4:
                    raise HomeAssistantError("RGBW color must be a tuple of 4 integers")
                await self.lan_client.async_set_rgbw(rgbw)

        if not kwargs:
            await self.lan_client.async_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        if not self.lan_client.connect_and_login:
            raise HomeAssistantError(
                "The device is not logged in or may not be on the local area network"
            )
        await self.lan_client.async_turn_off()
