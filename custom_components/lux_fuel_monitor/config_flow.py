"""Config and options flow for Luxembourg Fuel Monitor."""

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
    MAX_TREND_WINDOW_DAYS,
    MAX_UPDATE_INTERVAL_HOURS,
    MIN_TREND_WINDOW_DAYS,
    MIN_UPDATE_INTERVAL_HOURS,
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
_TITLE = "Luxembourg Fuel Monitor"


def _fuel_select(*, multiple: bool) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=_FUEL_OPTIONS,
            multiple=multiple,
            mode=SelectSelectorMode.LIST if multiple else SelectSelectorMode.DROPDOWN,
            translation_key="fuel_type",
        )
    )


class LuxFuelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial configuration."""

    VERSION = 1

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
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2 (optional): vehicle tank size and current fuel level."""
        if user_input is not None:
            if user_input.get(CONF_TANK_SIZE):
                self._data[CONF_TANK_SIZE] = user_input[CONF_TANK_SIZE]
            if user_input.get(CONF_CURRENT_LEVEL) is not None:
                self._data[CONF_CURRENT_LEVEL] = user_input[CONF_CURRENT_LEVEL]
            return self.async_create_entry(title=_TITLE, data=self._data)

        schema = vol.Schema(
            {
                vol.Optional(CONF_TANK_SIZE): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=200, step=1, unit_of_measurement="L",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_CURRENT_LEVEL): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=100, step=1, unit_of_measurement="%",
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="vehicle", data_schema=schema, last_step=True
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
        if user_input is not None:
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
                        min=1, max=200, step=1, unit_of_measurement="L",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                # The current fuel level is adjusted live via the
                # `number.*_current_fuel_level` slider entity, not here.
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
                        min=1, max=60, step=1, unit_of_measurement="months",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


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
    return options
