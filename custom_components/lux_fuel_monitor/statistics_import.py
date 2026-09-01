"""Backfill long-term statistics from the provider's price history.

Luxembourg's official source publishes prices back to 2017. Importing them into
Home Assistant's long-term statistics means the history graphs and the
``statistics`` / ``trend`` helper integrations work from the first minute, instead
of starting empty.

Statistic ids: ``lux_fuel_monitor:<fuel>_price`` (unit €/L, incl. VAT).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STATISTIC_SOURCE, UNIT_EUR_PER_LITER
from .coordinator import LuxFuelCoordinator
from .models import FUEL_LABELS, PricePoint

_LOGGER = logging.getLogger(__name__)


async def async_import_history_statistics(
    hass: HomeAssistant,
    coordinator: LuxFuelCoordinator,
    months: int,
) -> None:
    """Import daily mean/min/max price statistics for each tracked fuel."""
    if "recorder" not in hass.config.components:
        _LOGGER.debug("Recorder not enabled; skipping history import")
        return

    # Imported here so the integration loads even if the recorder component is
    # unavailable (e.g. minimal test setups).
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import async_import_statistics

    since = dt_util.now().date() - timedelta(days=max(months, 1) * 31)
    try:
        history = await coordinator.provider.async_get_history(since)
    except Exception as err:
        _LOGGER.warning("History import skipped: could not fetch history: %s", err)
        return

    today = dt_util.now().date()
    for fuel in coordinator.tracked_fuels:
        points = sorted(
            (p for p in history if p.fuel == fuel and p.effective_date <= today),
            key=lambda p: p.effective_date,
        )
        if len(points) < 2:
            continue

        statistics = _daily_statistics(StatisticData, points, since, today)
        if not statistics:
            continue

        metadata = StatisticMetaData(
            has_mean=True,
            has_sum=False,
            name=f"{FUEL_LABELS[fuel]} price",
            source=STATISTIC_SOURCE,
            statistic_id=f"{DOMAIN}:{fuel.value}_price",
            unit_of_measurement=UNIT_EUR_PER_LITER,
        )
        async_import_statistics(hass, metadata, statistics)
        _LOGGER.debug(
            "Imported %d daily statistics points for %s", len(statistics), fuel.value
        )


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
