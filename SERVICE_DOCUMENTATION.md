# AiDot Integration Services

## refresh_devices

This service allows you to refresh the list of discovered devices after login.

### Usage

To use the service, call `aidot.refresh_devices` with the following parameter:

- `config_entry_id`: The config entry ID for the AiDot integration instance you want to refresh devices for.

### Example

```yaml
service: aidot.refresh_devices
data:
  config_entry_id: "your_aidot_config_entry_id"
```

### What it does

1. Stops the current device discovery process
2. Restarts device discovery to find new devices
3. Reloads the integration to pick up any newly discovered devices
4. Logs the process for debugging purposes

### When to use

- After adding new AiDot devices to your network
- When devices aren't appearing in Home Assistant
- If you suspect devices have changed IP addresses
- When troubleshooting device connectivity

### Finding your config entry ID

You can find your config entry ID by:

1. Going to Settings > Devices & Services
2. Finding your AiDot integration
3. Using the config entry selector in the service call UI

The service will validate that the config entry exists and is loaded before attempting to refresh devices.
