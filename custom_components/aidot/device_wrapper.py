"""Wrapper for python-aidot library to isolate private API access.

This module provides abstraction over the python-aidot library's private APIs.
If the library changes its internal structure, only this file needs updating.

IMPORTANT: This wrapper exists because we rely on private APIs from python-aidot.
When upgrading python-aidot, check this file first for compatibility.

Current version: python-aidot==0.3.45
"""

from typing import Any

from aidot.device_client import DeviceClient
from aidot.discover import Discover


class DeviceClientWrapper:
    """Wrapper for DeviceClient that isolates private API access.
    
    This class provides a public interface to DeviceClient properties that
    are currently only available as private attributes.
    """

    def __init__(self, device_client: DeviceClient) -> None:
        """Initialize the wrapper.
        
        Args:
            device_client: The DeviceClient instance to wrap
        """
        self._client = device_client

    @property
    def ip_address(self) -> str | None:
        """Get the device IP address.
        
        Returns:
            The IP address string, or None if not available.
            
        Note:
            Accesses private attribute: device_client._ip_address
        """
        return getattr(self._client, "_ip_address", None)

    @property
    def is_connected(self) -> bool:
        """Check if device is connected and logged in.
        
        Returns:
            True if connected and authenticated, False otherwise.
        """
        return self._client.connect_and_login

    @property
    def is_connecting(self) -> bool:
        """Check if device is currently connecting.
        
        Returns:
            True if connection is in progress, False otherwise.
        """
        return self._client.connecting

    @property
    def unwrapped(self) -> DeviceClient:
        """Get the underlying DeviceClient instance.
        
        Returns:
            The wrapped DeviceClient for direct access when needed.
        """
        return self._client


class DiscoverWrapper:
    """Wrapper for Discover that isolates private API access.
    
    This class provides safe access to discovery internals.
    """

    def __init__(self, discover: Discover) -> None:
        """Initialize the wrapper.
        
        Args:
            discover: The Discover instance to wrap
        """
        self._discover = discover

    @property
    def discovered_devices(self) -> dict[str, Any]:
        """Get the dictionary of discovered devices.
        
        Returns:
            Dictionary mapping device IDs to discovery info.
            
        Note:
            Accesses private attribute: discover.discovered_device
        """
        return getattr(self._discover, "discovered_device", {})

    @property
    def broadcast_protocol(self) -> Any | None:
        """Get the broadcast protocol instance.
        
        Returns:
            The BroadcastProtocol instance, or None if not initialized.
            
        Note:
            Accesses private attribute: discover._broadcast_protocol
        """
        return getattr(self._discover, "_broadcast_protocol", None)

    @property
    def has_transport(self) -> bool:
        """Check if a transport has been created.
        
        Returns:
            True if transport exists, False otherwise.
            
        Note:
            Checks for private attribute: discover._transport
        """
        return hasattr(self._discover, "_transport")

    def get_transport(self) -> Any | None:
        """Get the UDP transport if it exists.
        
        Returns:
            The transport object, or None if not created.
            
        Note:
            Accesses private attribute: discover._transport
        """
        return getattr(self._discover, "_transport", None)

    @property
    def unwrapped(self) -> Discover:
        """Get the underlying Discover instance.
        
        Returns:
            The wrapped Discover for direct access when needed.
        """
        return self._discover
