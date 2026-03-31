"""Coordinator for Aidot."""

import asyncio
from datetime import timedelta
import logging
import socket

from aidot.client import AidotClient
from aidot.const import (
    CONF_ACCESS_TOKEN,
    CONF_AES_KEY,
    CONF_DEVICE_LIST,
    CONF_ID,
    CONF_LOGIN_INFO,
    CONF_TYPE,
)
from aidot.device_client import DeviceClient, DeviceStatusData
from aidot.discover import Discover
from aidot.exceptions import AidotAuthFailed, AidotNotLogin, AidotUserOrPassIncorrect

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.network import async_get_source_ip

from .const import DOMAIN

# Type alias for config entry
AidotConfigEntry = ConfigEntry["AidotDeviceManagerCoordinator"]

_LOGGER = logging.getLogger(__name__)

UPDATE_DEVICE_LIST_INTERVAL = timedelta(hours=6)


async def _get_discovery_source_ip(hass: HomeAssistant) -> str | None:
    """Get the source IP address for UDP broadcast discovery.
    
    Uses HomeAssistant's network configuration to determine which
    interface should be used for local network discovery.
    """
    try:
        # Get the source IP that would be used to reach a local address
        # Using 192.168.1.1 as a representative local address
        source_ip = await async_get_source_ip(hass, target_ip="192.168.1.1")
        _LOGGER.debug("Discovery will use source IP: %s", source_ip)
        return source_ip
    except Exception as e:
        _LOGGER.warning(
            "Could not determine source IP for discovery, will use default (0.0.0.0): %s", 
            e
        )
        return None


async def _patch_discover_with_source_ip(
    discover: Discover, source_ip: str | None
) -> None:
    """Patch the Discover object to use the correct network interface.
    
    Replaces the default try_create_broadcast method to bind to the
    specific source IP instead of 0.0.0.0.
    """
    if source_ip is None:
        return
    
    original_try_create_broadcast = discover.try_create_broadcast
    
    async def patched_try_create_broadcast():
        """Create broadcast endpoint bound to specific interface."""
        if discover._broadcast_protocol is None:
            from aidot.discover import BroadcastProtocol
            discover._broadcast_protocol = BroadcastProtocol(
                discover._discover_callback, discover._login_info[CONF_ID]
            )
            try:
                (transport, protocol) = await asyncio.get_event_loop().create_datagram_endpoint(
                    lambda: discover._broadcast_protocol,
                    local_addr=(source_ip, 0),  # Bind to specific IP instead of 0.0.0.0
                )
                _LOGGER.info(
                    "Discovery bound to %s (will send broadcasts from this address)",
                    source_ip
                )
            except OSError as e:
                _LOGGER.error(
                    "Failed to bind discovery to %s: %s. Falling back to default.",
                    source_ip,
                    e
                )
                # Fall back to original implementation
                await original_try_create_broadcast()
    
    discover.try_create_broadcast = patched_try_create_broadcast


class AidotDeviceUpdateCoordinator(DataUpdateCoordinator[DeviceStatusData]):
    """Class to manage Aidot data."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: AidotConfigEntry,
        device_client: DeviceClient,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=None,
        )
        self.device_client = device_client

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        self.device_client.set_status_fresh_cb(self._handle_status_update)

    def _handle_status_update(self, status: DeviceStatusData):
        """status callback"""
        self.async_set_updated_data(status)

    async def _async_update_data(self) -> DeviceStatusData:
        """Return current status."""
        return self.device_client.status


class AidotDeviceManagerCoordinator(DataUpdateCoordinator[None]):
    """Class to manage fetching Aidot data."""

    config_entry: AidotConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: AidotConfigEntry,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_DEVICE_LIST_INTERVAL,
        )
        self.client = AidotClient(
            session=async_get_clientsession(hass),
            token=config_entry.data[CONF_LOGIN_INFO],
        )
        self.client.set_token_fresh_cb(self.token_fresh_cb)
        self.device_coordinators: dict[str, AidotDeviceUpdateCoordinator] = {}
        self.previous_lists: set[str] = set()

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        try:
            await self.async_auto_login()
        except AidotUserOrPassIncorrect as error:
            raise ConfigEntryError from error
        
        # Get the correct source IP for discovery based on HA network config
        source_ip = await _get_discovery_source_ip(self.hass)
        
        # Start UDP broadcast discovery to find devices on the local network
        _LOGGER.info("Starting device discovery on local network...")
        self.client.start_discover()
        
        # Patch discovery to use the correct network interface
        if self.client._discover:
            await _patch_discover_with_source_ip(self.client._discover, source_ip)
            _LOGGER.info(
                "Device discovery started. Discover object: %s, Source IP: %s",
                self.client._discover,
                source_ip or "default (0.0.0.0)",
            )
        else:
            _LOGGER.error("Failed to start discovery - discover object is None")
        
        # Give discovery a moment to start and send first broadcast
        await asyncio.sleep(2)
        _LOGGER.info(
            "After 2s delay: Discovered devices: %s",
            self.client._discover.discovered_device if self.client._discover else "None",
        )

    async def _async_update_data(self) -> None:
        """Update data async."""
        try:
            data = await self.client.async_get_all_device()
        except AidotAuthFailed as error:
            self.token_fresh_cb()
            raise ConfigEntryError from error
        filter_device_list = [
            device
            for device in data.get(CONF_DEVICE_LIST)
            if (
                device[CONF_TYPE] == Platform.LIGHT
                and CONF_AES_KEY in device
                and device[CONF_AES_KEY][0] is not None
            )
        ]

        delete_lists = self.previous_lists - (
            current_lists := {device[CONF_ID] for device in filter_device_list}
        )

        for dev_id in delete_lists:
            if dev_id in self.device_coordinators:
                del self.device_coordinators[dev_id]
        if delete_lists:
            self._purge_deleted_lists()
        self.previous_lists = current_lists

        for device in filter_device_list:
            dev_id = device.get(CONF_ID)
            if dev_id not in self.device_coordinators:
                _LOGGER.debug(
                    "Creating device client for %s. Discovered IPs: %s",
                    dev_id,
                    self.client._discover.discovered_device if self.client._discover else "No discover",
                )
                device_client = self.client.get_device_client(device)
                _LOGGER.debug(
                    "Device client created for %s with IP: %s, connected: %s",
                    dev_id,
                    device_client._ip_address,
                    device_client.connect_and_login,
                )
                device_coordinator = AidotDeviceUpdateCoordinator(
                    self.hass, self.config_entry, device_client
                )
                await device_coordinator.async_config_entry_first_refresh()
                self.device_coordinators[dev_id] = device_coordinator

    def cleanup(self) -> None:
        """Perform cleanup actions."""
        self.client.cleanup()

    def token_fresh_cb(self) -> None:
        """Update token."""
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={CONF_LOGIN_INFO: self.client.login_info.copy()}
        )

    async def async_auto_login(self) -> None:
        """Async auto login."""
        if self.client.login_info.get(CONF_ACCESS_TOKEN) is None:
            try:
                await self.client.async_post_login()
            except AidotUserOrPassIncorrect as error:
                raise AidotUserOrPassIncorrect from error

    def _purge_deleted_lists(self) -> None:
        """Purge device entries of deleted lists."""

        device_reg = dr.async_get(self.hass)
        identifiers = {
            (
                DOMAIN,
                f"{device_coordinator.device_client.info.dev_id}",
            )
            for device_coordinator in self.device_coordinators.values()
        }
        for device in dr.async_entries_for_config_entry(
            device_reg, self.config_entry.entry_id
        ):
            if not set(device.identifiers) & identifiers:
                _LOGGER.debug("Removing obsolete device entry %s", device.name)
                device_reg.async_update_device(
                    device.id, remove_config_entry_id=self.config_entry.entry_id
                )
