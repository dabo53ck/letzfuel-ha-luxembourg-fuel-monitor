"""The LëtzFuel HA integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_HISTORY_IMPORT_MONTHS,
    OPT_HISTORY_IMPORT_ENABLED,
    OPT_HISTORY_IMPORT_MONTHS,
)
from .coordinator import LuxFuelConfigEntry, LuxFuelCoordinator
from .helpers import option_value
from .services import async_setup_services
from .statistics_import import async_import_history_statistics

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: LuxFuelConfigEntry) -> bool:
    """Set up LëtzFuel HA from a config entry."""
    coordinator = LuxFuelCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    async_setup_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    coordinator.async_setup_evening_schedule()
    coordinator.async_setup_midnight_schedule()
    coordinator.async_setup_level_entity_tracking()
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    if option_value(entry, OPT_HISTORY_IMPORT_ENABLED, True):
        months = int(
            option_value(
                entry, OPT_HISTORY_IMPORT_MONTHS, DEFAULT_HISTORY_IMPORT_MONTHS
            )
        )
        entry.async_create_background_task(
            hass,
            async_import_history_statistics(hass, coordinator, months),
            "letzfuel_ha_history_import",
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: LuxFuelConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: LuxFuelConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
