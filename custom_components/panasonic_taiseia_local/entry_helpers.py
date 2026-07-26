"""Config-entry helpers: reload only on options change; persist data without reload storms."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_OPTIONS_SNAPSHOT = "_options_snapshot"


def seed_options_snapshot(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Record current options so the next data-only update does not reload."""
    domain = hass.data.setdefault(DOMAIN, {})
    snaps = domain.setdefault(_OPTIONS_SNAPSHOT, {})
    snaps[entry.entry_id] = dict(entry.options)


def clear_options_snapshot(hass: HomeAssistant, entry_id: str) -> None:
    snaps = hass.data.get(DOMAIN, {}).get(_OPTIONS_SNAPSHOT)
    if isinstance(snaps, dict):
        snaps.pop(entry_id, None)


def options_changed_since_seed(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """True if options differ from the seeded snapshot (or no snapshot yet)."""
    snaps = hass.data.get(DOMAIN, {}).get(_OPTIONS_SNAPSHOT) or {}
    last = snaps.get(entry.entry_id)
    current = dict(entry.options)
    snaps[entry.entry_id] = current
    if last is None:
        return True
    return last != current


def async_update_entry_data(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    data: dict[str, Any] | None = None,
    title: str | None = None,
) -> None:
    """Persist entry data/title without intending an options-driven reload.

    Relies on ``async_reload_entry`` only reloading when options change.
    """
    kwargs: dict[str, Any] = {}
    if data is not None:
        kwargs["data"] = data
    if title is not None:
        kwargs["title"] = title
    if not kwargs:
        return
    # Ensure snapshot exists so data-only updates are ignored by the listener.
    seed_options_snapshot(hass, entry)
    hass.config_entries.async_update_entry(entry, **kwargs)
