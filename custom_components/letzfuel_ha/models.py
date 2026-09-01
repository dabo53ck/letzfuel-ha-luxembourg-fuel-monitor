"""Data models for the LëtzFuel HA integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class FuelType(StrEnum):
    """Supported (regulated) road fuel products in Luxembourg."""

    DIESEL = "diesel"
    SP95 = "sp95"
    SP98 = "sp98"


# Human-facing short labels, reused in entity names via translation placeholders.
FUEL_LABELS: dict[FuelType, str] = {
    FuelType.DIESEL: "Diesel",
    FuelType.SP95: "SP95 (E10)",
    FuelType.SP98: "SP98",
}


@dataclass(frozen=True, slots=True)
class PricePoint:
    """A single published maximum price for one fuel, effective from a date."""

    effective_date: date
    fuel: FuelType
    price_incl_vat: Decimal
    price_excl_vat: Decimal


@dataclass(frozen=True, slots=True)
class FuelPrices:
    """Resolved current / previous / upcoming prices for one fuel."""

    fuel: FuelType
    current: PricePoint
    #: Date on which the *current* price level first took effect.
    current_since: date
    #: Last published price that differed from the current one (None if unknown).
    previous: PricePoint | None
    #: Earliest future-dated published price, if the government has announced one.
    upcoming: PricePoint | None

    @property
    def has_pending_change(self) -> bool:
        """True when an announced upcoming price differs from the current price."""
        return (
            self.upcoming is not None
            and self.upcoming.price_incl_vat != self.current.price_incl_vat
        )


@dataclass(frozen=True, slots=True)
class PriceSet:
    """Everything the coordinator hands to the entities after a refresh."""

    fetched_at: datetime
    provider_name: str
    source_url: str
    attribution: str
    prices: dict[FuelType, FuelPrices]
    #: Recent points (bounded window) per fuel, used for trend calculation.
    recent_history: dict[FuelType, list[PricePoint]] = field(default_factory=dict)
