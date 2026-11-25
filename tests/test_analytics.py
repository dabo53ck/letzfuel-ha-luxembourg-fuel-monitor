"""Tests for the pure analytics helpers."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from homeassistant.util import dt as dt_util

from custom_components.letzfuel_ha.analytics import (
    compute_trend,
    drops_in_a_row,
    price_drop_today,
    refuel_recommendation,
)
from custom_components.letzfuel_ha.const import (
    RECOMMENDATION_AWAITING_PRICE,
    RECOMMENDATION_NO_CHANGE,
    RECOMMENDATION_PRICE_DROPPED,
    RECOMMENDATION_REFUEL_TODAY,
    RECOMMENDATION_WAIT,
    TREND_FALLING,
    TREND_RISING,
    TREND_STABLE,
)
from custom_components.letzfuel_ha.models import FuelPrices, FuelType, PricePoint


def _points(values: list[float]):
    today = dt_util.now().date()
    n = len(values)
    return [
        PricePoint(
            effective_date=today - timedelta(days=(n - 1 - i)),
            fuel=FuelType.DIESEL,
            price_incl_vat=Decimal(str(v)),
            price_excl_vat=Decimal(str(v)),
        )
        for i, v in enumerate(values)
    ]


def test_trend_rising() -> None:
    result = compute_trend(_points([1.70, 1.75, 1.80, 1.85]), window_days=14)
    assert result.state == TREND_RISING
    assert result.strength_per_week > 0
    assert result.samples == 4


def test_trend_falling() -> None:
    result = compute_trend(_points([1.90, 1.85, 1.80, 1.75]), window_days=14)
    assert result.state == TREND_FALLING


def test_trend_stable() -> None:
    result = compute_trend(_points([1.800, 1.801, 1.799, 1.800]), window_days=14)
    assert result.state == TREND_STABLE


def test_trend_insufficient_samples() -> None:
    result = compute_trend(_points([1.80]), window_days=14)
    assert result.state == TREND_STABLE
    assert result.strength_per_week is None


def _fp(current: str, upcoming: str | None) -> FuelPrices:
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
    return FuelPrices(FuelType.DIESEL, cur, today, None, up)


def test_recommendation() -> None:
    assert refuel_recommendation(_fp("1.80", "1.85")) == RECOMMENDATION_REFUEL_TODAY
    assert refuel_recommendation(_fp("1.80", "1.75")) == RECOMMENDATION_WAIT
    assert refuel_recommendation(_fp("1.80", "1.80")) == RECOMMENDATION_NO_CHANGE
    assert refuel_recommendation(_fp("1.80", None)) == RECOMMENDATION_AWAITING_PRICE
    assert refuel_recommendation(None) == RECOMMENDATION_AWAITING_PRICE


def _dropped(previous: str, current: str, since_days_ago: int = 0) -> FuelPrices:
    """Today's price, set ``since_days_ago``, after ``previous``; nothing announced."""
    today = dt_util.now().date()
    since = today - timedelta(days=since_days_ago)
    cur = PricePoint(since, FuelType.DIESEL, Decimal(current), Decimal(current))
    prev = PricePoint(
        since - timedelta(days=3), FuelType.DIESEL, Decimal(previous), Decimal(previous)
    )
    return FuelPrices(FuelType.DIESEL, cur, since, prev, None)


def test_price_dropped_until_tomorrow_is_known() -> None:
    assert price_drop_today(_dropped("1.90", "1.85")) == Decimal("0.05")
    assert refuel_recommendation(_dropped("1.90", "1.85")) == (
        RECOMMENDATION_PRICE_DROPPED
    )
    # went up, or changed on an earlier day: just waiting for the new price
    assert price_drop_today(_dropped("1.80", "1.85")) is None
    assert refuel_recommendation(_dropped("1.80", "1.85")) == (
        RECOMMENDATION_AWAITING_PRICE
    )
    assert price_drop_today(_dropped("1.90", "1.85", since_days_ago=1)) is None
    assert refuel_recommendation(_dropped("1.90", "1.85", since_days_ago=1)) == (
        RECOMMENDATION_AWAITING_PRICE
    )


def test_recommendation_minimum_difference() -> None:
    assert refuel_recommendation(_fp("1.80", "1.805"), 0.01) == (
        RECOMMENDATION_NO_CHANGE
    )
    assert refuel_recommendation(_fp("1.80", "1.795"), 0.01) == (
        RECOMMENDATION_NO_CHANGE
    )
    assert refuel_recommendation(_fp("1.80", "1.81"), 0.01) == (
        RECOMMENDATION_REFUEL_TODAY
    )
    assert refuel_recommendation(_fp("1.80", "1.79"), 0.01) == RECOMMENDATION_WAIT
    assert refuel_recommendation(_dropped("1.90", "1.895"), 0.01) == (
        RECOMMENDATION_AWAITING_PRICE
    )
    assert refuel_recommendation(_dropped("1.90", "1.89"), 0.01) == (
        RECOMMENDATION_PRICE_DROPPED
    )


def test_drops_in_a_row() -> None:
    assert drops_in_a_row(_points([1.90, 1.88, 1.88, 1.86, 1.85])) == 3
    assert drops_in_a_row(_points([1.80, 1.90, 1.85])) == 1
    assert drops_in_a_row(_points([1.90, 1.85, 1.86])) == 0
    assert drops_in_a_row(_points([1.85])) == 0
    # an announced price for tomorrow does not count yet
    tomorrow = PricePoint(
        dt_util.now().date() + timedelta(days=1),
        FuelType.DIESEL,
        Decimal("1.80"),
        Decimal("1.80"),
    )
    assert drops_in_a_row([*_points([1.90, 1.85]), tomorrow]) == 1
