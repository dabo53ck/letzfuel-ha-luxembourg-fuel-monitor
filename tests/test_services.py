"""Tests for the response services."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.letzfuel_ha.const import (
    DOMAIN,
    SERVICE_CALCULATE_FILL_COST,
    SERVICE_CALCULATE_TRIP_COST,
)


async def test_calculate_fill_cost(hass: HomeAssistant, init_integration) -> None:
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_CALCULATE_FILL_COST,
        {"liters": 40, "fuel_type": "diesel"},
        blocking=True,
        return_response=True,
    )
    assert response["cost"] == 74.6  # 40 * 1.865
    assert response["price_per_liter"] == 1.865
    assert response["currency"] == "EUR"


async def test_calculate_fill_cost_default_fuel(
    hass: HomeAssistant, init_integration
) -> None:
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_CALCULATE_FILL_COST,
        {"liters": 10},
        blocking=True,
        return_response=True,
    )
    assert response["fuel_type"] == "diesel"


async def test_calculate_trip_cost(hass: HomeAssistant, init_integration) -> None:
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_CALCULATE_TRIP_COST,
        {"distance_km": 300, "consumption_l_100km": 6.0, "fuel_type": "diesel"},
        blocking=True,
        return_response=True,
    )
    # 300 / 100 * 6 = 18 L ; 18 * 1.865
    assert response["liters_needed"] == 18.0
    assert response["cost"] == 33.57
