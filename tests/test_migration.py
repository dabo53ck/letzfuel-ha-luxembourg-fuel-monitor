"""Tests for the config entry migration."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.letzfuel_ha.const import (
    CONF_PRIMARY_FUEL,
    CONF_PROVIDER,
    CONF_TRACKED_FUELS,
    DEFAULT_PROVIDER,
    DOMAIN,
    OPT_EVENING_CHECK_TIME,
    OPT_HISTORY_IMPORT_ENABLED,
)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("18:01:00", "17:30:00"),  # the old default moves with the new one
        ("18:15:00", "18:15:00"),  # a custom time is kept
    ],
)
async def test_migrates_old_default_evening_time(
    hass: HomeAssistant, mock_petrol_lu, stored: str, expected: str
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="LëtzFuel HA",
        version=1,
        minor_version=1,
        data={
            CONF_PROVIDER: DEFAULT_PROVIDER,
            CONF_TRACKED_FUELS: ["diesel"],
            CONF_PRIMARY_FUEL: "diesel",
        },
        options={OPT_HISTORY_IMPORT_ENABLED: False, OPT_EVENING_CHECK_TIME: stored},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 2
    assert entry.options[OPT_EVENING_CHECK_TIME] == expected

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_newer_major_version_is_refused(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, version=2, data={})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
