"""Support for Aidot lights."""

import ctypes
import logging
from typing import Any

from aidot.client import AidotClient
from aidot.device_client import DeviceClient, DeviceStatusData
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGBW_COLOR,
    LightEntity,
)
from homeassistant.components.light.const import ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

_LOGGER = logging.getLogger(__name__)

DOMAIN = "aidot"

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Light."""
    device_list = hass.data[DOMAIN].get("device_list", [])
    user_info = hass.data[DOMAIN].get("login_response", {})
    products = hass.data[DOMAIN].get("products", {})
    for product in products:
        for device in device_list:
            if device["productId"] == product["id"]:
                device["product"] = product

    async_add_entities(
        AidotLight(hass, device_info, user_info)
        for device_info in device_list
        if device_info["type"] == "light"
        and "aesKey" in device_info
        and device_info["aesKey"][0] is not None
    )


class AidotLight(LightEntity):
    """Representation of a Aidot Wi-Fi Light."""

    def __init__(self, hass: HomeAssistant, device, user_info) -> None:
        """Initialize the light."""
        super().__init__()
        aidot_data = hass.data[DOMAIN]
        client: AidotClient = aidot_data.get("client")

        self.device = device
        self.user_info = user_info
        self._attr_unique_id = device["id"]
        self._attr_name = device["name"]
        modelId = device["modelId"]
        manufacturer = modelId.split(".")[0]
        model = modelId[len(manufacturer) + 1 :]
        mac = format_mac(device["mac"]) if device["mac"] is not None else ""
        identifiers: set[tuple[str, str]] = (
            set({(DOMAIN, self._attr_unique_id)}) if self._attr_unique_id else set()
        )
        self._attr_device_info = DeviceInfo(
            identifiers=identifiers,
            connections={(CONNECTION_NETWORK_MAC, mac)},
            manufacturer=manufacturer,
            model=model,
            name=device["name"],
            hw_version=device["hardwareVersion"],
        )
        self._cct_min = 0
        self._cct_max = 0
        self.device_status: DeviceStatusData | None = None

        supported_color_modes = set()
        if "product" in device and "serviceModules" in device["product"]:
            for service in device["product"]["serviceModules"]:
                if service["identity"] == "control.light.rgbw":
                    supported_color_modes.add(ColorMode.RGBW)
                elif service["identity"] == "control.light.cct":
                    self._cct_min = int(service["properties"][0]["minValue"])
                    self._cct_max = int(service["properties"][0]["maxValue"])
                    supported_color_modes.add(ColorMode.COLOR_TEMP)
                # elif "control.light.effect.mode" == service["identity"]:
                # self._attr_supported_features = LightEntityFeature.EFFECT | LightEntityFeature.FLASH
                # allowedValues = service["properties"][0]["allowedValues"]
                # print(f"allowedValues: {allowedValues}")
                # self._attr_effect_list = [item["name"] for item in allowedValues]

        if ColorMode.RGBW in supported_color_modes:
            self._attr_color_mode = ColorMode.RGBW
            self._attr_supported_color_modes = {ColorMode.RGBW, ColorMode.COLOR_TEMP}
        elif ColorMode.COLOR_TEMP in supported_color_modes:
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
        else:
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}


        self.lanCtrl = client.get_device_client(device)

        # async def handle_event(event):
        #     if not self.lanCtrl.connecting and not self.lanCtrl.connect_and_login:
        #         await self.lanCtrl.connect(event.data["ipAddress"])
        #         # self.pingtask = hass.loop.create_task(self.lanCtrl.ping_task())
        #         # self.recvtask = hass.loop.create_task(self.lanCtrl.recvData())

        # hass.bus.async_listen(device["id"], handle_event)

        # hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self.release)

    async def async_added_to_hass(self):
        """Called when the entity is added to Home Assistant."""
        # await self.lanCtrl.connect(self.ip_address)
        # await self.lanCtrl.async_login()
        await self.lanCtrl.async_wait_discovered()
        await self.lanCtrl.async_login()

    async def async_will_remove_from_hass(self, event: Event):
        """Release task."""
        # if hasattr(self, "pingtask") and self.pingtask is not None:
        #     self.pingtask.cancel()
        # if hasattr(self, "recvtask") and self.recvtask is not None:
        #     self.recvtask.cancel()

    async def updateState(self):
        """Update the state of the entity."""
        if self.hass is not None and self.entity_id is not None:
            await self.async_update_ha_state(True)

    @property
    def available(self):
        """Return True if entity is available."""
        return self.lanCtrl.connect_and_login and self.device_status is not None and self.device_status.on

    @property
    def is_on(self) -> bool:
        """Return True if the light is on."""
        return self.device_status is not None and self.device_status.on

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        return self.device_status is not None and self.device_status.dimming

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
        return self.device_status and self.device_status.cct

    @property
    def rgbw_color(self) -> tuple[int, int, int, int] | None:
        """Return the rgbw color value [int, int, int, int]."""
        return self.device_status and self.device_status.rgbw

    @property
    def color_mode(self) -> ColorMode | str | None:
        """Return the color mode of the light."""
        # if self.lanCtrl.info. == "rgbw":
        #     colorMode = ColorMode.RGBW
        # elif self.lanCtrl._colorMode == "cct":
        #     colorMode = ColorMode.COLOR_TEMP
        # else:
        #     colorMode = ColorMode.BRIGHTNESS
        colorMode = ColorMode.RGBW
        return colorMode

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        brightness = kwargs.get(ATTR_BRIGHTNESS, 255)

        if self.lanCtrl.connect_and_login is False:
            _LOGGER.error(
                "The device is not logged in or may not be on the local area network"
            )
            raise HomeAssistantError(
                "The device is not logged in or may not be on the local area network"
            )

        if ATTR_BRIGHTNESS in kwargs and brightness is not None:
            # action.update(self.lanCtrl.getDimingAction(brightness))
            await self.lanCtrl.async_set_brightness(brightness)
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            cct = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
            # action.update(self.lanCtrl.getCCTAction(cct))
            if cct is not None:
                if cct < self._cct_min or cct > self._cct_max:
                    _LOGGER.error(
                        "Color temperature %s is out of range (%s-%s)",
                        cct, self._cct_min, self._cct_max
                    )
                    raise HomeAssistantError(
                        f"Color temperature {cct} is out of range ({self._cct_min}-{self._cct_max})"
                    )
                await self.lanCtrl.async_set_cct(cct)
        if ATTR_RGBW_COLOR in kwargs:
            rgbw = kwargs.get(ATTR_RGBW_COLOR)
            if rgbw is not None:
                if len(rgbw) != 4:
                    _LOGGER.error("RGBW color must be a tuple of 4 integers")
                    raise HomeAssistantError("RGBW color must be a tuple of 4 integers")
                await self.lanCtrl.async_set_rgbw(rgbw)
        if not kwargs:
            await self.lanCtrl.async_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        if self.lanCtrl.connect_and_login is False:
            _LOGGER.error(
                "The device is not logged in or may not be on the local area network"
            )
            raise HomeAssistantError(
                "The device is not logged in or may not be on the local area network"
            )
        await self.lanCtrl.async_turn_off()

    async def async_update(self) -> None:
        """Update the state of the light."""
        if self.lanCtrl.connect_and_login is False:
            _LOGGER.error(
                "The device is not logged in or may not be on the local area network"
            )
            raise HomeAssistantError(
                "The device is not logged in or may not be on the local area network"
            )
        status = await self.lanCtrl.read_status()
        self.device_status = status
