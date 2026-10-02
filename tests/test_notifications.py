"""Tests for the built-in notifications and the recipient flow."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.letzfuel_ha.const import (
    CONF_PRIMARY_FUEL,
    CONF_PROVIDER,
    CONF_TRACKED_FUELS,
    DEFAULT_PROVIDER,
    DOMAIN,
    ISSUE_DUPLICATE_NOTIFICATIONS,
    OPT_HISTORY_IMPORT_ENABLED,
    RECOMMENDATION_STATES,
    SUBENTRY_NOTIFICATION,
)
from custom_components.letzfuel_ha.models import FuelType
from custom_components.letzfuel_ha.notification_texts import TEXTS
from custom_components.letzfuel_ha.notifications import (
    announced_lines,
    corrected_lines,
    default_language,
    effective_lines,
    payload,
)
from custom_components.letzfuel_ha.repairs import async_create_fix_flow

from .helpers import sheet_json

PERSON = "person.alex"


def _phone(hass: HomeAssistant, name: str = "phone") -> tuple[str, list[ServiceCall]]:
    """A Companion app device with its notify entity and a recording service."""
    entry = MockConfigEntry(domain="mobile_app", title=name)
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("mobile_app", name)}, name=name
    )
    er.async_get(hass).async_get_or_create(
        "notify",
        "mobile_app",
        f"{name}-notify",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id=name,
    )
    return device.id, async_mock_service(hass, "notify", f"mobile_app_{name}")


def _section(enabled: bool, **extra: Any) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "fuels": ["primary"],
        "direction": "both",
        "min_delta": 0,
        "priority": "normal",
        **extra,
    }


def _target(device_id: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "devices": [device_id],
        "language": "en",
        "announced": _section(True),
        "effective": _section(False),
        "recommendation": {
            "enabled": False,
            "states": ["refuel_today"],
            "no_change": False,
            "priority": "normal",
        },
        "countdown": {"enabled": False},
        "threshold": {
            "enabled": False,
            "fuels": ["primary"],
            "below": 0,
            "priority": "normal",
        },
        "presence": {"mode": "home", "critical_overrides": True},
    }
    data.update(overrides)
    return data


def _entry(*targets: dict[str, Any]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="LëtzFuel HA",
        version=1,
        minor_version=4,
        data={
            CONF_PROVIDER: DEFAULT_PROVIDER,
            CONF_TRACKED_FUELS: [f.value for f in FuelType],
            CONF_PRIMARY_FUEL: FuelType.DIESEL.value,
        },
        options={OPT_HISTORY_IMPORT_ENABLED: False},
        subentries_data=[
            ConfigSubentryData(
                data=t,
                subentry_type=SUBENTRY_NOTIFICATION,
                title=f"Target {i}",
                unique_id=None,
            )
            for i, t in enumerate(targets)
        ],
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _sheet(diesel: str) -> dict:
    """Today's prices (matching petrol.lu) plus tomorrow's Diesel."""
    today = dt_util.now().date()
    today_row = {
        FuelType.DIESEL: "1.865",
        FuelType.SP95: "1.792",
        FuelType.SP98: "1.983",
    }
    return sheet_json(
        [
            (today, today_row),
            (today + timedelta(days=1), {**today_row, FuelType.DIESEL: diesel}),
        ]
    )


def _tomorrow() -> str:
    return (dt_util.now().date() + timedelta(days=1)).strftime("%d/%m/%Y")


# -- texts and payload --------------------------------------------------------


def test_announced_lines_follow_the_filters() -> None:
    changes = [
        {
            "fuel": "diesel",
            "upcoming_price": 1.905,
            "delta": 0.04,
            "effective_date": "2026-10-02",
        },
        {
            "fuel": "sp95",
            "upcoming_price": 1.78,
            "delta": -0.012,
            "effective_date": "2026-10-02",
        },
    ]
    both = _section(True, fuels=["diesel", "sp95"])
    assert announced_lines(changes, both, FuelType.DIESEL, "en") == [
        "DIESEL: +4.0 ct/L → 1.905 €/L (02/10/2026)",
        "SP95: -1.2 ct/L → 1.780 €/L (02/10/2026)",
    ]
    up_only = _section(True, fuels=["diesel", "sp95"], direction="up")
    assert len(announced_lines(changes, up_only, FuelType.DIESEL, "en")) == 1
    big_only = _section(True, fuels=["diesel", "sp95"], min_delta=0.05)
    assert announced_lines(changes, big_only, FuelType.DIESEL, "de") == []
    assert announced_lines(changes, _section(True), FuelType.SP95, "de") == [
        "SP95: -1,2 ct/L → 1,780 €/L (02/10/2026)"
    ]


def test_effective_and_corrected_lines() -> None:
    changed = [
        {
            "fuel": "sp95",
            "old_price": 1.793,
            "new_price": 1.837,
            "effective_date": "2026-10-02",
        }
    ]
    assert effective_lines(
        changed, _section(True, fuels=["sp95"]), FuelType.DIESEL, "en"
    ) == ["SP95: 1.837 €/L (+4.4 ct/L)"]
    corrected = [
        {
            "fuel": "diesel",
            "effective_date": "2026-09-26",
            "announced_price": 2.055,
            "corrected_price": 2.095,
            "current_price": 2.095,
        }
    ]
    assert corrected_lines(corrected, _section(True), FuelType.DIESEL, "en") == [
        "DIESEL: 2.095 €/L (no change) instead of 2.055 €/L (26/09/2026)"
    ]


def test_payload_priorities() -> None:
    normal = payload("tag", "normal", {"entity_id": "sensor.x"})
    assert normal["group"] == "letzfuel_ha"
    assert normal["push"] == {"thread-id": "letzfuel_ha"}
    assert normal["entity_id"] == "sensor.x"
    critical = payload("tag", "critical", {})
    assert critical["channel"] == "alarm_stream"
    assert critical["push"]["interruption-level"] == "critical"
    assert (
        payload("tag", "elevated", {})["push"]["interruption-level"] == "time-sensitive"
    )


def test_every_recommendation_has_a_text() -> None:
    for language in TEXTS.values():
        assert set(language["rec_states"]) == set(RECOMMENDATION_STATES)


@pytest.mark.parametrize(
    ("ha", "expected"), [("de", "de"), ("fr-CH", "fr"), ("es", "en")]
)
def test_default_language(hass: HomeAssistant, ha: str, expected: str) -> None:
    hass.config.language = ha
    assert default_language(hass) == expected


# -- sending ----------------------------------------------------------------------


async def test_no_target_sends_nothing(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    _, calls = _phone(hass)
    entry = await _setup(hass, _entry())
    mock_petrol_lu(price_entries, sheet_payload=_sheet("1.905"))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert calls == []
    await _unload(hass, entry)


async def test_announcement_is_sent(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    device_id, calls = _phone(hass)
    entry = await _setup(hass, _entry(_target(device_id)))
    assert calls == []

    mock_petrol_lu(price_entries, sheet_payload=_sheet("1.905"))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["title"] == "Price change tomorrow"
    assert calls[0].data["message"] == f"DIESEL: +4.0 ct/L → 1.905 €/L ({_tomorrow()})"
    assert calls[0].data["data"]["tag"] == "letzfuel_announced"
    assert calls[0].data["data"]["entity_id"] == "sensor.letzfuel_ha_diesel_price"
    await _unload(hass, entry)


async def test_recommendation_and_countdown(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    device_id, calls = _phone(hass)
    target = _target(
        device_id,
        announced=_section(False),
        recommendation={
            "enabled": True,
            "states": ["refuel_today"],
            "no_change": False,
            "priority": "elevated",
        },
        countdown={"enabled": True},
    )
    entry = await _setup(hass, _entry(target))

    mock_petrol_lu(price_entries, sheet_payload=_sheet("1.905"))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert [c.data["data"]["tag"] for c in calls] == [
        "letzfuel_recommendation",
        "letzfuel_countdown",
    ]
    assert calls[0].data["message"] == "Refuel today"
    assert calls[0].data["data"]["push"]["interruption-level"] == "time-sensitive"
    assert calls[1].data["data"]["live_update"] is True
    assert calls[1].data["data"]["when"] > 0

    # once the recommendation moves on (normally just after midnight) the
    # countdown ends
    calls.clear()
    notifier = entry.runtime_data.notifier
    (subentry,) = entry.subentries.values()
    await notifier._recommendation(subentry, "refuel_today", "awaiting_price")
    await hass.async_block_till_done()
    assert [c.data["message"] for c in calls] == ["clear_notification"]
    await _unload(hass, entry)


async def test_restart_does_not_repeat_the_recommendation(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    device_id, calls = _phone(hass)
    target = _target(
        device_id,
        announced=_section(False),
        recommendation={
            "enabled": True,
            "states": ["refuel_today"],
            "no_change": False,
            "priority": "normal",
        },
    )
    entry = await _setup(hass, _entry(target))
    mock_petrol_lu(price_entries, sheet_payload=_sheet("1.905"))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert len(calls) == 1

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(calls) == 1
    await _unload(hass, entry)


async def test_threshold_fires_once_when_crossed(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    device_id, calls = _phone(hass)
    target = _target(
        device_id,
        announced=_section(False),
        threshold={
            "enabled": True,
            "fuels": ["primary"],
            "below": 1.85,
            "priority": "normal",
        },
    )
    entry = await _setup(hass, _entry(target))  # Diesel 1.865: above, no alert
    assert calls == []

    day, prices = price_entries[-1]
    cheaper = [
        *price_entries[:-1],
        (day, {**prices, FuelType.DIESEL: (D("1.840"), D("1.573"))}),
    ]
    sheet_today = {
        FuelType.DIESEL: "1.840",
        FuelType.SP95: "1.792",
        FuelType.SP98: "1.983",
    }
    mock_petrol_lu(
        cheaper, sheet_payload=sheet_json([(dt_util.now().date(), sheet_today)])
    )
    coordinator = entry.runtime_data
    coordinator.provider._cache = None  # skip the 5-min page cache
    await coordinator.async_refresh()
    await coordinator.async_refresh()  # still below: no second notification
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["title"] == "Price below your target"
    assert calls[0].data["message"] == "Diesel is at 1.840 €/L (target: below 1.850)."
    await _unload(hass, entry)


async def test_presence_gate(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    device_id, calls = _phone(hass)
    hass.states.async_set(PERSON, "not_home")
    target = _target(
        device_id,
        presence={"entity": PERSON, "mode": "home", "critical_overrides": True},
    )
    entry = await _setup(hass, _entry(target))

    mock_petrol_lu(price_entries, sheet_payload=_sheet("1.905"))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert calls == []
    await _unload(hass, entry)


# -- the send_notification action ----------------------------------------------------


async def _send(hass: HomeAssistant, **data: Any) -> dict[str, Any]:
    response = await hass.services.async_call(
        DOMAIN, "send_notification", data, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    assert response is not None
    return response


async def test_send_notification_action(
    hass: HomeAssistant, mock_petrol_lu, price_entries
) -> None:
    device_id, calls = _phone(hass)
    hass.states.async_set(PERSON, "not_home")
    target = _target(
        device_id,
        announced=_section(False),
        presence={"entity": PERSON, "mode": "home", "critical_overrides": True},
    )
    entry = await _setup(hass, _entry(target))
    mock_petrol_lu(price_entries, sheet_payload=_sheet("1.905"))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert calls == []  # switched off and away

    # preview: nothing is sent, the notification comes back
    response = await _send(hass, type="announced", target="target 0", preview=True)
    (result,) = response["results"]
    assert result["target"] == "Target 0"
    assert result["services"] == ["notify.mobile_app_phone"]
    assert result["sent"] is False
    assert result["notification"]["message"] == (
        f"DIESEL: +4.0 ct/L → 1.905 €/L ({_tomorrow()})"
    )
    assert calls == []

    # sent for real, although the type is off and nobody is home
    response = await _send(hass, type="recommendation")
    assert response["results"][0]["sent"] is True
    assert [c.data["message"] for c in calls] == ["Refuel today"]

    calls.clear()
    await _send(hass, type="countdown_end")
    assert [c.data["message"] for c in calls] == ["clear_notification"]

    # no price target set: nothing to send
    calls.clear()
    response = await _send(hass, type="threshold")
    assert response["results"][0] == {
        "target": "Target 0",
        "services": ["notify.mobile_app_phone"],
        "notification": None,
        "sent": False,
    }
    assert calls == []

    with pytest.raises(ServiceValidationError):
        await _send(hass, type="announced", target="Nobody")
    await _unload(hass, entry)


async def test_send_notification_without_targets(
    hass: HomeAssistant, mock_petrol_lu
) -> None:
    entry = await _setup(hass, _entry())
    with pytest.raises(ServiceValidationError):
        await _send(hass, type="announced")
    await _unload(hass, entry)


# -- the recipient flow ----------------------------------------------------


def _form(device_id: str | None, name: str = "Phone") -> dict[str, Any]:
    data = _target(device_id or "")
    if device_id is None:
        data["devices"] = []
    data.pop("presence")
    return {
        "name": name,
        **data,
        "presence": {"mode": "home", "critical_overrides": True},
    }


async def test_add_and_edit_a_target(hass: HomeAssistant, mock_petrol_lu) -> None:
    device_id, _ = _phone(hass)
    entry = await _setup(hass, _entry())
    coordinator = entry.runtime_data

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_NOTIFICATION), context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], _form(None)
    )
    assert result["errors"] == {"devices": "no_devices"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], _form(device_id)
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = entry.subentries.values()
    assert subentry.title == "Phone"
    assert subentry.data["devices"] == [device_id]
    # adding a target doesn't reload the integration
    assert entry.runtime_data is coordinator

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_NOTIFICATION),
        context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {**_form(device_id, "Alex"), "language": "de"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    subentry = entry.subentries[subentry.subentry_id]
    assert subentry.title == "Alex"
    assert subentry.data["language"] == "de"
    await _unload(hass, entry)


# -- duplicate notifications repair ---------------------------------------------------

_BLUEPRINT = """
blueprint:
  name: Test notifications
  domain: automation
  source_url: https://github.com/dabo53ck/letzfuel-ha-notifications-blueprint/blob/main/blueprints/automation/dabo53ck/letzfuel_ha_notifications.yaml
  input: {}
triggers:
  - trigger: event
    event_type: letzfuel_ha_price_change_announced
actions: []
"""


async def _blueprint_automation(hass: HomeAssistant, tmp_path: Path) -> str:
    folder = tmp_path / "blueprints/automation/test"
    folder.mkdir(parents=True)
    (folder / "notifications.yaml").write_text(_BLUEPRINT, encoding="utf-8")
    hass.config.config_dir = str(tmp_path)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "alias": "Fuel notifications",
                "use_blueprint": {"path": "test/notifications.yaml", "input": {}},
            }
        },
    )
    await hass.async_block_till_done()
    return "automation.fuel_notifications"


async def test_duplicate_notifications_repair(
    hass: HomeAssistant, mock_petrol_lu, tmp_path: Path
) -> None:
    automation = await _blueprint_automation(hass, tmp_path)
    device_id, _ = _phone(hass)
    entry = await _setup(hass, _entry(_target(device_id)))
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_DUPLICATE_NOTIFICATIONS)
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_placeholders == {"automations": "Fuel notifications"}

    flow = await async_create_fix_flow(hass, ISSUE_DUPLICATE_NOTIFICATIONS, issue.data)
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["step_id"] == "confirm"
    result = await flow.async_step_confirm({})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY

    assert hass.states.get(automation).state == "off"
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_DUPLICATE_NOTIFICATIONS)
        is None
    )
    await _unload(hass, entry)


async def test_no_repair_without_a_target(
    hass: HomeAssistant, mock_petrol_lu, tmp_path: Path
) -> None:
    await _blueprint_automation(hass, tmp_path)
    entry = await _setup(hass, _entry())
    await hass.async_block_till_done()

    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_DUPLICATE_NOTIFICATIONS)
        is None
    )
    await _unload(hass, entry)
