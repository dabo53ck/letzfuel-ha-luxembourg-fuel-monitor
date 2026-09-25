"""Announcement source: a public live price sheet (JSON).

The sheet lists every published maximum price (incl. VAT) as one row per
effective date and is usually updated on the evening the change is announced.
Like the other announcement sources it is only used for future-dated rows,
and a failure here never breaks the provider update.

Undocumented third-party feed: keep it optional and fail soft.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from aiohttp import ClientError, ClientSession

from ..const import USER_AGENT_VERSION, VAT_RATE_LU
from ..models import FuelType, PricePoint
from .announcements import AnnouncementResult
from .base import ProviderConnectionError, ProviderParseError

LIVE_SHEET_URL = "https://live-data.jifo.co/a3c240af-d4a8-4f7d-933b-14167f9a0d4b"
_USER_AGENT = (
    f"HomeAssistant-LetzFuelHA/{USER_AGENT_VERSION} "
    "(+https://github.com/dabo53ck/letzfuel-ha-luxembourg-fuel-monitor)"
)
_REQUEST_TIMEOUT = 20
_VAT_DECIMAL = Decimal("1") + Decimal(str(VAT_RATE_LU))
_DATE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")

# Header substrings -> fuel. Check "98"/"95" before the generic term.
_HEADER_MATCHERS: tuple[tuple[str, FuelType], ...] = (
    ("98", FuelType.SP98),
    ("95", FuelType.SP95),
    ("diesel", FuelType.DIESEL),
)


class LiveSheetAnnouncements:
    """Reads announced next-day prices from the live price sheet."""

    key = "live_sheet"

    def __init__(self, session: ClientSession) -> None:
        """Store the shared aiohttp session."""
        self._session = session

    async def async_fetch(self, today: date) -> AnnouncementResult:
        """Fetch the sheet and return its future-dated rows."""
        return parse_sheet(await self._async_fetch(), today)

    async def _async_fetch(self) -> dict:
        """GET the sheet JSON."""
        try:
            async with self._session.get(
                LIVE_SHEET_URL,
                headers={"User-Agent": _USER_AGENT},
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                if response.status != 200:
                    raise ProviderConnectionError(
                        f"live sheet returned HTTP {response.status}"
                    )
                body = await response.text()
        except (ClientError, TimeoutError) as err:
            raise ProviderConnectionError(f"Could not reach live sheet: {err}") from err

        try:
            data = json.loads(body)
        except ValueError as err:
            raise ProviderParseError(
                f"live sheet response was not valid JSON: {err}"
            ) from err
        if not isinstance(data, dict):
            raise ProviderParseError("live sheet response was not a JSON object")
        return data


def parse_sheet(data: dict, today: date) -> AnnouncementResult:
    """Turn the sheet payload into an :class:`AnnouncementResult`.

    Pure function -- unit tested directly.
    """
    try:
        rows = data["data"][0]
    except (KeyError, IndexError, TypeError) as err:
        raise ProviderParseError("live sheet: no data table") from err
    if not isinstance(rows, list):
        raise ProviderParseError("live sheet: data table is not a list")

    columns = _resolve_columns(rows)
    latest: date | None = None
    points: list[PricePoint] = []
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        day = _parse_date(row[0])
        if day is None:
            continue
        latest = day if latest is None else max(latest, day)
        if day <= today:
            continue
        for fuel, index in columns.items():
            incl = _parse_price(row[index]) if index < len(row) else None
            if incl is None:
                continue
            points.append(
                PricePoint(
                    effective_date=day,
                    fuel=fuel,
                    price_incl_vat=incl,
                    price_excl_vat=(incl / _VAT_DECIMAL).quantize(Decimal("0.0001")),
                )
            )
    return AnnouncementResult(latest_date=latest, points=points)


def _resolve_columns(rows: list) -> dict[FuelType, int]:
    """Map each fuel to its column index from the ``Date`` header row."""
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        if str(row[0]).strip().lower() != "date":
            continue
        resolved: dict[FuelType, int] = {}
        for idx, cell in enumerate(row[1:], start=1):
            text = str(cell).lower()
            for needle, fuel in _HEADER_MATCHERS:
                if needle in text and fuel not in resolved:
                    resolved[fuel] = idx
                    break
        if FuelType.DIESEL in resolved:
            return resolved
    raise ProviderParseError("live sheet: header row not recognised")


def _parse_date(value: object) -> date | None:
    """Parse a ``DD.MM.YYYY`` cell, or return None."""
    match = _DATE_RE.match(str(value))
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_price(value: object) -> Decimal | None:
    """Parse a ``"2.095 €"`` cell; blanks and junk yield None."""
    cleaned = str(value).replace("€", "").replace("\xa0", "").replace(" ", "")
    if not cleaned:
        return None
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        price = Decimal(cleaned)
    except InvalidOperation:
        return None
    return price if price.is_finite() and price > 0 else None
