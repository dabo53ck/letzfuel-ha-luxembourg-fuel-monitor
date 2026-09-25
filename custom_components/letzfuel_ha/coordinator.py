"""DataUpdateCoordinator for the LëtzFuel HA."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CURRENT_LEVEL,
    CONF_LEVEL_ENTITY,
    CONF_LEVEL_SOURCE,
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
    LATE_EVENING_POLL_MINUTES,
    LEVEL_SOURCE_ENTITY,
    LEVEL_SOURCE_MANUAL,
    MIDNIGHT_REFRESH_TIME,
    OPT_ANNOUNCEMENTS_ENABLED,
    OPT_EVENING_CHECK_TIME,
    OPT_PRICE_DISPLAY,
    OPT_TREND_WINDOW_DAYS,
    OPT_UPDATE_INTERVAL_HOURS,
    PRICE_DISPLAY_EXCL,
    SCHEDULE_JITTER_MAX_SECONDS,
    STALE_AFTER_DAYS,
)
from .helpers import option_value
from .models import FuelPrices, FuelType, PricePoint, PriceSet
from .providers import (
    ProviderConnectionError,
    ProviderParseError,
    build_price_set,
    get_provider,
)
from .providers.announcements import (
    AnnouncementResult,
    AnnouncementSource,
    current_prices,
    merge_announced,
    split_plausible,
)
from .providers.live_sheet import LiveSheetAnnouncements
from .providers.rtl_lu import RtlLuAnnouncements

_LOGGER = logging.getLogger(__name__)
_STORE_VERSION = 1

type LuxFuelConfigEntry = ConfigEntry[LuxFuelCoordinator]


class LuxFuelCoordinator(DataUpdateCoordinator[PriceSet]):
    """Polls the fuel price provider and drives change detection."""

    config_entry: LuxFuelConfigEntry

    def __init__(self, hass: HomeAssistant, entry: LuxFuelConfigEntry) -> None:
        """Set up the coordinator for a config entry."""
        session = async_get_clientsession(hass)
        self.provider = get_provider(
            entry.data.get(CONF_PROVIDER, DEFAULT_PROVIDER), session
        )
        #: Supply the announced next-day price earlier than the provider does,
        #: in priority order (the provider's own future rows beat all of them).
        self._announcement_sources: list[AnnouncementSource] = [
            RtlLuAnnouncements(session),
            LiveSheetAnnouncements(session),
        ]
        self._source_warned: set[str] = set()
        self._conflicts_warned: set[tuple[str, str, str, str]] = set()
        #: Last outcome per announcement source (exposed in diagnostics).
        self.announcement_status: dict[str, dict[str, Any]] = {}
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
        self._late_poll_unsub: CALLBACK_TYPE | None = None
        self._late_poll_deadline: datetime | None = None
        #: Fixed per-install offset for the evening and midnight refreshes.
        self.schedule_jitter = timedelta(
            seconds=_install_jitter_seconds(entry.entry_id)
        )
        self._midnight_unsub: CALLBACK_TYPE | None = None
        self._level_entity_unsub: CALLBACK_TYPE | None = None
        #: Live fuel level (%) set via the number entity; overrides the option.
        self.manual_fuel_level: float | None = None

    # -- lifecycle ---------------------------------------------------------

    async def _async_setup(self) -> None:
        """Load persisted change-detection state before the first refresh."""
        self._last_seen = await self._store.async_load() or {}

    async def async_shutdown(self) -> None:
        """Cancel scheduled callbacks on unload."""
        self._teardown_evening_schedule()
        self._teardown_midnight_schedule()
        self._teardown_level_entity_tracking()
        await super().async_shutdown()

    # -- polling ---------------------------------------------------------------

    async def _async_update_data(self) -> PriceSet:
        """Fetch prices, fold in the announcement, and run change detection."""
        try:
            history = await self.provider.async_get_history()
        except ProviderParseError as err:
            self._async_raise_issue(ISSUE_PARSE_ERROR, {"error": str(err)})
            raise UpdateFailed(f"{self.provider.name}: {err}") from err
        except ProviderConnectionError as err:
            raise UpdateFailed(f"{self.provider.name}: {err}") from err

        self._async_clear_issue(ISSUE_PARSE_ERROR)
        history = await self._async_merge_announcements(history)
        price_set = build_price_set(history, self.tracked_fuels, self.provider)
        self._async_check_stale(price_set)
        await self._async_detect_changes(price_set)
        return price_set

    async def _async_merge_announcements(
        self, history: list[PricePoint]
    ) -> list[PricePoint]:
        """Fold the announced next-day prices into ``history`` (best effort).

        The provider usually lists the next day's row only late in the evening,
        so without this the ``upcoming`` price -- and the pending-change binary
        sensor, the ``price_tomorrow`` sensor, the refuel recommendation and the
        announced event -- would come too late. Every source is optional: a
        failing one is logged once and skipped, implausible values are dropped,
        and the provider's own rows always win over an announcement.
        """
        if not option_value(self.config_entry, OPT_ANNOUNCEMENTS_ENABLED, True):
            self.announcement_status = {}
            return history

        today = dt_util.now().date()
        current = current_prices(history, today)
        results = await asyncio.gather(
            *(
                self._async_fetch_announcements(source, today)
                for source in self._announcement_sources
            )
        )

        batches: list[tuple[str, list[PricePoint]]] = []
        for source, result in zip(self._announcement_sources, results, strict=True):
            if result is None:
                continue
            kept, rejected = split_plausible(result.points, current, today)
            if kept:
                outcome = "announced"
            elif rejected:
                outcome = "implausible"
            else:
                outcome = "nothing_future"
            self._set_source_status(
                source.key, outcome, latest_date=result.latest_date, rejected=rejected
            )
            _LOGGER.debug(
                "Announcement source %s: latest date %s, %d future price(s), "
                "%d rejected",
                source.key,
                result.latest_date,
                len(kept),
                len(rejected),
            )
            if rejected:
                _LOGGER.debug("Rejected as implausible (%s): %s", source.key, rejected)
            batches.append((source.key, kept))

        merged, conflicts = merge_announced(history, batches)
        for conflict in conflicts:
            key = (
                conflict.fuel.value,
                conflict.effective_date.isoformat(),
                str(conflict.ignored),
                conflict.ignored_source,
            )
            if key in self._conflicts_warned:
                continue
            self._conflicts_warned.add(key)
            _LOGGER.warning(
                "Conflicting announced %s price for %s: kept %s, ignored %s from %s",
                conflict.fuel.value,
                conflict.effective_date,
                conflict.kept,
                conflict.ignored,
                conflict.ignored_source,
            )
        return merged

    async def _async_fetch_announcements(
        self, source: AnnouncementSource, today: date
    ) -> AnnouncementResult | None:
        """Fetch one source; log a failure once, return None instead of raising."""
        try:
            result = await source.async_fetch(today)
        except Exception as err:  # optional source: must fail soft, whatever broke
            self._set_source_status(source.key, "error", error=str(err))
            if source.key not in self._source_warned:
                _LOGGER.warning(
                    "Announcement source %s unavailable: %s", source.key, err
                )
                self._source_warned.add(source.key)
            return None
        if source.key in self._source_warned:
            _LOGGER.info("Announcement source %s recovered", source.key)
            self._source_warned.discard(source.key)
        return result

    def _set_source_status(
        self,
        key: str,
        outcome: str,
        *,
        latest_date: date | None = None,
        rejected: list[PricePoint] | None = None,
        error: str | None = None,
    ) -> None:
        self.announcement_status[key] = {
            "fetched_at": dt_util.utcnow().isoformat(),
            "outcome": outcome,
            "latest_date": latest_date.isoformat() if latest_date else None,
            "rejected": len(rejected or []),
            "error": error,
        }

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
            up_price = str(fp.upcoming.price_incl_vat) if fp.upcoming else None

            old_price = _as_float(prev.get("current_price"))
            new_price = float(fp.current.price_incl_vat)
            if (
                prev.get("current_date")
                and prev["current_date"] != cur_date
                and old_price != new_price
            ):
                changed.append(
                    {
                        "fuel": key,
                        "old_price": old_price,
                        "new_price": new_price,
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
            self._async_raise_issue(ISSUE_STALE_DATA, {"age_days": str(age_days)})
        else:
            self._async_clear_issue(ISSUE_STALE_DATA)

    # -- evening schedule --------------------------------------------------

    @callback
    def async_setup_evening_schedule(self) -> None:
        """(Re)arm the evening refresh that catches the government publication."""
        self._teardown_evening_schedule()
        parsed = dt_util.parse_time(
            option_value(
                self.config_entry, OPT_EVENING_CHECK_TIME, DEFAULT_EVENING_CHECK_TIME
            )
        ) or time(17, 30)
        at = _shift(parsed, self.schedule_jitter)
        self._evening_unsub = async_track_time_change(
            self.hass,
            self._async_evening_trigger,
            hour=at.hour,
            minute=at.minute,
            second=at.second,
        )
        # Set up (or restarted) after the evening check already ran today:
        # don't wait until tomorrow, keep polling for the rest of the evening.
        now = dt_util.now()
        if now.time() >= parsed and not self._has_upcoming():
            self._late_poll_deadline = _next_midnight(now)
            self._schedule_late_poll(now)

    @callback
    def _teardown_evening_schedule(self) -> None:
        if self._evening_unsub is not None:
            self._evening_unsub()
            self._evening_unsub = None
        for unsub in self._retry_unsubs:
            unsub()
        self._retry_unsubs.clear()
        self._cancel_late_poll()

    async def _async_evening_trigger(self, now: datetime) -> None:
        """Refresh at the configured time, then schedule the retry offsets."""
        # Yesterday's retries have all long since fired (safe one-shots) by
        # the time this runs again a day later -- reset instead of letting
        # fired-and-forgotten unsub refs pile up for the life of the entry.
        self._retry_unsubs.clear()
        self._cancel_late_poll()
        await self.async_refresh()
        if self._has_upcoming():
            return  # tomorrow's price is already known, changed or not
        for offset in EVENING_RETRY_OFFSETS_MINUTES:
            self._retry_unsubs.append(
                async_track_point_in_time(
                    self.hass,
                    self._async_evening_retry,
                    now + timedelta(minutes=offset),
                )
            )
        self._late_poll_deadline = _next_midnight(now)
        self._schedule_late_poll(
            now + timedelta(minutes=max(EVENING_RETRY_OFFSETS_MINUTES))
        )

    async def _async_evening_retry(self, now: datetime) -> None:
        """Retry only while no next-day price has appeared yet."""
        if self._has_upcoming():
            return
        await self.async_refresh()

    @callback
    def _schedule_late_poll(self, after: datetime) -> None:
        """Arm the next late-evening poll a random 20-30 min after ``after``.

        Nothing is armed once that would land past the evening's midnight --
        the midnight refresh takes over from there.
        """
        self._cancel_late_poll()
        low, high = LATE_EVENING_POLL_MINUTES
        when = after + timedelta(minutes=random.uniform(low, high))
        if self._late_poll_deadline is None or when >= self._late_poll_deadline:
            return
        self._late_poll_unsub = async_track_point_in_time(
            self.hass, self._async_late_poll, when
        )

    async def _async_late_poll(self, now: datetime) -> None:
        """Poll again unless tomorrow's price is known by now; then re-arm."""
        self._late_poll_unsub = None
        if self._has_upcoming():
            return
        await self.async_refresh()
        if not self._has_upcoming():
            self._schedule_late_poll(now)

    @callback
    def _cancel_late_poll(self) -> None:
        if self._late_poll_unsub is not None:
            self._late_poll_unsub()
            self._late_poll_unsub = None

    @callback
    def async_setup_midnight_schedule(self) -> None:
        """Arm the just-after-midnight refresh (see MIDNIGHT_REFRESH_TIME).

        The regular poll interval isn't anchored to wall-clock time, so the
        current/upcoming rollover would otherwise only be caught whenever the
        next periodic poll happens to land -- which can be hours into the new
        day. This refresh re-evaluates it promptly; no new data is needed for
        that, since the announced price was already merged in the evening.
        """
        self._teardown_midnight_schedule()
        parsed = dt_util.parse_time(MIDNIGHT_REFRESH_TIME) or time(0, 5)
        at = _shift(parsed, self.schedule_jitter)
        self._midnight_unsub = async_track_time_change(
            self.hass,
            self._async_midnight_trigger,
            hour=at.hour,
            minute=at.minute,
            second=at.second,
        )

    @callback
    def _teardown_midnight_schedule(self) -> None:
        if self._midnight_unsub is not None:
            self._midnight_unsub()
            self._midnight_unsub = None

    async def _async_midnight_trigger(self, now: datetime) -> None:
        await self.async_refresh()

    # -- external fuel-level entity --------------------------------------------

    @callback
    def async_setup_level_entity_tracking(self) -> None:
        """Recompute the refill sensor whenever the chosen level entity changes.

        Only armed when the fuel level source is another entity. Options edits
        reload the whole entry, so this is re-armed automatically on change.
        """
        self._teardown_level_entity_tracking()
        if self.level_source != LEVEL_SOURCE_ENTITY or not self.level_entity_id:
            return
        self._level_entity_unsub = async_track_state_change_event(
            self.hass, [self.level_entity_id], self._async_level_entity_changed
        )

    @callback
    def _teardown_level_entity_tracking(self) -> None:
        if self._level_entity_unsub is not None:
            self._level_entity_unsub()
            self._level_entity_unsub = None

    @callback
    def _async_level_entity_changed(self, _event: Event) -> None:
        self.async_update_listeners()

    @callback
    def _has_upcoming(self) -> bool:
        """True once tomorrow's price is known -- changed or not."""
        return bool(self.data and any(fp.upcoming for fp in self.data.prices.values()))

    @callback
    def _has_pending_change(self) -> bool:
        return bool(
            self.data and any(fp.has_pending_change for fp in self.data.prices.values())
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
    def level_source(self) -> str:
        """Whether the fuel level comes from the manual slider or an entity."""
        return option_value(self.config_entry, CONF_LEVEL_SOURCE, LEVEL_SOURCE_MANUAL)

    @property
    def level_entity_id(self) -> str | None:
        """The entity the fuel level is read from, when ``level_source`` is entity."""
        return option_value(self.config_entry, CONF_LEVEL_ENTITY, None) or None

    @property
    def current_level_pct(self) -> float | None:
        """Live fuel level (%).

        From the chosen entity when the source is ``entity``; otherwise the
        number entity if set, else the configured value.
        """
        if self.level_source == LEVEL_SOURCE_ENTITY and self.level_entity_id:
            return self._entity_level_pct()
        if self.manual_fuel_level is not None:
            return self.manual_fuel_level
        raw = option_value(self.config_entry, CONF_CURRENT_LEVEL, None)
        return float(raw) if raw is not None else None

    def _entity_level_pct(self) -> float | None:
        """Read the chosen level entity as a percentage (0-100), or ``None``.

        Anything unusable -- entity missing, unknown/unavailable, non-numeric,
        or outside 0-100 -- yields ``None`` so the refill sensor degrades to
        "unknown" instead of showing a wrong figure.
        """
        state = self.hass.states.get(self.level_entity_id)
        if state is None or state.state in ("unknown", "unavailable", "", None):
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        return value if 0 <= value <= 100 else None

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


def _install_jitter_seconds(entry_id: str) -> int:
    """Stable 0..SCHEDULE_JITTER_MAX_SECONDS offset for this config entry."""
    digest = hashlib.sha256(entry_id.encode()).digest()
    return int.from_bytes(digest[:4], "big") % (SCHEDULE_JITTER_MAX_SECONDS + 1)


def _shift(at: time, delta: timedelta) -> time:
    """Wall-clock time ``delta`` after ``at`` (wrapping past midnight)."""
    return (datetime.combine(date.min, at) + delta).time()


def _next_midnight(now: datetime) -> datetime:
    """Local midnight at the end of ``now``'s day."""
    return dt_util.start_of_local_day(dt_util.as_local(now).date() + timedelta(days=1))


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
