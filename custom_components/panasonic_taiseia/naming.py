"""Resolve friendly nicknames from panasonic_smart_app / known GWID map."""

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
_DEVICES_JSON_CANDIDATES = (
    Path("/config/pyscript/panasonic_devices.json"),
)


@dataclass(frozen=True)
class SuggestedName:
    nickname: str
    indoor_model: str | None = None


def looks_like_module_model(name: str | None) -> bool:
    """True if name is SA WiFi module model (e.g. RX-20190A06) rather than a room nick."""
    if not name:
        return True
    base = name.split("(")[0].strip()
    return bool(_SA_MODEL_RE.match(base)) or base.lower().startswith("panasonicsmart")


def _from_devices_json(mac: str) -> SuggestedName | None:
    mac_u = mac.upper()
    for path in _DEVICES_JSON_CANDIDATES:
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            gwid = str(item.get("GWID") or "").upper()
            if gwid != mac_u:
                continue
            nick = (item.get("NickName") or "").strip()
            model = (item.get("Model") or "").strip() or None
            if nick:
                return SuggestedName(nick, model)
    return None


def _from_smart_app_registry(hass: HomeAssistant, mac: str) -> SuggestedName | None:
    mac_u = mac.upper()
    registry = dr.async_get(hass)
    for device in registry.devices.values():
        for ident in device.identifiers:
            # identifiers may be 2- or 3-tuples depending on integration
            if not ident or ident[0] != "panasonic_smart_app":
                continue
            ident_s = str(ident[1]).upper()
            if not ident_s.startswith(mac_u):
                continue
            nick = (device.name_by_user or device.name or "").strip()
            model = (device.model or "").strip() or None
            if nick:
                return SuggestedName(nick, model)
    return None


def async_suggest_name(hass: HomeAssistant | None, mac: str | None) -> SuggestedName | None:
    """Suggest a human nickname for a CZ-T006 MAC (12 hex chars)."""
    if not mac or len(mac) < 12:
        return None
    mac12 = mac.replace(":", "").replace("-", "")[:12]
    if hass is not None:
        found = _from_smart_app_registry(hass, mac12)
        if found:
            return found
    return _from_devices_json(mac12)


def format_local_title(nickname: str, type_name: str | None = None) -> str:
    title = nickname.strip()
    if not title.endswith("(本地)") and "本地" not in title:
        title = f"{title} (本地)"
    if type_name and type_name not in title:
        # Keep room nick; type already implied for AC
        pass
    return title
