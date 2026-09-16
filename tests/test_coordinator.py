"""Tests for the coordinator: setup and change detection / events."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.letzfuel_ha.const import (
    CONF_PRIMARY_FUEL,
    CONF_PROVIDER,
    CONF_TRACKED_FUELS,
    DEFAULT_PROVIDER,
    DOMAIN,
    EVENING_RETRY_OFFSETS_MINUTES,
    EVENT_PRICE_CHANGE_ANNOUNCED,
    EVENT_PRICE_CHANGED,
    ISSUE_PARSE_ERROR,
    ISSUE_STALE_DATA,
    OPT_ANNOUNCEMENTS_ENABLED,
    OPT_HISTORY_IMPORT_ENABLED,
    STALE_AFTER_DAYS,
)
from custom_components.letzfuel_ha.models import (
    FuelPrices,
    FuelType,
    PricePoint,
    PriceSet,
)
from custom_components.letzfuel_ha.providers.base import ProviderParseError


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


async def test_rtl_announcement_drives_pending_change(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    """RTL's announced next-day price populates `upcoming` / pending change.

    petrol.lu's history carries no future row here; the upcoming price can only
    come from the RTL announcement source.
    """
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

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    fp = entry.runtime_data.fuel_prices(FuelType.DIESEL)
    assert fp.upcoming is not None
    assert fp.upcoming.effective_date == tomorrow
    assert fp.upcoming.price_incl_vat == Decimal("2.024")
    assert fp.has_pending_change

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
    """Regression guard: 2 min up to +14, then 5 min up to +29 (see const.py)."""
    assert EVENING_RETRY_OFFSETS_MINUTES == (2, 4, 6, 8, 10, 12, 14, 19, 24, 29)


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
