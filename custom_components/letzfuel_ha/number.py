"""Number platform: the live current fuel level.

Exposed as a slider so the fuel level (which changes every time you drive or
refuel) can be adjusted from a dashboard, instead of only in the options dialog.
It feeds ``sensor.*_refill_cost``.
"""

from __future__ import annotations

from homeassistant.components.number import (
    ENTITY_ID_FORMAT,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LEVEL_SOURCE_MANUAL
from .coordinator import LuxFuelConfigEntry, LuxFuelCoordinator
from .entity import LuxFuelEntity, stable_entity_id

_DEFAULT_LEVEL = 50.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxFuelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the fuel-level number for a manual tank with a configured size.

    In "entity" mode the level is read from another entity, so the slider would
    be a dead control -- it is not created.
    """
    coordinator = entry.runtime_data
    if coordinator.tank_size and coordinator.level_source == LEVEL_SOURCE_MANUAL:
        async_add_entities([CurrentFuelLevelNumber(coordinator)])


class CurrentFuelLevelNumber(LuxFuelEntity, RestoreNumber):
    """User-adjustable current fuel level (%)."""

    _attr_translation_key = "current_fuel_level"
    _attr_icon = "mdi:gas-station"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: LuxFuelCoordinator) -> None:
        """Set the unique id and a stable, language-independent entity_id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_current_fuel_level"
        self.entity_id = stable_entity_id(
            coordinator, ENTITY_ID_FORMAT, "current_fuel_level"
        )

    async def async_added_to_hass(self) -> None:
        """Restore the last value (falling back to the configured level)."""
        await super().async_added_to_hass()
        value: float
        restored = await self.async_get_last_number_data()
        if restored is not None and restored.native_value is not None:
            value = float(restored.native_value)
        elif self.coordinator.configured_level_pct is not None:
            value = self.coordinator.configured_level_pct
        else:
            value = _DEFAULT_LEVEL
        self.coordinator.manual_fuel_level = value
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """User input stays adjustable even if the price feed is down."""
        return True

    @property
    def native_value(self) -> float | None:
        """Return the current level."""
        return self.coordinator.manual_fuel_level

    async def async_set_native_value(self, value: float) -> None:
        """Store the new level and refresh the dependent sensors."""
        self.coordinator.manual_fuel_level = value
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()
