"""Optional nickname / indoor-model / ModelType hints (never required)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

_LOGGER = logging.getLogger(__package__)

_SA_MODEL_RE = re.compile(r"^RX-\d", re.I)
# Parsed once, off the event loop. None means "not loaded yet".
_DEVICE_HINTS: list[dict] | None = None


@dataclass(frozen=True)
class SuggestedName:
    nickname: str
    indoor_model: str | None = None
    model_type: str | None = None


def looks_like_module_model(name: str | None) -> bool:
    """True if name is SA WiFi module model (e.g. RX-20190A06) rather than a room nick."""
    if not name:
        return True
    base = name.split("(")[0].strip()
    return bool(_SA_MODEL_RE.match(base)) or base.lower().startswith("panasonicsmart")


def device_hint_paths(hass: HomeAssistant) -> tuple[Path, ...]:
    """Optional nickname files under the HA config dir (not hardcoded /config)."""
    return (
        Path(hass.config.path("pyscript", "panasonic_devices.json")),
        Path(hass.config.path("panasonic_devices.json")),
    )


def _read_device_hints(paths: tuple[Path, ...]) -> list[dict]:
    """Read the first valid devices JSON. Missing files are ignored."""
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


async def async_preload_device_hints(hass: HomeAssistant) -> None:
    """Load optional nickname hints off the event loop."""
    global _DEVICE_HINTS
    if _DEVICE_HINTS is not None:
        return
    _DEVICE_HINTS = await hass.async_add_executor_job(
        _read_device_hints, device_hint_paths(hass)
    )


def _from_devices_json(mac: str) -> SuggestedName | None:
    """Match a MAC against hints already loaded by async_preload_device_hints."""
    if not _DEVICE_HINTS:
        return None
    mac_u = mac.upper()
    for item in _DEVICE_HINTS:
        gwid = str(item.get("GWID") or "").upper()
        if gwid != mac_u:
            continue
        nick = (item.get("NickName") or "").strip()
        model = (item.get("Model") or "").strip() or None
        model_type = (item.get("ModelType") or "").strip() or None
        if nick:
            _LOGGER.debug("Hint for %s", mac_u)
            return SuggestedName(nick, model, model_type)
    return None


def _from_smart_app_registry(hass: HomeAssistant, mac: str) -> SuggestedName | None:
    mac_u = mac.upper()
    registry = dr.async_get(hass)
    for device in registry.devices.values():
        for ident in device.identifiers:
            if not ident or ident[0] != "panasonic_smart_app":
                continue
            ident_s = str(ident[1]).upper()
            if not ident_s.startswith(mac_u):
                continue
            nick = (device.name_by_user or device.name or "").strip()
            model = (device.model or "").strip() or None
            # ModelType is not on device registry; try via entities' config — skip.
            if nick:
                return SuggestedName(nick, model, None)
    return None


def async_suggest_name(hass: HomeAssistant | None, mac: str | None) -> SuggestedName | None:
    """Suggest nickname / indoor model / ModelType for a CZ-T006 MAC."""
    if not mac or len(mac) < 12:
        return None
    mac12 = mac.replace(":", "").replace("-", "")[:12]
    if hass is not None:
        found = _from_smart_app_registry(hass, mac12)
        # Prefer JSON when it also has ModelType
        json_hint = _from_devices_json(mac12)
        if json_hint and json_hint.model_type:
            if found:
                return SuggestedName(
                    found.nickname or json_hint.nickname,
                    found.indoor_model or json_hint.indoor_model,
                    json_hint.model_type,
                )
            return json_hint
        if found:
            return found
        return json_hint
    return _from_devices_json(mac12)


def format_device_title(nickname: str, *, cloud_only: bool = False) -> str:
    """Human title with path hint: (雲端) or (本地)."""
    title = (nickname or "").strip()
    for suffix in (" (本地)", " (雲端)", " (混合)", "(本地)", "(雲端)"):
        if title.endswith(suffix):
            title = title[: -len(suffix)].rstrip()
            break
    if not title:
        title = "Panasonic"
    if cloud_only:
        return f"{title} (雲端)"
    return f"{title} (本地)"


def format_local_title(nickname: str, type_name: str | None = None) -> str:
    """Back-compat: LAN / hybrid device title with (本地)."""
    _ = type_name
    return format_device_title(nickname, cloud_only=False)


def format_cloud_title(nickname: str) -> str:
    """Cloud-only device title with (雲端)."""
    return format_device_title(nickname, cloud_only=True)


def mask_account(username: str | None) -> str:
    """Mask EMS account for hub titles (avoid full email in the UI)."""
    raw = (username or "").strip()
    if not raw:
        return "帳號"
    if "@" in raw:
        local, _, domain = raw.partition("@")
        if not domain:
            return f"{local[0]}***" if local else "***"
        if len(local) <= 1:
            return f"*@{domain}"
        return f"{local[0]}***@{domain}"
    if len(raw) <= 2:
        return "***"
    return f"{raw[:2]}***"
