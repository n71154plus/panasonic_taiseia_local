"""The Panasonic TaiSEIA local integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_UPDATE_INTERVAL,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .naming import async_suggest_name, format_local_title, looks_like_module_model
from .taiseia import TaiSeiaClient, TaiSeiaError

_LOGGER = logging.getLogger(__package__)


def _interval(entry: ConfigEntry) -> int:
    return (
        entry.options.get(CONF_UPDATE_INTERVAL)
        or entry.data.get(CONF_UPDATE_INTERVAL)
        or DEFAULT_UPDATE_INTERVAL
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    host = entry.data[CONF_HOST]
    session = async_get_clientsession(hass)
    client = TaiSeiaClient(session, host)

    try:
        await client.async_probe()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot reach TaiSEIA device at {host}: {err}") from err

    # Persist type + upgrade placeholder module-model titles to room nicknames
    new_data = dict(entry.data)
    changed = False
    if new_data.get("device_type") != client.device.sa_type_id:
        new_data["device_type"] = client.device.sa_type_id
        changed = True

    suggested = async_suggest_name(hass, client.device.mac)
    new_title = entry.title
    if suggested:
        if suggested.indoor_model and new_data.get("indoor_model") != suggested.indoor_model:
            new_data["indoor_model"] = suggested.indoor_model
            changed = True
        if looks_like_module_model(entry.data.get(CONF_NAME)) or looks_like_module_model(
            entry.title
        ):
            nice = format_local_title(suggested.nickname)
            new_data[CONF_NAME] = nice
            new_title = nice
            changed = True

    if changed:
        hass.config_entries.async_update_entry(entry, data=new_data, title=new_title)

    async def async_update_data():
        try:
            status = await client.async_fetch_status()
            return {
                "status": status,
                "device": client.device,
                "name": entry.data.get(CONF_NAME) or client.device.sa_model or host,
                "indoor_model": entry.data.get("indoor_model"),
            }
        except Exception as err:
            raise UpdateFailed(
                f"TaiSEIA update failed for {host}: {type(err).__name__}: {err}"
            ) from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"panasonic_taiseia_{host}",
        update_method=async_update_data,
        update_interval=timedelta(seconds=_interval(entry)),
    )

    def update_local_state(status_key: str, value) -> None:
        if not coordinator.data:
            return
        status = dict(coordinator.data.get("status") or {})
        status[status_key] = str(value)
        coordinator.data = {**coordinator.data, "status": status}

    coordinator.update_local_state = update_local_state  # type: ignore[attr-defined]

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: client,
        DATA_COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
