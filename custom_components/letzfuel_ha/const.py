"""Constants for the LëtzFuel HA integration."""

from __future__ import annotations

from typing import Final

from .models import FuelType

DOMAIN: Final = "letzfuel_ha"
#: Static path the brand icon is served at (see __init__.py's async_setup) --
#: the notifications blueprint references this exact path as its icon_url.
BRAND_ICON_URL: Final = "/letzfuel_ha/icon.png"

# --- Providers -------------------------------------------------------------
DEFAULT_PROVIDER: Final = "petrol_lu"
#: Single source of truth for the version number both scrapers put in their
#: User-Agent string (manifest.json's "version" is HA's own source of truth
#: for the integration as a whole; keep this in sync by hand at release time).
USER_AGENT_VERSION: Final = "0.1.0"

# --- Config entry keys ---------------------------------------------------------
CONF_PROVIDER: Final = "provider"
CONF_TRACKED_FUELS: Final = "tracked_fuels"
CONF_PRIMARY_FUEL: Final = "primary_fuel"
CONF_TANK_SIZE: Final = "tank_size"
CONF_CURRENT_LEVEL: Final = "current_level_pct"
#: Where the current fuel level comes from: the manual slider or another entity.
CONF_LEVEL_SOURCE: Final = "level_source"
#: The entity whose state (a 0-100 %) is the fuel level, when source == entity.
CONF_LEVEL_ENTITY: Final = "level_entity_id"

LEVEL_SOURCE_MANUAL: Final = "manual"
LEVEL_SOURCE_ENTITY: Final = "entity"
LEVEL_SOURCES: Final = [LEVEL_SOURCE_MANUAL, LEVEL_SOURCE_ENTITY]
#: Domains offered in the fuel-level entity picker.
LEVEL_ENTITY_DOMAINS: Final = ["sensor", "number", "input_number"]

# --- Options keys ------------------------------------------------------------
OPT_UPDATE_INTERVAL_HOURS: Final = "update_interval_hours"
OPT_EVENING_CHECK_TIME: Final = "evening_check_time"
OPT_TREND_WINDOW_DAYS: Final = "trend_window_days"
OPT_PRICE_DISPLAY: Final = "price_display"
OPT_HISTORY_IMPORT_ENABLED: Final = "history_import_enabled"
OPT_HISTORY_IMPORT_MONTHS: Final = "history_import_months"
#: Also ask the additional announcement sources for the next-day price
#: (petrol.lu usually lists it only late in the evening).
OPT_ANNOUNCEMENTS_ENABLED: Final = "announcements_enabled"

PRICE_DISPLAY_INCL: Final = "incl_vat"
PRICE_DISPLAY_EXCL: Final = "excl_vat"

# --- Defaults --------------------------------------------------------------
DEFAULT_TRACKED_FUELS: Final = [FuelType.DIESEL, FuelType.SP95, FuelType.SP98]
DEFAULT_PRIMARY_FUEL: Final = FuelType.DIESEL
DEFAULT_UPDATE_INTERVAL_HOURS: Final = 6
DEFAULT_EVENING_CHECK_TIME: Final = "18:01:00"
#: Extra refreshes fired (minutes after the evening check) when no upcoming
#: price has appeared yet -- every 2 min for the first 14 min, then every
#: 5 min up to 29 min after the evening check (e.g. 18:03...18:15, then
#: 18:20/18:25/18:30 relative to the default 18:01 check time). Each retry
#: is a no-op (skipped, not cancelled) once a pending change is found --
#: harmless since it just checks state instead of refreshing again.
EVENING_RETRY_OFFSETS_MINUTES: Final = (2, 4, 6, 8, 10, 12, 14, 19, 24, 29)
#: After the last retry, keep polling until midnight while nothing has been
#: announced yet -- each gap drawn at random from this range (minutes) so
#: installs don't hit the sources in lockstep.
LATE_EVENING_POLL_MINUTES: Final = (20, 30)
#: Fixed time for the just-after-midnight refresh that promptly re-evaluates
#: the current/upcoming rollover, instead of waiting for the next periodic
#: poll (which can land hours later depending on when the last one ran).
#: Not user-configurable -- unlike the evening check there's no external
#: publish schedule to chase, so no retries are needed either.
MIDNIGHT_REFRESH_TIME: Final = "00:05:00"
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

# --- Announcement plausibility ---------------------------------------------
#: Announced prices further ahead than this (days) are ignored.
ANNOUNCE_MAX_DAYS_AHEAD: Final = 7
#: Announced prices further than this fraction from today's price are ignored.
ANNOUNCE_MAX_DEVIATION: Final = 0.15

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
#: NOT "unknown" -- Home Assistant's frontend hard-codes that literal string
#: (and "unavailable") to always render the generic core "Unknown" label,
#: short-circuiting before any entity/enum-specific translation is even
#: considered. Any of our own translations for that key are unreachable.
RECOMMENDATION_AWAITING_PRICE: Final = "awaiting_price"
RECOMMENDATION_STATES: Final = [
    RECOMMENDATION_REFUEL_TODAY,
    RECOMMENDATION_WAIT,
    RECOMMENDATION_NO_CHANGE,
    RECOMMENDATION_AWAITING_PRICE,
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
#: Effective dates are Luxembourg calendar days.
LU_TIME_ZONE: Final = "Europe/Luxembourg"
