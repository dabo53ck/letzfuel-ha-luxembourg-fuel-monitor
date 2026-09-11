"""Services for LëtzFuel HA.

Both services are response-only helpers for automations and scripts: they compute
a cost from the currently published prices and return it.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CONSUMPTION,
    ATTR_DISTANCE_KM,
    ATTR_FUEL_TYPE,
    ATTR_LITERS,
    ATTR_USE_TOMORROW_PRICE,
    CURRENCY_EURO,
    DOMAIN,
    SERVICE_CALCULATE_FILL_COST,
    SERVICE_CALCULATE_TRIP_COST,
)
from .coordinator import LuxFuelCoordinator
from .models import FuelType

_FILL_COST_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_LITERS): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=500)
        ),
        vol.Optional(ATTR_FUEL_TYPE): vol.In([f.value for f in FuelType]),
        vol.Optional(ATTR_USE_TOMORROW_PRICE, default=False): cv.boolean,
    }
)

_TRIP_COST_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DISTANCE_KM): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=100000)
        ),
        vol.Required(ATTR_CONSUMPTION): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=100)
        ),
        vol.Optional(ATTR_FUEL_TYPE): vol.In([f.value for f in FuelType]),
    }
)


def _get_coordinator(hass: HomeAssistant) -> LuxFuelCoordinator:
    """Return the single config entry's coordinator, or raise for the user."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]
    if not entries:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="not_configured"
        )
    return entries[0].runtime_data


def _resolve_fuel(coordinator: LuxFuelCoordinator, raw: str | None) -> FuelType:
    return FuelType(raw) if raw else coordinator.primary_fuel


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_CALCULATE_FILL_COST):
        return

    async def _calculate_fill_cost(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        fuel = _resolve_fuel(coordinator, call.data.get(ATTR_FUEL_TYPE))
        fp = coordinator.fuel_prices(fuel)
        if fp is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="fuel_not_available",
                translation_placeholders={"fuel": fuel.value},
            )
        point = (
            fp.upcoming
            if call.data[ATTR_USE_TOMORROW_PRICE] and fp.upcoming is not None
            else fp.current
        )
        price = coordinator.display_price(point)
        liters = call.data[ATTR_LITERS]
        return {
            "cost": round(liters * price, 2),
            "liters": liters,
            "price_per_liter": price,
            "fuel_type": fuel.value,
            "effective_date": point.effective_date.isoformat(),
            "currency": CURRENCY_EURO,
        }

    async def _calculate_trip_cost(call: ServiceCall) -> ServiceResponse:
        coordinator = _get_coordinator(hass)
        fuel = _resolve_fuel(coordinator, call.data.get(ATTR_FUEL_TYPE))
        fp = coordinator.fuel_prices(fuel)
        if fp is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="fuel_not_available",
                translation_placeholders={"fuel": fuel.value},
            )
        price = coordinator.display_price(fp.current)
        liters_needed = call.data[ATTR_DISTANCE_KM] / 100 * call.data[ATTR_CONSUMPTION]
        return {
            "liters_needed": round(liters_needed, 2),
            "cost": round(liters_needed * price, 2),
            "price_per_liter": price,
            "fuel_type": fuel.value,
            "currency": CURRENCY_EURO,
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_CALCULATE_FILL_COST,
        _calculate_fill_cost,
        schema=_FILL_COST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CALCULATE_TRIP_COST,
        _calculate_trip_cost,
        schema=_TRIP_COST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
