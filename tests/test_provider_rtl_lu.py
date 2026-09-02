"""Tests for the RTL.lu announcement source."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.letzfuel_ha.models import FuelType
from custom_components.letzfuel_ha.providers.base import (
    ProviderConnectionError,
    ProviderParseError,
)
from custom_components.letzfuel_ha.providers.rtl_lu import (
    RTL_CURRENT_URL,
    RtlLuAnnouncements,
    parse_announced,
)

TODAY = date(2026, 9, 2)


def _payload(day: str, **overrides: object) -> dict:
    return {
        "id": 2132,
        "date": f"{day}T00:00:00+02:00",
        "98oct": 1.983,
        "95oct": 1.792,
        "diesel": 2.024,
        **overrides,
    }


def test_parse_future_date_yields_points() -> None:
    by_fuel = {p.fuel: p for p in parse_announced(_payload("2026-09-03"), TODAY)}

    assert set(by_fuel) == {FuelType.DIESEL, FuelType.SP95, FuelType.SP98}
    diesel = by_fuel[FuelType.DIESEL]
    assert diesel.effective_date == date(2026, 9, 3)
    assert diesel.price_incl_vat == Decimal("2.024")
    # excl. VAT derived at the 17 % LU rate
    assert diesel.price_excl_vat == Decimal("1.7299")


def test_parse_today_or_past_yields_nothing() -> None:
    assert parse_announced(_payload("2026-09-02"), TODAY) == []
    assert parse_announced(_payload("2026-09-01"), TODAY) == []


def test_parse_bad_date_raises() -> None:
    with pytest.raises(ProviderParseError):
        parse_announced({"date": "not-a-date", "diesel": 2.0}, TODAY)


def test_parse_skips_missing_and_nonpositive_fuels() -> None:
    points = parse_announced(
        {
            "date": "2026-09-03T00:00:00+02:00",
            "diesel": 2.024,
            "95oct": 0,
            "98oct": None,
        },
        TODAY,
    )
    assert [p.fuel for p in points] == [FuelType.DIESEL]


async def test_fetch_http_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(RTL_CURRENT_URL, status=503)
    src = RtlLuAnnouncements(async_get_clientsession(hass))

    with pytest.raises(ProviderConnectionError):
        await src.async_get_announced_points(TODAY)


async def test_fetch_ok(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(RTL_CURRENT_URL, json=_payload("2026-09-03"))
    src = RtlLuAnnouncements(async_get_clientsession(hass))

    points = await src.async_get_announced_points(TODAY)
    assert {p.fuel for p in points} == {
        FuelType.DIESEL,
        FuelType.SP95,
        FuelType.SP98,
    }
