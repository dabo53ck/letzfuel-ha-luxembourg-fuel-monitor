"""Backfill each price sensor's long-term statistics from the provider history.

Luxembourg's source publishes prices back to 2017. Importing that
history into the recorder means each ``sensor.*_price`` entity's own history
graph (and the ``statistics`` / ``trend`` helpers built on it) shows data from
before the integration was installed, instead of starting empty.

This uses ``async_import_statistics`` against the real entity ids, so the
back-history merges into the same series the recorder keeps going forward.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN, UNIT_EUR_PER_LITER
from .coordinator import LuxFuelCoordinator
from .models import PricePoint

_LOGGER = logging.getLogger(__name__)

_RECORDER_SOURCE = "recorder"


async def async_import_history_statistics(
    hass: HomeAssistant,
    coordinator: LuxFuelCoordinator,
    months: int,
) -> None:
    """Best-effort backfill of price-sensor statistics (never raises)."""
    if "recorder" not in hass.config.components:
        _LOGGER.debug("Recorder not enabled; skipping history import")
        return
    try:
        await _async_import(hass, coordinator, months)
    except Exception:
        _LOGGER.exception("Historical statistics import failed")


async def _async_import(
    hass: HomeAssistant,
    coordinator: LuxFuelCoordinator,
    months: int,
) -> None:
    """Import daily mean/min/max price statistics for each tracked fuel."""
    # Imported here so the integration loads even when the recorder is absent
    # (e.g. minimal test setups).
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMeanType,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import async_import_statistics

    entity_registry = er.async_get(hass)
    since = dt_util.now().date() - timedelta(days=max(months, 1) * 31)
    history = await coordinator.provider.async_get_history(since)
    today = dt_util.now().date()

    for fuel in coordinator.tracked_fuels:
        unique_id = f"{coordinator.config_entry.entry_id}_{fuel.value}_price"
        entity_id = entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id is None:
            continue

        points = sorted(
            (p for p in history if p.fuel == fuel and p.effective_date <= today),
            key=lambda p: p.effective_date,
        )
        if len(points) < 2:
            continue

        rows = _daily_statistics(StatisticData, points, since, today)
        if not rows:
            continue

        metadata = StatisticMetaData(
            has_sum=False,
            mean_type=StatisticMeanType.ARITHMETIC,
            name=None,
            source=_RECORDER_SOURCE,
            statistic_id=entity_id,
            unit_class=None,
            unit_of_measurement=UNIT_EUR_PER_LITER,
        )
        async_import_statistics(hass, metadata, rows)
        _LOGGER.debug("Imported %d statistics points for %s", len(rows), entity_id)


def _daily_statistics(
    statistic_data_cls: type,
    points: list[PricePoint],
    since: date,
    today: date,
) -> list:
    """Forward-fill the change points into one statistics row per day."""
    tz = dt_util.get_default_time_zone()
    rows: list = []
    idx = 0
    current_price: float | None = None
    day = max(since, points[0].effective_date)

    while day <= today:
        while idx < len(points) and points[idx].effective_date <= day:
            current_price = float(points[idx].price_incl_vat)
            idx += 1
        if current_price is not None:
            start = dt_util.start_of_local_day(day).astimezone(tz)
            rows.append(
                statistic_data_cls(
                    start=start,
                    mean=current_price,
                    min=current_price,
                    max=current_price,
                )
            )
        day += timedelta(days=1)
    return rows
