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


def coalesce_sa_type(*candidates: Any, default: int | None = TYPE_AC) -> int | None:
    """Pick the first present SA / EMS device type.

    Unlike ``a or b or TYPE_AC``, an explicit ``0`` (unknown) is preserved and
    does not fall through to the AC default.
    """
    for raw in candidates:
        if raw is None or raw == "":
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return default


def ems_to_sa_type(device_type: Any) -> int:
    """EMS DeviceType aligns with TaiSEIA type ids for common appliances."""
    resolved = coalesce_sa_type(device_type, default=TYPE_AC)
    return TYPE_AC if resolved is None else resolved


def cloud_only_import_data(cd: CloudDevice, *, mac: str | None = None) -> dict[str, Any]:
    from .catalog import model_type_matches_device

    sa_type = ems_to_sa_type(cd.device_type)
    mt = (cd.model_type or "").strip() or None
    if mt and not model_type_matches_device(mt, sa_type):
        mt = None
    return {
        CONF_HOST: "0.0.0.0",
        CONF_NAME: format_cloud_title(cd.nickname),
        CONF_INDOOR_MODEL: cd.model or None,
        CONF_MODEL_TYPE: mt,
        CONF_DEVICE_TYPE: sa_type,
        "mac": (mac or cd.mac or "").upper() or None,
        "cloud_only": True,
        **cloud_fields_from_device(cd),
    }
