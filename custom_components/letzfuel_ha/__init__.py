"""The LëtzFuel HA integration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
    Platform,
)
from homeassistant.core import (
    CoreState,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.typing import ConfigType

from .const import (
    BRAND_ICON_URL,
    DEFAULT_HISTORY_IMPORT_MONTHS,
    EVENT_AUTOMATION_RELOADED,
    LEGACY_OPT_UPDATE_INTERVAL_HOURS,
    OPT_HISTORY_IMPORT_ENABLED,
    OPT_HISTORY_IMPORT_MONTHS,
)
from .coordinator import LuxFuelConfigEntry, LuxFuelCoordinator
from .duplicates import async_check_duplicates
from .helpers import option_value
from .services import async_setup_services
from .statistics_import import async_import_history_statistics

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SENSOR,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the brand icon locally for use as a notification icon_url."""
    icon_path = Path(__file__).parent / "brand" / "icon.png"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(BRAND_ICON_URL, str(icon_path), cache_headers=True)]
    )
    return True


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
    #: What a reload is needed for; subentry changes alone don't need one.
    coordinator.settings_snapshot = _settings(entry)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    _async_watch_duplicates(hass, entry)

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


async def async_migrate_entry(hass: HomeAssistant, entry: LuxFuelConfigEntry) -> bool:
    """Migrate an older config entry."""
    if entry.version > 1:
        return False  # from a newer, incompatible version
    if entry.minor_version < 4:
        # The update interval is no longer a setting.
        data, options = dict(entry.data), dict(entry.options)
        for values in (data, options):
            values.pop(LEGACY_OPT_UPDATE_INTERVAL_HOURS, None)
        hass.config_entries.async_update_entry(
            entry, data=data, options=options, minor_version=4
        )
        _LOGGER.debug("Migrated config entry to version 1.4")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LuxFuelConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _settings(entry: LuxFuelConfigEntry) -> tuple[dict[str, Any], dict[str, Any]]:
    return dict(entry.data), dict(entry.options)


async def _async_entry_updated(hass: HomeAssistant, entry: LuxFuelConfigEntry) -> None:
    """Reload on a settings change; a notification target change needs none."""
    coordinator = entry.runtime_data
    if _settings(entry) != coordinator.settings_snapshot:
        await hass.config_entries.async_reload(entry.entry_id)
        return
    await async_check_duplicates(hass, entry)


@callback
def _async_watch_duplicates(hass: HomeAssistant, entry: LuxFuelConfigEntry) -> None:
    """Re-check for duplicate notifications whenever automations change."""

    @callback
    def _schedule(_event: Event | None = None) -> None:
        entry.async_create_background_task(
            hass, async_check_duplicates(hass, entry), "letzfuel_ha_duplicates"
        )

    @callback
    def _is_automation(event_data: EventStateChangedData) -> bool:
        return event_data["entity_id"].startswith("automation.")

    entry.async_on_unload(hass.bus.async_listen(EVENT_AUTOMATION_RELOADED, _schedule))
    entry.async_on_unload(
        hass.bus.async_listen(
            EVENT_STATE_CHANGED, _schedule, event_filter=_is_automation
        )
    )
    if hass.state is CoreState.running:
        _schedule()
    else:
        entry.async_on_unload(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _schedule)
        )
