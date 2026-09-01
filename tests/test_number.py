"""Tests for the current-fuel-level number entity."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

NUMBER = "number.luxembourg_fuel_monitor_current_fuel_level"
REFILL = "sensor.luxembourg_fuel_monitor_refill_cost"


async def test_number_created_only_with_tank(
    hass: HomeAssistant, init_integration
) -> None:
    """No tank size -> no fuel-level number."""
    assert hass.states.get(NUMBER) is None


async def test_number_initial_value_from_config(
    hass: HomeAssistant, init_integration_vehicle
) -> None:
    """First run seeds the number from the configured level (40 %)."""
    state = hass.states.get(NUMBER)
    assert state is not None
    assert float(state.state) == 40.0
    # 50 L * (1 - 0.40) * 1.865
    assert float(hass.states.get(REFILL).state) == 55.95


async def test_setting_number_updates_refill_cost(
    hass: HomeAssistant, init_integration_vehicle
) -> None:
    """Moving the slider recomputes refill_cost right away."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": NUMBER, "value": 20},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert float(hass.states.get(NUMBER).state) == 20.0
    # 50 L * (1 - 0.20) * 1.865
    assert float(hass.states.get(REFILL).state) == 74.6
