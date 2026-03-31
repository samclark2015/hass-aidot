"""Coordinator for Aidot."""

import asyncio
import logging
from datetime import timedelta

from homeassistant.components.network import async_get_source_ip
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

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
from aidot.exceptions import AidotAuthFailed, AidotUserOrPassIncorrect

from .const import (
    DOMAIN,
    DISCOVERY_INITIAL_DELAY,
    DISCOVERY_STARTUP_BURST_COUNT,
    DISCOVERY_STARTUP_BURST_INTERVAL,
    RECONNECT_INTERVAL,
    CONNECTION_TIMEOUT,
    STATUS_WAIT_TIMEOUT,
    UPDATE_DEVICE_LIST_INTERVAL_HOURS,
)
from .device_wrapper import DiscoverWrapper, DeviceClientWrapper

type AidotConfigEntry = ConfigEntry[AidotDeviceManagerCoordinator]
_LOGGER = logging.getLogger(__name__)

UPDATE_DEVICE_LIST_INTERVAL = timedelta(hours=UPDATE_DEVICE_LIST_INTERVAL_HOURS)


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

            try:
                (
                    transport,
                    protocol,
                ) = await asyncio.get_event_loop().create_datagram_endpoint(
                    lambda: BroadcastProtocol(
                        discover._discover_callback, discover._login_info[CONF_ID]
                    ),
                    local_addr=(source_ip, 0),  # Bind to specific IP instead of 0.0.0.0
                )
                # Store the protocol instance that was actually created and connected
                discover._broadcast_protocol = protocol
                # Store transport for cleanup
                discover._transport = transport
                _LOGGER.info(
                    "Discovery bound to %s (will send broadcasts from this address)",
                    source_ip,
                )
            except OSError as e:
                _LOGGER.error(
                    "Failed to bind discovery to %s: %s. Falling back to default.",
                    source_ip,
                    e,
                )
                # Fall back to original implementation
                await original_try_create_broadcast()

    discover.try_create_broadcast = patched_try_create_broadcast


class AidotDeviceUpdateCoordinator(DataUpdateCoordinator[DeviceStatusData]):
    """Class to manage Aidot device data."""

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
        self._initial_status_received = False

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        self.device_client.set_status_fresh_cb(self._handle_status_update)

    def _handle_status_update(self, status: DeviceStatusData) -> None:
        """Handle status callback from device."""
        self._initial_status_received = True
        self.async_set_updated_data(status)

    async def _async_update_data(self) -> DeviceStatusData:
        """Return current status."""
        return self.device_client.status

    @property
    def is_connected(self) -> bool:
        """Check if device is connected and has received status."""
        return (
            self.device_client.connect_and_login
            and self.device_client.status.online
        )

    async def async_connect_and_wait_for_status(self) -> bool:
        """Attempt connection and wait for initial status.

        Returns True if connected and status received, False otherwise.
        """
        wrapper = DeviceClientWrapper(self.device_client)

        if not wrapper.ip_address:
            _LOGGER.debug("No IP address for device %s", self.device_client.device_id)
            return False

        # Check if already connected and has valid status
        if self.device_client.connect_and_login and self.device_client.status.online:
            # Already connected with valid status - mark as received and return success
            if not self._initial_status_received:
                _LOGGER.debug(
                    "Device %s already connected with valid status, marking as received",
                    self.device_client.device_id,
                )
                self._initial_status_received = True
            return True

        # Attempt connection if not already connected
        if not self.device_client.connect_and_login:
            try:
                await asyncio.wait_for(
                    self.device_client.async_login(),
                    timeout=CONNECTION_TIMEOUT,
                )
            except asyncio.TimeoutError:
                _LOGGER.debug(
                    "Connection timeout for device %s at %s",
                    self.device_client.device_id,
                    wrapper.ip_address,
                )
                return False
            except Exception as e:
                _LOGGER.debug(
                    "Connection failed for device %s: %s",
                    self.device_client.device_id,
                    e,
                )
                return False

        # Wait for initial status
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < STATUS_WAIT_TIMEOUT:
            if self._initial_status_received and self.device_client.status.online:
                return True
            await asyncio.sleep(0.25)

        _LOGGER.debug(
            "Status timeout for device %s (connected=%s, online=%s, initial_received=%s)",
            self.device_client.device_id,
            self.device_client.connect_and_login,
            self.device_client.status.online,
            self._initial_status_received,
        )
        return False


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
        self._discovery_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        try:
            await self.async_auto_login()
        except AidotUserOrPassIncorrect as error:
            raise ConfigEntryError from error

        source_ip = await async_get_source_ip(self.hass)
        _LOGGER.info(
            "Starting device discovery on local network using source IP: %s",
            source_ip or "default (0.0.0.0)",
        )

        # Create discover with our callback
        if self.client._discover is None:
            self.client._discover = Discover(
                self.client.login_info,
                self._create_discover_callback(),
            )

            if source_ip:
                await _patch_discover_with_source_ip(self.client._discover, source_ip)

            # Start the ongoing broadcast task
            self._discovery_task = asyncio.create_task(
                self.client._discover.repeat_broadcast()
            )
            self._discovery_task.add_done_callback(self._handle_discovery_task_done)
            _LOGGER.info("Device discovery broadcast task started")
        else:
            _LOGGER.warning("Discovery already started, skipping initialization")

        # Aggressive startup discovery - burst of broadcasts
        _LOGGER.info(
            "Sending startup discovery burst (%d broadcasts)",
            DISCOVERY_STARTUP_BURST_COUNT,
        )
        for i in range(DISCOVERY_STARTUP_BURST_COUNT):
            if self.client._discover:
                await self.client._discover.try_create_broadcast()
                await self.client._discover.send_broadcast()
                _LOGGER.debug(
                    "Startup discovery broadcast %d/%d sent",
                    i + 1,
                    DISCOVERY_STARTUP_BURST_COUNT,
                )
            if i < DISCOVERY_STARTUP_BURST_COUNT - 1:
                await asyncio.sleep(DISCOVERY_STARTUP_BURST_INTERVAL)

        # Brief wait after burst for responses
        await asyncio.sleep(DISCOVERY_INITIAL_DELAY)

        if self.client._discover:
            wrapper = DiscoverWrapper(self.client._discover)
            _LOGGER.info(
                "After startup discovery: found %d device(s): %s",
                len(wrapper.discovered_devices),
                list(wrapper.discovered_devices.keys()),
            )
        else:
            _LOGGER.error("Discovery object is None after setup")

        # Start reconnect loop
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        self._reconnect_task.add_done_callback(self._handle_reconnect_task_done)

    def _create_discover_callback(self):
        """Create the discovery callback with access to self."""

        def _discover_callback(dev_id: str, event: dict[str, str]) -> None:
            device_ip = event["ipAddress"]
            _LOGGER.debug("Discovery: device %s at IP %s", dev_id, device_ip)

            # Update IP on existing device client
            device_client = self.client._device_clients.get(dev_id)
            if device_client is not None:
                device_client.update_ip_address(device_ip)

            # If we have a coordinator for this device, attempt connection
            if dev_id in self.device_coordinators:
                coordinator = self.device_coordinators[dev_id]
                if not coordinator.is_connected:
                    # Schedule async connection attempt
                    self.hass.async_create_task(
                        self._attempt_device_connection(dev_id)
                    )

        return _discover_callback

    async def _attempt_device_connection(self, dev_id: str) -> None:
        """Attempt to connect to a device and sync its status."""
        if dev_id not in self.device_coordinators:
            return

        coordinator = self.device_coordinators[dev_id]

        _LOGGER.debug("Attempting connection to device %s", dev_id)

        if await coordinator.async_connect_and_wait_for_status():
            _LOGGER.info(
                "Device %s connected - state: on=%s, brightness=%s, available=%s",
                dev_id,
                coordinator.data.on if coordinator.data else "N/A",
                coordinator.data.dimming if coordinator.data else "N/A",
                coordinator.data.online if coordinator.data else False,
            )
            # Trigger entity update
            coordinator.async_set_updated_data(coordinator.device_client.status)
        else:
            _LOGGER.debug("Device %s connection attempt failed", dev_id)

    async def _reconnect_loop(self) -> None:
        """Periodically attempt to reconnect disconnected devices."""
        while True:
            await asyncio.sleep(RECONNECT_INTERVAL)

            # Find disconnected devices
            disconnected = [
                dev_id
                for dev_id, coord in self.device_coordinators.items()
                if not coord.is_connected
            ]

            if not disconnected:
                continue

            _LOGGER.debug(
                "Reconnect loop: %d disconnected device(s): %s",
                len(disconnected),
                disconnected,
            )

            # Send discovery broadcast to find device IPs
            if self.client._discover:
                await self.client._discover.try_create_broadcast()
                await self.client._discover.send_broadcast()

    def _handle_reconnect_task_done(self, task: asyncio.Task) -> None:
        """Handle reconnect task completion or failure."""
        try:
            task.result()
        except asyncio.CancelledError:
            _LOGGER.debug("Reconnect task was cancelled")
        except Exception:
            _LOGGER.exception("Reconnect task failed with unexpected error")

    async def _async_update_data(self) -> None:
        """Update data async - fetch device list and create coordinators."""
        try:
            data = await self.client.async_get_all_device()
        except AidotAuthFailed as error:
            self.token_fresh_cb()
            raise ConfigEntryError from error

        filter_device_list = [
            device
            for device in data.get(CONF_DEVICE_LIST, [])
            if (
                device[CONF_TYPE] == Platform.LIGHT
                and CONF_AES_KEY in device
                and device[CONF_AES_KEY][0] is not None
            )
        ]

        current_device_ids = {device[CONF_ID] for device in filter_device_list}

        # Handle removed devices
        removed_ids = set(self.device_coordinators.keys()) - current_device_ids
        for dev_id in removed_ids:
            _LOGGER.info("Device %s removed from account", dev_id)
            del self.device_coordinators[dev_id]

        if removed_ids:
            self._purge_deleted_lists()

        # Create coordinators for new devices (they start as unavailable)
        for device in filter_device_list:
            dev_id = device[CONF_ID]

            if dev_id in self.device_coordinators:
                continue  # Already have coordinator

            _LOGGER.debug("Creating coordinator for device %s", dev_id)

            # Create device client
            device_client = self.client.get_device_client(device)

            # Create coordinator (starts as unavailable until connected)
            device_coordinator = AidotDeviceUpdateCoordinator(
                self.hass, self.config_entry, device_client
            )
            await device_coordinator._async_setup()

            # Initialize with default status (unavailable)
            device_coordinator.async_set_updated_data(device_client.status)

            self.device_coordinators[dev_id] = device_coordinator

            _LOGGER.info(
                "Device %s coordinator created (available=%s)",
                dev_id,
                device_coordinator.is_connected,
            )

            # Attempt immediate connection if IP is known
            wrapper = DeviceClientWrapper(device_client)
            if wrapper.ip_address:
                self.hass.async_create_task(self._attempt_device_connection(dev_id))

    def cleanup(self) -> None:
        """Perform cleanup actions."""
        if self._discovery_task and not self._discovery_task.done():
            self._discovery_task.cancel()

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()

        # Close the discovery transport if it was created
        if self.client._discover:
            wrapper = DiscoverWrapper(self.client._discover)
            if wrapper.has_transport:
                transport = wrapper.get_transport()
                if transport and not transport.is_closing():
                    transport.close()
                    _LOGGER.debug("Closed discovery UDP transport")

        self.client.cleanup()

    def _handle_discovery_task_done(self, task: asyncio.Task) -> None:
        """Handle discovery task completion or failure."""
        try:
            task.result()
        except asyncio.CancelledError:
            _LOGGER.debug("Discovery task was cancelled")
        except Exception:
            _LOGGER.exception("Discovery task failed with unexpected error")

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
