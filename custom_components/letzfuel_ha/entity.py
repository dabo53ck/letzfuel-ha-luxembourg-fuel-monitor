"""Shared entity base for LëtzFuel HA."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LuxFuelCoordinator


def stable_entity_id(
    coordinator: LuxFuelCoordinator, entity_id_format: str, slug: str
) -> str:
    """Return a language-independent ``entity_id`` suggestion.

    By default Home Assistant builds the ``entity_id`` by slugifying the
    *translated* entity name, so the same sensor lands at
    ``sensor.letzfuel_ha_tankempfehlung`` on a German instance and
    ``sensor.letzfuel_ha_refuel_recommendation`` on an English one. That makes
    the entities impossible to reference from the shared notification blueprint
    or from the documentation. Pinning ``entity_id`` here fixes the slug to the
    English form on every install, in every language.

    Entities that already exist keep whatever ``entity_id`` the registry stored
    for their ``unique_id``, so this only affects first creation.
    """
    return async_generate_entity_id(
        entity_id_format, f"{DOMAIN}_{slug}", hass=coordinator.hass
    )


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
            model="Luxembourg regulated maximum fuel prices",
            configuration_url=coordinator.provider.source_url,
            entry_type=DeviceEntryType.SERVICE,
        )
