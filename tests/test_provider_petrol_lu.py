"""Tests for the petrol.lu provider parser."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from homeassistant.util import dt as dt_util

from custom_components.letzfuel_ha.models import FuelType
from custom_components.letzfuel_ha.providers.base import (
    ProviderParseError,
    build_price_set,
)
from custom_components.letzfuel_ha.providers.petrol_lu import (
    PetrolLuProvider,
    _parse_decimal,
    _parse_history,
)

from .helpers import build_petrol_lu_html

SAMPLE = (Path(__file__).parent / "fixtures" / "petrol_lu_sample.html").read_text(
    encoding="utf-8"
)


def test_parse_sample_html() -> None:
    points = _parse_history(SAMPLE)

    diesel = {
        p.effective_date: p for p in points if p.fuel is FuelType.DIESEL
    }
    assert diesel[date(2026, 9, 1)].price_incl_vat == Decimal("1.865")
    assert diesel[date(2026, 9, 1)].price_excl_vat == Decimal("1.5940")
    assert diesel[date(2026, 8, 18)].price_incl_vat == Decimal("1.840")

    # Heating-oil columns are blank ("-") and must be ignored, not crash.
    assert all(p.fuel in set(FuelType) for p in points)


def test_parse_no_table_raises() -> None:
    with pytest.raises(ProviderParseError):
        _parse_history("<html><body><p>nothing here</p></body></html>")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.865", Decimal("1.865")),
        ("1,865", Decimal("1.865")),
        ("1 865,5", Decimal("1865.5")),
        ("€1.75", Decimal("1.75")),
        ("-", None),
        ("", None),
        ("n/a", None),
    ],
)
def test_parse_decimal(raw: str, expected: Decimal | None) -> None:
    assert _parse_decimal(raw) == expected


def test_build_price_set_resolves_current_previous_upcoming() -> None:
    today = dt_util.now().date()
    entries = [
        (today - timedelta(days=10), {FuelType.DIESEL: (Decimal("1.80"), Decimal("1.54"))}),
        (today, {FuelType.DIESEL: (Decimal("1.86"), Decimal("1.59"))}),
        (today + timedelta(days=1), {FuelType.DIESEL: (Decimal("1.90"), Decimal("1.62"))}),
    ]
    points = _parse_history(build_petrol_lu_html(entries))

    price_set = build_price_set(points, [FuelType.DIESEL], PetrolLuProvider(None))
    fp = price_set.prices[FuelType.DIESEL]

    assert fp.current.price_incl_vat == Decimal("1.86")
    assert fp.previous.price_incl_vat == Decimal("1.80")
    assert fp.current_since == today
    assert fp.upcoming.price_incl_vat == Decimal("1.90")
    assert fp.has_pending_change is True


def test_build_price_set_no_pending_change_when_equal() -> None:
    today = dt_util.now().date()
    entries = [
        (today, {FuelType.DIESEL: (Decimal("1.86"), Decimal("1.59"))}),
        (today + timedelta(days=1), {FuelType.DIESEL: (Decimal("1.86"), Decimal("1.59"))}),
    ]
    points = _parse_history(build_petrol_lu_html(entries))
    price_set = build_price_set(points, [FuelType.DIESEL], PetrolLuProvider(None))
    assert price_set.prices[FuelType.DIESEL].has_pending_change is False
