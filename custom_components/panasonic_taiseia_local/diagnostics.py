"""Home Assistant config-entry diagnostics download."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_HUB
from .diagnostics_data import (
    async_build_device_diagnostics,
    async_build_hub_diagnostics,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (hub or device)."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
        return await async_build_hub_diagnostics(hass, entry)
    return await async_build_device_diagnostics(hass, entry)
