"""Support for Aidot diagnostic sensors."""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AidotConfigEntry, AidotDeviceUpdateCoordinator


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
                        AidotIPAddressSensor(hass, device_coordinator),
                        AidotConnectionStatusSensor(hass, device_coordinator),
                    ]
                )
            async_add_entities(entities)
            lists_added |= new_lists

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
        hass: HomeAssistant,
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
        self, hass: HomeAssistant, coordinator: AidotDeviceUpdateCoordinator
    ) -> None:
        """Initialize the IP address sensor."""
        super().__init__(hass, coordinator, "ip_address")

    @property
    def native_value(self) -> str | None:
        """Return the IP address."""
        if hasattr(self.coordinator.device_client, "_ip_address"):
            return self.coordinator.device_client._ip_address
        return None


class AidotConnectionStatusSensor(AidotDiagnosticSensor):
    """Sensor that displays the device's connection status."""

    _attr_translation_key = "connection_status"
    _attr_icon = "mdi:connection"

    def __init__(
        self, hass: HomeAssistant, coordinator: AidotDeviceUpdateCoordinator
    ) -> None:
        """Initialize the connection status sensor."""
        super().__init__(hass, coordinator, "connection_status")

    @property
    def native_value(self) -> str:
        """Return the connection status."""
        if self.coordinator.device_client.connect_and_login:
            return "Connected"
        elif self.coordinator.device_client.connecting:
            return "Connecting"
        else:
            return "Disconnected"

    @property
    def icon(self) -> str:
        """Return the icon based on connection status."""
        if self.coordinator.device_client.connect_and_login:
            return "mdi:lan-connect"
        elif self.coordinator.device_client.connecting:
            return "mdi:lan-pending"
        else:
            return "mdi:lan-disconnect"
