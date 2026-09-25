"""Tests for the shared announcement helpers (plausibility, merge rule)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from custom_components.letzfuel_ha.const import ANNOUNCE_MAX_DAYS_AHEAD
from custom_components.letzfuel_ha.models import FuelType, PricePoint
from custom_components.letzfuel_ha.providers.announcements import (
    current_prices,
    merge_announced,
    split_plausible,
)

D = Decimal
TODAY = date(2026, 9, 24)
TOMORROW = TODAY + timedelta(days=1)


def _pt(day: date, price: str, fuel: FuelType = FuelType.DIESEL) -> PricePoint:
    return PricePoint(day, fuel, D(price), D(price))


def test_current_prices_ignores_future_rows() -> None:
    history = [
        _pt(TODAY - timedelta(days=3), "2.000"),
        _pt(TODAY, "2.055"),
        _pt(TOMORROW, "2.095"),
        _pt(TODAY, "1.835", FuelType.SP95),
    ]
    assert current_prices(history, TODAY) == {
        FuelType.DIESEL: D("2.055"),
        FuelType.SP95: D("1.835"),
    }


def test_split_plausible() -> None:
    current = {FuelType.DIESEL: D("2.055")}
    good = _pt(TOMORROW, "2.095")
    too_high = _pt(TOMORROW, "2.500")  # +21.7 %
    too_low = _pt(TOMORROW, "1.700")  # -17.3 %
    today_row = _pt(TODAY, "2.095")
    too_far = _pt(TODAY + timedelta(days=ANNOUNCE_MAX_DAYS_AHEAD + 1), "2.095")
    zero = _pt(TOMORROW, "0")
    # no current price known for SP95 -> only the date check applies
    unknown_fuel = _pt(TOMORROW, "9.999", FuelType.SP95)

    kept, rejected = split_plausible(
        [good, too_high, too_low, today_row, too_far, zero, unknown_fuel],
        current,
        TODAY,
    )

    assert kept == [good, unknown_fuel]
    assert rejected == [too_high, too_low, today_row, too_far, zero]


def test_merge_adds_new_points() -> None:
    history = [_pt(TODAY, "2.055")]
    merged, conflicts = merge_announced(history, [("a", [_pt(TOMORROW, "2.095")])])

    assert merged == [*history, _pt(TOMORROW, "2.095")]
    assert conflicts == []


def test_merge_history_wins_over_sources() -> None:
    history = [_pt(TODAY, "2.055"), _pt(TOMORROW, "2.095")]
    merged, conflicts = merge_announced(history, [("a", [_pt(TOMORROW, "2.105")])])

    assert merged == history
    assert len(conflicts) == 1
    assert conflicts[0].kept == D("2.095")
    assert conflicts[0].ignored == D("2.105")
    assert conflicts[0].ignored_source == "a"


def test_merge_earlier_source_wins() -> None:
    history = [_pt(TODAY, "2.055")]
    merged, conflicts = merge_announced(
        history,
        [
            ("a", [_pt(TOMORROW, "2.095")]),
            ("b", [_pt(TOMORROW, "2.090"), _pt(TOMORROW, "1.835", FuelType.SP95)]),
        ],
    )

    assert merged == [
        *history,
        _pt(TOMORROW, "2.095"),
        _pt(TOMORROW, "1.835", FuelType.SP95),
    ]
    assert [(c.ignored_source, c.ignored) for c in conflicts] == [("b", D("2.090"))]


def test_merge_same_price_is_not_a_conflict() -> None:
    history = [_pt(TOMORROW, "2.095")]
    merged, conflicts = merge_announced(history, [("a", [_pt(TOMORROW, "2.095")])])

    assert merged == history
    assert conflicts == []
