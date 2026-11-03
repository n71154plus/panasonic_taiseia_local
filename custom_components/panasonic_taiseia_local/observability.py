"""Supportability helpers: control/EMS health snapshots and repair issues."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .cloud import credentials_reject_reason, credentials_rejected
from .const import (
    CONF_CONTROL_MODE,
    CONF_ENTRY_TYPE,
    CONF_USERNAME,
    DATA_CONTROL,
    DATA_EMS_GATE,
    DEFAULT_CONTROL_MODE,
    DOMAIN,
    ENTRY_TYPE_HUB,
)
from .naming import mask_account

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
else:
    ConfigEntry = Any  # runtime duck-typing for tests
    HomeAssistant = Any

_LOGGER = logging.getLogger(__package__)

ISSUE_EMS_REAUTH = "ems_credentials_rejected"

# Honest App-parity notes for diagnostics (not user-facing marketing).
MOLD_DRY_BEHAVIOR: dict[str, Any] = {
    "preference_service": {
        "default": "0x17",
        "ux_vx": "0x56",
    },
    "official_start": "ems_power_off_while_preference_on",
    "lan_power_off": "0x00=0 does not start the official mold-dry cycle on tested RX-20xxxA06 modules",
    "lan_stop_codes_2_3": "rejected (0xFFFF) on tested RX-20xxxA06; may work on some other modules",
    "local_only": "no official local start command; fan-mode simulation would only approximate drying",
}


def ems_reauth_issue_id(entry_id: str) -> str:
    return f"{ISSUE_EMS_REAUTH}_{entry_id}"


def control_health_snapshot(
    *,
    control: Any | None,
    entry: ConfigEntry,
    cloud_only: bool = False,
) -> dict[str, Any]:
    """Compact runtime health for coordinator data / diagnostics."""
    mode = entry.options.get(CONF_CONTROL_MODE) or DEFAULT_CONTROL_MODE
    out: dict[str, Any] = {
        "control_mode": mode,
        "cloud_only": bool(cloud_only),
        "lan_ok": None,
        "last_path": None,
        "can_use_lan": None,
        "can_use_cloud": None,
    }
    if control is None:
        return out
    out["lan_ok"] = bool(getattr(control, "lan_ok", False))
    out["last_path"] = getattr(control, "last_path", None)
    try:
        out["can_use_lan"] = bool(control.can_use_lan())
        out["can_use_cloud"] = bool(control.can_use_cloud())
    except Exception:  # noqa: BLE001
        pass
    return out


def auth_health_snapshot(hub: ConfigEntry | None) -> dict[str, Any]:
    if hub is None:
        return {"has_hub": False}
    username = (hub.data.get(CONF_USERNAME) or "").strip()
    rejected = bool(username and credentials_rejected(username))
    return {
        "has_hub": True,
        "hub_entry_id": hub.entry_id,
        "account_masked": mask_account(username) if username else None,
        "credentials_ok": not rejected,
        "credentials_reject_reason": credentials_reject_reason(username)
        if rejected
        else None,
    }


def ems_health_snapshot(hass: HomeAssistant) -> dict[str, Any]:
    """Shared EMS gate / transport view when a CloudAccount is alive."""
    from .ems_transport import EmsGate

    domain = hass.data.get(DOMAIN) or {}
    gate = domain.get(DATA_EMS_GATE)
    out: dict[str, Any] = {
        "gate_present": isinstance(gate, EmsGate),
        "queue_depth": gate.queue_depth() if isinstance(gate, EmsGate) else None,
    }
    # Prefer the first live CloudAccount transport if any device stored one.
    transport = None
    for entry_data in domain.values():
        if not isinstance(entry_data, dict):
            continue
        control = entry_data.get(DATA_CONTROL)
        cloud = getattr(control, "_cloud", None) if control is not None else None
        if cloud is not None and getattr(cloud, "transport", None) is not None:
            transport = cloud.transport
            break
    if transport is not None and hasattr(transport, "cooldown_snapshot"):
        out["transport"] = transport.cooldown_snapshot()
    else:
        out["transport"] = None
    return out


async def async_create_ems_reauth_issue(
    hass: HomeAssistant, hub: ConfigEntry
) -> None:
    from homeassistant.helpers import issue_registry as ir

    username = (hub.data.get(CONF_USERNAME) or "").strip()
    ir.async_create_issue(
        hass,
        DOMAIN,
        ems_reauth_issue_id(hub.entry_id),
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_EMS_REAUTH,
        translation_placeholders={
            "account": mask_account(username) if username else hub.title or "EMS",
            "title": hub.title or "Panasonic TaiSEIA",
        },
        data={"entry_id": hub.entry_id},
    )


async def async_delete_ems_reauth_issue(
    hass: HomeAssistant, hub_entry_id: str
) -> None:
    from homeassistant.helpers import issue_registry as ir

    ir.async_delete_issue(hass, DOMAIN, ems_reauth_issue_id(hub_entry_id))


def is_hub_entry(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HUB
