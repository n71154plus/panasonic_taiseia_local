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
    version: int | None = None,
) -> None:
    """Persist entry data/title/version without intending an options-driven reload.

    Relies on ``async_reload_entry`` only reloading when options change.
    """
    kwargs: dict[str, Any] = {}
    if data is not None:
        kwargs["data"] = data
    if title is not None:
        kwargs["title"] = title
    if version is not None:
        kwargs["version"] = version
    if not kwargs:
        return
    # Ensure snapshot exists so data-only updates are ignored by the listener.
    seed_options_snapshot(hass, entry)
    hass.config_entries.async_update_entry(entry, **kwargs)


def async_update_entry_options(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    options: dict[str, Any],
    reload: bool = True,
    data: dict[str, Any] | None = None,
    title: str | None = None,
) -> None:
    """Persist options; ``reload=True`` lets the update listener reload the entry.

    Use ``reload=False`` during setup (e.g. lock cloud control mode) so nested
    unload/reload does not race the current setup.
    """
    kwargs: dict[str, Any] = {"options": options}
    if data is not None:
        kwargs["data"] = data
    if title is not None:
        kwargs["title"] = title
    if reload:
        # Drop snapshot so options_changed_since_seed sees a real change.
        clear_options_snapshot(hass, entry.entry_id)
    else:
        # Pretend we are already at the target options → listener skips reload.
        domain = hass.data.setdefault(DOMAIN, {})
        snaps = domain.setdefault(_OPTIONS_SNAPSHOT, {})
        snaps[entry.entry_id] = dict(options)
    hass.config_entries.async_update_entry(entry, **kwargs)
