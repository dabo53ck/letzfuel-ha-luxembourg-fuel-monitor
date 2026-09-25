"""Config and options flow for LëtzFuel HA."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)

from .const import (
    CONF_CURRENT_LEVEL,
    CONF_LEVEL_ENTITY,
    CONF_LEVEL_SOURCE,
    CONF_PRIMARY_FUEL,
    CONF_PROVIDER,
    CONF_TANK_SIZE,
    CONF_TRACKED_FUELS,
    DEFAULT_EVENING_CHECK_TIME,
    DEFAULT_HISTORY_IMPORT_MONTHS,
    DEFAULT_PRICE_DISPLAY,
    DEFAULT_PRIMARY_FUEL,
    DEFAULT_PROVIDER,
    DEFAULT_TRACKED_FUELS,
    DEFAULT_TREND_WINDOW_DAYS,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
    LEVEL_ENTITY_DOMAINS,
    LEVEL_SOURCE_ENTITY,
    LEVEL_SOURCE_MANUAL,
    LEVEL_SOURCES,
    MAX_TREND_WINDOW_DAYS,
    MAX_UPDATE_INTERVAL_HOURS,
    MIN_TREND_WINDOW_DAYS,
    MIN_UPDATE_INTERVAL_HOURS,
    OPT_ANNOUNCEMENTS_ENABLED,
    OPT_EVENING_CHECK_TIME,
    OPT_HISTORY_IMPORT_ENABLED,
    OPT_HISTORY_IMPORT_MONTHS,
    OPT_PRICE_DISPLAY,
    OPT_TREND_WINDOW_DAYS,
    OPT_UPDATE_INTERVAL_HOURS,
    PRICE_DISPLAY_EXCL,
    PRICE_DISPLAY_INCL,
)
from .helpers import option_value
from .models import FuelType
from .providers import (
    ProviderConnectionError,
    ProviderParseError,
    get_provider,
)

_FUEL_OPTIONS = [f.value for f in FuelType]
_TITLE = "LëtzFuel HA"


def _fuel_select(*, multiple: bool) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=_FUEL_OPTIONS,
            multiple=multiple,
            mode=SelectSelectorMode.LIST if multiple else SelectSelectorMode.DROPDOWN,
            translation_key="fuel_type",
        )
    )


def _level_source_select() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=LEVEL_SOURCES,
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="level_source",
        )
    )


def _level_entity_select() -> EntitySelector:
    """Pick the entity the fuel level is read from.

    Filtered by domain only: the typical source (a car integration's tank
    sensor) carries no ``device_class`` and ``EntitySelector`` has no unit
    filter, so the 0-100 % range is validated later, when the value is read.
    """
    return EntitySelector(
        EntitySelectorConfig(domain=LEVEL_ENTITY_DOMAINS, multiple=False)
    )


class LuxFuelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration."""

    VERSION = 1
    #: 2: the old default evening check time (18:01) moves to 17:30.
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Init transient state."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: choose fuels + primary fuel; verify the source is reachable.

        Only one entry is allowed; ``single_config_entry`` in the manifest makes
        Home Assistant abort a second attempt with ``single_instance_allowed``.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            provider = get_provider(
                DEFAULT_PROVIDER, async_get_clientsession(self.hass)
            )
            try:
                await provider.async_get_history()
            except ProviderParseError:
                errors["base"] = "parse_error"
            except ProviderConnectionError:
                errors["base"] = "cannot_connect"

            if not errors:
                self._data = {
                    CONF_PROVIDER: DEFAULT_PROVIDER,
                    CONF_TRACKED_FUELS: user_input[CONF_TRACKED_FUELS],
                    CONF_PRIMARY_FUEL: user_input[CONF_PRIMARY_FUEL],
                }
                return await self.async_step_vehicle()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TRACKED_FUELS,
                    default=[f.value for f in DEFAULT_TRACKED_FUELS],
                ): _fuel_select(multiple=True),
                vol.Required(
                    CONF_PRIMARY_FUEL, default=DEFAULT_PRIMARY_FUEL.value
                ): _fuel_select(multiple=False),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2 (optional): vehicle tank size and current fuel level.

        The fuel level is either the manual slider (``current_level_pct``) or
        read live from another entity (``level_entity_id``).
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            source = user_input.get(CONF_LEVEL_SOURCE, LEVEL_SOURCE_MANUAL)
            level_entity = user_input.get(CONF_LEVEL_ENTITY)
            if source == LEVEL_SOURCE_ENTITY and not level_entity:
                errors["base"] = "level_entity_required"
            else:
                if user_input.get(CONF_TANK_SIZE):
                    self._data[CONF_TANK_SIZE] = user_input[CONF_TANK_SIZE]
                self._data[CONF_LEVEL_SOURCE] = source
                if source == LEVEL_SOURCE_ENTITY:
                    self._data[CONF_LEVEL_ENTITY] = level_entity
                elif user_input.get(CONF_CURRENT_LEVEL) is not None:
                    self._data[CONF_CURRENT_LEVEL] = user_input[CONF_CURRENT_LEVEL]
                return self.async_create_entry(title=_TITLE, data=self._data)

        schema = vol.Schema(
            {
                vol.Optional(CONF_TANK_SIZE): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=200,
                        step=1,
                        unit_of_measurement="L",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_LEVEL_SOURCE, default=LEVEL_SOURCE_MANUAL
                ): _level_source_select(),
                vol.Optional(CONF_CURRENT_LEVEL): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=100,
                        step=1,
                        unit_of_measurement="%",
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(CONF_LEVEL_ENTITY): _level_entity_select(),
            }
        )
        return self.async_show_form(
            step_id="vehicle", data_schema=schema, errors=errors, last_step=True
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> LuxFuelOptionsFlow:
        """Return the options flow."""
        return LuxFuelOptionsFlow()


class LuxFuelOptionsFlow(OptionsFlow):
    """Handle editing settings after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Single options page."""
        errors: dict[str, str] = {}
        if user_input is not None:
            source = user_input.get(CONF_LEVEL_SOURCE, LEVEL_SOURCE_MANUAL)
            if source == LEVEL_SOURCE_ENTITY and not user_input.get(CONF_LEVEL_ENTITY):
                errors["base"] = "level_entity_required"
            else:
                return self.async_create_entry(data=_clean_options(user_input))

        current = {**self.config_entry.data, **self.config_entry.options}

        def _get(key: str, default: Any) -> Any:
            return option_value(self.config_entry, key, default)

        schema = vol.Schema(
            {
                vol.Required(
                    OPT_UPDATE_INTERVAL_HOURS,
                    default=_get(
                        OPT_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_UPDATE_INTERVAL_HOURS,
                        max=MAX_UPDATE_INTERVAL_HOURS,
                        step=1,
                        unit_of_measurement="h",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    OPT_EVENING_CHECK_TIME,
                    default=_get(OPT_EVENING_CHECK_TIME, DEFAULT_EVENING_CHECK_TIME),
                ): TimeSelector(),
                vol.Required(
                    OPT_ANNOUNCEMENTS_ENABLED,
                    default=_get(OPT_ANNOUNCEMENTS_ENABLED, True),
                ): BooleanSelector(),
                vol.Required(
                    OPT_TREND_WINDOW_DAYS,
                    default=_get(OPT_TREND_WINDOW_DAYS, DEFAULT_TREND_WINDOW_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_TREND_WINDOW_DAYS,
                        max=MAX_TREND_WINDOW_DAYS,
                        step=1,
                        unit_of_measurement="d",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    OPT_PRICE_DISPLAY,
                    default=_get(OPT_PRICE_DISPLAY, DEFAULT_PRICE_DISPLAY),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[PRICE_DISPLAY_INCL, PRICE_DISPLAY_EXCL],
                        translation_key="price_display",
                    )
                ),
                vol.Required(
                    CONF_TRACKED_FUELS,
                    default=_get(
                        CONF_TRACKED_FUELS,
                        [f.value for f in DEFAULT_TRACKED_FUELS],
                    ),
                ): _fuel_select(multiple=True),
                vol.Required(
                    CONF_PRIMARY_FUEL,
                    default=_get(CONF_PRIMARY_FUEL, DEFAULT_PRIMARY_FUEL.value),
                ): _fuel_select(multiple=False),
                vol.Optional(
                    CONF_TANK_SIZE,
                    description={"suggested_value": current.get(CONF_TANK_SIZE)},
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=200,
                        step=1,
                        unit_of_measurement="L",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                # In "manual" mode the level is adjusted live via the
                # `number.*_current_fuel_level` slider entity, not here.
                vol.Required(
                    CONF_LEVEL_SOURCE,
                    default=_get(CONF_LEVEL_SOURCE, LEVEL_SOURCE_MANUAL),
                ): _level_source_select(),
                vol.Optional(
                    CONF_LEVEL_ENTITY,
                    description={"suggested_value": current.get(CONF_LEVEL_ENTITY)},
                ): _level_entity_select(),
                vol.Required(
                    OPT_HISTORY_IMPORT_ENABLED,
                    default=_get(OPT_HISTORY_IMPORT_ENABLED, True),
                ): BooleanSelector(),
                vol.Required(
                    OPT_HISTORY_IMPORT_MONTHS,
                    default=_get(
                        OPT_HISTORY_IMPORT_MONTHS, DEFAULT_HISTORY_IMPORT_MONTHS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=60,
                        step=1,
                        unit_of_measurement="months",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


def _clean_options(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalise numeric inputs and drop cleared optional fields."""
    options = dict(user_input)
    for int_key in (
        OPT_UPDATE_INTERVAL_HOURS,
        OPT_TREND_WINDOW_DAYS,
        OPT_HISTORY_IMPORT_MONTHS,
    ):
        if int_key in options and options[int_key] is not None:
            options[int_key] = int(options[int_key])
    if not options.get(CONF_TANK_SIZE):
        options.pop(CONF_TANK_SIZE, None)
    if options.get(CONF_CURRENT_LEVEL) is None:
        options.pop(CONF_CURRENT_LEVEL, None)
    if options.get(CONF_LEVEL_SOURCE) != LEVEL_SOURCE_ENTITY or not options.get(
        CONF_LEVEL_ENTITY
    ):
        options.pop(CONF_LEVEL_ENTITY, None)
    return options
