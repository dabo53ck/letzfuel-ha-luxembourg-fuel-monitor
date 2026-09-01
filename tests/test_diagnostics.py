"""Tests for diagnostics."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.lux_fuel_monitor.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics(hass: HomeAssistant, init_integration_vehicle) -> None:
    diag = await async_get_config_entry_diagnostics(hass, init_integration_vehicle)

    assert diag["provider"]["key"] == "petrol_lu"
    assert diag["coordinator"]["last_update_success"] is True
    assert "diesel" in diag["data"]["prices"]
    assert diag["data"]["prices"]["diesel"]["current"]["price_incl_vat"] == 1.865
    # current fuel level is redacted
    assert diag["entry"]["data"]["current_level_pct"] == "**REDACTED**"
