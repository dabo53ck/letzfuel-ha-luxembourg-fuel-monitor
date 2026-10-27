"""Tests for diagnostics."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.letzfuel_ha.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.fixture
def morning(freezer) -> None:
    """Before 18:15, so the backup feed stays on standby."""
    freezer.move_to(dt_util.start_of_local_day().replace(hour=10))


async def test_diagnostics(
    hass: HomeAssistant, morning, init_integration_vehicle
) -> None:
    diag = await async_get_config_entry_diagnostics(hass, init_integration_vehicle)

    assert diag["provider"]["key"] == "petrol_lu"
    assert diag["coordinator"]["last_update_success"] is True
    assert "diesel" in diag["data"]["prices"]
    assert diag["data"]["prices"]["diesel"]["current"]["price_incl_vat"] == 1.865
    sources = diag["announcement_sources"]
    assert set(sources) == {"backup_feed", "live_sheet"}
    assert sources["live_sheet"]["outcome"] == "nothing_future"
    assert sources["backup_feed"] == {"outcome": "standby"}
    assert diag["coordinator"]["announcement_feed_broken_since"] is None
    # current fuel level is redacted
    assert diag["entry"]["data"]["current_level_pct"] == "**REDACTED**"
