"""Config and options flow for LëtzFuel HA."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import SectionConfig, section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
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
    DOMAIN,
    FUEL_CHOICE_PRIMARY,
    LEVEL_ENTITY_DOMAINS,
    LEVEL_SOURCE_ENTITY,
    LEVEL_SOURCE_MANUAL,
    LEVEL_SOURCES,
    MAX_TREND_WINDOW_DAYS,
    MIN_TREND_WINDOW_DAYS,
    NOTIFY_ANNOUNCED,
    NOTIFY_COUNTDOWN,
    NOTIFY_DEVICES,
    NOTIFY_EFFECTIVE,
    NOTIFY_LANGUAGE,
    NOTIFY_PRESENCE,
    NOTIFY_RECOMMENDATION,
    NOTIFY_TAP_PATH,
    NOTIFY_THRESHOLD,
    OPT_ANNOUNCEMENTS_ENABLED,
    OPT_EVENING_CHECK_TIME,
    OPT_HISTORY_IMPORT_ENABLED,
    OPT_HISTORY_IMPORT_MONTHS,
    OPT_PRICE_DISPLAY,
    OPT_TREND_WINDOW_DAYS,
    PRICE_DISPLAY_EXCL,
    PRICE_DISPLAY_INCL,
    PRIORITY_CRITICAL,
    PRIORITY_ELEVATED,
    PRIORITY_NORMAL,
    RECOMMENDATION_REFUEL_TODAY,
    RECOMMENDATION_WAIT,
    SUBENTRY_NOTIFICATION,
)
from .helpers import option_value
from .models import FuelType
from .notification_texts import SUPPORTED_LANGUAGES
from .notifications import default_language
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
    #: 3: earlier default evening check times move to the current default.
    #: 4: the update interval is no longer a setting; its stored value is dropped.
    MINOR_VERSION = 4

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
            if not _primary_is_tracked(user_input):
                errors["base"] = "primary_not_tracked"
            else:
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

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Recipients are added as subentries."""
        return {SUBENTRY_NOTIFICATION: NotificationSubentryFlow}


class LuxFuelOptionsFlow(OptionsFlow):
    """Handle editing settings after setup: a menu with two pages."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["general", "vehicle"])

    def _get(self, key: str, default: Any) -> Any:
        return option_value(self.config_entry, key, default)

    def _save(self, values: dict[str, Any]) -> ConfigFlowResult:
        """Keep the options of the other page, replace this page's."""
        return self.async_create_entry(data={**self.config_entry.options, **values})

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prices, announcements, trend, display, fuels and history."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not _primary_is_tracked(user_input):
                errors["base"] = "primary_not_tracked"
            else:
                values = dict(user_input)
                for key in (OPT_TREND_WINDOW_DAYS, OPT_HISTORY_IMPORT_MONTHS):
                    if values.get(key) is not None:
                        values[key] = int(values[key])
                return self._save(values)

        schema = vol.Schema(
            {
                vol.Required(
                    OPT_EVENING_CHECK_TIME,
                    default=self._get(
                        OPT_EVENING_CHECK_TIME, DEFAULT_EVENING_CHECK_TIME
                    ),
                ): TimeSelector(),
                vol.Required(
                    OPT_ANNOUNCEMENTS_ENABLED,
                    default=self._get(OPT_ANNOUNCEMENTS_ENABLED, True),
                ): BooleanSelector(),
                vol.Required(
                    OPT_TREND_WINDOW_DAYS,
                    default=self._get(OPT_TREND_WINDOW_DAYS, DEFAULT_TREND_WINDOW_DAYS),
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
                    default=self._get(OPT_PRICE_DISPLAY, DEFAULT_PRICE_DISPLAY),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[PRICE_DISPLAY_INCL, PRICE_DISPLAY_EXCL],
                        translation_key="price_display",
                    )
                ),
                vol.Required(
                    CONF_TRACKED_FUELS,
                    default=self._get(
                        CONF_TRACKED_FUELS, [f.value for f in DEFAULT_TRACKED_FUELS]
                    ),
                ): _fuel_select(multiple=True),
                vol.Required(
                    CONF_PRIMARY_FUEL,
                    default=self._get(CONF_PRIMARY_FUEL, DEFAULT_PRIMARY_FUEL.value),
                ): _fuel_select(multiple=False),
                vol.Required(
                    OPT_HISTORY_IMPORT_ENABLED,
                    default=self._get(OPT_HISTORY_IMPORT_ENABLED, True),
                ): BooleanSelector(),
                vol.Required(
                    OPT_HISTORY_IMPORT_MONTHS,
                    default=self._get(
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
        return self.async_show_form(
            step_id="general", data_schema=schema, errors=errors
        )

    async def async_step_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Tank size and where the fuel level comes from."""
        errors: dict[str, str] = {}
        if user_input is not None:
            source = user_input.get(CONF_LEVEL_SOURCE, LEVEL_SOURCE_MANUAL)
            if source == LEVEL_SOURCE_ENTITY and not user_input.get(CONF_LEVEL_ENTITY):
                errors["base"] = "level_entity_required"
            else:
                return self._save(_clean_vehicle(user_input))

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
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
                    default=self._get(CONF_LEVEL_SOURCE, LEVEL_SOURCE_MANUAL),
                ): _level_source_select(),
                vol.Optional(
                    CONF_LEVEL_ENTITY,
                    description={"suggested_value": current.get(CONF_LEVEL_ENTITY)},
                ): _level_entity_select(),
            }
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="vehicle", data_schema=schema, errors=errors
        )


def _primary_is_tracked(user_input: dict[str, Any]) -> bool:
    """The primary fuel drives the vehicle and recommendation sensors."""
    return user_input.get(CONF_PRIMARY_FUEL) in (
        user_input.get(CONF_TRACKED_FUELS) or []
    )


def _clean_vehicle(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalise the vehicle page."""
    values = dict(user_input)
    if not values.get(CONF_TANK_SIZE):
        # Stored as None rather than dropped: a missing key would fall back to
        # the size entered during the initial setup (see ``option_value``).
        values[CONF_TANK_SIZE] = None
    if values.get(CONF_LEVEL_SOURCE) != LEVEL_SOURCE_ENTITY or not values.get(
        CONF_LEVEL_ENTITY
    ):
        values[CONF_LEVEL_ENTITY] = None
    return values


# -- recipients (config subentries) ---------------------------------

_FUEL_CHOICES = [FUEL_CHOICE_PRIMARY, *_FUEL_OPTIONS]
_PRIORITIES = [PRIORITY_NORMAL, PRIORITY_ELEVATED, PRIORITY_CRITICAL]


def _choice(options: list[str], key: str, *, multiple: bool = False) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            multiple=multiple,
            mode=SelectSelectorMode.LIST if multiple else SelectSelectorMode.DROPDOWN,
            translation_key=key,
        )
    )


def _price_change_section(values: dict[str, Any], *, enabled: bool) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                "enabled", default=values.get("enabled", enabled)
            ): BooleanSelector(),
            vol.Required(
                "fuels", default=values.get("fuels", [FUEL_CHOICE_PRIMARY])
            ): _choice(_FUEL_CHOICES, "notify_fuel", multiple=True),
            vol.Required("direction", default=values.get("direction", "both")): _choice(
                ["both", "up", "down"], "notify_direction"
            ),
            vol.Required(
                "min_delta", default=values.get("min_delta", 0)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=0.5,
                    step=0.001,
                    unit_of_measurement="€/L",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                "priority", default=values.get("priority", PRIORITY_NORMAL)
            ): _choice(_PRIORITIES, "notify_priority"),
        }
    )


def _target_schema(hass: Any, data: dict[str, Any], title: str) -> vol.Schema:
    presence = data.get(NOTIFY_PRESENCE, {})
    rec = data.get(NOTIFY_RECOMMENDATION, {})
    threshold = data.get(NOTIFY_THRESHOLD, {})
    collapsed = SectionConfig(collapsed=True)
    return vol.Schema(
        {
            vol.Required("name", default=title): TextSelector(),
            vol.Required(
                NOTIFY_DEVICES, default=data.get(NOTIFY_DEVICES, [])
            ): DeviceSelector(
                DeviceSelectorConfig(integration="mobile_app", multiple=True)
            ),
            vol.Required(
                NOTIFY_LANGUAGE,
                default=data.get(NOTIFY_LANGUAGE, default_language(hass)),
            ): _choice(list(SUPPORTED_LANGUAGES), "notify_language"),
            vol.Optional(
                NOTIFY_TAP_PATH,
                description={"suggested_value": data.get(NOTIFY_TAP_PATH)},
            ): TextSelector(),
            vol.Required(NOTIFY_ANNOUNCED): section(
                _price_change_section(data.get(NOTIFY_ANNOUNCED, {}), enabled=True),
                collapsed,
            ),
            vol.Required(NOTIFY_EFFECTIVE): section(
                _price_change_section(data.get(NOTIFY_EFFECTIVE, {}), enabled=False),
                collapsed,
            ),
            vol.Required(NOTIFY_RECOMMENDATION): section(
                vol.Schema(
                    {
                        vol.Required(
                            "enabled", default=rec.get("enabled", False)
                        ): BooleanSelector(),
                        vol.Required(
                            "states",
                            default=rec.get("states", [RECOMMENDATION_REFUEL_TODAY]),
                        ): _choice(
                            [RECOMMENDATION_REFUEL_TODAY, RECOMMENDATION_WAIT],
                            "notify_recommendation",
                            multiple=True,
                        ),
                        vol.Required(
                            "no_change", default=rec.get("no_change", False)
                        ): BooleanSelector(),
                        vol.Required(
                            "priority", default=rec.get("priority", PRIORITY_NORMAL)
                        ): _choice(_PRIORITIES, "notify_priority"),
                    }
                ),
                collapsed,
            ),
            vol.Required(NOTIFY_COUNTDOWN): section(
                vol.Schema(
                    {
                        vol.Required(
                            "enabled",
                            default=data.get(NOTIFY_COUNTDOWN, {}).get(
                                "enabled", False
                            ),
                        ): BooleanSelector(),
                    }
                ),
                collapsed,
            ),
            vol.Required(NOTIFY_THRESHOLD): section(
                vol.Schema(
                    {
                        vol.Required(
                            "enabled", default=threshold.get("enabled", False)
                        ): BooleanSelector(),
                        vol.Required(
                            "fuels",
                            default=threshold.get("fuels", [FUEL_CHOICE_PRIMARY]),
                        ): _choice(_FUEL_CHOICES, "notify_fuel", multiple=True),
                        vol.Required(
                            "below", default=threshold.get("below", 0)
                        ): NumberSelector(
                            NumberSelectorConfig(
                                min=0,
                                max=5,
                                step=0.001,
                                unit_of_measurement="€/L",
                                mode=NumberSelectorMode.BOX,
                            )
                        ),
                        vol.Required(
                            "priority",
                            default=threshold.get("priority", PRIORITY_NORMAL),
                        ): _choice(_PRIORITIES, "notify_priority"),
                    }
                ),
                collapsed,
            ),
            vol.Required(NOTIFY_PRESENCE): section(
                vol.Schema(
                    {
                        vol.Optional(
                            "entity",
                            description={"suggested_value": presence.get("entity")},
                        ): EntitySelector(
                            EntitySelectorConfig(domain=["person", "group"])
                        ),
                        vol.Required(
                            "mode", default=presence.get("mode", "home")
                        ): _choice(["home", "away"], "notify_presence_mode"),
                        vol.Required(
                            "critical_overrides",
                            default=presence.get("critical_overrides", True),
                        ): BooleanSelector(),
                    }
                ),
                collapsed,
            ),
        }
    )


def _split_target(user_input: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    data = dict(user_input)
    title = str(data.pop("name", "")).strip()
    if not (data.get(NOTIFY_TAP_PATH) or "").strip():
        data.pop(NOTIFY_TAP_PATH, None)
    return title, data


class NotificationSubentryFlow(ConfigSubentryFlow):
    """Add or edit a recipient."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            title, data = _split_target(user_input)
            if not data.get(NOTIFY_DEVICES):
                errors[NOTIFY_DEVICES] = "no_devices"
            else:
                return self.async_create_entry(
                    title=title or "Notifications", data=data
                )
        schema = _target_schema(self.hass, {}, "")
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            title, data = _split_target(user_input)
            if not data.get(NOTIFY_DEVICES):
                errors[NOTIFY_DEVICES] = "no_devices"
            else:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=title or subentry.title,
                    data=data,
                )
        schema = _target_schema(self.hass, dict(subentry.data), subentry.title)
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )
