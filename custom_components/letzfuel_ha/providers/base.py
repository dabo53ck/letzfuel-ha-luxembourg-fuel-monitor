"""Provider abstraction for Luxembourg fuel price sources.

The integration talks to fuel price sources exclusively through :class:`FuelProvider`.
Adding a new Luxembourg source later (a different scraper, an API, ...) means
implementing one subclass and registering it in ``providers/__init__.py`` -- no changes
to the coordinator or entities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date, timedelta

from homeassistant.util import dt as dt_util

from ..const import RECENT_HISTORY_DAYS
from ..models import FuelPrices, FuelType, PricePoint, PriceSet


class ProviderError(Exception):
    """Base error for provider failures."""


class ProviderConnectionError(ProviderError):
    """The source could not be reached."""


class ProviderParseError(ProviderError):
    """The source was reached but its content could not be understood."""


class FuelProvider(ABC):
    """Interface every fuel price source must implement."""

    #: Stable machine key, used in config data and diagnostics.
    key: str
    #: Human readable source name.
    name: str
    #: Canonical URL of the source (shown as the device ``configuration_url``).
    source_url: str
    #: Attribution string surfaced on every entity.
    attribution: str

    @abstractmethod
    async def async_get_history(self, since: date | None = None) -> list[PricePoint]:
        """Return every known price point, optionally limited to ``since`` onwards.

        Points may be future-dated: Luxembourg publishes the next day's maximum
        prices the evening before they take effect.
        """

    async def async_get_last_update(self) -> date | None:
        """Return the effective date of the most recent (non-future) price change."""
        history = await self.async_get_history()
        today = dt_util.now().date()
        past = sorted(p.effective_date for p in history if p.effective_date <= today)
        return past[-1] if past else None

    async def async_get_current_prices(self, fuels: Iterable[FuelType]) -> PriceSet:
        """Resolve current / previous / upcoming prices for ``fuels``."""
        history = await self.async_get_history()
        return build_price_set(history, fuels, self)


def build_price_set(
    history: list[PricePoint],
    fuels: Iterable[FuelType],
    provider: FuelProvider,
) -> PriceSet:
    """Turn a flat list of price points into a resolved :class:`PriceSet`.

    Pure function -- unit tested directly.
    """
    today = dt_util.now().date()
    recent_cutoff = today - timedelta(days=RECENT_HISTORY_DAYS)

    prices: dict[FuelType, FuelPrices] = {}
    recent: dict[FuelType, list[PricePoint]] = {}

    for fuel in fuels:
        points = sorted(
            (p for p in history if p.fuel == fuel),
            key=lambda p: p.effective_date,
        )
        if not points:
            continue

        past = [p for p in points if p.effective_date <= today]
        future = [p for p in points if p.effective_date > today]
        if not past:
            continue

        current = past[-1]
        current_since = current.effective_date
        previous: PricePoint | None = None
        for point in reversed(past[:-1]):
            if point.price_incl_vat == current.price_incl_vat:
                current_since = point.effective_date
                continue
            previous = point
            break

        upcoming = future[0] if future else None

        prices[fuel] = FuelPrices(
            fuel=fuel,
            current=current,
            current_since=current_since,
            previous=previous,
            upcoming=upcoming,
        )
        recent[fuel] = [p for p in points if p.effective_date >= recent_cutoff]

    return PriceSet(
        fetched_at=dt_util.utcnow(),
        provider_name=provider.name,
        source_url=provider.source_url,
        attribution=provider.attribution,
        prices=prices,
        recent_history=recent,
    )
