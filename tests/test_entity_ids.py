"""Entity IDs must be stable and language-independent.

Home Assistant derives an ``entity_id`` from the *translated* entity name, so
without an explicit suggestion a German instance ends up with
``sensor.letzfuel_ha_tankempfehlung`` instead of the documented
``sensor.letzfuel_ha_refuel_recommendation`` — which would break the shared
notification blueprint and every example in the docs.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.letzfuel_ha.const import (
    CONF_PRIMARY_FUEL,
    CONF_PROVIDER,
    CONF_TANK_SIZE,
    CONF_TRACKED_FUELS,
    DEFAULT_PROVIDER,
    DOMAIN,
    OPT_HISTORY_IMPORT_ENABLED,
)
from custom_components.letzfuel_ha.models import FuelType

# The canonical entity_ids the blueprint and the README rely on.
EXPECTED = {
    "sensor.letzfuel_ha_diesel_price",
    "sensor.letzfuel_ha_diesel_change",
    "sensor.letzfuel_ha_diesel_trend",
    "sensor.letzfuel_ha_diesel_price_tomorrow",
    "sensor.letzfuel_ha_sp95_e10_price",
    "sensor.letzfuel_ha_sp95_e10_change",
    "sensor.letzfuel_ha_sp98_price",
    "sensor.letzfuel_ha_sp98_change",
    "sensor.letzfuel_ha_refuel_recommendation",
    "sensor.letzfuel_ha_last_price_update",
    "sensor.letzfuel_ha_full_tank_cost",
    "sensor.letzfuel_ha_refill_cost",
    "sensor.letzfuel_ha_full_tank_cost_change",
    "binary_sensor.letzfuel_ha_price_change_pending",
    "number.letzfuel_ha_current_fuel_level",
}


@pytest.mark.parametrize("language", ["en", "de", "fr", "lb"])
async def test_entity_ids_are_language_independent(
    hass: HomeAssistant, mock_petrol_lu, language: str
) -> None:
    """Every documented entity_id exists regardless of the instance language."""
    hass.config.language = language

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="LëtzFuel HA",
        data={
            CONF_PROVIDER: DEFAULT_PROVIDER,
            CONF_TRACKED_FUELS: [f.value for f in FuelType],
            CONF_PRIMARY_FUEL: FuelType.DIESEL.value,
            CONF_TANK_SIZE: 50,
            "current_level_pct": 40,
        },
        options={OPT_HISTORY_IMPORT_ENABLED: False},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    present = set(hass.states.async_entity_ids())
    missing = EXPECTED - present
    assert not missing, f"missing entity_ids for language {language!r}: {missing}"

    if language == "de":
        # The German entity name is "Tankempfehlung"; without a pinned
        # entity_id the sensor would land there instead.
        assert "sensor.letzfuel_ha_tankempfehlung" not in present

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
