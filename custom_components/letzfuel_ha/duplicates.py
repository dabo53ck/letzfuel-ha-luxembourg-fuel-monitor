"""Repair issue when built-in notifications and a blueprint automation overlap.

With a notification target set up, an automation built from one of the
notifications blueprints sends the same notifications a second time. The
blueprint is recognised by its ``source_url``: Home Assistant picks the file
path itself when a blueprint is imported, so the path is not reliable.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import (
    DOMAIN,
    ISSUE_DUPLICATE_NOTIFICATIONS,
    NOTIFICATION_BLUEPRINT_SOURCES,
    SUBENTRY_NOTIFICATION,
)
from .coordinator import LuxFuelConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_blueprint_automations(hass: HomeAssistant) -> list[str]:
    """Entity ids of enabled automations built from a notifications blueprint."""
    if "automation" not in hass.config.components:
        return []
    from homeassistant.components.automation import (
        blueprint_in_automation,
    )
    from homeassistant.components.automation.helpers import (
        async_get_blueprints,
    )

    blueprints = async_get_blueprints(hass)
    found: list[str] = []
    for state in hass.states.async_all("automation"):
        if state.state != "on":
            continue
        path = blueprint_in_automation(hass, state.entity_id)
        if not path:
            continue
        try:
            blueprint = await blueprints.async_get_blueprint(path)
        except Exception:  # a broken or missing blueprint is not ours to report
            _LOGGER.debug("Could not read blueprint %s", path, exc_info=True)
            continue
        source = str(blueprint.metadata.get("source_url") or "")
        if any(marker in source for marker in NOTIFICATION_BLUEPRINT_SOURCES):
            found.append(state.entity_id)
    return sorted(found)


async def async_check_duplicates(
    hass: HomeAssistant, entry: LuxFuelConfigEntry
) -> None:
    """Raise or clear the duplicate-notifications repair issue."""
    has_target = any(
        sub.subentry_type == SUBENTRY_NOTIFICATION for sub in entry.subentries.values()
    )
    automations = await async_blueprint_automations(hass) if has_target else []
    if not automations:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_DUPLICATE_NOTIFICATIONS)
        return
    names = ", ".join(
        (state.name if (state := hass.states.get(eid)) else eid) for eid in automations
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_DUPLICATE_NOTIFICATIONS,
        is_fixable=True,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_DUPLICATE_NOTIFICATIONS,
        translation_placeholders={"automations": names},
        data={"automations": automations},
    )
