"""Constants for the EZVIZ HG2 integration."""

from typing import Final

DOMAIN: Final = "ezviz_hg2"

CONF_SESSION_ID: Final = "session_id"
CONF_RFSESSION_ID: Final = "rf_session_id"

DEFAULT_API_URL: Final = "apiieu.ezvizlife.com"
DEFAULT_SCAN_INTERVAL: Final = 15
MIN_SCAN_INTERVAL: Final = 5
MAX_SCAN_INTERVAL: Final = 300
FULL_REFRESH_INTERVAL: Final = 60
DEFAULT_TIMEOUT: Final = 30
DEFAULT_BLE_TIMEOUT: Final = 20

CONF_OPEN_DURATION: Final = "open_duration"
CONF_CLOSE_DURATION: Final = "close_duration"
CONF_BLE_FALLBACK_ENABLED: Final = "ble_fallback_enabled"
CONF_BLE_ADDRESS: Final = "ble_address"
CONF_BLE_VERIFY_CODE: Final = "ble_verify_code"
MIN_TRAVEL_DURATION: Final = 3
MAX_TRAVEL_DURATION: Final = 120

# One "gate" subentry per HG2 holds that device's own travel duration and
# BLE fallback settings, so multiple gates on the same EZVIZ account do not
# share a single set of values (see coordinator.py / config_flow.py).
SUBENTRY_TYPE_GATE: Final = "gate"

SERVICE_SEND_IOT_ACTION: Final = "send_iot_action"
SERVICE_GET_IOT_FEATURE: Final = "get_iot_feature"
SERVICE_GET_CLOUD_METADATA: Final = "get_cloud_metadata"
SERVICE_GET_MANUAL_SCENES: Final = "get_manual_scenes"
SERVICE_SEND_BLE_COMMAND: Final = "send_ble_command"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_SERIAL: Final = "serial"
ATTR_RESOURCE_ID: Final = "resource_id"
ATTR_LOCAL_INDEX: Final = "local_index"
ATTR_DOMAIN_ID: Final = "domain_id"
ATTR_ACTION_ID: Final = "action_id"
ATTR_PAYLOAD: Final = "payload"
ATTR_FILTER: Final = "filter"
ATTR_COMMAND: Final = "command"
