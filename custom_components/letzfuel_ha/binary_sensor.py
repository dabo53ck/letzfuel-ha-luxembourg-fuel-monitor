"""Binary sensor platform: is a next-day price change pending?"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LuxFuelConfigEntry
from .entity import LuxFuelEntity, stable_entity_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxFuelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the pending-change binary sensor."""
    async_add_entities([PriceChangePendingBinarySensor(entry.runtime_data)])


class PriceChangePendingBinarySensor(LuxFuelEntity, BinarySensorEntity):
    """On when the government has published a next-day price that differs from today."""

    _attr_translation_key = "price_change_pending"

    def __init__(self, coordinator: Any) -> None:
        """Set the unique id and a stable, language-independent entity_id."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_price_change_pending"
        )
        self.entity_id = stable_entity_id(
            coordinator, ENTITY_ID_FORMAT, "price_change_pending"
        )

    @property
    def is_on(self) -> bool:
        """Return True when any tracked fuel has a pending price change."""
        data = self.coordinator.data
        if data is None:
            return False
        return any(fp.has_pending_change for fp in data.prices.values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose which fuels change and by how much."""
        data = self.coordinator.data
        if data is None:
            return {}
        affected: list[str] = []
        deltas: dict[str, float] = {}
        effective_date: str | None = None
        for fuel, fp in data.prices.items():
            if not fp.has_pending_change or fp.upcoming is None:
                continue
            affected.append(fuel.value)
            deltas[fuel.value] = round(
                float(fp.upcoming.price_incl_vat - fp.current.price_incl_vat), 4
            )
            effective_date = fp.upcoming.effective_date.isoformat()
        return {
            "affected_fuels": affected,
            "deltas": deltas,
            "effective_date": effective_date,
        }
