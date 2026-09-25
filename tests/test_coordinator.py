"""Tests for the coordinator: setup and change detection / events."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.letzfuel_ha.const import (
    ANNOUNCE_FEED_BROKEN_ISSUE_DAYS,
    CONF_PRIMARY_FUEL,
    CONF_PROVIDER,
    CONF_TRACKED_FUELS,
    DEFAULT_EVENING_CHECK_TIME,
    DEFAULT_PROVIDER,
    DOMAIN,
    EVENING_RETRY_OFFSETS_MINUTES,
    EVENT_PRICE_CHANGE_ANNOUNCED,
    EVENT_PRICE_CHANGE_CORRECTED,
    EVENT_PRICE_CHANGED,
    ISSUE_ANNOUNCEMENTS_UNAVAILABLE,
    ISSUE_PARSE_ERROR,
    ISSUE_STALE_DATA,
    LATE_EVENING_POLL_MINUTES,
    OPT_ANNOUNCEMENTS_ENABLED,
    OPT_HISTORY_IMPORT_ENABLED,
    SCHEDULE_JITTER_MAX_SECONDS,
    STALE_AFTER_DAYS,
)
from custom_components.letzfuel_ha.models import (
    FuelPrices,
    FuelType,
    PricePoint,
    PriceSet,
)
from custom_components.letzfuel_ha.providers.base import ProviderParseError

from .helpers import sheet_json

_COORD = "custom_components.letzfuel_ha.coordinator"


def _entry(**options: object) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="LëtzFuel HA",
        data={
            CONF_PROVIDER: DEFAULT_PROVIDER,
            CONF_TRACKED_FUELS: [FuelType.DIESEL.value],
            CONF_PRIMARY_FUEL: FuelType.DIESEL.value,
        },
        options={OPT_HISTORY_IMPORT_ENABLED: False, **options},
    )


async def test_setup_populates_data(hass: HomeAssistant, init_integration) -> None:
    coordinator = init_integration.runtime_data
    assert coordinator.last_update_success
    fp = coordinator.fuel_prices(FuelType.DIESEL)
    assert fp is not None
    assert fp.current.price_incl_vat == Decimal("1.865")
    # re-published unchanged today -> last real move was 8 days ago
    assert fp.previous.price_incl_vat == Decimal("1.800")
    assert fp.current_since == dt_util.now().date() - timedelta(days=8)


def _price_set(current: str, upcoming: str | None) -> PriceSet:
    today = dt_util.now().date()
    cur = PricePoint(today, FuelType.DIESEL, Decimal(current), Decimal(current))
    up = (
        PricePoint(
            today + timedelta(days=1),
            FuelType.DIESEL,
            Decimal(upcoming),
            Decimal(upcoming),
        )
        if upcoming
        else None
    )
    fp = FuelPrices(FuelType.DIESEL, cur, today, None, up)
    return PriceSet(
        fetched_at=dt_util.utcnow(),
        provider_name="test",
        source_url="http://example.test",
        attribution="test",
        prices={FuelType.DIESEL: fp},
        recent_history={FuelType.DIESEL: [cur]},
    )


async def test_announced_event_fires_once(
    hass: HomeAssistant, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    events = []
    hass.bus.async_listen(EVENT_PRICE_CHANGE_ANNOUNCED, lambda e: events.append(e))

    coordinator._last_seen = {}
    await coordinator._async_detect_changes(_price_set("1.865", "1.900"))
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["changes"][0]["direction"] == "up"

    # Same upcoming again -> no duplicate event.
    await coordinator._async_detect_changes(_price_set("1.865", "1.900"))
    await hass.async_block_till_done()
    assert len(events) == 1


async def test_fallback_announces_while_primary_is_down(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    """With the primary feed unreachable, the fallback supplies tomorrow."""
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(price_entries, rtl_payload=_rtl(tomorrow, 2.024), sheet_status=500)

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    fp = coordinator.fuel_prices(FuelType.DIESEL)
    assert fp.upcoming is not None
    assert fp.upcoming.effective_date == tomorrow
    assert fp.upcoming.price_incl_vat == Decimal("2.024")
    assert fp.has_pending_change
    assert coordinator.announcement_status["live_sheet"]["outcome"] == "error"
    assert coordinator.announcement_status["rtl_lu"]["outcome"] == "announced"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_rtl_failure_is_non_fatal(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    """A dead RTL endpoint must not break the petrol.lu update."""
    mock_petrol_lu(price_entries, rtl_status=502)

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    assert coordinator.last_update_success
    fp = coordinator.fuel_prices(FuelType.DIESEL)
    assert fp is not None
    assert fp.upcoming is None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_announcements_option_disables_rtl(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    """With the option off, an announced RTL price is ignored."""
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(
        price_entries,
        rtl_payload={
            "id": 2132,
            "date": f"{tomorrow.isoformat()}T00:00:00+02:00",
            "98oct": 1.983,
            "95oct": 1.792,
            "diesel": 2.024,
        },
    )

    entry = _entry(**{OPT_ANNOUNCEMENTS_ENABLED: False})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    fp = entry.runtime_data.fuel_prices(FuelType.DIESEL)
    assert fp.upcoming is None
    assert not fp.has_pending_change

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def test_evening_retry_offsets_cadence() -> None:
    """Regression guard: every 2 min for an hour (17:32 ... 18:30 by default)."""
    assert EVENING_RETRY_OFFSETS_MINUTES == tuple(range(2, 61, 2))
    assert DEFAULT_EVENING_CHECK_TIME == "17:30:00"


async def test_evening_trigger_schedules_and_resets_retries(
    hass: HomeAssistant, init_integration
) -> None:
    """No pending change -> one retry timer per offset; a later evening resets

    the list instead of accumulating already-fired unsub refs across days.
    """
    coordinator = init_integration.runtime_data

    await coordinator._async_evening_trigger(dt_util.utcnow())
    assert len(coordinator._retry_unsubs) == len(EVENING_RETRY_OFFSETS_MINUTES)
    first_batch = list(coordinator._retry_unsubs)

    # Simulates the next day's trigger -- must reset, not pile onto, the list.
    await coordinator._async_evening_trigger(dt_util.utcnow())
    assert len(coordinator._retry_unsubs) == len(EVENING_RETRY_OFFSETS_MINUTES)

    # Cancel both batches. In production the first batch's real
    # async_track_point_in_time timers would already have fired by the time
    # a second evening trigger runs a day later, so nothing to clean up
    # there -- here no real time passes between the two calls above, so
    # they're still pending and the test harness (rightly) fails on any
    # lingering timer left after the test.
    for unsub in [*first_batch, *coordinator._retry_unsubs]:
        unsub()


async def test_changed_event_on_effective_date_advance(
    hass: HomeAssistant, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    events = []
    hass.bus.async_listen(EVENT_PRICE_CHANGED, lambda e: events.append(e))

    yesterday = (dt_util.now().date() - timedelta(days=1)).isoformat()
    coordinator._last_seen = {
        "diesel": {
            "current_date": yesterday,
            "current_price": "1.800",
            "upcoming_date": None,
            "upcoming_price": None,
        }
    }
    await coordinator._async_detect_changes(_price_set("1.865", None))
    await hass.async_block_till_done()

    assert len(events) == 1
    change = events[0].data["changes"][0]
    assert change["old_price"] == pytest.approx(1.800)
    assert change["new_price"] == pytest.approx(1.865)


async def test_no_changed_event_when_price_unchanged_on_date_advance(
    hass: HomeAssistant, init_integration
) -> None:
    """The effective date advancing alone (e.g. every midnight rollover)
    must not fire a changed event when the price itself didn't move --
    on a day where only some tracked fuels get a real price change, the
    others just get a fresh same-price record for the new date."""
    coordinator = init_integration.runtime_data
    events = []
    hass.bus.async_listen(EVENT_PRICE_CHANGED, lambda e: events.append(e))

    yesterday = (dt_util.now().date() - timedelta(days=1)).isoformat()
    coordinator._last_seen = {
        "diesel": {
            "current_date": yesterday,
            "current_price": "1.865",
            "upcoming_date": None,
            "upcoming_price": None,
        }
    }
    await coordinator._async_detect_changes(_price_set("1.865", None))
    await hass.async_block_till_done()

    assert len(events) == 0


async def test_changed_event_only_includes_fuels_that_actually_moved(
    hass: HomeAssistant, init_integration
) -> None:
    """Mixed day, multiple tracked fuels in one refresh: SP95 gets a real
    price change, Diesel's record just rolls over to a new date at the
    same price. Only SP95 may appear in the changed event -- this is the
    exact real-world scenario from the bug report (Diesel sent a false
    "-0.0 ct/L" notification on a day only SP95/SP98 actually changed).
    """
    coordinator = init_integration.runtime_data
    events = []
    hass.bus.async_listen(EVENT_PRICE_CHANGED, lambda e: events.append(e))

    today = dt_util.now().date()
    yesterday = (today - timedelta(days=1)).isoformat()

    diesel_cur = PricePoint(today, FuelType.DIESEL, Decimal("1.865"), Decimal("1.865"))
    sp95_cur = PricePoint(today, FuelType.SP95, Decimal("1.950"), Decimal("1.950"))

    price_set = PriceSet(
        fetched_at=dt_util.utcnow(),
        provider_name="test",
        source_url="http://example.test",
        attribution="test",
        prices={
            FuelType.DIESEL: FuelPrices(FuelType.DIESEL, diesel_cur, today, None, None),
            FuelType.SP95: FuelPrices(FuelType.SP95, sp95_cur, today, None, None),
        },
        recent_history={FuelType.DIESEL: [diesel_cur], FuelType.SP95: [sp95_cur]},
    )

    coordinator._last_seen = {
        "diesel": {
            "current_date": yesterday,
            "current_price": "1.865",  # unchanged from today -> no event
            "upcoming_date": None,
            "upcoming_price": None,
        },
        "sp95": {
            "current_date": yesterday,
            "current_price": "1.900",  # differs from today -> real change
            "upcoming_date": None,
            "upcoming_price": None,
        },
    }
    await coordinator._async_detect_changes(price_set)
    await hass.async_block_till_done()

    assert len(events) == 1
    changed_fuels = {c["fuel"] for c in events[0].data["changes"]}
    assert changed_fuels == {"sp95"}


def _stale_price_set(age_days: int) -> PriceSet:
    """A PriceSet whose newest price is `age_days` old."""
    old_date = dt_util.now().date() - timedelta(days=age_days)
    cur = PricePoint(old_date, FuelType.DIESEL, Decimal("1.865"), Decimal("1.594"))
    fp = FuelPrices(FuelType.DIESEL, cur, old_date, None, None)
    return PriceSet(
        fetched_at=dt_util.utcnow(),
        provider_name="test",
        source_url="http://example.test",
        attribution="test",
        prices={FuelType.DIESEL: fp},
        recent_history={FuelType.DIESEL: [cur]},
    )


async def test_stale_data_issue_raised_and_cleared(
    hass: HomeAssistant, init_integration
) -> None:
    """A newest price older than STALE_AFTER_DAYS raises a repair issue;

    a fresh price_set clears it again.
    """
    coordinator = init_integration.runtime_data
    age = STALE_AFTER_DAYS + 1

    coordinator._async_check_stale(_stale_price_set(age))
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_STALE_DATA)
    assert issue is not None
    assert issue.translation_placeholders == {"age_days": str(age)}

    coordinator._async_check_stale(_price_set("1.865", None))
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_STALE_DATA) is None


async def test_stale_data_issue_not_raised_within_window(
    hass: HomeAssistant, init_integration
) -> None:
    """Right at the STALE_AFTER_DAYS boundary, no issue is raised."""
    coordinator = init_integration.runtime_data

    coordinator._async_check_stale(_stale_price_set(STALE_AFTER_DAYS))
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_STALE_DATA) is None


async def test_parse_error_issue_raised_and_cleared(
    hass: HomeAssistant, init_integration
) -> None:
    """A provider parse failure raises a repair issue; recovery clears it."""
    coordinator = init_integration.runtime_data

    with patch.object(
        coordinator.provider,
        "async_get_history",
        side_effect=ProviderParseError("boom"),
    ):
        await coordinator.async_refresh()

    assert not coordinator.last_update_success
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_PARSE_ERROR)
    assert issue is not None
    assert issue.translation_placeholders == {"error": "boom"}

    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_PARSE_ERROR) is None


# -- announcement feeds: primary, fallback, leader, corrections ---------------


def _sheet(day, diesel: str, sp95: str = "1.792", sp98: str = "1.983") -> dict:
    """Today's row (matching petrol.lu) plus a complete row for ``day``."""
    today = dt_util.now().date()
    return sheet_json(
        [
            (
                today,
                {
                    FuelType.DIESEL: "1.865",
                    FuelType.SP95: "1.792",
                    FuelType.SP98: "1.983",
                },
            ),
            (
                day,
                {FuelType.DIESEL: diesel, FuelType.SP95: sp95, FuelType.SP98: sp98},
            ),
        ]
    )


def _rtl(day, diesel: float) -> dict:
    return {
        "id": 1,
        "date": f"{day.isoformat()}T00:00:00+02:00",
        "98oct": 1.983,
        "95oct": 1.792,
        "diesel": diesel,
    }


async def _setup(hass: HomeAssistant, **options: object) -> MockConfigEntry:
    entry = _entry(**options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_primary_announces_and_fallback_stays_on_standby(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    """The 2026-09-25 case: the fallback's wrong Diesel is never even asked."""
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(
        price_entries,
        sheet_payload=_sheet(tomorrow, "1.905"),
        rtl_payload=_rtl(tomorrow, 1.800),
    )

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    fp = coordinator.fuel_prices(FuelType.DIESEL)
    assert fp.upcoming.effective_date == tomorrow
    assert fp.upcoming.price_incl_vat == Decimal("1.905")

    status = coordinator.announcement_status
    assert status["live_sheet"]["outcome"] == "announced"
    assert status["live_sheet"]["latest_date"] == tomorrow.isoformat()
    assert status["rtl_lu"] == {"outcome": "standby"}

    await _unload(hass, entry)


async def test_primary_disagreeing_with_provider_falls_back(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    """A stale / mis-edited feed (today's price differs) is not trusted."""
    today = dt_util.now().date()
    tomorrow = today + timedelta(days=1)
    stale = sheet_json(
        [
            (
                today,
                {
                    FuelType.DIESEL: "1.800",
                    FuelType.SP95: "1.792",
                    FuelType.SP98: "1.983",
                },
            ),
            (
                tomorrow,
                {
                    FuelType.DIESEL: "1.950",
                    FuelType.SP95: "1.792",
                    FuelType.SP98: "1.983",
                },
            ),
        ]
    )
    mock_petrol_lu(
        price_entries, sheet_payload=stale, rtl_payload=_rtl(tomorrow, 1.905)
    )

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.announcement_status["live_sheet"]["outcome"] == "inconsistent"
    assert coordinator.announcement_status["rtl_lu"]["outcome"] == "announced"
    assert coordinator.fuel_prices(FuelType.DIESEL).upcoming.price_incl_vat == Decimal(
        "1.905"
    )

    await _unload(hass, entry)


async def test_provider_row_wins_over_announcement(
    hass: HomeAssistant, mock_petrol_lu, price_entries, caplog
) -> None:
    tomorrow = dt_util.now().date() + timedelta(days=1)
    entries = [
        *price_entries,
        (tomorrow, {FuelType.DIESEL: (Decimal("1.900"), Decimal("1.624"))}),
    ]
    mock_petrol_lu(entries, sheet_payload=_sheet(tomorrow, "1.950"))

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.fuel_prices(FuelType.DIESEL).upcoming.price_incl_vat == Decimal(
        "1.900"
    )

    await coordinator.async_refresh()
    assert caplog.text.count("ignored 1.950 from live_sheet") == 1

    await _unload(hass, entry)


async def test_announced_price_is_the_leader_until_provider_knows(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    """A later, different feed value can't flip an announcement."""
    tomorrow = dt_util.now().date() + timedelta(days=1)
    announced: list = []
    hass.bus.async_listen(EVENT_PRICE_CHANGE_ANNOUNCED, announced.append)
    mock_petrol_lu(price_entries, sheet_payload=_sheet(tomorrow, "1.905"))

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await hass.async_block_till_done()
    assert len(announced) == 1

    # the feed changes its mind (e.g. an editor's typo fixed the other way)
    mock_petrol_lu(price_entries, sheet_payload=_sheet(tomorrow, "1.925"))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.fuel_prices(FuelType.DIESEL).upcoming.price_incl_vat == Decimal(
        "1.905"
    )
    assert len(announced) == 1

    await _unload(hass, entry)


async def test_correction_when_provider_differs_in_the_evening(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    """The 2026-09-25 case: announced a drop, officially unchanged."""
    tomorrow = dt_util.now().date() + timedelta(days=1)
    announced: list = []
    corrected: list = []
    hass.bus.async_listen(EVENT_PRICE_CHANGE_ANNOUNCED, announced.append)
    hass.bus.async_listen(EVENT_PRICE_CHANGE_CORRECTED, corrected.append)
    mock_petrol_lu(price_entries, sheet_payload=_sheet(tomorrow, "1.825"))

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    await hass.async_block_till_done()
    assert len(announced) == 1

    # petrol.lu publishes tomorrow's row: Diesel stays at 1.865
    entries = [
        *price_entries,
        (tomorrow, {FuelType.DIESEL: (Decimal("1.865"), Decimal("1.594"))}),
    ]
    mock_petrol_lu(entries, sheet_payload=_sheet(tomorrow, "1.825"))
    coordinator.provider._cache = None  # skip the 5-min page cache
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(announced) == 1
    assert len(corrected) == 1
    (change,) = corrected[0].data["changes"]
    assert change == {
        "fuel": "diesel",
        "effective_date": tomorrow.isoformat(),
        "announced_price": 1.825,
        "corrected_price": 1.865,
        "current_price": 1.865,
        "delta": 0.0,
        "direction": "none",
    }
    fp = coordinator.fuel_prices(FuelType.DIESEL)
    assert fp.upcoming.price_incl_vat == Decimal("1.865")
    assert not fp.has_pending_change

    # resolved: nothing fires again
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(corrected) == 1

    await _unload(hass, entry)


async def test_no_correction_when_provider_confirms(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    tomorrow = dt_util.now().date() + timedelta(days=1)
    corrected: list = []
    hass.bus.async_listen(EVENT_PRICE_CHANGE_CORRECTED, corrected.append)
    mock_petrol_lu(price_entries, sheet_payload=_sheet(tomorrow, "1.905"))
    entry = await _setup(hass)
    coordinator = entry.runtime_data

    entries = [
        *price_entries,
        (tomorrow, {FuelType.DIESEL: (Decimal("1.905"), Decimal("1.628"))}),
    ]
    mock_petrol_lu(entries, sheet_payload=_sheet(tomorrow, "1.905"))
    coordinator.provider._cache = None  # skip the 5-min page cache
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert corrected == []
    assert coordinator._last_seen["diesel"]["announced_date"] is None

    await _unload(hass, entry)


async def test_correction_after_midnight(hass: HomeAssistant, init_integration) -> None:
    """The provider only lists the new day after midnight: still corrected."""
    coordinator = init_integration.runtime_data
    corrected: list = []
    hass.bus.async_listen(EVENT_PRICE_CHANGE_CORRECTED, corrected.append)

    today = dt_util.now().date()
    yesterday = today - timedelta(days=1)
    coordinator._last_seen = {
        "diesel": {
            "current_date": yesterday.isoformat(),
            "current_price": "1.865",
            "upcoming_date": None,
            "upcoming_price": None,
            "announced_date": today.isoformat(),
            "announced_price": "1.825",
            "announced_base": "1.865",
        }
    }
    coordinator._official = {(FuelType.DIESEL, today): Decimal("1.905")}
    await coordinator._async_detect_changes(_price_set("1.905", None))
    await hass.async_block_till_done()

    (change,) = corrected[0].data["changes"]
    assert change["corrected_price"] == 1.905
    assert change["announced_price"] == 1.825
    assert change["delta"] == 0.04
    assert change["direction"] == "up"


async def test_implausible_announcement_is_ignored(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(price_entries, sheet_payload=_sheet(tomorrow, "18.65"))

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    # the typo'd Diesel price is dropped; the other fuels' row still counts
    assert coordinator.fuel_prices(FuelType.DIESEL).upcoming is None
    assert coordinator.announcement_status["live_sheet"]["rejected"] == 1

    await _unload(hass, entry)


async def test_all_announcement_sources_failing_is_non_fatal(
    hass: HomeAssistant, mock_petrol_lu, price_entries, caplog
) -> None:
    mock_petrol_lu(price_entries, rtl_status=502, sheet_status=500)

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.last_update_success
    assert coordinator.fuel_prices(FuelType.DIESEL).upcoming is None
    for key in ("rtl_lu", "live_sheet"):
        assert coordinator.announcement_status[key]["outcome"] == "error"

    # warned once per source, then quiet until it recovers
    await coordinator.async_refresh()
    assert caplog.text.count("Announcement source rtl_lu unavailable") == 1
    assert caplog.text.count("Announcement source live_sheet unavailable") == 1

    mock_petrol_lu(price_entries)
    await coordinator.async_refresh()
    assert "Announcement source live_sheet recovered" in caplog.text
    assert coordinator.announcement_status["live_sheet"]["outcome"] == (
        "nothing_future"
    )
    assert coordinator.announcement_status["rtl_lu"] == {"outcome": "standby"}

    await _unload(hass, entry)


async def test_repair_issue_when_primary_down_for_days(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    mock_petrol_lu(price_entries, sheet_status=500)
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, ISSUE_ANNOUNCEMENTS_UNAVAILABLE) is None

    coordinator.primary_broken_since = dt_util.utcnow() - timedelta(
        days=ANNOUNCE_FEED_BROKEN_ISSUE_DAYS, hours=1
    )
    await coordinator.async_refresh()
    assert registry.async_get_issue(DOMAIN, ISSUE_ANNOUNCEMENTS_UNAVAILABLE)

    mock_petrol_lu(price_entries)
    await coordinator.async_refresh()
    assert registry.async_get_issue(DOMAIN, ISSUE_ANNOUNCEMENTS_UNAVAILABLE) is None
    assert coordinator.primary_broken_since is None

    await _unload(hass, entry)


async def test_announcements_option_disables_every_source(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(
        price_entries,
        rtl_payload=_rtl(tomorrow, 1.905),
        sheet_payload=_sheet(tomorrow, "1.905"),
    )

    entry = await _setup(hass, **{OPT_ANNOUNCEMENTS_ENABLED: False})
    coordinator = entry.runtime_data
    assert coordinator.fuel_prices(FuelType.DIESEL).upcoming is None
    assert coordinator.announcement_status == {}

    await _unload(hass, entry)


# -- late-evening polling -------------------------------------------------------


def _local(hour: int, minute: int = 0) -> datetime:
    return dt_util.start_of_local_day() + timedelta(hours=hour, minutes=minute)


async def test_evening_trigger_arms_randomized_late_poll(
    hass: HomeAssistant, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    tracker = MagicMock()
    with (
        patch(f"{_COORD}.random.uniform", return_value=25.0) as uniform,
        patch(f"{_COORD}.async_track_point_in_time", tracker),
    ):
        await coordinator._async_evening_trigger(_local(17, 30))

    uniform.assert_called_with(*LATE_EVENING_POLL_MINUTES)
    times = [call.args[2] for call in tracker.call_args_list]
    # every 2 min until 18:30, then the first late poll 25 min after that
    assert times[:-1] == [
        _local(17, 30) + timedelta(minutes=m) for m in EVENING_RETRY_OFFSETS_MINUTES
    ]
    assert times[-2] == _local(18, 30)
    assert times[-1] == _local(18, 55)
    assert coordinator._late_poll_deadline == _local(24)


async def test_late_poll_stops_at_midnight(
    hass: HomeAssistant, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    coordinator._late_poll_deadline = _local(24)
    tracker = MagicMock()
    with (
        patch(f"{_COORD}.random.uniform", return_value=25.0),
        patch(f"{_COORD}.async_track_point_in_time", tracker),
    ):
        coordinator._schedule_late_poll(_local(23, 20))
        assert tracker.call_args.args[2] == _local(23, 45)
        tracker.reset_mock()

        coordinator._schedule_late_poll(_local(23, 40))  # would be 00:05
        tracker.assert_not_called()
        assert coordinator._late_poll_unsub is None


async def test_late_poll_rearms_until_announced(
    hass: HomeAssistant, mock_petrol_lu, price_entries, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    # Set up after 18:01 (wall clock), setup already armed a real late poll;
    # calling the callback directly below would orphan that timer.
    coordinator._cancel_late_poll()
    coordinator._late_poll_deadline = _local(24) + timedelta(days=1)
    tracker = MagicMock()
    with patch(f"{_COORD}.async_track_point_in_time", tracker):
        # nothing announced yet -> refresh, then arm the next poll
        await coordinator._async_late_poll(_local(19))
        assert tracker.call_count == 1

        # the sheet now has tomorrow -> refresh finds it, no further poll
        tomorrow = dt_util.now().date() + timedelta(days=1)
        mock_petrol_lu(
            price_entries,
            sheet_payload=_sheet(tomorrow, "1.905"),
        )
        await coordinator._async_late_poll(_local(19, 25))
        assert coordinator._has_pending_change()
        assert tracker.call_count == 1

    coordinator._late_poll_unsub = None  # the MagicMock "unsub" needs no cleanup


@pytest.mark.parametrize(("hour", "armed"), [(20, True), (10, False)])
async def test_setup_after_evening_check_starts_late_polling(
    hass: HomeAssistant, mock_petrol_lu, freezer, hour: int, armed: bool
) -> None:
    """A restart at 20:40 (after the 18:01 check) still polls that evening."""
    freezer.move_to(_local(hour, 40))

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert (coordinator._late_poll_unsub is not None) is armed

    await _unload(hass, entry)
    assert coordinator._late_poll_unsub is None


async def test_unchanged_announcement_ends_evening_polling(
    hass: HomeAssistant, mock_petrol_lu, price_entries, init_integration
) -> None:
    """Tomorrow announced at today's price: nothing left to wait for."""
    coordinator = init_integration.runtime_data
    coordinator._cancel_late_poll()  # a setup after 17:30 may have armed one
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(price_entries, sheet_payload=_sheet(tomorrow, "1.865"))
    tracker = MagicMock()
    with patch(f"{_COORD}.async_track_point_in_time", tracker):
        await coordinator._async_evening_trigger(_local(17, 30))
        # neither retries nor late-evening polls get armed
        tracker.assert_not_called()
        assert coordinator._late_poll_unsub is None

        await coordinator._async_late_poll(_local(19))
        await coordinator._async_evening_retry(_local(17, 32))
        tracker.assert_not_called()


async def test_unexpected_source_error_is_non_fatal(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    """Garbage that isn't a ProviderError must not break the update either."""
    mock_petrol_lu(
        price_entries,
        sheet_status=500,
        rtl_payload={"id": 1, "date": "2026-13-45T00:00:00+02:00", "diesel": 2.0},
    )

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.last_update_success
    assert coordinator.announcement_status["rtl_lu"]["outcome"] == "error"

    await _unload(hass, entry)


def test_install_jitter_is_stable_and_bounded() -> None:
    from custom_components.letzfuel_ha.coordinator import _install_jitter_seconds

    values = {_install_jitter_seconds(f"entry{i}") for i in range(500)}
    assert values <= set(range(SCHEDULE_JITTER_MAX_SECONDS + 1))
    assert len(values) > 30  # actually spread out
    assert _install_jitter_seconds("abc") == _install_jitter_seconds("abc")


@pytest.mark.parametrize(
    ("jitter", "evening", "midnight"),
    [(0, (17, 30, 0), (0, 5, 0)), (45, (17, 30, 45), (0, 5, 45))],
)
async def test_schedules_apply_install_jitter(
    hass: HomeAssistant, mock_petrol_lu, jitter, evening, midnight
) -> None:
    tracker = MagicMock()
    with (
        patch(f"{_COORD}._install_jitter_seconds", return_value=jitter),
        patch(f"{_COORD}.async_track_time_change", tracker),
    ):
        entry = await _setup(hass)
    armed = {
        call.args[1].__name__: (
            call.kwargs["hour"],
            call.kwargs["minute"],
            call.kwargs["second"],
        )
        for call in tracker.call_args_list
    }
    assert armed["_async_evening_trigger"] == evening
    assert armed["_async_midnight_trigger"] == midnight
    await _unload(hass, entry)


async def test_all_implausible_announcement_reports_implausible(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(
        price_entries, sheet_payload=_sheet(tomorrow, "18.65", "17.92", "19.83")
    )

    entry = await _setup(hass)
    status = entry.runtime_data.announcement_status["live_sheet"]
    assert status["outcome"] == "implausible"
    assert status["rejected"] == 3

    await _unload(hass, entry)
