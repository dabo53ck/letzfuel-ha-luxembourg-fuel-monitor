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
    LATE_EVENING_POLL_MINUTES,
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


# -- multiple announcement sources ---------------------------------------------


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


async def test_sheet_announces_when_rtl_is_stale(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    """The 2026-09-24 case: RTL keeps listing today, the sheet has tomorrow."""
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(
        price_entries,
        sheet_payload=sheet_json([(tomorrow, {FuelType.DIESEL: "1.905"})]),
    )

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    fp = coordinator.fuel_prices(FuelType.DIESEL)
    assert fp.upcoming is not None
    assert fp.upcoming.effective_date == tomorrow
    assert fp.upcoming.price_incl_vat == Decimal("1.905")
    assert fp.has_pending_change

    status = coordinator.announcement_status
    assert status["rtl_lu"]["outcome"] == "nothing_future"
    assert status["rtl_lu"]["latest_date"] == dt_util.now().date().isoformat()
    assert status["live_sheet"]["outcome"] == "announced"
    assert status["live_sheet"]["latest_date"] == tomorrow.isoformat()

    await _unload(hass, entry)


async def test_provider_row_wins_over_announcement(
    hass: HomeAssistant, mock_petrol_lu, price_entries, caplog
) -> None:
    tomorrow = dt_util.now().date() + timedelta(days=1)
    entries = [
        *price_entries,
        (tomorrow, {FuelType.DIESEL: (Decimal("1.900"), Decimal("1.624"))}),
    ]
    mock_petrol_lu(entries, rtl_payload=_rtl(tomorrow, 1.950))

    entry = await _setup(hass)
    fp = entry.runtime_data.fuel_prices(FuelType.DIESEL)
    assert fp.upcoming.price_incl_vat == Decimal("1.900")
    assert "Conflicting announced diesel price" in caplog.text
    assert "ignored 1.95 from rtl_lu" in caplog.text

    await _unload(hass, entry)


async def test_rtl_wins_over_sheet_and_conflict_logged_once(
    hass: HomeAssistant, mock_petrol_lu, price_entries, caplog
) -> None:
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(
        price_entries,
        rtl_payload=_rtl(tomorrow, 1.905),
        sheet_payload=sheet_json([(tomorrow, {FuelType.DIESEL: "1.915"})]),
    )

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.fuel_prices(FuelType.DIESEL).upcoming.price_incl_vat == Decimal(
        "1.905"
    )

    await coordinator.async_refresh()
    assert caplog.text.count("ignored 1.915 from live_sheet") == 1

    await _unload(hass, entry)


async def test_implausible_announcement_is_ignored(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(
        price_entries,
        sheet_payload=sheet_json([(tomorrow, {FuelType.DIESEL: "18.65"})]),
    )

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.fuel_prices(FuelType.DIESEL).upcoming is None
    assert coordinator.announcement_status["live_sheet"]["outcome"] == "implausible"
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

    await _unload(hass, entry)


async def test_announcements_option_disables_every_source(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(
        price_entries,
        rtl_payload=_rtl(tomorrow, 1.905),
        sheet_payload=sheet_json([(tomorrow, {FuelType.DIESEL: "1.905"})]),
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
        await coordinator._async_evening_trigger(_local(18, 1))

    uniform.assert_called_with(*LATE_EVENING_POLL_MINUTES)
    times = [call.args[2] for call in tracker.call_args_list]
    # the fixed retries, then the first late poll 25 min after the last one
    assert times[:-1] == [
        _local(18, 1) + timedelta(minutes=m) for m in EVENING_RETRY_OFFSETS_MINUTES
    ]
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
            sheet_payload=sheet_json([(tomorrow, {FuelType.DIESEL: "1.905"})]),
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
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(price_entries, rtl_payload=_rtl(tomorrow, 1.865))
    tracker = MagicMock()
    with patch(f"{_COORD}.async_track_point_in_time", tracker):
        await coordinator._async_evening_trigger(_local(18, 1))
        # no pending change -> the fixed retries are still armed ...
        assert tracker.call_count == len(EVENING_RETRY_OFFSETS_MINUTES)
        # ... but no late-evening polling on top
        assert coordinator._late_poll_unsub is None

        await coordinator._async_late_poll(_local(19))
        assert tracker.call_count == len(EVENING_RETRY_OFFSETS_MINUTES)
    coordinator._retry_unsubs.clear()


async def test_unexpected_source_error_is_non_fatal(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    """Garbage that isn't a ProviderError must not break the update either."""
    mock_petrol_lu(
        price_entries,
        rtl_payload={"id": 1, "date": "2026-13-45T00:00:00+02:00", "diesel": 2.0},
    )

    entry = await _setup(hass)
    coordinator = entry.runtime_data
    assert coordinator.last_update_success
    assert coordinator.announcement_status["rtl_lu"]["outcome"] == "error"
    assert coordinator.announcement_status["live_sheet"]["outcome"] == (
        "nothing_future"
    )

    await _unload(hass, entry)
