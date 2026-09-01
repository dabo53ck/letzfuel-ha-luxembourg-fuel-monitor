"""Shared entity base for LëtzFuel HA."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LuxFuelCoordinator


class LuxFuelEntity(CoordinatorEntity[LuxFuelCoordinator]):
    """Base entity: shared device, attribution and naming behaviour."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LuxFuelCoordinator) -> None:
        """Attach the coordinator and describe the (single) service device."""
        super().__init__(coordinator)
        self._attr_attribution = coordinator.provider.attribution
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name="LëtzFuel HA",
            manufacturer="LëtzFuel HA",
            model="Luxembourg official maximum fuel prices",
            configuration_url=coordinator.provider.source_url,
            entry_type=DeviceEntryType.SERVICE,
        )
