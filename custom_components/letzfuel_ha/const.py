"""Constants for the LëtzFuel HA integration."""

from __future__ import annotations

from typing import Final

from .models import FuelType

DOMAIN: Final = "letzfuel_ha"

# --- Providers -------------------------------------------------------------
DEFAULT_PROVIDER: Final = "petrol_lu"

# --- Config entry keys ---------------------------------------------------------
CONF_PROVIDER: Final = "provider"
CONF_TRACKED_FUELS: Final = "tracked_fuels"
CONF_PRIMARY_FUEL: Final = "primary_fuel"
CONF_TANK_SIZE: Final = "tank_size"
CONF_CURRENT_LEVEL: Final = "current_level_pct"

# --- Options keys ------------------------------------------------------------
OPT_UPDATE_INTERVAL_HOURS: Final = "update_interval_hours"
OPT_EVENING_CHECK_TIME: Final = "evening_check_time"
OPT_TREND_WINDOW_DAYS: Final = "trend_window_days"
OPT_PRICE_DISPLAY: Final = "price_display"
OPT_HISTORY_IMPORT_ENABLED: Final = "history_import_enabled"
OPT_HISTORY_IMPORT_MONTHS: Final = "history_import_months"
#: Fetch the announced next-day price from RTL.lu (petrol.lu does not carry it).
OPT_ANNOUNCEMENTS_ENABLED: Final = "announcements_enabled"

PRICE_DISPLAY_INCL: Final = "incl_vat"
PRICE_DISPLAY_EXCL: Final = "excl_vat"

# --- Defaults --------------------------------------------------------------
DEFAULT_TRACKED_FUELS: Final = [FuelType.DIESEL, FuelType.SP95, FuelType.SP98]
DEFAULT_PRIMARY_FUEL: Final = FuelType.DIESEL
DEFAULT_UPDATE_INTERVAL_HOURS: Final = 6
DEFAULT_EVENING_CHECK_TIME: Final = "18:01:00"
#: Extra refreshes fired (minutes after the evening check) when no upcoming price
#: has appeared yet. Cancelled early once one does.
EVENING_RETRY_OFFSETS_MINUTES: Final = (10, 20)
DEFAULT_TREND_WINDOW_DAYS: Final = 14
DEFAULT_HISTORY_IMPORT_MONTHS: Final = 12
DEFAULT_PRICE_DISPLAY: Final = PRICE_DISPLAY_INCL

MIN_UPDATE_INTERVAL_HOURS: Final = 1
MAX_UPDATE_INTERVAL_HOURS: Final = 24
MIN_TREND_WINDOW_DAYS: Final = 3
MAX_TREND_WINDOW_DAYS: Final = 90

#: How many days of history the coordinator keeps in memory for trend maths.
RECENT_HISTORY_DAYS: Final = 120
#: Data older than this (with a failing fetch) raises a repair issue.
STALE_AFTER_DAYS: Final = 14

# --- Trend classification -------------------------------------------------
TREND_RISING: Final = "rising"
TREND_FALLING: Final = "falling"
TREND_STABLE: Final = "stable"
TREND_STATES: Final = [TREND_RISING, TREND_FALLING, TREND_STABLE]
#: Projected absolute move over the window below this (EUR/L) counts as "stable".
TREND_STABLE_THRESHOLD_EUR: Final = 0.005

# --- Refuel recommendation ---------------------------------------------------
RECOMMENDATION_REFUEL_TODAY: Final = "refuel_today"
RECOMMENDATION_WAIT: Final = "wait"
RECOMMENDATION_NO_CHANGE: Final = "no_change"
RECOMMENDATION_UNKNOWN: Final = "unknown"
RECOMMENDATION_STATES: Final = [
    RECOMMENDATION_REFUEL_TODAY,
    RECOMMENDATION_WAIT,
    RECOMMENDATION_NO_CHANGE,
    RECOMMENDATION_UNKNOWN,
]

# --- Events --------------------------------------------------------------------
EVENT_PRICE_CHANGE_ANNOUNCED: Final = f"{DOMAIN}_price_change_announced"
EVENT_PRICE_CHANGED: Final = f"{DOMAIN}_price_changed"

# --- Repair issues ---------------------------------------------------------
ISSUE_STALE_DATA: Final = "stale_data"
ISSUE_PARSE_ERROR: Final = "parse_error"

# --- Services --------------------------------------------------------------
SERVICE_CALCULATE_FILL_COST: Final = "calculate_fill_cost"
SERVICE_CALCULATE_TRIP_COST: Final = "calculate_trip_cost"

ATTR_LITERS: Final = "liters"
ATTR_FUEL_TYPE: Final = "fuel_type"
ATTR_USE_TOMORROW_PRICE: Final = "use_tomorrow_price"
ATTR_DISTANCE_KM: Final = "distance_km"
ATTR_CONSUMPTION: Final = "consumption_l_100km"

# --- Misc ----------------------------------------------------------------------
CURRENCY_EURO: Final = "EUR"
UNIT_EUR_PER_LITER: Final = "€/L"
#: Luxembourg standard VAT rate (informational attribute only; the source
#: publishes both incl. and excl. VAT figures directly).
VAT_RATE_LU: Final = 0.17
