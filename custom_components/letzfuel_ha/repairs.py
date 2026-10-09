"""Fix flows for LëtzFuel HA repair issues."""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .const import ISSUE_DUPLICATE_NOTIFICATIONS, NEW_BLUEPRINT_URL


class TurnOffBlueprintAutomationsFlow(RepairsFlow):
    """Turn off the blueprint automations that duplicate the notifications."""

    def __init__(self, automations: list[str]) -> None:
        self._automations = automations

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            await self.hass.services.async_call(
                "automation",
                "turn_off",
                {"entity_id": self._automations},
                blocking=True,
            )
            return self.async_create_entry(data={})
        names = ", ".join(
            (state.name if (state := self.hass.states.get(eid)) else eid)
            for eid in self._automations
        )
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "automations": names,
                "blueprint_url": NEW_BLUEPRINT_URL,
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Create the fix flow for a fixable issue."""
    assert issue_id == ISSUE_DUPLICATE_NOTIFICATIONS
    return TurnOffBlueprintAutomationsFlow(list((data or {}).get("automations", [])))
