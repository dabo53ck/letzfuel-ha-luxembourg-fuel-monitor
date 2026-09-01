"""Fuel price provider registry.

Register a new Luxembourg source here and it becomes selectable without any other
change to the integration.
"""

from __future__ import annotations

from aiohttp import ClientSession

from .base import (
    FuelProvider,
    ProviderConnectionError,
    ProviderError,
    ProviderParseError,
    build_price_set,
)
from .petrol_lu import PetrolLuProvider

_PROVIDER_CLASSES: dict[str, type[FuelProvider]] = {
    PetrolLuProvider.key: PetrolLuProvider,
}

AVAILABLE_PROVIDERS: tuple[str, ...] = tuple(_PROVIDER_CLASSES)


def get_provider(key: str, session: ClientSession) -> FuelProvider:
    """Instantiate the provider registered under ``key``."""
    try:
        provider_cls = _PROVIDER_CLASSES[key]
    except KeyError as err:
        raise ValueError(f"Unknown fuel provider: {key}") from err
    return provider_cls(session)


__all__ = [
    "AVAILABLE_PROVIDERS",
    "FuelProvider",
    "ProviderConnectionError",
    "ProviderError",
    "ProviderParseError",
    "build_price_set",
    "get_provider",
]
