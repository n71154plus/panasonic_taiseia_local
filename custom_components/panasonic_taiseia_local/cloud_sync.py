"""Apply EMS cloud inventory onto local config entries / device registry."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .cloud import CloudAccount, CloudDevice
from .const import (
    CONF_CLOUD_AUTH,
    CONF_CLOUD_DEVICE_TYPE,
    CONF_CLOUD_GWID,
    CONF_CLOUD_MODEL,
    CONF_CLOUD_MODEL_ID,
    CONF_CLOUD_MODEL_TYPE,
    CONF_CLOUD_NICKNAME,
    CONF_CP_TOKEN,
    CONF_ENTRY_TYPE,
    CONF_INDOOR_MODEL,
    CONF_MODEL_TYPE,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    DOMAIN,
    ENTRY_TYPE_DEVICE,
    ENTRY_TYPE_HUB,
    MANUFACTURER,
)
from .naming import format_cloud_title, format_local_title, looks_like_module_model

_LOGGER = logging.getLogger(__package__)


def cloud_fields_from_device(cd: CloudDevice) -> dict[str, Any]:
    return {
        CONF_CLOUD_NICKNAME: cd.nickname,
        CONF_CLOUD_MODEL: cd.model or None,
        CONF_CLOUD_MODEL_ID: cd.model_id or None,
        CONF_CLOUD_MODEL_TYPE: cd.model_type or None,
        CONF_CLOUD_DEVICE_TYPE: cd.device_type,
        CONF_CLOUD_GWID: cd.gwid or None,
        CONF_CLOUD_AUTH: cd.auth or None,
    }


def merge_cloud_into_entry_data(
    data: dict[str, Any], cd: CloudDevice, *, update_name: bool = True
) -> dict[str, Any]:
    """Return updated entry data with cloud metadata."""
    out = dict(data)
    out.update(cloud_fields_from_device(cd))
    if cd.model and not out.get(CONF_INDOOR_MODEL):
        out[CONF_INDOOR_MODEL] = cd.model
    if cd.model_type and not out.get(CONF_MODEL_TYPE):
        out[CONF_MODEL_TYPE] = cd.model_type
    if update_name and cd.nickname:
        cloud_only = bool(out.get("cloud_only")) or (
            str(out.get("host") or "") in ("", "0.0.0.0")
            and bool(out.get(CONF_CLOUD_GWID))
        )
        # Refresh path suffix when nickname looks like module model or wrong path tag
        current = out.get(CONF_NAME) or ""
        wrong_local = cloud_only and "(本地)" in str(current)
        if (
            looks_like_module_model(current)
            or not current
            or wrong_local
        ):
            out[CONF_NAME] = (
                format_cloud_title(cd.nickname)
                if cloud_only
                else format_local_title(cd.nickname)
            )
    return out


def hub_device_identifier(entry: ConfigEntry) -> tuple[str, str]:
    uid = entry.unique_id or f"hub:{entry.entry_id}"
    return (DOMAIN, uid)


async def async_ensure_hub_device(
    hass: HomeAssistant, entry: ConfigEntry
) -> dr.DeviceEntry:
    registry = dr.async_get(hass)
    username = entry.data.get(CONF_USERNAME) or "Panasonic"
    return registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={hub_device_identifier(entry)},
        manufacturer=MANUFACTURER,
        name=entry.title or f"Panasonic TaiSEIA（{username}）",
        model="主設定 · EMS 帳號",
        configuration_url="https://ems2.panasonic.com.tw/",
    )


def _mac_key(value: str | None) -> str | None:
    if not value:
        return None
    mac = value.replace(":", "").replace("-", "").lower()
    return mac if len(mac) == 12 else None


async def async_fetch_cloud_devices(
    hass: HomeAssistant, hub: ConfigEntry
) -> list[CloudDevice]:
    session = async_get_clientsession(hass)
    cloud = CloudAccount(
        session,
        hub.data.get(CONF_USERNAME, ""),
        hub.data.get(CONF_PASSWORD, ""),
        refresh_token=hub.data.get(CONF_REFRESH_TOKEN),
        cp_token=hub.data.get(CONF_CP_TOKEN),
    )
    devices = await cloud.async_get_devices()
    new_data = dict(hub.data)
    new_data[CONF_CP_TOKEN] = cloud.cp_token
    new_data[CONF_REFRESH_TOKEN] = cloud.refresh_token
    hass.config_entries.async_update_entry(hub, data=new_data)
    return devices


async def async_sync_cloud_to_devices(
    hass: HomeAssistant, hub: ConfigEntry
) -> int:
    """Pull EMS list and patch linked local device entries + registry."""
    try:
        devices = await async_fetch_cloud_devices(hass, hub)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Cloud sync failed: %s", err)
        return 0

    by_mac = {
        (cd.mac or "").lower(): cd
        for cd in devices
        if cd.mac and cd.is_local_candidate
    }
    by_gwid = {(cd.gwid or "").lower(): cd for cd in devices if cd.gwid}
    updated = 0
    registry = dr.async_get(hass)

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB:
            continue
        if entry.data.get(CONF_ENTRY_TYPE) not in (ENTRY_TYPE_DEVICE, None):
            continue
        cd = None
        mac = _mac_key(entry.data.get("mac") or entry.unique_id)
        if mac and mac in by_mac:
            cd = by_mac[mac]
        if cd is None:
            gwid = (entry.data.get(CONF_CLOUD_GWID) or "").lower()
            if not gwid and (entry.unique_id or "").startswith("gwid:"):
                gwid = (entry.unique_id or "")[5:].lower()
            if gwid and gwid in by_gwid:
                cd = by_gwid[gwid]
        if cd is None:
            continue
        new_data = merge_cloud_into_entry_data(dict(entry.data), cd)
        title = new_data.get(CONF_NAME) or entry.title
        if new_data != dict(entry.data) or title != entry.title:
            hass.config_entries.async_update_entry(
                entry, data=new_data, title=title
            )
            updated += 1

        # Refresh device registry model / name from cloud
        identifiers = set()
        if mac:
            identifiers.add((DOMAIN, mac))
        if entry.unique_id:
            identifiers.add((DOMAIN, entry.unique_id))
        gwid_id = (cd.gwid or "").lower()
        if gwid_id:
            identifiers.add((DOMAIN, f"gwid:{gwid_id}"))
        device = None
        for ident in identifiers:
            device = registry.async_get_device({ident})
            if device is not None:
                break
        if device is not None:
            registry.async_update_device(
                device.id,
                name=title,
                model=_device_model_string(new_data, cd),
                serial_number=(cd.gwid or mac or "").upper() or None,
            )

    _LOGGER.info("Synced cloud metadata to %s local device(s)", updated)
    return updated


def _device_model_string(data: dict[str, Any], cd: CloudDevice) -> str:
    bits = [
        data.get(CONF_INDOOR_MODEL) or cd.model,
        data.get(CONF_MODEL_TYPE) or cd.model_type,
    ]
    return " · ".join(str(b) for b in bits if b) or (cd.nickname or "TaiSEIA")


def cloud_attrs_from_entry(entry: ConfigEntry | dict) -> dict[str, Any]:
    data = entry.data if isinstance(entry, ConfigEntry) else entry
    attrs: dict[str, Any] = {}
    mapping = {
        "官網暱稱": CONF_CLOUD_NICKNAME,
        "官網機型": CONF_CLOUD_MODEL,
        "官網 ModelID": CONF_CLOUD_MODEL_ID,
        "官網 ModelType": CONF_CLOUD_MODEL_TYPE,
        "官網 GWID": CONF_CLOUD_GWID,
        "官網 Auth": CONF_CLOUD_AUTH,
    }
    for label, key in mapping.items():
        val = data.get(key)
        if val not in (None, ""):
            attrs[label] = val
    dtype = data.get(CONF_CLOUD_DEVICE_TYPE)
    if dtype is not None:
        from .probe_info import cloud_type_name

        attrs["官網設備類型"] = cloud_type_name(int(dtype)) or dtype
    return attrs
