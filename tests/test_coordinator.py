"""Tests for the coordinator: setup and change detection / events."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.lux_fuel_monitor.const import (
    EVENT_PRICE_CHANGE_ANNOUNCED,
    EVENT_PRICE_CHANGED,
)
from custom_components.lux_fuel_monitor.models import (
    FuelPrices,
    FuelType,
    PricePoint,
    PriceSet,
)


async def test_setup_populates_data(hass: HomeAssistant, init_integration) -> None:
    coordinator = init_integration.runtime_data
    assert coordinator.last_update_success
    fp = coordinator.fuel_prices(FuelType.DIESEL)
    assert fp is not None
    assert fp.current.price_incl_vat == Decimal("1.865")
    # re-published unchanged today -> last real move was 8 days ago
    assert fp.previous.price_incl_vat == Decimal("1.800")
    assert fp.current_since == dt_util.now().date() - timedelta(days=8)


def _price_set(current: str, upcoming: str | None) -> PriceSet:
    today = dt_util.now().date()
    cur = PricePoint(today, FuelType.DIESEL, Decimal(current), Decimal(current))
    up = (
        PricePoint(
            today + timedelta(days=1), FuelType.DIESEL, Decimal(upcoming), Decimal(upcoming)
        )
        if upcoming
        else None
    )
    fp = FuelPrices(FuelType.DIESEL, cur, today, None, up)
    return PriceSet(
        fetched_at=dt_util.utcnow(),
        provider_name="test",
        source_url="http://example.test",
        attribution="test",
        prices={FuelType.DIESEL: fp},
        recent_history={FuelType.DIESEL: [cur]},
    )


async def test_announced_event_fires_once(hass: HomeAssistant, init_integration) -> None:
    coordinator = init_integration.runtime_data
    events = []
    hass.bus.async_listen(EVENT_PRICE_CHANGE_ANNOUNCED, lambda e: events.append(e))

    coordinator._last_seen = {}
    await coordinator._async_detect_changes(_price_set("1.865", "1.900"))
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["changes"][0]["direction"] == "up"

    # Same upcoming again -> no duplicate event.
    await coordinator._async_detect_changes(_price_set("1.865", "1.900"))
    await hass.async_block_till_done()
    assert len(events) == 1


async def test_changed_event_on_effective_date_advance(
    hass: HomeAssistant, init_integration
) -> None:
    coordinator = init_integration.runtime_data
    events = []
    hass.bus.async_listen(EVENT_PRICE_CHANGED, lambda e: events.append(e))

    yesterday = (dt_util.now().date() - timedelta(days=1)).isoformat()
    coordinator._last_seen = {
        "diesel": {
            "current_date": yesterday,
            "current_price": "1.800",
            "upcoming_date": None,
            "upcoming_price": None,
        }
    }
    await coordinator._async_detect_changes(_price_set("1.865", None))
    await hass.async_block_till_done()

    assert len(events) == 1
    change = events[0].data["changes"][0]
    assert change["old_price"] == pytest.approx(1.800)
    assert change["new_price"] == pytest.approx(1.865)
