"""DataUpdateCoordinator for the Luxembourg Fuel Monitor."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CURRENT_LEVEL,
    CONF_PRIMARY_FUEL,
    CONF_PROVIDER,
    CONF_TANK_SIZE,
    CONF_TRACKED_FUELS,
    DEFAULT_EVENING_CHECK_TIME,
    DEFAULT_PRICE_DISPLAY,
    DEFAULT_PRIMARY_FUEL,
    DEFAULT_PROVIDER,
    DEFAULT_TRACKED_FUELS,
    DEFAULT_TREND_WINDOW_DAYS,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    EVENING_RETRY_OFFSETS_MINUTES,
    EVENT_PRICE_CHANGE_ANNOUNCED,
    EVENT_PRICE_CHANGED,
    ISSUE_PARSE_ERROR,
    ISSUE_STALE_DATA,
    OPT_EVENING_CHECK_TIME,
    OPT_PRICE_DISPLAY,
    OPT_TREND_WINDOW_DAYS,
    OPT_UPDATE_INTERVAL_HOURS,
    PRICE_DISPLAY_EXCL,
    STALE_AFTER_DAYS,
)
from .helpers import option_value
from .models import FuelPrices, FuelType, PricePoint, PriceSet
from .providers import (
    ProviderConnectionError,
    ProviderParseError,
    get_provider,
)

_LOGGER = logging.getLogger(__name__)
_STORE_VERSION = 1

type LuxFuelConfigEntry = ConfigEntry[LuxFuelCoordinator]


class LuxFuelCoordinator(DataUpdateCoordinator[PriceSet]):
    """Polls the fuel price provider and drives change detection."""

    config_entry: LuxFuelConfigEntry

    def __init__(self, hass: HomeAssistant, entry: LuxFuelConfigEntry) -> None:
        """Set up the coordinator for a config entry."""
        self.provider = get_provider(
            entry.data.get(CONF_PROVIDER, DEFAULT_PROVIDER),
            async_get_clientsession(hass),
        )
        interval_hours = int(
            option_value(
                entry, OPT_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS
            )
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=interval_hours),
            config_entry=entry,
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, _STORE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._last_seen: dict[str, Any] = {}
        self._evening_unsub: CALLBACK_TYPE | None = None
        self._retry_unsubs: list[CALLBACK_TYPE] = []
        #: Live fuel level (%) set via the number entity; overrides the option.
        self.manual_fuel_level: float | None = None

    # -- lifecycle ---------------------------------------------------------

    async def _async_setup(self) -> None:
        """Load persisted change-detection state before the first refresh."""
        self._last_seen = await self._store.async_load() or {}

    async def async_shutdown(self) -> None:
        """Cancel scheduled callbacks on unload."""
        self._teardown_evening_schedule()
        await super().async_shutdown()

    # -- polling ---------------------------------------------------------------

    async def _async_update_data(self) -> PriceSet:
        """Fetch prices and run change detection."""
        try:
            price_set = await self.provider.async_get_current_prices(self.tracked_fuels)
        except ProviderParseError as err:
            self._async_raise_issue(ISSUE_PARSE_ERROR, {"error": str(err)})
            raise UpdateFailed(f"{self.provider.name}: {err}") from err
        except ProviderConnectionError as err:
            raise UpdateFailed(f"{self.provider.name}: {err}") from err

        self._async_clear_issue(ISSUE_PARSE_ERROR)
        self._async_check_stale(price_set)
        await self._async_detect_changes(price_set)
        return price_set

    # -- change detection & events ------------------------------------------

    async def _async_detect_changes(self, price_set: PriceSet) -> None:
        """Fire announced / changed bus events and persist a snapshot."""
        snapshot: dict[str, Any] = {}
        announced: list[dict[str, Any]] = []
        changed: list[dict[str, Any]] = []

        for fuel, fp in price_set.prices.items():
            key = fuel.value
            prev = self._last_seen.get(key, {})
            cur_date = fp.current.effective_date.isoformat()
            up_date = fp.upcoming.effective_date.isoformat() if fp.upcoming else None
            up_price = (
                str(fp.upcoming.price_incl_vat) if fp.upcoming else None
            )

            if prev.get("current_date") and prev["current_date"] != cur_date:
                changed.append(
                    {
                        "fuel": key,
                        "old_price": _as_float(prev.get("current_price")),
                        "new_price": float(fp.current.price_incl_vat),
                        "effective_date": cur_date,
                    }
                )

            if fp.has_pending_change:
                seen_this = (
                    prev.get("upcoming_date") == up_date
                    and prev.get("upcoming_price") == up_price
                )
                if not seen_this:
                    delta = fp.upcoming.price_incl_vat - fp.current.price_incl_vat
                    announced.append(
                        {
                            "fuel": key,
                            "current_price": float(fp.current.price_incl_vat),
                            "upcoming_price": float(fp.upcoming.price_incl_vat),
                            "delta": round(float(delta), 4),
                            "direction": "up" if delta > 0 else "down",
                            "effective_date": up_date,
                        }
                    )

            snapshot[key] = {
                "current_date": cur_date,
                "current_price": str(fp.current.price_incl_vat),
                "upcoming_date": up_date,
                "upcoming_price": up_price,
            }

        if announced:
            _LOGGER.debug("Firing %s: %s", EVENT_PRICE_CHANGE_ANNOUNCED, announced)
            self.hass.bus.async_fire(
                EVENT_PRICE_CHANGE_ANNOUNCED,
                {"provider": price_set.provider_name, "changes": announced},
            )
        if changed:
            _LOGGER.debug("Firing %s: %s", EVENT_PRICE_CHANGED, changed)
            self.hass.bus.async_fire(
                EVENT_PRICE_CHANGED,
                {"provider": price_set.provider_name, "changes": changed},
            )

        if snapshot != self._last_seen:
            self._last_seen = snapshot
            await self._store.async_save(snapshot)

    def _async_check_stale(self, price_set: PriceSet) -> None:
        """Raise/clear a repair issue when the newest price is very old."""
        if not price_set.prices:
            return
        newest = max(fp.current.effective_date for fp in price_set.prices.values())
        age_days = (dt_util.now().date() - newest).days
        if age_days > STALE_AFTER_DAYS:
            self._async_raise_issue(
                ISSUE_STALE_DATA, {"age_days": str(age_days)}
            )
        else:
            self._async_clear_issue(ISSUE_STALE_DATA)

    # -- evening schedule --------------------------------------------------

    @callback
    def async_setup_evening_schedule(self) -> None:
        """(Re)arm the ~18:01 refresh that catches the government publication."""
        self._teardown_evening_schedule()
        parsed = dt_util.parse_time(
            option_value(
                self.config_entry, OPT_EVENING_CHECK_TIME, DEFAULT_EVENING_CHECK_TIME
            )
        ) or time(18, 1)
        self._evening_unsub = async_track_time_change(
            self.hass,
            self._async_evening_trigger,
            hour=parsed.hour,
            minute=parsed.minute,
            second=parsed.second,
        )

    @callback
    def _teardown_evening_schedule(self) -> None:
        if self._evening_unsub is not None:
            self._evening_unsub()
            self._evening_unsub = None
        for unsub in self._retry_unsubs:
            unsub()
        self._retry_unsubs.clear()

    async def _async_evening_trigger(self, now: datetime) -> None:
        """Refresh at the configured time, then schedule +10/+20 min retries."""
        await self.async_refresh()
        if self._has_pending_change():
            return
        for offset in EVENING_RETRY_OFFSETS_MINUTES:
            self._retry_unsubs.append(
                async_track_point_in_time(
                    self.hass,
                    self._async_evening_retry,
                    now + timedelta(minutes=offset),
                )
            )

    async def _async_evening_retry(self, now: datetime) -> None:
        """Retry only while no next-day price has appeared yet."""
        if self._has_pending_change():
            return
        await self.async_refresh()

    @callback
    def _has_pending_change(self) -> bool:
        return bool(
            self.data
            and any(fp.has_pending_change for fp in self.data.prices.values())
        )

    # -- repair issues ---------------------------------------------------------

    def _async_raise_issue(self, issue_id: str, placeholders: dict[str, str]) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=issue_id,
            translation_placeholders=placeholders,
        )

    def _async_clear_issue(self, issue_id: str) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    # -- convenience accessors used by entities & services -----------------

    @property
    def tracked_fuels(self) -> list[FuelType]:
        raw = option_value(
            self.config_entry,
            CONF_TRACKED_FUELS,
            [f.value for f in DEFAULT_TRACKED_FUELS],
        )
        valid = {f.value for f in FuelType}
        resolved = [FuelType(value) for value in raw if value in valid]
        return resolved or list(DEFAULT_TRACKED_FUELS)

    @property
    def primary_fuel(self) -> FuelType:
        try:
            return FuelType(
                option_value(self.config_entry, CONF_PRIMARY_FUEL, DEFAULT_PRIMARY_FUEL)
            )
        except ValueError:
            return DEFAULT_PRIMARY_FUEL

    @property
    def tank_size(self) -> float | None:
        raw = option_value(self.config_entry, CONF_TANK_SIZE, None)
        return float(raw) if raw else None

    @property
    def current_level_pct(self) -> float | None:
        """Live fuel level: the number entity if set, else the configured value."""
        if self.manual_fuel_level is not None:
            return self.manual_fuel_level
        raw = option_value(self.config_entry, CONF_CURRENT_LEVEL, None)
        return float(raw) if raw is not None else None

    @property
    def configured_level_pct(self) -> float | None:
        """The fuel level captured in the config/options (number entity default)."""
        raw = option_value(self.config_entry, CONF_CURRENT_LEVEL, None)
        return float(raw) if raw is not None else None

    @property
    def trend_window_days(self) -> int:
        return int(
            option_value(
                self.config_entry, OPT_TREND_WINDOW_DAYS, DEFAULT_TREND_WINDOW_DAYS
            )
        )

    @property
    def use_incl_vat(self) -> bool:
        return (
            option_value(self.config_entry, OPT_PRICE_DISPLAY, DEFAULT_PRICE_DISPLAY)
            != PRICE_DISPLAY_EXCL
        )

    def fuel_prices(self, fuel: FuelType) -> FuelPrices | None:
        if self.data is None:
            return None
        return self.data.prices.get(fuel)

    def recent_history(self, fuel: FuelType) -> list[PricePoint]:
        if self.data is None:
            return []
        return self.data.recent_history.get(fuel, [])

    def display_price(self, point: PricePoint | None) -> float | None:
        if point is None:
            return None
        value = point.price_incl_vat if self.use_incl_vat else point.price_excl_vat
        return float(value)


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
