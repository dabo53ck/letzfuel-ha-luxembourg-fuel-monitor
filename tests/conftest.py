"""Fixtures for the LëtzFuel HA tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.letzfuel_ha.const import (
    CONF_PRIMARY_FUEL,
    CONF_PROVIDER,
    CONF_TANK_SIZE,
    CONF_TRACKED_FUELS,
    DEFAULT_PROVIDER,
    DOMAIN,
    OPT_HISTORY_IMPORT_ENABLED,
)
from custom_components.letzfuel_ha.models import FuelType
from custom_components.letzfuel_ha.providers.live_sheet import LIVE_SHEET_URL
from custom_components.letzfuel_ha.providers.petrol_lu import SOURCE_URL
from custom_components.letzfuel_ha.providers.rtl_lu import RTL_CURRENT_URL

from .helpers import build_petrol_lu_html, sheet_json

D = Decimal


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom component in every test."""
    yield


@pytest.fixture(autouse=True)
def _no_ha_deprecation_reports(caplog: pytest.LogCaptureFixture):
    """Fail any test in which HA reports a deprecated API use by this component.

    Home Assistant logs "Detected that custom integration '<domain>' ..." for a
    deprecated call and stops supporting it a year later, so a regression here is
    only ever visible in a log line (CI runs against the latest HA release).
    """
    yield
    # caplog.records only holds the current phase (teardown, here), so the setup
    # and call phases have to be read explicitly.
    records = [
        *caplog.get_records("setup"),
        *caplog.get_records("call"),
        *caplog.records,
    ]
    reports = [
        record.getMessage()
        for record in records
        if record.name == "homeassistant.helpers.frame"
        and f"custom integration '{DOMAIN}'" in record.getMessage()
    ]
    assert not reports, "Home Assistant reported a deprecated API use:\n" + "\n".join(
        reports
    )


@pytest.fixture
def price_entries():
    """A small, deterministic price history anchored on 'today'.

    Diesel's most recent change was 8 days ago (1.800 -> 1.865); it was
    re-published unchanged today.
    """
    today = dt_util.now().date()
    return [
        (
            today - timedelta(days=20),
            {
                FuelType.DIESEL: (D("1.800"), D("1.539")),
                FuelType.SP95: (D("1.700"), D("1.453")),
                FuelType.SP98: (D("1.900"), D("1.624")),
            },
        ),
        (
            today - timedelta(days=8),
            {
                FuelType.DIESEL: (D("1.865"), D("1.594")),
                FuelType.SP95: (D("1.720"), D("1.470")),
                FuelType.SP98: (D("1.932"), D("1.651")),
            },
        ),
        (
            today,
            {
                FuelType.DIESEL: (D("1.865"), D("1.594")),
                FuelType.SP95: (D("1.792"), D("1.531")),
                FuelType.SP98: (D("1.983"), D("1.695")),
            },
        ),
    ]


@pytest.fixture
def mock_petrol_lu(
    aioclient_mock: AiohttpClientMocker, price_entries
) -> Callable[[list], None]:
    """Mock the petrol.lu page; returns a setter to change the body later."""

    def _set(
        entries: list,
        rtl_payload: dict | None = None,
        rtl_status: int = 200,
        sheet_payload: dict | None = None,
        sheet_status: int = 200,
    ) -> None:
        aioclient_mock.clear_requests()
        aioclient_mock.get(SOURCE_URL, text=build_petrol_lu_html(entries))
        # RTL announcement source: default to "no change announced" (date = today)
        # so tests that don't care about it are unaffected.
        aioclient_mock.get(
            RTL_CURRENT_URL,
            status=rtl_status,
            json=rtl_payload
            or {
                "id": 0,
                "date": f"{dt_util.now().date().isoformat()}T00:00:00+02:00",
                "98oct": 1.983,
                "95oct": 1.792,
                "diesel": 1.865,
            },
        )
        # Live sheet announcement source: agrees with petrol.lu on today's
        # prices (so it is trusted) and lists nothing beyond today.
        aioclient_mock.get(
            LIVE_SHEET_URL,
            status=sheet_status,
            json=sheet_payload
            or sheet_json(
                [
                    (
                        dt_util.now().date(),
                        {
                            FuelType.DIESEL: "1.865",
                            FuelType.SP95: "1.792",
                            FuelType.SP98: "1.983",
                        },
                    )
                ]
            ),
        )

    _set(price_entries)
    return _set


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A loaded-ready config entry (history import disabled for tests)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="LëtzFuel HA",
        data={
            CONF_PROVIDER: DEFAULT_PROVIDER,
            CONF_TRACKED_FUELS: [f.value for f in FuelType],
            CONF_PRIMARY_FUEL: FuelType.DIESEL.value,
        },
        options={OPT_HISTORY_IMPORT_ENABLED: False},
    )


@pytest.fixture
def config_entry_with_vehicle() -> MockConfigEntry:
    """Config entry that also configures a 50 L tank at 40%."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="LëtzFuel HA",
        data={
            CONF_PROVIDER: DEFAULT_PROVIDER,
            CONF_TRACKED_FUELS: [f.value for f in FuelType],
            CONF_PRIMARY_FUEL: FuelType.DIESEL.value,
            CONF_TANK_SIZE: 50,
            "current_level_pct": 40,
        },
        options={OPT_HISTORY_IMPORT_ENABLED: False},
    )


async def _setup_and_teardown(hass: HomeAssistant, entry: MockConfigEntry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_petrol_lu, config_entry: MockConfigEntry
):
    """Set up the integration and return the config entry (unloaded on teardown)."""
    async for entry in _setup_and_teardown(hass, config_entry):
        yield entry


@pytest.fixture
async def init_integration_vehicle(
    hass: HomeAssistant, mock_petrol_lu, config_entry_with_vehicle: MockConfigEntry
):
    """Set up the integration with a configured vehicle tank."""
    async for entry in _setup_and_teardown(hass, config_entry_with_vehicle):
        yield entry
