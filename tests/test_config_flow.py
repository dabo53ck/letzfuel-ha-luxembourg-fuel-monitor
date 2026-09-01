"""Tests for the config and options flow."""

from __future__ import annotations

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.lux_fuel_monitor.const import (
    CONF_PRIMARY_FUEL,
    CONF_TANK_SIZE,
    CONF_TRACKED_FUELS,
    DOMAIN,
    OPT_TREND_WINDOW_DAYS,
    OPT_UPDATE_INTERVAL_HOURS,
)
from custom_components.lux_fuel_monitor.models import FuelType
from custom_components.lux_fuel_monitor.providers.petrol_lu import SOURCE_URL


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

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TANK_SIZE: 55}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_TANK_SIZE] == 55
    assert result["data"][CONF_PRIMARY_FUEL] == FuelType.DIESEL.value

    await hass.async_block_till_done()
    await hass.config_entries.async_unload(result["result"].entry_id)
    await hass.async_block_till_done()


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock
) -> None:
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


async def test_options_flow(hass: HomeAssistant, init_integration) -> None:
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            OPT_UPDATE_INTERVAL_HOURS: 12,
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
    assert init_integration.options[OPT_UPDATE_INTERVAL_HOURS] == 12
    assert init_integration.options[OPT_TREND_WINDOW_DAYS] == 21
    assert init_integration.options["price_display"] == "excl_vat"
