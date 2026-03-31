# AGENTS.md - Development Guidelines for Home Assistant AiDot Integration

This document provides coding guidelines and essential information for AI coding agents and developers working on the Home Assistant AiDot integration.

## Project Overview

This is a Home Assistant custom component integration for AiDot smart lights using local polling. The integration provides a hub-based configuration flow with support for lights and diagnostic sensors.

**Key Info:**
- Domain: `aidot`
- Integration Type: Hub (local_polling)
- Quality Scale Target: Bronze (moving toward Silver)
- External Dependency: `python-aidot==0.3.45`
- Python Version: 3.10+

## Build, Lint, and Test Commands

### Running Tests
```bash
# No test framework currently configured
# Tests would typically use pytest when implemented:
# pytest tests/
# pytest tests/test_config_flow.py  # Single test file
# pytest tests/test_config_flow.py::test_specific_function  # Single test
```

### Linting and Code Quality
```bash
# No linters currently configured in the project
# Recommended for Home Assistant integrations:
# ruff check custom_components/aidot/
# ruff format custom_components/aidot/
# mypy custom_components/aidot/
```

### Development Setup
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On macOS/Linux

# Install Home Assistant core (for development)
pip install homeassistant

# The integration's dependency is auto-installed by Home Assistant:
# python-aidot==0.3.45
```

### Installation in Home Assistant
```bash
# Copy to Home Assistant config directory
cp -r custom_components/aidot /path/to/homeassistant/config/custom_components/

# Restart Home Assistant
```

## Code Style Guidelines

### Import Order and Organization

**Standard import pattern:**
```python
"""Module docstring."""

from __future__ import annotations  # Always first for type hints

import asyncio  # Standard library imports
import logging
from datetime import timedelta
from typing import Any

import aiohttp  # Third-party imports
import voluptuous as vol

from homeassistant.components.light import (  # Home Assistant imports
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from aidot.client import AidotClient  # External library imports
from aidot.const import CONF_LOGIN_INFO

from .const import DOMAIN  # Relative imports last
from .coordinator import AidotConfigEntry
```

**Import rules:**
1. Always include `from __future__ import annotations` for Python 3.10+ compatibility
2. Group imports: stdlib → third-party → homeassistant → external libs → relative
3. Use parentheses for multi-line imports
4. Import specific items, not entire modules when possible

### Type Hints and Annotations

**Always use type hints:**
```python
async def async_setup_entry(
    hass: HomeAssistant,
    entry: AidotConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Light."""
```

**Type alias pattern:**
```python
type AidotConfigEntry = ConfigEntry[AidotDeviceManagerCoordinator]
```

**Use modern union syntax:**
```python
def get_ip_address(self) -> str | None:  # Preferred
    # NOT: Optional[str]
```

### Naming Conventions

**Classes:** `PascalCase`
```python
class AidotDeviceManagerCoordinator(DataUpdateCoordinator):
```

**Functions/Methods:** `snake_case` with async prefix for async functions
```python
async def async_turn_on(self, **kwargs: Any) -> None:
async def async_setup_entry(hass: HomeAssistant, entry: AidotConfigEntry) -> bool:
```

**Constants:** `UPPER_SNAKE_CASE`
```python
DOMAIN = "aidot"
PARALLEL_UPDATES = 1
DISCOVERY_INITIAL_DELAY = 1.0
UPDATE_DEVICE_LIST_INTERVAL = timedelta(hours=6)
```

**Private attributes:** Prefix with single underscore
```python
self._attr_is_on = True
self._discovery_task: asyncio.Task | None = None
```

### Docstrings

**Use triple-quoted strings for all docstrings:**
```python
"""Module docstring at file start."""

class AidotLight(CoordinatorEntity, LightEntity):
    """Representation of a Aidot Wi-Fi Light."""
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
```

**For complex functions, use detailed docstrings:**
```python
async def _patch_discover_with_source_ip(
    discover: Discover, source_ip: str | None
) -> None:
    """Patch the Discover object to use the correct network interface.

    Replaces the default try_create_broadcast method to bind to the
    specific source IP instead of 0.0.0.0.
    """
```

### Error Handling

**Use specific exception types:**
```python
try:
    login_info = await client.async_post_login()
except AidotUserOrPassIncorrect:
    errors["base"] = "invalid_auth"
except (aiohttp.ClientError, asyncio.TimeoutError) as err:
    _LOGGER.error("Network error during login: %s", err)
    errors["base"] = "cannot_connect"
except Exception:
    _LOGGER.exception("Unexpected error during login")
    errors["base"] = "unknown"
```

**Key principles:**
1. Catch specific exceptions first, generic last
2. Always log exceptions with context
3. Use `_LOGGER.exception()` for unexpected errors (includes traceback)
4. Re-raise as Home Assistant exceptions when appropriate:
   - `ConfigEntryError` for setup issues
   - `HomeAssistantError` for command failures
5. Use `from err` or `from error` for exception chaining

**Optimistic updates pattern:**
```python
# Update UI immediately
self._attr_is_on = True
self.async_write_ha_state()

try:
    await self.coordinator.device_client.send_dev_attr(attrs)
except ConnectionError as err:
    # Revert on failure
    self._attr_is_on = False
    self.coordinator.async_set_updated_data(self.coordinator.device_client.status)
    _LOGGER.error("Failed to turn on %s: %s", self.entity_id, err)
    raise HomeAssistantError(f"Failed to turn on light: {err}") from err
```

### Logging

**Always create module-level logger:**
```python
_LOGGER = logging.getLogger(__name__)
```

**Logging levels:**
- `_LOGGER.debug()` - Detailed diagnostic info
- `_LOGGER.info()` - Important state changes, discoveries
- `_LOGGER.warning()` - Recoverable issues
- `_LOGGER.error()` - Errors requiring attention
- `_LOGGER.exception()` - Unexpected exceptions with traceback

**Good logging examples:**
```python
_LOGGER.info("Starting device discovery on local network using source IP: %s", source_ip)
_LOGGER.debug("Startup discovery broadcast %d/%d sent", i + 1, count)
_LOGGER.warning("Discovery protocol may not be fully initialized")
_LOGGER.error("Failed to turn on %s: %s", self.entity_id, err)
```

## Architecture Patterns

### Coordinator Pattern
All devices use the `DataUpdateCoordinator` pattern with two levels:
1. `AidotDeviceManagerCoordinator` - Manages discovery and device list
2. `AidotDeviceUpdateCoordinator` - Per-device status updates

### Entity Setup Pattern
```python
@callback
def add_entities() -> None:
    """Add light entities."""
    nonlocal lists_added
    new_lists = {device_id for device_id in coordinator.device_coordinators}
    
    if new_lists - lists_added:
        async_add_entities(Entity(coordinator) for device_id in new_lists)
        lists_added |= new_lists
    elif lists_added - new_lists:
        # Handle removed devices
        removed_device_ids = lists_added - new_lists
        entity_registry = er.async_get(hass)
        # Remove entities...
        lists_added -= removed_device_ids

coordinator.async_add_listener(add_entities)
add_entities()
```

### Private API Isolation
The `device_wrapper.py` module isolates access to private APIs from the `python-aidot` library:
```python
# Always wrap private API access in DeviceClientWrapper or DiscoverWrapper
wrapper = DeviceClientWrapper(device_client)
ip = wrapper.ip_address  # Instead of device_client._ip_address
```

**When upgrading `python-aidot`, check `device_wrapper.py` first!**

## Git Commit Style

Based on recent commits:
```
feat: add new feature description
feat: enhance existing feature with improvement details
fix: resolve issue description
```

**Pattern:** `type: concise description in imperative mood`

## Important Notes

1. **PARALLEL_UPDATES = 1** is set on light platform to prevent command conflicts
2. **Constants** are centralized in `const.py` with inline documentation
3. **Entity naming:** Use `_attr_has_entity_name = True` and `_attr_name = None` for device name
4. **Unique IDs:** Use `coordinator.device_client.info.dev_id` for entity unique IDs
5. **Diagnostic entities:** Use `EntityCategory.DIAGNOSTIC` for connection status sensors
6. **Device registry:** Always include MAC address connection: `CONNECTION_NETWORK_MAC`

## Home Assistant Integration Quality Checklist

Current status tracked in `quality_scale.yaml`. When making changes:
- ✅ Use runtime_data for entry data storage
- ✅ Implement config_entry unloading with cleanup
- ✅ Mark entities unavailable when offline
- ✅ Use entity translations (strings.json)
- 🔲 Add action exceptions (in progress)
- 🔲 Add test coverage
- 🔲 Implement reauthentication flow
