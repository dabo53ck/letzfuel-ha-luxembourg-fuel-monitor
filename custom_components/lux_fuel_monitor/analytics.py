"""Pure analytics helpers (trend, refuel recommendation).

Kept free of Home Assistant imports (except ``dt`` for "today") so they are easy
to unit test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from homeassistant.util import dt as dt_util

from .const import (
    RECOMMENDATION_NO_CHANGE,
    RECOMMENDATION_REFUEL_TODAY,
    RECOMMENDATION_UNKNOWN,
    RECOMMENDATION_WAIT,
    TREND_FALLING,
    TREND_RISING,
    TREND_STABLE,
    TREND_STABLE_THRESHOLD_EUR,
)
from .models import FuelPrices, PricePoint


@dataclass(frozen=True, slots=True)
class TrendResult:
    """Outcome of a trend calculation over a rolling window."""

    state: str
    #: Signed slope expressed as EUR/L per week (None when not enough samples).
    strength_per_week: float | None
    samples: int
    window_start: date | None
    window_end: date | None


def _linreg_slope(xs: list[float], ys: list[float]) -> float:
    """Ordinary least-squares slope; 0.0 when x has no variance."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return numerator / denominator


def compute_trend(
    points: list[PricePoint],
    window_days: int,
    *,
    use_incl_vat: bool = True,
) -> TrendResult:
    """Classify the price trend over the last ``window_days`` days."""
    today = dt_util.now().date()
    start = today - timedelta(days=window_days)
    window = sorted(
        (p for p in points if start <= p.effective_date <= today),
        key=lambda p: p.effective_date,
    )
    if len(window) < 2:
        return TrendResult(TREND_STABLE, None, len(window), None, None)

    origin = window[0].effective_date
    xs = [float((p.effective_date - origin).days) for p in window]
    ys = [
        float(p.price_incl_vat if use_incl_vat else p.price_excl_vat) for p in window
    ]
    slope_per_day = _linreg_slope(xs, ys)
    projected = slope_per_day * window_days

    if abs(projected) < TREND_STABLE_THRESHOLD_EUR:
        state = TREND_STABLE
    elif slope_per_day > 0:
        state = TREND_RISING
    else:
        state = TREND_FALLING

    return TrendResult(
        state=state,
        strength_per_week=round(slope_per_day * 7, 5),
        samples=len(window),
        window_start=window[0].effective_date,
        window_end=window[-1].effective_date,
    )


def refuel_recommendation(fuel_prices: FuelPrices | None) -> str:
    """Advise whether to refuel today based on the announced next-day price."""
    if fuel_prices is None:
        return RECOMMENDATION_UNKNOWN
    if fuel_prices.upcoming is None:
        return RECOMMENDATION_UNKNOWN
    delta = fuel_prices.upcoming.price_incl_vat - fuel_prices.current.price_incl_vat
    if delta > 0:
        return RECOMMENDATION_REFUEL_TODAY
    if delta < 0:
        return RECOMMENDATION_WAIT
    return RECOMMENDATION_NO_CHANGE
