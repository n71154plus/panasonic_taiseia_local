"""Shared diagnostic payload builders (probe sensor, HA diagnostics, services)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CP_TOKEN,
    CONF_ENTRY_TYPE,
    CONF_HUB_ENTRY_ID,
    CONF_MODEL_TYPE,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_PROFILE,
    DOMAIN,
    ENTRY_TYPE_DEVICE,
    ENTRY_TYPE_HUB,
)
from .probe_info import (
    decode_status_value,
    service_label,
    status_highlights,
    type_summary,
)
from .taiseia import DeviceInfo

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
else:
    ConfigEntry = Any  # runtime: duck-typed entry objects in tests / HA

_REDACT_KEYS = {
    CONF_PASSWORD,
    CONF_CP_TOKEN,
    CONF_REFRESH_TOKEN,
    "password",
    "cp_token",
    "refresh_token",
    "token",
}


def mask_username(username: str | None) -> str | None:
    """Mask an email / account for diagnostics."""
    if not username:
        return None
    text = str(username)
    if "@" in text:
        local, _, domain = text.partition("@")
        if len(local) <= 2:
            masked_local = "*" * len(local)
        else:
            masked_local = f"{local[0]}***{local[-1]}"
        return f"{masked_local}@{domain}"
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}***{text[-2:]}"


def redact_mapping(data: dict[str, Any] | None) -> dict[str, Any]:
    """Copy a mapping with secrets removed / username masked."""
    out: dict[str, Any] = {}
    for key, value in (data or {}).items():
        if key in _REDACT_KEYS:
            out[key] = "**REDACTED**"
        elif key == CONF_USERNAME:
            out[key] = mask_username(str(value) if value is not None else None)
        else:
            out[key] = value
    return out


def parse_service_id(raw: Any) -> int:
    """Accept int, decimal string, or hex like 0x12 / 12h."""
    if isinstance(raw, bool):
        raise ValueError("invalid service id")
    if isinstance(raw, int):
        return raw & 0xFFFF
    text = str(raw).strip().lower()
    if not text:
        raise ValueError("empty service id")
    if text.startswith("0x"):
        return int(text, 16) & 0xFFFF
    if text.endswith("h") and text[:-1]:
        return int(text[:-1], 16) & 0xFFFF
    return int(text, 10) & 0xFFFF


def _name_overrides_from_profile(profile: Any) -> dict[int, str] | None:
    if profile is None:
        return None
    return {cmd.service: cmd.name for cmd in profile.commands}


def services_structured(
    device: DeviceInfo,
    *,
    name_overrides: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Structured service list for diagnostics JSON."""
    rows: list[dict[str, Any]] = []
    for sid, info in sorted(device.services.items()):
        rows.append(
            {
                "id": sid,
                "id_hex": f"0x{sid:02X}",
                "name": service_label(
                    sid, device.sa_type_id, name_overrides=name_overrides
                ),
                "writable": bool(info.writable),
                "min": info.min_value,
                "max": info.max_value,
            }
        )
    return rows


def status_structured(
    status: dict[str, str],
    sa_type: int,
    *,
    name_overrides: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(
        status.keys(),
        key=lambda k: int(k, 16) if str(k).lower().startswith("0x") else str(k),
    ):
        raw = status[key]
        try:
            sid = int(key, 16)
        except ValueError:
            rows.append({"key": key, "raw": raw})
            continue
        decoded = decode_status_value(sa_type, sid, raw)
        rows.append(
            {
                "id": sid,
                "id_hex": f"0x{sid:02X}",
                "name": service_label(
                    sid, sa_type, name_overrides=name_overrides
                ),
                "raw": raw,
                "decoded": decoded,
            }
        )
    return rows


def profile_summary(profile: Any) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "model_type": profile.model_type,
        "device_type": profile.device_type,
        "device_name": profile.device_name,
        "protocol": profile.protocol,
        "command_count": len(profile.commands),
        "commands": [
            {
                "id": cmd.service,
                "id_hex": f"0x{cmd.service:02X}",
                "name": cmd.name,
                "parameter_type": cmd.parameter_type,
            }
            for cmd in profile.commands
        ],
    }


def build_device_snapshot(
    *,
    entry: ConfigEntry,
    device: DeviceInfo,
    status: dict[str, str],
    profile: Any,
    coordinator_ok: bool | None,
    poll_interval: Any = None,
    lan: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a full device diagnostics dict from in-memory state."""
    overrides = _name_overrides_from_profile(profile)
    sa_type = device.sa_type_id
    payload: dict[str, Any] = {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "unique_id": entry.unique_id,
            "version": entry.version,
            "data": redact_mapping(dict(entry.data)),
            "options": redact_mapping(dict(entry.options)),
        },
        "device": {
            "host": device.host,
            "port": device.port,
            "mac": device.mac or None,
            "type_id": sa_type,
            "type_id_hex": f"0x{sa_type:02X}",
            "type_name": type_summary(device),
            "sa_model": device.sa_model or device.model_number or None,
            "friendly_name": device.friendly_name or None,
            "manufacturer": device.manufacturer or None,
            "sw_version": device.sw_version or None,
            "service_count": len(device.services),
        },
        "model_type": (extra or {}).get("model_type")
        or entry.data.get(CONF_MODEL_TYPE)
        or (profile.model_type if profile else None),
        "services": services_structured(device, name_overrides=overrides),
        "status_highlights": status_highlights(status, sa_type),
        "status": status_structured(
            status, sa_type, name_overrides=overrides
        ),
        "status_raw": dict(status),
        "profile": profile_summary(profile),
        "coordinator_ok": coordinator_ok,
        "poll_interval": poll_interval,
        "lan": lan or {},
    }
    if extra:
        for key in (
            "indoor_model",
            "cloud_nickname",
            "cloud_model",
            "cloud_model_id",
            "cloud_model_type",
            "cloud_gwid",
        ):
            val = extra.get(key)
            if val not in (None, ""):
                payload[key] = val
    return payload


def probe_sensor_attributes(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Traditional-Chinese attributes for the diagnostic probe sensor (compact)."""
    device = snapshot.get("device") or {}
    attrs: dict[str, Any] = {
        "設備類型": device.get("type_name"),
        "ModelType": snapshot.get("model_type"),
        "類型代碼": device.get("type_id_hex"),
        "服務數量": device.get("service_count"),
        "服務清單": [
            f"{row['id_hex']} {row['name']} "
            f"[{'讀寫' if row.get('writable') else '唯讀'}] "
            f"{row.get('min')}–{row.get('max')}"
            for row in snapshot.get("services") or []
        ],
        "即時狀態數量": len(snapshot.get("status_raw") or {}),
        "狀態摘要": snapshot.get("status_highlights") or {},
        "即時狀態": [
            (
                f"{row['id_hex']} {row['name']} = {row['raw']}"
                + (
                    f"（{row['decoded']}）"
                    if row.get("decoded") and row.get("decoded") != str(row.get("raw"))
                    else ""
                )
            )
            for row in snapshot.get("status") or []
            if "id_hex" in row
        ],
        "即時狀態原始": snapshot.get("status_raw") or {},
        "IP": device.get("host"),
        "埠": device.get("port"),
        "MAC": device.get("mac"),
        "SA模組": device.get("sa_model"),
        "室內機型號": snapshot.get("indoor_model"),
        "輪詢間隔秒": snapshot.get("poll_interval"),
        "協調器成功": snapshot.get("coordinator_ok"),
    }
    lan = snapshot.get("lan") or {}
    if lan.get("timeout") is not None:
        attrs["LAN逾時"] = lan.get("timeout")
    if lan.get("retries") is not None:
        attrs["LAN重試"] = lan.get("retries")
    if lan.get("max_concurrent") is not None:
        attrs["LAN併發上限"] = lan.get("max_concurrent")
    for key, label in (
        ("cloud_nickname", "官網暱稱"),
        ("cloud_model", "官網機型"),
        ("cloud_model_id", "官網 ModelID"),
        ("cloud_model_type", "官網 ModelType"),
        ("cloud_gwid", "官網 GWID"),
    ):
        val = snapshot.get(key)
        if val not in (None, ""):
            attrs[label] = val
    hub = (snapshot.get("entry") or {}).get("data", {}).get(CONF_HUB_ENTRY_ID)
    if hub:
        attrs["主設定 entry"] = hub
    return attrs


async def async_build_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Assemble diagnostics for a device config entry."""
    from .lan_settings import async_get_lan_settings

    domain_data = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    client = domain_data.get(DATA_CLIENT)
    coordinator = domain_data.get(DATA_COORDINATOR)
    profile = domain_data.get(DATA_PROFILE)

    if client is None:
        return {
            "entry": {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "data": redact_mapping(dict(entry.data)),
                "options": redact_mapping(dict(entry.options)),
            },
            "error": "client_not_loaded",
        }

    lan_settings = await async_get_lan_settings(hass)
    lan = {
        "timeout": lan_settings.timeout,
        "retries": lan_settings.retries,
        "retry_delay": lan_settings.retry_delay,
        "max_concurrent": lan_settings.max_concurrent,
    }
    status = {}
    poll_interval = None
    extra: dict[str, Any] = {}
    coordinator_ok = None
    if coordinator is not None:
        coordinator_ok = coordinator.last_update_success
        data = coordinator.data or {}
        status = dict(data.get("status") or {})
        poll_interval = data.get("poll_interval")
        for key in (
            "model_type",
            "indoor_model",
            "cloud_nickname",
            "cloud_model",
            "cloud_model_id",
            "cloud_model_type",
            "cloud_gwid",
            "name",
        ):
            if key in data:
                extra[key] = data[key]

    return build_device_snapshot(
        entry=entry,
        device=client.device,
        status=status,
        profile=profile,
        coordinator_ok=coordinator_ok,
        poll_interval=poll_interval,
        lan=lan,
        extra=extra,
    )


async def async_build_hub_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Assemble diagnostics for a hub config entry."""
    from .lan_settings import async_get_lan_settings

    lan_settings = await async_get_lan_settings(hass)
    linked = []
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_DEVICE:
            continue
        if other.data.get(CONF_HUB_ENTRY_ID) != entry.entry_id:
            continue
        linked.append(
            {
                "entry_id": other.entry_id,
                "title": other.title,
                "host": other.data.get(CONF_HOST),
                "mac": other.data.get("mac"),
                "model_type": other.data.get(CONF_MODEL_TYPE),
                "name": other.data.get(CONF_NAME),
            }
        )
    return {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "unique_id": entry.unique_id,
            "data": redact_mapping(dict(entry.data)),
            "options": redact_mapping(dict(entry.options)),
        },
        "lan": {
            "timeout": lan_settings.timeout,
            "retries": lan_settings.retries,
            "retry_delay": lan_settings.retry_delay,
            "max_concurrent": lan_settings.max_concurrent,
        },
        "linked_devices": linked,
        "linked_device_count": len(linked),
    }
