"""Constants for the AiDot integration."""

from homeassistant.const import Platform

DOMAIN = "aidot"

PLATFORMS: list[Platform] = [Platform.LIGHT]

# Config flow constants
CONF_COUNTRY = "country"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SELECTED_HOUSE = "selected_house"

# Data keys
DATA_LOGIN_RESPONSE = "login_response"
DATA_SELECTED_HOUSE = "selected_house"
DATA_DEVICE_LIST = "device_list"
DATA_PRODUCT_LIST = "product_list"

# Service constants
SERVICE_REFRESH_DEVICES = "refresh_devices"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
