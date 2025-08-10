#!/usr/bin/env python3
"""Test script for AiDot integration service."""

import asyncio
import sys

# Add the custom_components path to sys.path
sys.path.insert(0, "/workspaces/hass-aidot")

from custom_components.aidot import async_setup
from custom_components.aidot.const import DOMAIN, SERVICE_REFRESH_DEVICES


class MockHass:
    """Mock Home Assistant instance for testing."""

    def __init__(self):
        self.services = MockServices()
        self.config_entries = MockConfigEntries()


class MockServices:
    """Mock services registry."""

    def __init__(self):
        self.registered_services = {}

    def async_register(self, domain, service, handler, schema=None):
        """Register a service."""
        if domain not in self.registered_services:
            self.registered_services[domain] = {}
        self.registered_services[domain][service] = {
            "handler": handler,
            "schema": schema,
        }
        print(f"✓ Service {domain}.{service} registered successfully")


class MockConfigEntries:
    """Mock config entries registry."""

    def async_get_entry(self, entry_id):
        """Get a config entry by ID."""
        return None


async def test_service_registration():
    """Test that the service is registered correctly."""
    print("Testing AiDot service registration...")

    hass = MockHass()
    config = {}

    # Test async_setup function
    result = await async_setup(hass, config)

    if result:
        print("✓ async_setup completed successfully")
    else:
        print("✗ async_setup failed")
        return False

    # Check if service was registered
    if DOMAIN in hass.services.registered_services:
        services = hass.services.registered_services[DOMAIN]
        if SERVICE_REFRESH_DEVICES in services:
            print(f"✓ Service {SERVICE_REFRESH_DEVICES} found in registered services")
            service_info = services[SERVICE_REFRESH_DEVICES]
            print(f"  Handler: {service_info['handler']}")
            print(f"  Schema: {service_info['schema']}")
            return True
        else:
            print(f"✗ Service {SERVICE_REFRESH_DEVICES} not found")
            return False
    else:
        print(f"✗ Domain {DOMAIN} not found in services")
        return False


if __name__ == "__main__":
    result = asyncio.run(test_service_registration())
    if result:
        print("\n✓ All tests passed!")
    else:
        print("\n✗ Tests failed!")
        sys.exit(1)
