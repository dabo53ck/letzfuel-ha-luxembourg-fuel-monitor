"""Tests for the price-change-pending binary sensor."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.letzfuel_ha.models import FuelType

from .helpers import sheet_json

ENTITY_ID = "binary_sensor.letzfuel_ha_price_change_pending"
#: Today's prices in the ``price_entries`` fixture (the feed must agree).
TODAY_PRICES = {
    FuelType.DIESEL: "1.865",
    FuelType.SP95: "1.792",
    FuelType.SP98: "1.983",
}


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
    """An announced next-day price turns the sensor on with details."""
    tomorrow = dt_util.now().date() + timedelta(days=1)
    mock_petrol_lu(
        price_entries,
        sheet_payload=sheet_json(
            [
                (dt_util.now().date(), TODAY_PRICES),
                (
                    tomorrow,
                    {
                        FuelType.SP98: "1.983",  # unchanged -> not "affected"
                        FuelType.SP95: "1.792",  # unchanged -> not "affected"
                        FuelType.DIESEL: "2.024",  # up from 1.865 -> affected
                    },
                ),
            ]
        ),
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
