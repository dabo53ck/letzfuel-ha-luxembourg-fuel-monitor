"""Backup announcement source: a published national maximum price set.

``BACKUP_FEED_URL`` returns the most recently
*published* Luxembourg maximum prices (incl. VAT) together with the date they
take effect. When the Ministry announces a change for the next day -- around
18:00 the evening before -- this endpoint carries it several hours before
petrol.lu does.

petrol.lu stays the source of truth for the current price and the full history;
this module only supplies the announced (future-dated) price, and is asked only
while the primary announcement feed is unusable. The price is merged into the
coordinator's price history so the existing ``has_pending_change`` /
``EVENT_PRICE_CHANGE_ANNOUNCED`` logic can act on it.

Undocumented third-party JSON API: keep it optional, fail soft, and never let a
failure here break the petrol.lu update.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from aiohttp import ClientError, ClientSession
from homeassistant.util import dt as dt_util

from ..const import LU_TIME_ZONE, USER_AGENT, VAT_DIVISOR
from ..models import FuelType, PricePoint
from .announcements import AnnouncementResult
from .base import ProviderConnectionError, ProviderParseError

BACKUP_FEED_URL = "https://api-gate.rtl.lu/fuel-prices/current"
_REQUEST_TIMEOUT = 20

#: Feed JSON key -> fuel. The feed only publishes prices incl. VAT.
_FUEL_KEYS: dict[str, FuelType] = {
    "diesel": FuelType.DIESEL,
    "95oct": FuelType.SP95,
    "98oct": FuelType.SP98,
}


class BackupFeedAnnouncements:
    """Reads the announced next-day price set from the backup feed."""

    key = "backup_feed"

    def __init__(self, session: ClientSession) -> None:
        """Store the shared aiohttp session."""
        self._session = session

    async def async_fetch(self, today: date) -> AnnouncementResult:
        """Fetch the payload; report its effective date and any future points."""
        data = await self._async_fetch()
        latest = parse_effective_date(data)
        points = parse_announced(data, today)
        return AnnouncementResult(
            latest_date=latest,
            points=points,
            rows={latest: {p.fuel: p.price_incl_vat for p in points}} if points else {},
        )

    async def _async_fetch(self) -> dict:
        """GET the current price JSON."""
        try:
            async with self._session.get(
                BACKUP_FEED_URL,
                headers={"User-Agent": USER_AGENT},
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                if response.status != 200:
                    raise ProviderConnectionError(
                        f"Backup feed returned HTTP {response.status}"
                    )
                body = await response.text()
        except (ClientError, TimeoutError) as err:
            raise ProviderConnectionError(
                f"Could not reach the backup feed: {err}"
            ) from err

        try:
            data = json.loads(body)
        except ValueError as err:
            raise ProviderParseError(
                f"Backup feed response was not valid JSON: {err}"
            ) from err
        if not isinstance(data, dict):
            raise ProviderParseError("Backup feed response was not a JSON object")
        return data


def parse_announced(data: dict, today: date) -> list[PricePoint]:
    """Turn the backup feed payload into future-dated price points.

    Pure function -- unit tested directly. Returns ``[]`` when the payload's
    effective date is today or earlier (the feed is then merely mirroring the price
    that is already in effect).
    """
    effective = parse_effective_date(data)
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
            raise ProviderParseError(
                f"Backup feed: bad price for {key}: {value!r}"
            ) from err
        if incl <= 0:
            continue
        excl = (incl / VAT_DIVISOR).quantize(Decimal("0.0001"))
        points.append(
            PricePoint(
                effective_date=effective,
                fuel=fuel,
                price_incl_vat=incl,
                price_excl_vat=excl,
            )
        )
    return points


def parse_effective_date(data: dict) -> date:
    """Return the payload's effective date as a Luxembourg calendar date.

    Converted to Luxembourg time first, so a UTC timestamp for midnight there
    (``...T22:00:00Z`` in summer) still maps to the right day, whatever time
    zone Home Assistant runs in.
    """
    raw_date = data.get("date")
    parsed = dt_util.parse_datetime(str(raw_date)) if raw_date else None
    if parsed is None:
        raise ProviderParseError(
            f"Backup feed: unparseable effective date {raw_date!r}"
        )
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt_util.get_time_zone(LU_TIME_ZONE))
    return parsed.date()
