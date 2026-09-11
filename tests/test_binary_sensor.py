"""Tests for the price-change-pending binary sensor."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

ENTITY_ID = "binary_sensor.letzfuel_ha_price_change_pending"


async def test_off_with_no_pending_change(
    hass: HomeAssistant, init_integration
) -> None:
    """No announced next-day price -> off, empty attributes."""
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "off"
    assert state.attributes["affected_fuels"] == []
    assert state.attributes["deltas"] == {}
    assert state.attributes["effective_date"] is None


async def test_on_with_pending_change(
    hass: HomeAssistant, mock_petrol_lu, price_entries, config_entry
) -> None:
    """An RTL-announced next-day price turns the sensor on with details."""
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(
        price_entries,
        rtl_payload={
            "id": 2132,
            "date": f"{tomorrow.isoformat()}T00:00:00+02:00",
            "98oct": 1.983,  # unchanged vs. today -> not "affected"
            "95oct": 1.792,  # unchanged vs. today -> not "affected"
            "diesel": 2.024,  # up from 1.865 -> affected
        },
    )

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "on"
    assert state.attributes["affected_fuels"] == ["diesel"]
    assert state.attributes["deltas"]["diesel"] == pytest.approx(0.159)
    assert state.attributes["effective_date"] == tomorrow.isoformat()

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
