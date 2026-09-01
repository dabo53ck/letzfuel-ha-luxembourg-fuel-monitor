"""Sensor platform for LëtzFuel HA."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .analytics import compute_trend, refuel_recommendation
from .const import (
    CURRENCY_EURO,
    RECOMMENDATION_STATES,
    TREND_STATES,
    UNIT_EUR_PER_LITER,
    VAT_RATE_LU,
)
from .coordinator import LuxFuelConfigEntry, LuxFuelCoordinator
from .entity import LuxFuelEntity
from .models import FUEL_LABELS, FuelType

# --- description ------------------------------------------------------------

ValueFn = Callable[[LuxFuelCoordinator, "FuelType | None"], StateType | datetime]
AttrsFn = Callable[[LuxFuelCoordinator, "FuelType | None"], Mapping[str, Any]]
AvailFn = Callable[[LuxFuelCoordinator, "FuelType | None"], bool]


@dataclass(frozen=True, kw_only=True)
class LuxFuelSensorDescription(SensorEntityDescription):
    """Describes a LëtzFuel HA sensor."""

    value_fn: ValueFn
    attributes_fn: AttrsFn | None = None
    available_fn: AvailFn | None = None
    per_fuel: bool = False
    needs_tank: bool = False
    #: Enabled by default only for the configured primary fuel (disabled for the
    #: other tracked fuels). Ignored for non per-fuel sensors.
    primary_only_default: bool = False


# --- helpers -------------------------------------------------------------


def _pct_change(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return round((current - previous) / previous * 100, 3)


def _display(coordinator: LuxFuelCoordinator, point: Any) -> float | None:
    return coordinator.display_price(point)


# --- per-fuel value / attribute functions --------------------------------


def _price_value(coordinator: LuxFuelCoordinator, fuel: FuelType | None) -> float | None:
    fp = coordinator.fuel_prices(fuel)  # type: ignore[arg-type]
    return coordinator.display_price(fp.current) if fp else None


def _price_attrs(
    coordinator: LuxFuelCoordinator, fuel: FuelType | None
) -> Mapping[str, Any]:
    fp = coordinator.fuel_prices(fuel)  # type: ignore[arg-type]
    if fp is None:
        return {}
    data = coordinator.data
    attrs: dict[str, Any] = {
        "currency": CURRENCY_EURO,
        "fuel_type": fp.fuel.value,
        "effective_date": fp.current.effective_date.isoformat(),
        "price_incl_vat": float(fp.current.price_incl_vat),
        "price_excl_vat": float(fp.current.price_excl_vat),
        "vat_rate": VAT_RATE_LU,
        "price_since": fp.current_since.isoformat(),
        "previous_price": (
            _display(coordinator, fp.previous) if fp.previous else None
        ),
        "previous_effective_date": (
            fp.previous.effective_date.isoformat() if fp.previous else None
        ),
        "source": data.provider_name if data else None,
        "source_url": data.source_url if data else None,
    }
    if fp.upcoming is not None:
        attrs["next_price"] = _display(coordinator, fp.upcoming)
        attrs["next_effective_date"] = fp.upcoming.effective_date.isoformat()
    return attrs


def _change_value(
    coordinator: LuxFuelCoordinator, fuel: FuelType | None
) -> float | None:
    fp = coordinator.fuel_prices(fuel)  # type: ignore[arg-type]
    if fp is None:
        return None
    if fp.previous is None:
        return 0.0
    current = coordinator.display_price(fp.current)
    previous = coordinator.display_price(fp.previous)
    if current is None or previous is None:
        return None
    return round(current - previous, 4)


def _change_attrs(
    coordinator: LuxFuelCoordinator, fuel: FuelType | None
) -> Mapping[str, Any]:
    fp = coordinator.fuel_prices(fuel)  # type: ignore[arg-type]
    if fp is None:
        return {}
    current = coordinator.display_price(fp.current) or 0.0
    previous = (
        coordinator.display_price(fp.previous) if fp.previous else None
    )
    days_at_price = (dt_util.now().date() - fp.current_since).days
    return {
        "current_price": current,
        "previous_price": previous,
        "percentage_change": (
            _pct_change(current, previous) if previous is not None else None
        ),
        "change_date": fp.current_since.isoformat(),
        "days_at_current_price": days_at_price,
    }


def _trend_value(coordinator: LuxFuelCoordinator, fuel: FuelType | None) -> str:
    result = compute_trend(
        coordinator.recent_history(fuel),  # type: ignore[arg-type]
        coordinator.trend_window_days,
        use_incl_vat=coordinator.use_incl_vat,
    )
    return result.state


def _trend_attrs(
    coordinator: LuxFuelCoordinator, fuel: FuelType | None
) -> Mapping[str, Any]:
    result = compute_trend(
        coordinator.recent_history(fuel),  # type: ignore[arg-type]
        coordinator.trend_window_days,
        use_incl_vat=coordinator.use_incl_vat,
    )
    return {
        "trend_strength": result.strength_per_week,
        "trend_strength_unit": "€/L per week",
        "trend_window_days": coordinator.trend_window_days,
        "samples_used": result.samples,
        "window_start": (
            result.window_start.isoformat() if result.window_start else None
        ),
        "window_end": result.window_end.isoformat() if result.window_end else None,
    }


def _tomorrow_value(
    coordinator: LuxFuelCoordinator, fuel: FuelType | None
) -> float | None:
    fp = coordinator.fuel_prices(fuel)  # type: ignore[arg-type]
    if fp is None or fp.upcoming is None:
        return None
    return coordinator.display_price(fp.upcoming)


def _tomorrow_attrs(
    coordinator: LuxFuelCoordinator, fuel: FuelType | None
) -> Mapping[str, Any]:
    fp = coordinator.fuel_prices(fuel)  # type: ignore[arg-type]
    if fp is None or fp.upcoming is None:
        return {}
    delta = coordinator.display_price(fp.upcoming) - coordinator.display_price(fp.current)  # type: ignore[operator]
    return {
        "effective_date": fp.upcoming.effective_date.isoformat(),
        "change_vs_today": round(delta, 4),
        "direction": "up" if delta > 0 else "down" if delta < 0 else "unchanged",
    }


# --- global value / attribute functions --------------------------------


def _recommendation_value(
    coordinator: LuxFuelCoordinator, _fuel: FuelType | None
) -> str:
    return refuel_recommendation(coordinator.fuel_prices(coordinator.primary_fuel))


def _recommendation_attrs(
    coordinator: LuxFuelCoordinator, _fuel: FuelType | None
) -> Mapping[str, Any]:
    fp = coordinator.fuel_prices(coordinator.primary_fuel)
    if fp is None:
        return {"primary_fuel": coordinator.primary_fuel.value}
    today = coordinator.display_price(fp.current)
    tomorrow = coordinator.display_price(fp.upcoming) if fp.upcoming else None
    delta = (
        round(tomorrow - today, 4)
        if tomorrow is not None and today is not None
        else None
    )
    saving = (
        round(abs(delta) * coordinator.tank_size, 2)
        if delta is not None and coordinator.tank_size
        else None
    )
    return {
        "primary_fuel": coordinator.primary_fuel.value,
        "today_price": today,
        "tomorrow_price": tomorrow,
        "delta": delta,
        "potential_saving_full_tank": saving,
    }


def _last_update_value(
    coordinator: LuxFuelCoordinator, _fuel: FuelType | None
) -> datetime | None:
    fp = coordinator.fuel_prices(coordinator.primary_fuel)
    if fp is None:
        return None
    return dt_util.start_of_local_day(fp.current_since)


def _last_update_attrs(
    coordinator: LuxFuelCoordinator, _fuel: FuelType | None
) -> Mapping[str, Any]:
    data = coordinator.data
    return {
        "last_fetch_success": coordinator.last_update_success,
        "fetched_at": data.fetched_at.isoformat() if data else None,
        "source": data.provider_name if data else None,
        "source_url": data.source_url if data else None,
    }


def _days_since_change_value(
    coordinator: LuxFuelCoordinator, _fuel: FuelType | None
) -> int | None:
    fp = coordinator.fuel_prices(coordinator.primary_fuel)
    if fp is None:
        return None
    return (dt_util.now().date() - fp.current_since).days


# --- vehicle value / attribute functions --------------------------------


def _primary_price(coordinator: LuxFuelCoordinator) -> float | None:
    fp = coordinator.fuel_prices(coordinator.primary_fuel)
    return coordinator.display_price(fp.current) if fp else None


def _full_tank_value(
    coordinator: LuxFuelCoordinator, _fuel: FuelType | None
) -> float | None:
    price = _primary_price(coordinator)
    if price is None or not coordinator.tank_size:
        return None
    return round(coordinator.tank_size * price, 2)


def _full_tank_attrs(
    coordinator: LuxFuelCoordinator, _fuel: FuelType | None
) -> Mapping[str, Any]:
    return {
        "tank_size": coordinator.tank_size,
        "fuel_type": coordinator.primary_fuel.value,
        "price_per_liter": _primary_price(coordinator),
    }


def _refill_value(
    coordinator: LuxFuelCoordinator, _fuel: FuelType | None
) -> float | None:
    price = _primary_price(coordinator)
    level = coordinator.current_level_pct
    if price is None or not coordinator.tank_size or level is None:
        return None
    missing_fraction = max(0.0, 1.0 - level / 100.0)
    return round(coordinator.tank_size * missing_fraction * price, 2)


def _refill_attrs(
    coordinator: LuxFuelCoordinator, _fuel: FuelType | None
) -> Mapping[str, Any]:
    level = coordinator.current_level_pct
    liters_needed = None
    if coordinator.tank_size and level is not None:
        liters_needed = round(
            coordinator.tank_size * max(0.0, 1.0 - level / 100.0), 2
        )
    return {
        "current_level_pct": level,
        "tank_size": coordinator.tank_size,
        "liters_needed": liters_needed,
        "price_per_liter": _primary_price(coordinator),
    }


def _full_tank_change_value(
    coordinator: LuxFuelCoordinator, _fuel: FuelType | None
) -> float | None:
    fp = coordinator.fuel_prices(coordinator.primary_fuel)
    if fp is None or fp.previous is None or not coordinator.tank_size:
        return None
    new_cost = coordinator.tank_size * (coordinator.display_price(fp.current) or 0.0)
    old_cost = coordinator.tank_size * (coordinator.display_price(fp.previous) or 0.0)
    return round(new_cost - old_cost, 2)


def _full_tank_change_attrs(
    coordinator: LuxFuelCoordinator, _fuel: FuelType | None
) -> Mapping[str, Any]:
    fp = coordinator.fuel_prices(coordinator.primary_fuel)
    if fp is None or fp.previous is None or not coordinator.tank_size:
        return {}
    new_price = coordinator.display_price(fp.current) or 0.0
    old_price = coordinator.display_price(fp.previous) or 0.0
    new_cost = round(coordinator.tank_size * new_price, 2)
    old_cost = round(coordinator.tank_size * old_price, 2)
    return {
        "old_full_tank_cost": old_cost,
        "new_full_tank_cost": new_cost,
        "difference": round(new_cost - old_cost, 2),
        "per_litre_change": round(new_price - old_price, 4),
        "change_date": fp.current_since.isoformat(),
    }


# --- descriptions ------------------------------------------------------------

PER_FUEL_SENSORS: tuple[LuxFuelSensorDescription, ...] = (
    LuxFuelSensorDescription(
        key="price",
        translation_key="price",
        per_fuel=True,
        native_unit_of_measurement=UNIT_EUR_PER_LITER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_price_value,
        attributes_fn=_price_attrs,
    ),
    LuxFuelSensorDescription(
        key="change",
        translation_key="change",
        per_fuel=True,
        native_unit_of_measurement=UNIT_EUR_PER_LITER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=_change_value,
        attributes_fn=_change_attrs,
    ),
    LuxFuelSensorDescription(
        key="trend",
        translation_key="trend",
        per_fuel=True,
        device_class=SensorDeviceClass.ENUM,
        options=list(TREND_STATES),
        primary_only_default=True,
        value_fn=_trend_value,
        attributes_fn=_trend_attrs,
    ),
    LuxFuelSensorDescription(
        key="price_tomorrow",
        translation_key="price_tomorrow",
        per_fuel=True,
        native_unit_of_measurement=UNIT_EUR_PER_LITER,
        suggested_display_precision=3,
        primary_only_default=True,
        value_fn=_tomorrow_value,
        attributes_fn=_tomorrow_attrs,
    ),
)

GLOBAL_SENSORS: tuple[LuxFuelSensorDescription, ...] = (
    LuxFuelSensorDescription(
        key="refuel_recommendation",
        translation_key="refuel_recommendation",
        device_class=SensorDeviceClass.ENUM,
        options=list(RECOMMENDATION_STATES),
        value_fn=_recommendation_value,
        attributes_fn=_recommendation_attrs,
    ),
    LuxFuelSensorDescription(
        key="last_price_update",
        translation_key="last_price_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_last_update_value,
        attributes_fn=_last_update_attrs,
    ),
    LuxFuelSensorDescription(
        key="days_since_last_change",
        translation_key="days_since_last_change",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=_days_since_change_value,
    ),
)

VEHICLE_SENSORS: tuple[LuxFuelSensorDescription, ...] = (
    LuxFuelSensorDescription(
        key="full_tank_cost",
        translation_key="full_tank_cost",
        needs_tank=True,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        value_fn=_full_tank_value,
        attributes_fn=_full_tank_attrs,
    ),
    LuxFuelSensorDescription(
        key="refill_cost",
        translation_key="refill_cost",
        needs_tank=True,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        value_fn=_refill_value,
        attributes_fn=_refill_attrs,
    ),
    LuxFuelSensorDescription(
        key="full_tank_cost_change",
        translation_key="full_tank_cost_change",
        needs_tank=True,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=CURRENCY_EURO,
        value_fn=_full_tank_change_value,
        attributes_fn=_full_tank_change_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxFuelConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensor entities for a config entry."""
    coordinator = entry.runtime_data
    entities: list[LuxFuelSensor] = []

    for fuel in coordinator.tracked_fuels:
        entities.extend(
            LuxFuelSensor(coordinator, description, fuel)
            for description in PER_FUEL_SENSORS
        )

    entities.extend(
        LuxFuelSensor(coordinator, description) for description in GLOBAL_SENSORS
    )

    if coordinator.tank_size:
        entities.extend(
            LuxFuelSensor(coordinator, description) for description in VEHICLE_SENSORS
        )

    async_add_entities(entities)


class LuxFuelSensor(LuxFuelEntity, SensorEntity):
    """A single LëtzFuel HA sensor, driven by its description."""

    entity_description: LuxFuelSensorDescription

    def __init__(
        self,
        coordinator: LuxFuelCoordinator,
        description: LuxFuelSensorDescription,
        fuel: FuelType | None = None,
    ) -> None:
        """Build the entity for ``description`` (optionally scoped to ``fuel``)."""
        super().__init__(coordinator)
        self.entity_description = description
        self._fuel = fuel
        suffix = f"{fuel.value}_{description.key}" if fuel else description.key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{suffix}"
        if fuel is not None:
            self._attr_translation_placeholders = {"fuel": FUEL_LABELS[fuel]}
        if description.primary_only_default:
            # On for the favourite fuel only; the other fuels' copies start off.
            self._attr_entity_registry_enabled_default = (
                fuel is not None and fuel == coordinator.primary_fuel
            )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current sensor value."""
        return self.entity_description.value_fn(self.coordinator, self._fuel)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return the description's extra attributes, if any."""
        if self.entity_description.attributes_fn is None:
            return None
        return dict(self.entity_description.attributes_fn(self.coordinator, self._fuel))

    @property
    def available(self) -> bool:
        """Available while the coordinator has data for this fuel."""
        if not super().available:
            return False
        if self._fuel is not None:
            return self.coordinator.fuel_prices(self._fuel) is not None
        return self.coordinator.data is not None
