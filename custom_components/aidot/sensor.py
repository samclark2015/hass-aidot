"""Support for Aidot diagnostic sensors."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AidotConfigEntry, AidotDeviceUpdateCoordinator
from .device_wrapper import DeviceClientWrapper


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AidotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Aidot diagnostic sensors."""
    coordinator = entry.runtime_data
    lists_added: set[str] = set()

    @callback
    def add_entities() -> None:
        """Add sensor entities."""
        nonlocal lists_added
        new_lists = {
            device_coordinator.device_client.device_id
            for device_coordinator in coordinator.device_coordinators.values()
        }

        if new_lists - lists_added:
            entities = []
            for device_id in new_lists:
                device_coordinator = coordinator.device_coordinators[device_id]
                entities.extend(
                    [
                        AidotIPAddressSensor(device_coordinator),
                        AidotConnectionStatusSensor(device_coordinator),
                    ]
                )
            async_add_entities(entities)
            lists_added |= new_lists
        elif lists_added - new_lists:
            # Remove entities for devices that no longer exist
            removed_device_ids = lists_added - new_lists
            entity_registry = er.async_get(hass)
            for device_id in removed_device_ids:
                # Remove both sensor types for this device
                for sensor_type in ["ip_address", "connection_status"]:
                    entity_id = entity_registry.async_get_entity_id(
                        "sensor", DOMAIN, f"{device_id}_{sensor_type}"
                    )
                    if entity_id:
                        entity_registry.async_remove(entity_id)
            lists_added -= removed_device_ids

    coordinator.async_add_listener(add_entities)
    add_entities()


class AidotDiagnosticSensor(
    CoordinatorEntity[AidotDeviceUpdateCoordinator], SensorEntity
):
    """Base class for Aidot diagnostic sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: AidotDeviceUpdateCoordinator,
        sensor_type: str,
    ) -> None:
        """Initialize the diagnostic sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_client.info.dev_id}_{sensor_type}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_client.info.dev_id)},
        )


class AidotIPAddressSensor(AidotDiagnosticSensor):
    """Sensor that displays the device's IP address."""

    _attr_translation_key = "ip_address"
    _attr_icon = "mdi:ip-network"

    def __init__(
        self, coordinator: AidotDeviceUpdateCoordinator
    ) -> None:
        """Initialize the IP address sensor."""
        super().__init__(coordinator, "ip_address")

    @property
    def native_value(self) -> str | None:
        """Return the IP address."""
        wrapper = DeviceClientWrapper(self.coordinator.device_client)
        return wrapper.ip_address


class AidotConnectionStatusSensor(AidotDiagnosticSensor):
    """Sensor that displays the device's connection status."""

    _attr_translation_key = "connection_status"
    _attr_icon = "mdi:connection"

    def __init__(
        self, coordinator: AidotDeviceUpdateCoordinator
    ) -> None:
        """Initialize the connection status sensor."""
        super().__init__(coordinator, "connection_status")

    @property
    def native_value(self) -> str:
        """Return the connection status."""
        wrapper = DeviceClientWrapper(self.coordinator.device_client)
        if wrapper.is_connected:
            return "Connected"
        elif wrapper.is_connecting:
            return "Connecting"
        else:
            return "Disconnected"

    @property
    def icon(self) -> str:
        """Return the icon based on connection status."""
        wrapper = DeviceClientWrapper(self.coordinator.device_client)
        if wrapper.is_connected:
            return "mdi:lan-connect"
        elif wrapper.is_connecting:
            return "mdi:lan-pending"
        else:
            return "mdi:lan-disconnect"
