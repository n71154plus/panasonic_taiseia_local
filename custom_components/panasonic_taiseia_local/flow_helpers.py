"""Shared helpers for config / options flows."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant

from .cloud import CloudDevice
from .cloud_sync import cloud_fields_from_device
from .const import (
    CONF_CLOUD_GWID,
    CONF_DEVICE_TYPE,
    CONF_ENTRY_TYPE,
    CONF_INDOOR_MODEL,
    CONF_MODEL_TYPE,
    DOMAIN,
    ENTRY_TYPE_HUB,
    TYPE_AC,
)
from .naming import format_cloud_title


def hub_entry(hass: HomeAssistant) -> ConfigEntry | None:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            return entry
    return None


def configured_ids(hass: HomeAssistant) -> set[str]:
    """MAC / GWID / unique_id keys already configured as device entries."""
    out: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            continue
        for raw in (
            entry.unique_id,
            entry.data.get("mac"),
            entry.data.get(CONF_CLOUD_GWID),
        ):
            if not raw:
                continue
            key = str(raw).lower()
            if key.startswith("gwid:"):
                key = key[5:]
            out.add(key)
            if len(key) == 12:
                out.add(key)
    return out


def configured_macs(hass: HomeAssistant) -> set[str]:
    """Back-compat alias used by discover/manual flows."""
    return {k for k in configured_ids(hass) if len(k) == 12}


def ems_to_sa_type(device_type: int) -> int:
    """EMS DeviceType aligns with TaiSEIA type ids for common appliances."""
    try:
        return int(device_type)
    except (TypeError, ValueError):
        return TYPE_AC


def cloud_only_import_data(cd: CloudDevice, *, mac: str | None = None) -> dict[str, Any]:
    sa_type = ems_to_sa_type(cd.device_type)
    return {
        CONF_HOST: "0.0.0.0",
        CONF_NAME: format_cloud_title(cd.nickname),
        CONF_INDOOR_MODEL: cd.model or None,
        CONF_MODEL_TYPE: cd.model_type or None,
        CONF_DEVICE_TYPE: sa_type,
        "mac": (mac or cd.mac or "").upper() or None,
        "cloud_only": True,
        **cloud_fields_from_device(cd),
    }
