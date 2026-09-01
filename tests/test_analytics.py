"""Tests for the pure analytics helpers."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from homeassistant.util import dt as dt_util

from custom_components.letzfuel_ha.analytics import (
    compute_trend,
    refuel_recommendation,
)
from custom_components.letzfuel_ha.const import (
    RECOMMENDATION_NO_CHANGE,
    RECOMMENDATION_REFUEL_TODAY,
    RECOMMENDATION_UNKNOWN,
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
    assert refuel_recommendation(_fp("1.80", None)) == RECOMMENDATION_UNKNOWN
    assert refuel_recommendation(None) == RECOMMENDATION_UNKNOWN
