"""Repair flows for actionable integration failures."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a repair flow for an issue."""
    return EmsReauthRepairFlow()


class EmsReauthRepairFlow(RepairsFlow):
    """Guide the user into the hub reauthentication flow."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        if user_input is not None:
            entry_id = (self.data or {}).get("entry_id")
            entry = (
                self.hass.config_entries.async_get_entry(str(entry_id))
                if entry_id
                else None
            )
            if entry is not None:
                entry.async_start_reauth(self.hass)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
        )


# Keep ConfirmRepairFlow import used for HA typing / discovery patterns.
_ = ConfirmRepairFlow
