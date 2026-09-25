"""Shared plumbing for the next-day announcement sources.

The provider (petrol.lu) is the source of truth for current prices and history,
but it usually lists the next day's row only late in the evening. An
announcement feed supplies the announced (future-dated) price earlier, with a
fallback feed for when it is unusable. Both are optional and fail soft; this
module holds what they share: the result type, a consistency check against the
provider, a plausibility filter, and the rule for merging them into the
provider history (the provider always wins).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

from ..const import ANNOUNCE_MAX_DAYS_AHEAD, ANNOUNCE_MAX_DEVIATION
from ..models import FuelType, PricePoint


@dataclass(frozen=True, slots=True)
class AnnouncementResult:
    """What one announcement source returned on one fetch."""

    #: Newest effective date the source currently lists (None if it lists none).
    latest_date: date | None
    #: Future-dated price points only (effective after "today").
    points: list[PricePoint] = field(default_factory=list)
    #: Every complete row the source lists, past and future (incl. VAT).
    rows: dict[date, dict[FuelType, Decimal]] = field(default_factory=dict)


class AnnouncementSource(Protocol):
    """A source of announced next-day prices."""

    #: Stable machine key, used in logs and diagnostics.
    key: str

    async def async_fetch(self, today: date) -> AnnouncementResult:
        """Fetch the source; raise ``ProviderError`` on failure."""


@dataclass(frozen=True, slots=True)
class Conflict:
    """Two sources announced different prices for the same fuel and day."""

    fuel: FuelType
    effective_date: date
    kept: Decimal
    ignored: Decimal
    ignored_source: str


def current_prices(
    history: Iterable[PricePoint], today: date
) -> dict[FuelType, Decimal]:
    """Latest price in effect today, per fuel (incl. VAT)."""
    latest: dict[FuelType, PricePoint] = {}
    for point in history:
        if point.effective_date > today:
            continue
        prev = latest.get(point.fuel)
        if prev is None or point.effective_date >= prev.effective_date:
            latest[point.fuel] = point
    return {fuel: point.price_incl_vat for fuel, point in latest.items()}


def current_points(
    history: Iterable[PricePoint], today: date
) -> dict[FuelType, PricePoint]:
    """Latest point in effect today, per fuel."""
    latest: dict[FuelType, PricePoint] = {}
    for point in history:
        if point.effective_date > today:
            continue
        prev = latest.get(point.fuel)
        if prev is None or point.effective_date >= prev.effective_date:
            latest[point.fuel] = point
    return latest


def matches_provider(
    rows: dict[date, dict[FuelType, Decimal]],
    current: dict[FuelType, PricePoint],
) -> bool:
    """True if the source agrees with the provider on the price in effect now.

    Compares the source's row for the provider's current effective date (or
    the newest row before it) with the provider's current prices. A source
    that is stale or mis-edited fails this and is not trusted for tomorrow.
    Keyed on the provider's date, not the calendar day, so the check still
    holds after midnight before the provider has published the new day.
    """
    if not current:
        return False
    ref = max(point.effective_date for point in current.values())
    past = [day for day in rows if day <= ref]
    if not past:
        return False
    row = rows[max(past)]
    compared = [fuel for fuel in current if fuel in row]
    return bool(compared) and all(
        row[fuel] == current[fuel].price_incl_vat for fuel in compared
    )


def split_plausible(
    points: Iterable[PricePoint],
    current: dict[FuelType, Decimal],
    today: date,
) -> tuple[list[PricePoint], list[PricePoint]]:
    """Split announced points into ``(plausible, rejected)``.

    Rejected: not in the future, too far ahead, non-positive, or further than
    ``ANNOUNCE_MAX_DEVIATION`` from the price in effect today. A typo in a
    hand-maintained source must not trigger a notification.
    """
    horizon = today + timedelta(days=ANNOUNCE_MAX_DAYS_AHEAD)
    max_dev = Decimal(str(ANNOUNCE_MAX_DEVIATION))
    kept: list[PricePoint] = []
    rejected: list[PricePoint] = []
    for point in points:
        ok = today < point.effective_date <= horizon and point.price_incl_vat > 0
        base = current.get(point.fuel)
        if ok and base:
            ok = abs(point.price_incl_vat - base) <= base * max_dev
        (kept if ok else rejected).append(point)
    return kept, rejected


def merge_announced(
    history: list[PricePoint],
    batches: Iterable[tuple[str, list[PricePoint]]],
) -> tuple[list[PricePoint], list[Conflict]]:
    """Add announced points to ``history``; earlier entries take precedence.

    ``history`` (the provider) wins over every batch, and batches win in the
    order given. A lower-priority point for a fuel/day that is already known is
    dropped; if its price differs, that is reported as a :class:`Conflict`.
    """
    known: dict[tuple[FuelType, date], Decimal] = {
        (p.fuel, p.effective_date): p.price_incl_vat for p in history
    }
    merged = list(history)
    conflicts: list[Conflict] = []
    for source_key, points in batches:
        for point in points:
            key = (point.fuel, point.effective_date)
            if key not in known:
                known[key] = point.price_incl_vat
                merged.append(point)
            elif known[key] != point.price_incl_vat:
                conflicts.append(
                    Conflict(
                        fuel=point.fuel,
                        effective_date=point.effective_date,
                        kept=known[key],
                        ignored=point.price_incl_vat,
                        ignored_source=source_key,
                    )
                )
    return merged, conflicts
