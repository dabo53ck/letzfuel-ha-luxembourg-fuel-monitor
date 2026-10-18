"""Tests for the config and options flow."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.letzfuel_ha.const import (
    CONF_LEVEL_ENTITY,
    CONF_LEVEL_SOURCE,
    CONF_PRIMARY_FUEL,
    CONF_TANK_SIZE,
    CONF_TRACKED_FUELS,
    DOMAIN,
    LEVEL_SOURCE_ENTITY,
    LEVEL_SOURCE_MANUAL,
    OPT_TREND_WINDOW_DAYS,
)
from custom_components.letzfuel_ha.models import FuelType
from custom_components.letzfuel_ha.providers.petrol_lu import SOURCE_URL


async def test_user_flow_happy_path(hass: HomeAssistant, mock_petrol_lu) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TRACKED_FUELS: [FuelType.DIESEL.value, FuelType.SP95.value],
            CONF_PRIMARY_FUEL: FuelType.DIESEL.value,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "vehicle"

    with patch("custom_components.letzfuel_ha.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TANK_SIZE: 55}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TANK_SIZE] == 55
    assert result["data"][CONF_PRIMARY_FUEL] == FuelType.DIESEL.value


async def test_user_flow_cannot_connect(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(SOURCE_URL, exc=aiohttp.ClientError())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TRACKED_FUELS: [FuelType.DIESEL.value],
            CONF_PRIMARY_FUEL: FuelType.DIESEL.value,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_single_instance(hass: HomeAssistant, init_integration) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def _options_page(hass: HomeAssistant, entry_id: str, page: str) -> dict:
    """Open the options menu and pick ``page``."""
    result = await hass.config_entries.options.async_init(entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": page}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == page
    return result


async def test_options_flow(hass: HomeAssistant, init_integration) -> None:
    result = await _options_page(hass, init_integration.entry_id, "general")

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "evening_check_time": "18:01:00",
            OPT_TREND_WINDOW_DAYS: 21,
            "price_display": "excl_vat",
            CONF_TRACKED_FUELS: [FuelType.DIESEL.value],
            CONF_PRIMARY_FUEL: FuelType.DIESEL.value,
            "history_import_enabled": False,
            "history_import_months": 6,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options[OPT_TREND_WINDOW_DAYS] == 21
    assert init_integration.options["price_display"] == "excl_vat"


_BASE_OPTIONS = {
    "evening_check_time": "18:01:00",
    OPT_TREND_WINDOW_DAYS: 14,
    "price_display": "incl_vat",
    CONF_TRACKED_FUELS: [FuelType.DIESEL.value],
    CONF_PRIMARY_FUEL: FuelType.DIESEL.value,
    "history_import_enabled": False,
    "history_import_months": 12,
}


async def test_options_flow_level_from_entity(
    hass: HomeAssistant, init_integration_vehicle
) -> None:
    """Choosing 'entity' as the level source stores the picked entity."""
    hass.states.async_set("sensor.car_fuel_level", "55", {"unit_of_measurement": "%"})

    result = await _options_page(hass, init_integration_vehicle.entry_id, "vehicle")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_TANK_SIZE: 50,
            CONF_LEVEL_SOURCE: LEVEL_SOURCE_ENTITY,
            CONF_LEVEL_ENTITY: "sensor.car_fuel_level",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    opts = init_integration_vehicle.options
    assert opts[CONF_LEVEL_SOURCE] == LEVEL_SOURCE_ENTITY
    assert opts[CONF_LEVEL_ENTITY] == "sensor.car_fuel_level"


async def test_options_flow_entity_source_requires_entity(
    hass: HomeAssistant, init_integration_vehicle
) -> None:
    """'entity' source without an entity re-shows the form with an error."""
    result = await _options_page(hass, init_integration_vehicle.entry_id, "vehicle")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_TANK_SIZE: 50, CONF_LEVEL_SOURCE: LEVEL_SOURCE_ENTITY},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "level_entity_required"}


async def test_user_flow_primary_must_be_tracked(
    hass: HomeAssistant, mock_petrol_lu
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TRACKED_FUELS: [FuelType.DIESEL.value],
            CONF_PRIMARY_FUEL: FuelType.SP98.value,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "primary_not_tracked"}


async def test_options_flow_primary_must_be_tracked(
    hass: HomeAssistant, init_integration
) -> None:
    result = await _options_page(hass, init_integration.entry_id, "general")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **_BASE_OPTIONS,
            CONF_TRACKED_FUELS: [FuelType.DIESEL.value],
            CONF_PRIMARY_FUEL: FuelType.SP98.value,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "primary_not_tracked"}


async def test_options_flow_tank_size_can_be_cleared(
    hass: HomeAssistant, init_integration_vehicle
) -> None:
    """Clearing the tank size wins over the size from the initial setup."""
    assert init_integration_vehicle.runtime_data.tank_size == 50
    result = await _options_page(hass, init_integration_vehicle.entry_id, "vehicle")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LEVEL_SOURCE: LEVEL_SOURCE_MANUAL}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration_vehicle.runtime_data.tank_size is None


async def test_options_pages_keep_each_other(
    hass: HomeAssistant, init_integration_vehicle
) -> None:
    """Saving one page keeps what the other page stored."""
    result = await _options_page(hass, init_integration_vehicle.entry_id, "vehicle")
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TANK_SIZE: 60, CONF_LEVEL_SOURCE: LEVEL_SOURCE_MANUAL}
    )
    await hass.async_block_till_done()
    result = await _options_page(hass, init_integration_vehicle.entry_id, "general")
    await hass.config_entries.options.async_configure(
        result["flow_id"], {**_BASE_OPTIONS, OPT_TREND_WINDOW_DAYS: 30}
    )
    await hass.async_block_till_done()

    opts = init_integration_vehicle.options
    assert opts[CONF_TANK_SIZE] == 60
    assert opts[OPT_TREND_WINDOW_DAYS] == 30
