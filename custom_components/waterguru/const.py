"""Constants for the WaterGuru integration."""

DOMAIN = "waterguru"
MANUFACTURER = "WaterGuru"

CONF_SCAN_INTERVAL_HOURS = "scan_interval_hours"
CONF_TEMPERATURE_UNIT = "temperature_unit"

# WaterGuru measures roughly once a day; polling more often just hammers
# their Lambda. Six hours matches what the community settled on.
DEFAULT_SCAN_INTERVAL_HOURS = 6
MIN_SCAN_INTERVAL_HOURS = 1
MAX_SCAN_INTERVAL_HOURS = 24

TEMP_AUTO = "auto"
TEMP_F = "fahrenheit"
TEMP_C = "celsius"

SERVICE_REFRESH = "refresh"
