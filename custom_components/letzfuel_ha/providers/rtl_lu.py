"""Announcement source: RTL.lu's published national maximum price set.

``https://api-gate.rtl.lu/fuel-prices/current`` returns the most recently
*published* Luxembourg maximum prices (incl. VAT) together with the date they
take effect. When the Ministry announces a change for the next day -- around
18:00 the evening before -- this endpoint carries it several hours before
petrol.lu does.

petrol.lu stays the source of truth for the current price and the full history;
this module is used **only** to obtain the announced (future-dated) price, which
is merged into the coordinator's price history so the existing
``has_pending_change`` / ``EVENT_PRICE_CHANGE_ANNOUNCED`` logic can act on it.

Undocumented third-party JSON API: keep it optional, fail soft, and never let a
failure here break the petrol.lu update.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from aiohttp import ClientError, ClientSession
from homeassistant.util import dt as dt_util

from ..const import VAT_RATE_LU
from ..models import FuelType, PricePoint
from .base import ProviderConnectionError, ProviderParseError

RTL_CURRENT_URL = "https://api-gate.rtl.lu/fuel-prices/current"
_USER_AGENT = (
    "HomeAssistant-LetzFuelHA "
    "(+https://github.com/dabo53ck/letzfuel-ha-luxembourg-fuel-monitor)"
)
_REQUEST_TIMEOUT = 20
_VAT_DECIMAL = Decimal("1") + Decimal(str(VAT_RATE_LU))

#: RTL JSON key -> fuel. RTL only publishes prices incl. VAT.
_FUEL_KEYS: dict[str, FuelType] = {
    "diesel": FuelType.DIESEL,
    "95oct": FuelType.SP95,
    "98oct": FuelType.SP98,
}


class RtlLuAnnouncements:
    """Reads the announced next-day price set from RTL.lu."""

    def __init__(self, session: ClientSession) -> None:
        """Store the shared aiohttp session."""
        self._session = session

    async def async_get_announced_points(self, today: date) -> list[PricePoint]:
        """Return future-dated ``PricePoint``s, or ``[]`` when nothing is announced.

        ``today`` is passed in so the caller controls the clock (and tests stay
        deterministic).
        """
        data = await self._async_fetch()
        return parse_announced(data, today)

    async def _async_fetch(self) -> dict:
        """GET the current price JSON."""
        try:
            async with self._session.get(
                RTL_CURRENT_URL,
                headers={"User-Agent": _USER_AGENT},
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                if response.status != 200:
                    raise ProviderConnectionError(
                        f"RTL.lu returned HTTP {response.status}"
                    )
                body = await response.text()
        except (ClientError, TimeoutError) as err:
            raise ProviderConnectionError(f"Could not reach RTL.lu: {err}") from err

        try:
            data = json.loads(body)
        except ValueError as err:
            raise ProviderParseError(f"RTL.lu response was not valid JSON: {err}") from err
        if not isinstance(data, dict):
            raise ProviderParseError("RTL.lu response was not a JSON object")
        return data


def parse_announced(data: dict, today: date) -> list[PricePoint]:
    """Turn the RTL ``/current`` payload into future-dated price points.

    Pure function -- unit tested directly. Returns ``[]`` when the payload's
    effective date is today or earlier (RTL is then merely mirroring the price
    that is already in effect).
    """
    raw_date = data.get("date")
    parsed = dt_util.parse_datetime(str(raw_date)) if raw_date else None
    if parsed is None:
        raise ProviderParseError(f"RTL.lu: unparseable effective date {raw_date!r}")

    effective = parsed.date()
    if effective <= today:
        return []

    points: list[PricePoint] = []
    for key, fuel in _FUEL_KEYS.items():
        value = data.get(key)
        if value is None:
            continue
        try:
            incl = Decimal(str(value))
        except (ArithmeticError, ValueError) as err:
            raise ProviderParseError(f"RTL.lu: bad price for {key}: {value!r}") from err
        if incl <= 0:
            continue
        excl = (incl / _VAT_DECIMAL).quantize(Decimal("0.0001"))
        points.append(
            PricePoint(
                effective_date=effective,
                fuel=fuel,
                price_incl_vat=incl,
                price_excl_vat=excl,
            )
        )
    return points
