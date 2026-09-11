"""Fuel level read from another entity instead of the manual slider."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.letzfuel_ha.const import (
    CONF_LEVEL_ENTITY,
    CONF_LEVEL_SOURCE,
    CONF_PRIMARY_FUEL,
    CONF_PROVIDER,
    CONF_TANK_SIZE,
    CONF_TRACKED_FUELS,
    DEFAULT_PROVIDER,
    DOMAIN,
    LEVEL_SOURCE_ENTITY,
    OPT_HISTORY_IMPORT_ENABLED,
)
from custom_components.letzfuel_ha.models import FuelType

LEVEL_ENTITY = "sensor.car_fuel_level"
REFILL = "sensor.letzfuel_ha_refill_cost"
NUMBER = "number.letzfuel_ha_current_fuel_level"


def _entry() -> MockConfigEntry:
    """A 50 L tank whose level is read from ``LEVEL_ENTITY``."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="LëtzFuel HA",
        data={
            CONF_PROVIDER: DEFAULT_PROVIDER,
            CONF_TRACKED_FUELS: [f.value for f in FuelType],
            CONF_PRIMARY_FUEL: FuelType.DIESEL.value,
            CONF_TANK_SIZE: 50,
            CONF_LEVEL_SOURCE: LEVEL_SOURCE_ENTITY,
            CONF_LEVEL_ENTITY: LEVEL_ENTITY,
        },
        options={OPT_HISTORY_IMPORT_ENABLED: False},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_refill_cost_reads_from_entity(
    hass: HomeAssistant, mock_petrol_lu
) -> None:
    """The refill cost uses the chosen entity's % and no slider is created."""
    hass.states.async_set(LEVEL_ENTITY, "60", {"unit_of_measurement": "%"})
    await _setup(hass, _entry())

    # 50 L * (1 - 0.60) * 1.865
    assert float(hass.states.get(REFILL).state) == 37.3
    assert hass.states.get(NUMBER) is None

    attrs = hass.states.get(REFILL).attributes
    assert attrs["level_source"] == LEVEL_SOURCE_ENTITY
    assert attrs["level_entity_id"] == LEVEL_ENTITY
    assert attrs["current_level_pct"] == 60.0


async def test_refill_cost_follows_entity_changes(
    hass: HomeAssistant, mock_petrol_lu
) -> None:
    """A change on the chosen entity recomputes the refill cost right away."""
    hass.states.async_set(LEVEL_ENTITY, "60", {"unit_of_measurement": "%"})
    await _setup(hass, _entry())
    assert float(hass.states.get(REFILL).state) == 37.3

    hass.states.async_set(LEVEL_ENTITY, "25", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()

    # 50 L * (1 - 0.25) * 1.865
    assert float(hass.states.get(REFILL).state) == 69.94


@pytest.mark.parametrize(
    "value", ["unavailable", "unknown", "not-a-number", "150", "-5"]
)
async def test_unusable_entity_state_yields_no_refill_cost(
    hass: HomeAssistant, mock_petrol_lu, value: str
) -> None:
    """Anything that isn't a 0-100 number degrades the sensor to unknown."""
    hass.states.async_set(LEVEL_ENTITY, value, {"unit_of_measurement": "%"})
    await _setup(hass, _entry())

    assert hass.states.get(REFILL).state in ("unknown", "unavailable")
