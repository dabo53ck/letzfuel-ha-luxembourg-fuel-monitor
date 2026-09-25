"""Tests for the live sheet announcement source."""

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
from custom_components.letzfuel_ha.providers.live_sheet import (
    LIVE_SHEET_URL,
    LiveSheetAnnouncements,
    parse_sheet,
)

from .helpers import sheet_json

TODAY = date(2026, 9, 24)
TOMORROW = date(2026, 9, 25)


def _payload() -> dict:
    return sheet_json(
        [
            (
                date(2026, 9, 23),
                {
                    FuelType.SP95: "1.849",
                    FuelType.SP98: "2.075",
                    FuelType.DIESEL: "2.055",
                },
            ),
            (
                TODAY,
                {
                    FuelType.SP95: "1.835",
                    FuelType.SP98: "2.059",
                    FuelType.DIESEL: "2.055",
                },
            ),
            (
                TOMORROW,
                {
                    FuelType.SP95: "1.835",
                    FuelType.SP98: "2.059",
                    FuelType.DIESEL: "2.095",
                },
            ),
        ]
    )


def test_parse_future_rows_yield_points() -> None:
    result = parse_sheet(_payload(), TODAY)

    assert result.latest_date == TOMORROW
    by_fuel = {p.fuel: p for p in result.points}
    assert set(by_fuel) == {FuelType.DIESEL, FuelType.SP95, FuelType.SP98}
    diesel = by_fuel[FuelType.DIESEL]
    assert diesel.effective_date == TOMORROW
    assert diesel.price_incl_vat == Decimal("2.095")
    # excl. VAT derived at the 17 % LU rate
    assert diesel.price_excl_vat == Decimal("1.7906")


def test_parse_nothing_future() -> None:
    result = parse_sheet(_payload(), TOMORROW)

    assert result.latest_date == TOMORROW
    assert result.points == []


def _row(day: date, diesel: str, sp95: str = "1.835", sp98: str = "2.059") -> tuple:
    return (day, {FuelType.DIESEL: diesel, FuelType.SP95: sp95, FuelType.SP98: sp98})


def test_parse_skips_incomplete_rows() -> None:
    """The editors add the row first and fill the prices in one by one."""
    payload = sheet_json([_row(TODAY, "2.055")])
    rows = payload["data"][0]
    rows.append(["25.09.2026", "", "", "", ""])  # row created, still empty
    rows.append(["26.09.2026", "1.888 €", "", "", ""])  # only SP95 so far
    rows.append(["27.09.2026", "n/a", "NaN", "0", ""])  # junk
    rows.append(["not a date", "1.000 €", "1.000 €", "1.000 €", ""])

    result = parse_sheet(payload, TODAY)

    assert result.points == []
    assert result.latest_date == TODAY


def test_parse_complete_row_after_filling() -> None:
    payload = sheet_json([_row(TODAY, "2.055"), _row(TOMORROW, "2.095")])

    result = parse_sheet(payload, TODAY)

    assert result.latest_date == TOMORROW
    assert {p.fuel for p in result.points} == set(FuelType)


def test_parse_comma_decimal() -> None:
    payload = sheet_json([_row(TOMORROW, "2,095", "1,835", "2,059")])

    by_fuel = {p.fuel: p for p in parse_sheet(payload, TODAY).points}
    assert by_fuel[FuelType.DIESEL].price_incl_vat == Decimal("2.095")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"data": [None]},
        {"data": [[["Foo", "Bar"], ["25.09.2026", "1.0"]]]},
    ],
)
def test_parse_unusable_payload_raises(payload: dict) -> None:
    with pytest.raises(ProviderParseError):
        parse_sheet(payload, TODAY)


async def test_fetch_ok(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(LIVE_SHEET_URL, json=_payload())
    src = LiveSheetAnnouncements(async_get_clientsession(hass))

    result = await src.async_fetch(TODAY)
    assert result.latest_date == TOMORROW
    assert len(result.points) == 3


async def test_fetch_http_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(LIVE_SHEET_URL, status=503)
    src = LiveSheetAnnouncements(async_get_clientsession(hass))

    with pytest.raises(ProviderConnectionError):
        await src.async_fetch(TODAY)


async def test_fetch_bad_json(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(LIVE_SHEET_URL, text="<html>nope</html>")
    src = LiveSheetAnnouncements(async_get_clientsession(hass))

    with pytest.raises(ProviderParseError):
        await src.async_fetch(TODAY)


async def test_fetch_non_object_json(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    aioclient_mock.get(LIVE_SHEET_URL, json=[1, 2, 3])
    src = LiveSheetAnnouncements(async_get_clientsession(hass))

    with pytest.raises(ProviderParseError):
        await src.async_fetch(TODAY)
