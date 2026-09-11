"""Diagnostics for LëtzFuel HA."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import LuxFuelConfigEntry
from .models import FuelPrices, PricePoint

_REDACT: set[str] = {"current_level_pct"}


def _point(point: PricePoint | None) -> dict[str, Any] | None:
    if point is None:
        return None
    return {
        "effective_date": point.effective_date.isoformat(),
        "price_incl_vat": float(point.price_incl_vat),
        "price_excl_vat": float(point.price_excl_vat),
    }


def _fuel_prices(fp: FuelPrices) -> dict[str, Any]:
    return {
        "current": _point(fp.current),
        "current_since": fp.current_since.isoformat(),
        "previous": _point(fp.previous),
        "upcoming": _point(fp.upcoming),
        "has_pending_change": fp.has_pending_change,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LuxFuelConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), _REDACT),
            "options": async_redact_data(dict(entry.options), _REDACT),
        },
        "provider": {
            "key": coordinator.provider.key,
            "name": coordinator.provider.name,
            "source_url": coordinator.provider.source_url,
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception)
            if coordinator.last_exception
            else None,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "tracked_fuels": [f.value for f in coordinator.tracked_fuels],
            "primary_fuel": coordinator.primary_fuel.value,
        },
        "data": {
            "fetched_at": data.fetched_at.isoformat() if data else None,
            "provider_name": data.provider_name if data else None,
            "prices": (
                {fuel.value: _fuel_prices(fp) for fuel, fp in data.prices.items()}
                if data
                else {}
            ),
            "recent_history_counts": (
                {fuel.value: len(pts) for fuel, pts in data.recent_history.items()}
                if data
                else {}
            ),
        },
    }
