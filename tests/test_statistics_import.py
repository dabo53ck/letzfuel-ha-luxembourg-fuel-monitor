"""Tests for the long-term statistics backfill."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.lux_fuel_monitor.statistics_import import (
    async_import_history_statistics,
)

_TARGET = "homeassistant.components.recorder.statistics.async_import_statistics"


async def test_history_import_targets_real_sensors(
    recorder_mock,
    hass: HomeAssistant,
    mock_petrol_lu,
    config_entry,
) -> None:
    """It imports statistics for each price sensor's actual entity_id."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data

    with patch(_TARGET) as mock_import:
        await async_import_history_statistics(hass, coordinator, 12)

    assert mock_import.called
    metadatas = [call.args[1] for call in mock_import.call_args_list]
    stat_ids = {meta["statistic_id"] for meta in metadatas}

    assert "sensor.luxembourg_fuel_monitor_diesel_price" in stat_ids
    for meta in metadatas:
        assert meta["source"] == "recorder"
        assert meta["statistic_id"].startswith("sensor.luxembourg_fuel_monitor_")
        assert meta["unit_of_measurement"] == "€/L"
        assert meta["mean_type"] is not None

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_history_import_is_noop_without_recorder(
    hass: HomeAssistant, mock_petrol_lu, config_entry
) -> None:
    """No recorder component -> silent skip, no exception."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data

    with patch(_TARGET) as mock_import:
        await async_import_history_statistics(hass, coordinator, 12)

    assert not mock_import.called

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
