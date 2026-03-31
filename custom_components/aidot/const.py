"""Constants for the aidot integration."""

DOMAIN = "aidot"

# Discovery settings
DISCOVERY_INITIAL_DELAY = 3.0  # seconds to wait for initial discovery responses

# Command retry settings
COMMAND_MAX_RETRIES = 2  # number of retries after initial attempt
COMMAND_RETRY_BASE_DELAY = 1.0  # seconds to wait before first retry
COMMAND_RETRY_BACKOFF_FACTOR = 1.5  # exponential backoff multiplier

# Update intervals
UPDATE_DEVICE_LIST_INTERVAL_HOURS = 6  # hours between device list refreshes
