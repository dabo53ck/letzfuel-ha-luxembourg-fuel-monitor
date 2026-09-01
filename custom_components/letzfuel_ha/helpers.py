"""Small shared helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry


def option_value(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Read a setting, preferring the options flow value over the initial config.

    Several settings (tracked fuels, tank size, primary fuel, ...) are captured in
    the config flow but remain editable in the options flow. This keeps every
    read consistent.
    """
    if key in entry.options:
        return entry.options[key]
    if key in entry.data:
        return entry.data[key]
    return default
