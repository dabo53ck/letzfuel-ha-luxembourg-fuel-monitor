"""Tests for the sensor and binary_sensor platforms."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.letzfuel_ha.const import (
    CONF_PRIMARY_FUEL,
    CONF_PROVIDER,
    CONF_TRACKED_FUELS,
    DEFAULT_PROVIDER,
    DOMAIN,
    OPT_HISTORY_IMPORT_ENABLED,
    RECOMMENDATION_REFUEL_TODAY,
)
from custom_components.letzfuel_ha.models import FuelType

PREFIX = "sensor.letzfuel_ha_"
BPREFIX = "binary_sensor.letzfuel_ha_"


async def test_price_sensor(hass: HomeAssistant, init_integration) -> None:
    state = hass.states.get(f"{PREFIX}diesel_price")
    assert state is not None
    assert float(state.state) == 1.865
    assert state.attributes["price_excl_vat"] == 1.594
    assert state.attributes["currency"] == "EUR"
    assert state.attributes["fuel_type"] == "diesel"


async def test_change_sensor(hass: HomeAssistant, init_integration) -> None:
    state = hass.states.get(f"{PREFIX}diesel_change")
    # 1.865 (current level) - 1.800 (previous distinct price)
    assert round(float(state.state), 3) == 0.065
    assert state.attributes["percentage_change"] is not None


async def test_trend_and_tomorrow_default_to_primary_fuel_only(
    hass: HomeAssistant, init_integration
) -> None:
    """trend / price_tomorrow are enabled only for the primary fuel (diesel)."""
    registry = er.async_get(hass)

    for key in ("trend", "price_tomorrow"):
        primary = registry.async_get(f"{PREFIX}diesel_{key}")
        other = registry.async_get(f"{PREFIX}sp95_e10_{key}")
        assert primary is not None and primary.disabled_by is None
        assert other is not None
        assert other.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_recommendation_and_pending(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    today = dt_util.now().date()
    entries = [
        *price_entries,
        (
            today + timedelta(days=1),
            {FuelType.DIESEL: (Decimal("1.920"), Decimal("1.641"))},
        ),
    ]
    mock_petrol_lu(entries)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_PROVIDER: DEFAULT_PROVIDER,
            CONF_TRACKED_FUELS: [FuelType.DIESEL.value],
            CONF_PRIMARY_FUEL: FuelType.DIESEL.value,
        },
        options={OPT_HISTORY_IMPORT_ENABLED: False},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert (
        hass.states.get(f"{PREFIX}refuel_recommendation").state
        == RECOMMENDATION_REFUEL_TODAY
    )
    assert hass.states.get(f"{BPREFIX}price_change_pending").state == STATE_ON

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_vehicle_sensors(hass: HomeAssistant, init_integration_vehicle) -> None:
    full_tank = hass.states.get(f"{PREFIX}full_tank_cost")
    assert full_tank is not None
    # 50 L * 1.865 EUR/L
    assert float(full_tank.state) == 93.25

    refill = hass.states.get(f"{PREFIX}refill_cost")
    # 50 L * (1 - 0.40) * 1.865
    assert float(refill.state) == 55.95


async def test_no_vehicle_sensors_without_tank(
    hass: HomeAssistant, init_integration
) -> None:
    assert hass.states.get(f"{PREFIX}full_tank_cost") is None
