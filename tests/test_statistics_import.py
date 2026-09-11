"""Tests for the long-term statistics backfill."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.letzfuel_ha.models import FuelType, PricePoint
from custom_components.letzfuel_ha.statistics_import import (
    _daily_statistics,
    async_import_history_statistics,
)

_TARGET = "homeassistant.components.recorder.statistics.async_import_statistics"


def _point(day: date, price: str) -> PricePoint:
    return PricePoint(day, FuelType.DIESEL, Decimal(price), Decimal(price))


def test_daily_statistics_forward_fills() -> None:
    start = date(2026, 8, 1)
    points = [_point(date(2026, 8, 1), "1.80"), _point(date(2026, 8, 4), "1.86")]
    rows = _daily_statistics(dict, points, start, date(2026, 8, 5))

    # one row per day, price carried forward until the next change
    assert len(rows) == 5
    assert rows[0]["mean"] == 1.8
    assert rows[2]["mean"] == 1.8  # 2026-08-03, still the old price
    assert rows[3]["mean"] == 1.86  # 2026-08-04, change day
    assert all(r["start"].minute == 0 and r["start"].second == 0 for r in rows)


async def test_history_import_targets_real_sensors(
    hass: HomeAssistant, mock_petrol_lu, config_entry
) -> None:
    """It imports statistics for each price sensor's actual entity_id."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data

    hass.config.components.add("recorder")
    with patch(_TARGET) as mock_import:
        await async_import_history_statistics(hass, coordinator, 12)

    assert mock_import.called
    metadatas = [call.args[1] for call in mock_import.call_args_list]
    stat_ids = {meta["statistic_id"] for meta in metadatas}

    assert "sensor.letzfuel_ha_diesel_price" in stat_ids
    for meta in metadatas:
        assert meta["source"] == "recorder"
        assert meta["statistic_id"].startswith("sensor.letzfuel_ha_")
        assert meta["unit_of_measurement"] == "€/L"
        assert meta["mean_type"] is not None

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_history_import_noop_without_recorder(
    hass: HomeAssistant, mock_petrol_lu, config_entry
) -> None:
    """No recorder component -> silent skip, no exception, no call."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    with patch(_TARGET) as mock_import:
        await async_import_history_statistics(hass, config_entry.runtime_data, 12)

    assert not mock_import.called

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()


def test_daily_statistics_carries_price_from_before_the_window() -> None:
    old = [_point(date(2020, 1, 1), "1.20"), _point(date(2020, 2, 1), "1.25")]
    rows = _daily_statistics(dict, old, date.today() - timedelta(days=3), date.today())
    # points are all far in the past, but forward-fill still emits the carried
    # price for every day in the window
    assert rows and all(r["mean"] == 1.25 for r in rows)
