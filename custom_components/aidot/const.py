"""Constants for the aidot integration."""

DOMAIN = "aidot"

# Discovery settings
DISCOVERY_INITIAL_DELAY = 1.0  # seconds to wait for initial discovery responses
DISCOVERY_STARTUP_BURST_COUNT = 3  # number of rapid discovery broadcasts at startup
DISCOVERY_STARTUP_BURST_INTERVAL = 1.0  # seconds between startup burst broadcasts

# Command retry settings
COMMAND_MAX_RETRIES = 2  # number of retries after initial attempt
COMMAND_RETRY_BASE_DELAY = 1.0  # seconds to wait before first retry
COMMAND_RETRY_BACKOFF_FACTOR = 1.5  # exponential backoff multiplier

# Connection settings
RECONNECT_INTERVAL = 30.0  # seconds between reconnection attempts
CONNECTION_TIMEOUT = 5.0  # seconds to wait for connection attempt
STATUS_WAIT_TIMEOUT = 3.0  # seconds to wait for initial status after connection

# Update intervals
UPDATE_DEVICE_LIST_INTERVAL_HOURS = 6  # hours between device list refreshes
